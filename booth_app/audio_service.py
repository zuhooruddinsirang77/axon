"""
Speech I/O for the booth.

STT (speech-to-text), tried in order:
  1. faster-whisper — runs fully offline/local on CPU, no API key needed.
     This is what makes Urdu/Hindi/Arabic/French recognition actually work:
     it's the same Whisper model quality across all five booth languages,
     unlike a free web endpoint that's mostly tuned for English.
  2. Groq's hosted Whisper API — only if GROQ_API_KEY is set. Groq's LPU
     inference is fast enough to use as a live fallback without the booth
     feeling laggy; used via Groq's OpenAI-compatible endpoint so no extra
     SDK dependency is needed.
  3. OpenAI's hosted Whisper API — only if OPENAI_API_KEY is set. Higher
     accuracy, but costs money and needs internet.

Free-form intent understanding: `classify_intent()` uses Groq's chat
completion endpoint (AXON_LLM_MODEL, e.g. llama-3.3-70b-versatile) as a
fallback when a transcript/typed line doesn't hit any of the fast literal
keyword checks in main.py — e.g. "I'd like to see the hospital one" instead
of a bare "1" or "healthcare". Only called on the slow path (network), never
blocking the render loop; main.py runs it on a background thread.

TTS (text-to-speech), tried in order:
  1. ElevenLabs — only if ELEVENLABS_API_KEY is set (paid).
  2. edge-tts — free Microsoft neural voices, one per booth language. This
     is the default "nice, professional-sounding" voice with no API key.
  3. pyttsx3 — offline Windows SAPI voice, last resort so the booth is
     never silently silent (e.g. no internet at the venue).

Mic capture uses SpeechRecognition's ambient-noise-adjusted recording
(works well and is already a dependency); whichever STT engine wins just
transcribes the resulting WAV bytes.
"""
import asyncio
import hashlib
import os
import tempfile
import threading
import time

import requests
from dotenv import load_dotenv

import config

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_STT_MODEL = os.environ.get("AXON_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL = os.environ.get("AXON_LLM_MODEL", "openai/gpt-oss-120b")
WHISPER_MODEL_SIZE = os.environ.get("AXON_WHISPER_MODEL", "small")

# Below this peak sample amplitude (out of 32767), a capture is treated as
# silence/no-speech and never reaches STT — see the comment at its use in
# listen() for why.
_MIN_SPEECH_PEAK = 300

# When set, the keyed/paid calls (ElevenLabs TTS, Groq/OpenAI STT fallback,
# Groq intent classification) are proxied through this backend instead of
# calling those providers directly, so the API keys never need to live on
# the kiosk PC. Direct calls above are kept as an automatic fallback if the
# backend is unset or unreachable (e.g. local dev, or a flaky venue network).
BACKEND_URL = os.environ.get("AXON_BACKEND_URL", "").rstrip("/")
BOOTH_API_KEY = os.environ.get("AXON_BOOTH_API_KEY", "")

try:
    import pyttsx3
    _TTS_FALLBACK_AVAILABLE = True
except ImportError:
    _TTS_FALLBACK_AVAILABLE = False

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:
    _SR_AVAILABLE = False

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

# Microsoft Edge neural voices, one confident/natural voice per booth
# language. rate/pitch nudged down slightly for a more deliberate "booth
# announcer" pace rather than a rushed, default chatbot read. en/ar are
# overridable via AXON_TTS_VOICE_EN / AXON_TTS_VOICE_AR for quick swaps
# without touching code.
EDGE_TTS_VOICES = {
    # AndrewNeural is Microsoft's newer, warmer US male voice — noticeably
    # more natural/professional-sounding than the older GuyNeural, which
    # reads flat and robotic for an announcer-style booth.
    "en": (os.environ.get("AXON_TTS_VOICE_EN", "en-US-AndrewNeural"), "-9%", "+0Hz"),
    "ur": ("ur-PK-AsadNeural", "-9%", "+0Hz"),
    "hi": ("hi-IN-MadhurNeural", "-9%", "+0Hz"),
    "ar": (os.environ.get("AXON_TTS_VOICE_AR", "ar-SA-HamedNeural"), "-9%", "+0Hz"),
    "fr": ("fr-FR-HenriNeural", "-9%", "+0Hz"),
}


class AudioService:
    def __init__(self):
        self.openai_client = None
        self.elevenlabs_client = None
        self.groq_client = None

        if OPENAI_API_KEY:
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY)

        if ELEVENLABS_API_KEY:
            from elevenlabs.client import ElevenLabs
            self.elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        if GROQ_API_KEY:
            # Groq exposes an OpenAI-compatible endpoint for both audio
            # transcription and chat completions, so the existing `openai`
            # dependency covers this too — no separate SDK needed.
            from openai import OpenAI
            self.groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

        self._tts_lock = threading.Lock()
        self._recognizer = sr.Recognizer() if _SR_AVAILABLE else None
        if self._recognizer is not None:
            # Default pause_threshold (0.8s of sub-threshold audio to
            # consider a phrase finished) plus phrase_time_limit=6 in
            # listen() below were observed to make every capture run to
            # nearly the full 6s regardless of how short the utterance
            # actually was (e.g. a single word still captured ~6.5s) on
            # this laptop's mic array — its background noise floor
            # apparently doesn't drop cleanly below the calibrated energy
            # threshold between words. Tightening this doesn't fix that
            # root cause but shortens the perceived lag for the common
            # case where it does work.
            self._recognizer.pause_threshold = 0.5
        self._mic = self._init_microphone() if _SR_AVAILABLE else None

        # Guards the mic context manager. main.py can trigger a new
        # listen_async() (e.g. re-entering LANG_SELECT after ESC) while a
        # previous listen() is still blocked inside `with self._mic as
        # source:` waiting for speech — sr.Microphone raises "already
        # inside a context manager" if entered twice concurrently, which
        # otherwise permanently breaks that listen() call and looked like
        # voice input just silently dying.
        self._mic_lock = threading.Lock()

        # ElevenLabs quota/plan errors (e.g. free-plan 402s) are the same on
        # every call, so retrying per-utterance just adds a network
        # round-trip of latency to every single line. Disable it for the
        # rest of the session after the first failure instead.
        self._elevenlabs_disabled = False

        # Same reasoning as _elevenlabs_disabled above, for the backend TTS
        # proxy: a down/erroring backend (e.g. its own ElevenLabs quota
        # exhausted) fails identically on every call, so stop trying it
        # for the rest of the session after the first failure rather than
        # eating a network round-trip before every single line falls
        # through to edge-tts anyway.
        self._backend_tts_disabled = False

        # Tracks the single currently-playing voice line so a new speak()
        # call can cut off whatever's still playing instead of overlapping
        # it (pygame.mixer otherwise happily plays multiple sounds at once).
        self._playback_lock = threading.Lock()
        self._active_channel = None

        # Bumped by the caller (main.py, on state change) so an in-flight
        # synthesis for a state the app has already left can be discarded
        # instead of landing on top of the new state's speech.
        self._latest_generation = 0

        self._whisper_model = None
        self._whisper_ready = threading.Event()
        self._whisper_failed = False
        if WhisperModel is not None:
            threading.Thread(target=self._load_whisper, daemon=True).start()
        else:
            self._whisper_failed = True

    def _load_whisper(self):
        try:
            print(f"[AudioService] loading faster-whisper '{WHISPER_MODEL_SIZE}' model...")
            self._whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
            )
            print("[AudioService] faster-whisper ready.")
        except Exception as e:
            self._whisper_failed = True
            print(f"[AudioService] faster-whisper failed to load: {e}")
        finally:
            self._whisper_ready.set()

    def _init_microphone(self):
        """Pick the default input device explicitly and actually probe-open
        it (rather than trusting SpeechRecognition to do so lazily), logging
        exactly what happened.

        SpeechRecognition's own `Microphone.__enter__` swallows the real
        PyAudio error when a device can't be opened (bare `except Exception:
        self.audio.terminate()`, no re-raise), which turns any real failure
        — wrong sample rate, another app holding the mic exclusively, a
        Windows privacy-permission block — into a useless `'NoneType' object
        has no attribute 'close'` on every single listen() call instead of
        one clear message here.
        """
        try:
            import pyaudio
        except ImportError as e:
            print(f"[AudioService] PyAudio unavailable, voice input disabled: {e}")
            return None

        device_name, device_index, sample_rate = None, None, None
        pa = pyaudio.PyAudio()
        try:
            info = pa.get_default_input_device_info()
            device_name = info.get("name", "unknown device")
            device_index = info["index"]
            sample_rate = int(info["defaultSampleRate"])
        except Exception:
            pass
        finally:
            pa.terminate()

        if device_index is None:
            print("[AudioService] No microphone/input device found — voice "
                  "input disabled, use the keypad/number keys instead.")
            return None

        pa = pyaudio.PyAudio()
        try:
            probe = pa.open(
                input_device_index=device_index, channels=1, format=pyaudio.paInt16,
                rate=sample_rate, frames_per_buffer=1024, input=True,
            )
            probe.close()
        except Exception as e:
            print(f"[AudioService] Microphone '{device_name}' was found but "
                  f"could not be opened ({e}) — voice input disabled, use the "
                  f"keypad/number keys instead. On Windows this is usually "
                  f"Settings > Privacy & security > Microphone > 'Let desktop "
                  f"apps access your microphone' being off, or another app "
                  f"holding the microphone exclusively.")
            return None
        finally:
            pa.terminate()

        try:
            mic = sr.Microphone(device_index=device_index)
            print(f"[AudioService] Using microphone: {device_name}")
            return mic
        except Exception as e:
            print(f"[AudioService] Failed to open microphone '{device_name}': {e}")
            return None

    # ------------------------------------------------------------------
    # Text-to-Speech
    # ------------------------------------------------------------------
    def speak(self, text, lang_code="en", blocking=False, generation=None):
        """Speak `text`. Runs on a background thread unless blocking=True.

        `generation` (from main.py's per-state-change counter) lets a slow
        in-flight synthesis be discarded if the app has already moved to a
        different state by the time it's ready to play, instead of speaking
        over the new state's line.
        """
        def _stale():
            return generation is not None and generation != self._latest_generation

        def _run():
            if _stale():
                return
            if (BACKEND_URL and not self._backend_tts_disabled
                    and self._speak_backend(text, generation)):
                return
            if _stale():
                return
            if (self.elevenlabs_client and not self._elevenlabs_disabled
                    and self._speak_elevenlabs(text, generation)):
                return
            if _stale():
                return
            if edge_tts is not None and self._speak_edge(text, lang_code, generation):
                return
            if _stale():
                return
            if _TTS_FALLBACK_AVAILABLE:
                # A fresh engine per call avoids a pyttsx3/SAPI COM deadlock
                # ("run loop already started") that occurs when a single
                # engine instance is reused across different threads.
                with self._tts_lock:
                    engine = pyttsx3.init()
                    engine.setProperty("rate", 160)
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
            else:
                print(f"[TTS:{lang_code}] {text}")

        if blocking:
            _run()
        else:
            threading.Thread(target=_run, daemon=True).start()

    def set_generation(self, generation):
        """Called by main.py on every state change; invalidates any speech
        synthesized for an earlier state that hasn't played yet."""
        self._latest_generation = generation

    def stop_speaking(self):
        """Immediately cut off whatever's currently playing."""
        with self._playback_lock:
            if self._active_channel is not None:
                self._active_channel.stop()

    @property
    def is_speaking(self):
        return self._active_channel is not None and self._active_channel.get_busy()

    def _play_and_track(self, sound):
        """Stop whatever's currently playing before starting `sound` — the
        booth should only ever say one thing at a time."""
        with self._playback_lock:
            if self._active_channel is not None:
                self._active_channel.stop()
            self._active_channel = sound.play()

    def _cache_path(self, lang_code, text, voice_key=""):
        """`voice_key` (voice/rate/pitch) is part of the digest so tuning
        the voice or speaking rate in EDGE_TTS_VOICES actually takes
        effect — otherwise a phrase already cached at the old rate would
        keep getting replayed forever regardless of code changes here."""
        digest = hashlib.sha1(f"{lang_code}|{voice_key}|{text}".encode("utf-8")).hexdigest()[:16]
        return os.path.join(config.TEMP_DIR, "cache", f"tts_{lang_code}_{digest}.mp3")

    def _backend_headers(self):
        return {"X-Booth-Key": BOOTH_API_KEY} if BOOTH_API_KEY else {}

    def _speak_backend(self, text, generation=None):
        """Returns True if backend TTS played (or was intentionally skipped
        as stale); False so the caller falls back to a direct provider."""
        try:
            import pygame

            resp = requests.post(
                f"{BACKEND_URL}/tts", json={"text": text},
                headers=self._backend_headers(), timeout=15,
            )
            resp.raise_for_status()

            if generation is not None and generation != self._latest_generation:
                return True

            os.makedirs(config.TEMP_DIR, exist_ok=True)
            out_path = os.path.join(config.TEMP_DIR, f"tts_{int(time.time() * 1000)}.mp3")
            with open(out_path, "wb") as f:
                f.write(resp.content)

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sound = pygame.mixer.Sound(out_path)
            self._play_and_track(sound)
            return True
        except Exception as e:
            print(f"[AudioService] Backend TTS failed, falling back: {e}")
            self._backend_tts_disabled = True
            print("[AudioService] Disabling backend TTS for the rest of this "
                  "session (edge-tts will be used instead).")
            return False

    def _speak_elevenlabs(self, text, generation=None):
        """Returns True if ElevenLabs audio played (or was intentionally
        skipped as stale); False so the caller falls back to the next voice."""
        try:
            import pygame

            os.makedirs(config.TEMP_DIR, exist_ok=True)
            out_path = os.path.join(config.TEMP_DIR, f"tts_{int(time.time() * 1000)}.mp3")

            audio = self.elevenlabs_client.text_to_speech.convert(
                voice_id=config.ELEVENLABS_VOICE_ID or "21m00Tcm4TlvDq8ikWAM",
                model_id=config.ELEVENLABS_MODEL,
                text=text,
            )
            with open(out_path, "wb") as f:
                for chunk in audio:
                    f.write(chunk)

            if generation is not None and generation != self._latest_generation:
                return True

            sound = pygame.mixer.Sound(out_path)
            self._play_and_track(sound)
            return True
        except Exception as e:
            print(f"[AudioService] ElevenLabs TTS failed, falling back: {e}")
            self._elevenlabs_disabled = True
            print("[AudioService] Disabling ElevenLabs for the rest of this "
                  "session (edge-tts will be used instead).")
            return False

    def _speak_edge(self, text, lang_code, generation=None):
        """Returns True if edge-tts audio played (or was intentionally
        skipped as stale); False so the caller falls back to the offline voice."""
        try:
            import pygame

            voice, rate, pitch = EDGE_TTS_VOICES.get(lang_code, EDGE_TTS_VOICES["en"])
            cache_path = self._cache_path(lang_code, text, voice_key=f"{voice}|{rate}|{pitch}")

            if not os.path.exists(cache_path):
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)

                async def generate():
                    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
                    await communicate.save(cache_path)

                asyncio.run(generate())

            if generation is not None and generation != self._latest_generation:
                return True

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sound = pygame.mixer.Sound(cache_path)
            self._play_and_track(sound)
            return True
        except Exception as e:
            print(f"[AudioService] edge-tts failed, falling back to offline voice: {e}")
            return False

    # ------------------------------------------------------------------
    # Speech-to-Text
    # ------------------------------------------------------------------
    def listen(self, timeout=6, phrase_time_limit=4, lang_code=None):
        """
        Blocking mic capture + transcription.
        `lang_code` (e.g. "en", "ur") biases decoding to that language;
        pass None to let the STT engine auto-detect (used during language
        selection, before the booth knows which language to expect).
        Returns the transcript string, or None if unavailable / no speech.
        Call this from a background thread, never from the render loop.
        """
        if not (self._recognizer and self._mic):
            return None

        if not self._mic_lock.acquire(timeout=0.1):
            print("[AudioService] Mic already in use by another listen() call — skipping.")
            return None

        audio = None
        last_err = None
        try:
            for attempt in range(2):
                try:
                    with self._mic as source:
                        self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        audio = self._recognizer.listen(
                            source, timeout=timeout, phrase_time_limit=phrase_time_limit
                        )
                    break
                except Exception as e:
                    last_err = e
                    if attempt == 0:
                        time.sleep(0.3)  # transient device-busy hiccup — retry once
        finally:
            self._mic_lock.release()

        if audio is None:
            print(f"[AudioService] Mic capture failed: {last_err}")
            return None

        # Volume of what was actually captured — distinguishes "mic picked
        # up nothing/too quiet" (low rms/peak here) from "captured fine but
        # every STT engine returned empty" (rms/peak look normal but the
        # final transcript below is still empty), which otherwise look
        # identical from the outside (both just silently produce no result).
        try:
            import numpy as np
            samples = np.frombuffer(audio.get_raw_data(), dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if len(samples) else 0.0
            peak = int(np.max(np.abs(samples))) if len(samples) else 0
            print(f"[AudioService] Captured audio: {len(samples)} samples, "
                  f"rms={rms:.1f} peak={peak} (out of 32767)")
            # Whisper hallucinates stock filler phrases ("Thank you.",
            # "Thanks for watching!") on near-silent input instead of
            # returning empty — observed here at peak~186 on a clip with
            # no real speech. A real word spoken at normal volume toward
            # this mic reads in the thousands (peak~2400-2800 observed),
            # so treat anything this quiet as "nothing said" up front
            # rather than feeding it to STT and risking a hallucinated
            # transcript that silently does the wrong thing.
            if peak < _MIN_SPEECH_PEAK:
                print(f"[AudioService] Captured audio too quiet (peak={peak} < "
                      f"{_MIN_SPEECH_PEAK}) — treating as no speech.")
                return None
        except Exception:
            pass

        os.makedirs(config.TEMP_DIR, exist_ok=True)
        wav_path = os.path.join(config.TEMP_DIR, f"stt_{int(time.time() * 1000)}.wav")
        with open(wav_path, "wb") as f:
            f.write(audio.get_wav_data())

        try:
            text = self._transcribe_whisper_local(wav_path, lang_code)
            if not text and BACKEND_URL:
                text = self._transcribe_backend(wav_path, "stt/groq")
            if not text and self.groq_client:
                text = self._transcribe_groq(wav_path)
            if not text and BACKEND_URL:
                text = self._transcribe_backend(wav_path, "stt/openai")
            if not text and self.openai_client:
                text = self._transcribe_openai(wav_path)
            print(f"[AudioService] Transcript: {text!r}")
            return text or None
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _transcribe_whisper_local(self, wav_path, lang_code):
        if WhisperModel is None or self._whisper_failed:
            return ""
        if not self._whisper_ready.is_set():
            self._whisper_ready.wait(timeout=15)
        if self._whisper_model is None:
            return ""
        try:
            segments, _info = self._whisper_model.transcribe(
                wav_path, language=lang_code, beam_size=5, vad_filter=True
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            print(f"[AudioService] faster-whisper transcription failed: {e}")
            return ""

    def _transcribe_backend(self, wav_path, endpoint):
        try:
            with open(wav_path, "rb") as f:
                resp = requests.post(
                    f"{BACKEND_URL}/{endpoint}",
                    files={"file": (os.path.basename(wav_path), f, "audio/wav")},
                    headers=self._backend_headers(), timeout=20,
                )
            resp.raise_for_status()
            return resp.json().get("text", "") or ""
        except Exception as e:
            print(f"[AudioService] Backend {endpoint} failed: {e}")
            return ""

    def _transcribe_groq(self, wav_path):
        try:
            with open(wav_path, "rb") as f:
                result = self.groq_client.audio.transcriptions.create(
                    model=GROQ_STT_MODEL, file=f
                )
            return result.text
        except Exception as e:
            print(f"[AudioService] Groq transcription failed: {e}")
            return ""

    def _transcribe_openai(self, wav_path):
        try:
            with open(wav_path, "rb") as f:
                result = self.openai_client.audio.transcriptions.create(
                    model=config.WHISPER_MODEL, file=f
                )
            return result.text
        except Exception as e:
            print(f"[AudioService] OpenAI Whisper transcription failed: {e}")
            return ""

    def listen_async(self, callback, timeout=6, phrase_time_limit=4, lang_code=None):
        """Non-blocking variant of listen(); calls callback(transcript_or_None)."""
        def _run():
            result = self.listen(
                timeout=timeout, phrase_time_limit=phrase_time_limit, lang_code=lang_code
            )
            callback(result)

        threading.Thread(target=_run, daemon=True).start()

    @property
    def voice_input_available(self):
        has_engine = ((WhisperModel is not None and not self._whisper_failed)
                      or BACKEND_URL or self.groq_client or self.openai_client)
        return bool(has_engine and self._recognizer and self._mic)

    # ------------------------------------------------------------------
    # Free-form intent understanding (LLM fallback for non-literal phrasing)
    # ------------------------------------------------------------------
    @property
    def llm_available(self):
        return bool(BACKEND_URL) or self.groq_client is not None

    def _classify_intent_backend(self, text, options):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/classify-intent",
                json={"text": text, "options": list(options)},
                headers=self._backend_headers(), timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("label")
        except Exception as e:
            print(f"[AudioService] Backend intent classification failed: {e}")
            return None

    def classify_intent(self, text, options):
        """Ask the LLM to pick the best-matching option for a transcript/typed
        line that didn't hit any literal keyword.

        `options`: list of (label, description) tuples describing the valid
        choices in the caller's current context, e.g.
            [("hiding", "play the hiding game"), ("myth", "answer the myth quiz")]
        Returns the matched label, or None if nothing fits / LLM unavailable.
        Blocking — call this from a background thread, never the render loop.
        """
        if not text or not text.strip():
            return None

        if BACKEND_URL:
            label = self._classify_intent_backend(text, options)
            if label is not None:
                return label

        if not self.groq_client:
            return None

        option_lines = "\n".join(f"{i}. {label}: {desc}" for i, (label, desc) in enumerate(options, 1))
        prompt = (
            "You are an intent classifier for a live interactive AI booth. "
            "A visitor just said or typed the following (it may be transcribed "
            "imperfectly, and may be in English, Urdu, Hindi, Arabic, or French):\n"
            f'"{text}"\n\n'
            "Pick the single best-matching option below — the visitor may refer "
            "to it by its label, its description, or its number (e.g. \"one\", "
            "\"1\", or the number spoken in their own language) — or reply with "
            "exactly NONE if nothing reasonably matches. Reply with ONLY the "
            "option label and nothing else — no punctuation, no explanation.\n\n"
            f"{option_lines}"
        )
        try:
            resp = self.groq_client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=150,
                reasoning_effort="low",
            )
            label = resp.choices[0].message.content.strip().strip('"').strip("'").lower()
            valid_labels = {l.lower() for l, _ in options}
            return label if label in valid_labels else None
        except Exception as e:
            print(f"[AudioService] Groq intent classification failed: {e}")
            return None
