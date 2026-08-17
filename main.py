"""
Axon Interactive AI Booth — Pygame FSM engine.

States: IDLE_VISION -> LANG_SELECT -> GAME_MENU -> {GAME_HIDING | GAME_MYTH |
GAME_WHEEL} -> HUMAN_HANDOFF -> back to IDLE_VISION.

Keyboard overrides (always active, per SRD section 5):
  ESC       reset to IDLE_VISION
  SPACE     skip current audio / force next state
  1-6       manually trigger building grid options (GAME_HIDING) or
            language / game-menu options where applicable
  S         force-trigger swag wheel spin
  ENTER     open a type-instead-of-speak box (whenever the booth would
            otherwise be listening); the typed line is run through the
            same phrase parsing as a real voice transcript
"""
import math
import os
import random
import sys
import threading
import time

import pygame

import config
import text_render
import theme
from audio_service import AudioService
from vision_service import VisionService

# Must run before pygame opens a window: without this, Windows treats the
# process as DPI-unaware and silently bitmap-stretches its rendered output
# to fill the real panel whenever display scaling is above 100% (e.g. a
# 1920x1080 monitor at 125% scaling reports as 1536x864 to the app) — that
# stretch is what cuts off the top/bottom/left of the booth UI.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# State names
# ---------------------------------------------------------------------------
IDLE_VISION = "IDLE_VISION"
LANG_SELECT = "LANG_SELECT"
GAME_MENU = "GAME_MENU"
GAME_HIDING = "GAME_HIDING"
GAME_MYTH = "GAME_MYTH"
GAME_WHEEL = "GAME_WHEEL"
HUMAN_HANDOFF = "HUMAN_HANDOFF"


def load_asset(filename, size=None, mode="contain"):
    """Load a PNG from assets/. `mode`='contain' fits within size (letterbox,
    preserves alpha/aspect); 'cover' fills size, center-cropping overflow."""
    path = os.path.join(config.ASSETS_DIR, filename)
    try:
        img = pygame.image.load(path).convert_alpha()
    except Exception as e:
        print(f"[main] Warning: could not load {filename}: {e}")
        surf = pygame.Surface(size or (300, 300), pygame.SRCALPHA)
        surf.fill((40, 50, 70, 255))
        return surf

    if not size:
        return img

    src_w, src_h = img.get_size()
    dst_w, dst_h = size

    if mode == "cover":
        scale = max(dst_w / src_w, dst_h / src_h)
        new_w, new_h = round(src_w * scale), round(src_h * scale)
        scaled = pygame.transform.smoothscale(img, (new_w, new_h))
        out = pygame.Surface(size, pygame.SRCALPHA)
        out.blit(scaled, ((dst_w - new_w) // 2, (dst_h - new_h) // 2))
        return out
    else:  # contain
        scale = min(dst_w / src_w, dst_h / src_h)
        new_w, new_h = round(src_w * scale), round(src_h * scale)
        scaled = pygame.transform.smoothscale(img, (new_w, new_h))
        out = pygame.Surface(size, pygame.SRCALPHA)
        out.blit(scaled, ((dst_w - new_w) // 2, (dst_h - new_h) // 2))
        return out


class BoothApp:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        # `window` is the real OS surface (whatever size/DPI the monitor
        # actually is); `screen` is a fixed 1920x1080 canvas that every draw
        # method targets unchanged. Presenting scales+letterboxes `screen`
        # onto `window`, so layout math never has to know the real display's
        # resolution or aspect ratio — and nothing gets clipped at the edges.
        self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("Axon Interactive AI Booth")
        self.screen = pygame.Surface((config.WIDTH, config.HEIGHT))
        self.clock = pygame.time.Clock()

        self.font_title = pygame.font.SysFont(config.FONT_NAME, config.FONT_TITLE_SIZE, bold=True)
        self.font_subtitle = pygame.font.SysFont(config.FONT_NAME, config.FONT_SUBTITLE_SIZE)
        self.font_card = pygame.font.SysFont(config.FONT_NAME, config.FONT_CARD_SIZE, bold=True)
        self.font_banner = pygame.font.SysFont(config.FONT_NAME, config.FONT_BANNER_SIZE, bold=True)
        self.font_small = pygame.font.SysFont(config.FONT_NAME, config.FONT_SMALL_SIZE)
        self.font_wordmark = pygame.font.SysFont(config.FONT_NAME, config.FONT_WORDMARK_SIZE, bold=True)

        self._load_assets()

        self.vision = VisionService()
        self.vision.start()
        self.audio = AudioService()

        self.language = config.DEFAULT_LANGUAGE
        self.state = IDLE_VISION
        self.state_entered_at = time.time()
        self.face_hold_start = None
        self._spoken_for_state = False
        self._listen_started = False
        self.pending_transcript = None
        self.listening = False
        self.pending_llm_intent = None
        self._speech_generation = 0

        # Type-instead-of-speak fallback — same phrase parsing as a real
        # voice transcript, useful whenever the mic isn't cooperating.
        self.text_input_active = False
        self.text_input_buffer = ""

        # Cross-fade: snapshot of the previous state's frame, blended out
        # over _TRANSITION_DURATION instead of a hard cut.
        self._prev_frame = None
        self._transition_start = None
        self._TRANSITION_DURATION = 0.25

        self.hiding_choice = None
        self.myth_answer = None
        self.wheel_spinning = False
        self.wheel_angle = 0.0
        self.wheel_spin_start = 0.0
        self.wheel_spin_duration = config.WHEEL_SPIN_DURATION
        self.wheel_target_angle = 0.0
        self.wheel_result_index = None

        self.running = True

    # ------------------------------------------------------------------
    def _load_assets(self):
        c = config
        self.img_axon_mischievous = load_asset(c.ASSET_AXON_MISCHIEVOUS, c.MASCOT_OVERLAY_SIZE)
        self.img_axon_waving = load_asset(c.ASSET_AXON_WAVING, c.MASCOT_OVERLAY_SIZE)
        self.img_axon_thinking = load_asset(c.ASSET_AXON_THINKING, c.MASCOT_OVERLAY_SIZE)
        self.img_axon_jumping = load_asset(c.ASSET_AXON_JUMPING, c.MASCOT_OVERLAY_SIZE)

        # Idle hero "breathing" scale: precompute the whole cycle once
        # rather than calling smoothscale() (expensive) on every single
        # frame for what's a ~2% size wobble.
        self._idle_breath_frames = []
        w, h = self.img_axon_mischievous.get_size()
        steps = 32
        for i in range(steps):
            s = 1.15 + 0.02 * math.sin(i / steps * 2 * math.pi)
            self._idle_breath_frames.append(
                pygame.transform.smoothscale(self.img_axon_mischievous, (round(w * s), round(h * s)))
            )

        self.buildings = []
        for b in c.BUILDINGS:
            card_img = load_asset(b["img"], c.CARD_SIZE, mode="cover")
            card_img = theme.round_corners(card_img, radius=14)
            self.buildings.append({
                **b,
                "card_img": card_img,
                "reveal_costume": load_asset(b["reveal_img"], c.REVEAL_COSTUME_SIZE, mode="contain"),
            })

        self.grid_positions = []
        sx, sy = c.GRID_START
        gx, gy = c.GRID_GAP
        for i in range(6):
            col, row = i % 3, i // 3
            self.grid_positions.append((sx + col * gx, sy + row * gy))

        self.bg_gradient = theme.vertical_gradient(
            (c.WIDTH, c.HEIGHT), c.BG_COLOR_TOP, c.BG_COLOR_BOTTOM
        )
        # Bake the ambient texture + edge darkening into the static
        # background once at load time rather than compositing extra
        # full-screen layers every frame.
        self.bg_gradient.blit(theme.tech_grid((c.WIDTH, c.HEIGHT), c.ACCENT_COLOR), (0, 0))
        self.bg_gradient.blit(theme.vignette((c.WIDTH, c.HEIGHT), max_alpha=150), (0, 0))

        self.glow_accent = theme.radial_glow(420, c.ACCENT_COLOR, max_alpha=40)
        self.glow_accent2 = theme.radial_glow(360, c.ACCENT_COLOR_2, max_alpha=32)

        # Brand chrome: gradient logo ring (mirrors the mascot's glowing
        # eye visor) and the hairline that separates header/footer bars
        # from the content area.
        self.logo_ring = theme.conic_ring(56, c.BRAND_GRADIENT, thickness=7)
        self.brand_hline = theme.horizontal_gradient_surface((c.WIDTH, 3), c.BRAND_GRADIENT)
        self.header_h = 100
        self.footer_h = 44

    # ------------------------------------------------------------------
    # State transition helper
    # ------------------------------------------------------------------
    def goto(self, new_state):
        if new_state != self.state:
            self._prev_frame = self.screen.copy()
            self._transition_start = time.time()

        self.state = new_state
        self.state_entered_at = time.time()
        self._spoken_for_state = False
        self._listen_started = False
        self.pending_transcript = None

        # A new state means whatever was still playing/queued for the old
        # one is no longer relevant — cut it off now, and invalidate any
        # slower-to-synthesize line still in flight so it can't land on top
        # of the new state's speech.
        self._speech_generation += 1
        self.audio.set_generation(self._speech_generation)
        self.audio.stop_speaking()

        if new_state == IDLE_VISION:
            self.face_hold_start = None
            self.hiding_choice = None
            self.myth_answer = None
            self.wheel_spinning = False
            self.wheel_result_index = None

    def speak_once(self, key):
        """Speak the localized string for `key` exactly once per state entry."""
        if not self._spoken_for_state:
            self._spoken_for_state = True
            self.audio.speak(config.t(self.language, key), self.language,
                              generation=self._speech_generation)

    def start_listening_once(self):
        if self._listen_started or not self.audio.voice_input_available:
            return
        self._listen_started = True
        self.listening = True

        def _cb(transcript):
            self.pending_transcript = transcript or ""
            self.listening = False

        # Language isn't chosen yet during LANG_SELECT, so let STT
        # auto-detect; every later state biases decoding to self.language.
        lang_hint = None if self.state == LANG_SELECT else self.language
        self.audio.listen_async(_cb, lang_code=lang_hint)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type != pygame.KEYDOWN:
            return

        if self.text_input_active:
            self._handle_text_input_key(event)
            return

        if event.key == pygame.K_ESCAPE:
            self.goto(IDLE_VISION)
            return

        if event.key == pygame.K_SPACE:
            self._force_advance()
            return

        if event.key == pygame.K_s and self.state == GAME_WHEEL:
            self._start_wheel_spin()
            return

        if event.key == pygame.K_RETURN and self._text_input_eligible():
            self.text_input_active = True
            self.text_input_buffer = ""
            return

        num_keys = {
            pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
            pygame.K_4: 4, pygame.K_5: 5, pygame.K_6: 6,
        }
        if event.key in num_keys:
            self._handle_number(num_keys[event.key])
            return

        if self.state == GAME_MYTH:
            if event.key == pygame.K_t:
                self._answer_myth(True)
            elif event.key == pygame.K_f:
                self._answer_myth(False)

    def _text_input_eligible(self):
        """States where the booth would otherwise be listening for a voice
        answer — the same states typing can stand in for."""
        if self.state in (LANG_SELECT, GAME_MENU):
            return True
        if self.state == GAME_HIDING:
            return self.hiding_choice is None
        if self.state == GAME_WHEEL:
            return not self.wheel_spinning
        return False

    def _handle_text_input_key(self, event):
        if event.key == pygame.K_ESCAPE:
            self.text_input_active = False
            self.text_input_buffer = ""
        elif event.key == pygame.K_RETURN:
            text = self.text_input_buffer.strip()
            self.text_input_active = False
            self.text_input_buffer = ""
            if text:
                self._process_transcript(text)
        elif event.key == pygame.K_BACKSPACE:
            self.text_input_buffer = self.text_input_buffer[:-1]
        elif event.unicode and event.unicode.isprintable():
            self.text_input_buffer += event.unicode

    def _force_advance(self):
        order = {
            IDLE_VISION: LANG_SELECT,
            LANG_SELECT: GAME_MENU,
            GAME_MENU: GAME_HIDING,
            GAME_HIDING: HUMAN_HANDOFF,
            GAME_MYTH: HUMAN_HANDOFF,
            GAME_WHEEL: HUMAN_HANDOFF,
            HUMAN_HANDOFF: IDLE_VISION,
        }
        self.goto(order.get(self.state, IDLE_VISION))

    def _handle_number(self, n):
        if self.state == LANG_SELECT:
            if 1 <= n <= len(config.LANGUAGES):
                self.language = config.LANGUAGES[n - 1]["code"]
                self.goto(GAME_MENU)
        elif self.state == GAME_MENU:
            if n == 1:
                self.goto(GAME_HIDING)
            elif n == 2:
                self.goto(GAME_MYTH)
            elif n == 3:
                self.goto(GAME_WHEEL)
        elif self.state == GAME_HIDING:
            if 1 <= n <= 6 and self.hiding_choice is None:
                self.hiding_choice = n - 1
                self.audio.speak(config.t(self.language, "reveal_pitch"), self.language,
                                  generation=self._speech_generation)

    def _answer_myth(self, answer_true):
        if self.myth_answer is not None:
            return
        self.myth_answer = answer_true
        key = "myth_true_reaction" if answer_true else "myth_false_reaction"
        self.audio.speak(config.t(self.language, key), self.language,
                          generation=self._speech_generation)

    def _start_wheel_spin(self):
        if self.wheel_spinning:
            return
        self.wheel_spinning = True
        self.wheel_spin_start = time.time()
        n = len(config.WHEEL_PRIZES)
        self.wheel_result_index = random.randrange(n)
        slice_deg = 360.0 / n
        target_slice_center = self.wheel_result_index * slice_deg + slice_deg / 2
        extra_spins = 360.0 * random.randint(4, 6)
        self.wheel_target_angle = extra_spins + (360 - target_slice_center)

    # ------------------------------------------------------------------
    # Per-state update logic
    # ------------------------------------------------------------------
    def update(self, dt):
        if self.state == IDLE_VISION:
            self._update_idle()
        elif self.state == LANG_SELECT:
            self._update_lang_select()
        elif self.state == GAME_MENU:
            self._update_game_menu()
        elif self.state == GAME_HIDING:
            self._update_game_hiding()
        elif self.state == GAME_MYTH:
            self.speak_once("myth_question")
        elif self.state == GAME_WHEEL:
            self._update_game_wheel(dt)
        elif self.state == HUMAN_HANDOFF:
            self._update_handoff()

        if self.pending_transcript:
            self._process_transcript(self.pending_transcript)
            self.pending_transcript = None

        if self.pending_llm_intent:
            generation, state, label = self.pending_llm_intent
            self.pending_llm_intent = None
            # Only act if the app is still where the classification was
            # requested for — otherwise it's a stale answer to a question
            # that's no longer being asked.
            if label and generation == self._speech_generation and state == self.state:
                self._apply_intent(state, label)

    def _update_idle(self):
        self.speak_once("welcome")
        if self.vision.face_present():
            if self.face_hold_start is None:
                self.face_hold_start = time.time()
            elif time.time() - self.face_hold_start >= config.FACE_DETECT_HOLD_TIME:
                self.goto(LANG_SELECT)
        else:
            self.face_hold_start = None

    def _update_lang_select(self):
        self.speak_once("lang_prompt")
        self.start_listening_once()

    def _update_game_menu(self):
        self.speak_once("game_menu_prompt")
        self.start_listening_once()

    def _update_game_hiding(self):
        self.speak_once("hiding_prompt")
        if self.hiding_choice is None:
            self.start_listening_once()
        else:
            if time.time() - self.state_entered_at > 6.0:
                self.goto(HUMAN_HANDOFF)

    def _update_game_wheel(self, dt):
        self.speak_once("wheel_prompt")
        if not self.wheel_spinning:
            self.start_listening_once()
        else:
            elapsed = time.time() - self.wheel_spin_start
            progress = min(elapsed / self.wheel_spin_duration, 1.0)
            eased = 1 - (1 - progress) ** 3  # ease-out cubic deceleration
            self.wheel_angle = eased * self.wheel_target_angle
            if progress >= 1.0:
                self.wheel_spinning = False
                if time.time() - self.wheel_spin_start > self.wheel_spin_duration + 2.0:
                    self.goto(HUMAN_HANDOFF)

    def _update_handoff(self):
        self.speak_once("handoff_audio")
        if time.time() - self.state_entered_at >= config.HANDOFF_TIMEOUT:
            self.goto(IDLE_VISION)

    def _process_transcript(self, transcript):
        text = transcript.lower().strip()
        if not text:
            return

        if self.state == LANG_SELECT:
            # Language select always keeps moving (unclear speech just
            # defaults to English) rather than waiting on a slower LLM
            # round-trip for the very first interaction.
            for i, lang in enumerate(config.LANGUAGES):
                if any(k in text for k in lang["keywords"]):
                    self.language = lang["code"]
                    self.goto(GAME_MENU)
                    return
            self.language = config.DEFAULT_LANGUAGE
            self.goto(GAME_MENU)
            return

        elif self.state == GAME_MENU:
            if "1" in text or "hid" in text:
                self.goto(GAME_HIDING)
                return
            elif "2" in text or "myth" in text:
                self.goto(GAME_MYTH)
                return
            elif "3" in text or "spin" in text or "wheel" in text:
                self.goto(GAME_WHEEL)
                return

        elif self.state == GAME_HIDING and self.hiding_choice is None:
            for n in "123456":
                if n in text:
                    self._handle_number(int(n))
                    return

        elif self.state == GAME_WHEEL and not self.wheel_spinning:
            if "spin" in text:
                self._start_wheel_spin()
                return

        # No literal keyword matched — ask the LLM (if configured) to
        # interpret more natural phrasing, e.g. "I'd like to see the
        # hospital one" instead of a bare "1" or "healthcare". This resolves
        # asynchronously (network call) so the render loop never blocks on
        # it; see _try_llm_intent / pending_llm_intent in update().
        self._try_llm_intent(text)

    def _intent_options_for_state(self, state):
        """Valid (label, description) choices the LLM may pick between for
        the given state — mirrors the literal keyword checks above, used
        only when those don't match anything."""
        if state == GAME_MENU:
            return [
                ("hiding", "Play the hiding game — guess which industry Axon is hiding in"),
                ("myth", "Answer the AI myth-vs-fact quiz question"),
                ("wheel", "Spin the prize / swag wheel"),
            ]
        if state == GAME_HIDING:
            return [(str(i + 1), b["name"]) for i, b in enumerate(config.BUILDINGS)]
        if state == GAME_WHEEL:
            return [("spin", "Spin the wheel / I'm ready / give me a prize")]
        return None

    def _try_llm_intent(self, text):
        if not self.audio.llm_available:
            return
        options = self._intent_options_for_state(self.state)
        if not options:
            return

        state, generation = self.state, self._speech_generation

        def _run():
            label = self.audio.classify_intent(text, options)
            self.pending_llm_intent = (generation, state, label)

        threading.Thread(target=_run, daemon=True).start()

    def _apply_intent(self, state, label):
        """Act on an LLM-classified label — only called from update() after
        confirming the app is still in the same state it was classified for."""
        if state == GAME_MENU:
            if label == "hiding":
                self.goto(GAME_HIDING)
            elif label == "myth":
                self.goto(GAME_MYTH)
            elif label == "wheel":
                self.goto(GAME_WHEEL)
        elif state == GAME_HIDING and self.hiding_choice is None and label in "123456":
            self._handle_number(int(label))
        elif state == GAME_WHEEL and not self.wheel_spinning and label == "spin":
            self._start_wheel_spin()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self):
        self.screen.blit(self.bg_gradient, (0, 0))
        self._draw_header()

        if self.state == IDLE_VISION:
            self._draw_idle()
        elif self.state == LANG_SELECT:
            self._draw_lang_select()
        elif self.state == GAME_MENU:
            self._draw_game_menu()
        elif self.state == GAME_HIDING:
            self._draw_game_hiding()
        elif self.state == GAME_MYTH:
            self._draw_game_myth()
        elif self.state == GAME_WHEEL:
            self._draw_game_wheel()
        elif self.state == HUMAN_HANDOFF:
            self._draw_handoff()

        if self.text_input_active:
            self._draw_text_input_box()
        elif self._text_input_eligible():
            self._draw_type_hint()

        self._draw_footer()
        theme.draw_corner_frame(self.screen, (config.WIDTH, config.HEIGHT), config.BRAND_GRADIENT)

        self._apply_transition()
        self._present()

    def _draw_type_hint(self):
        hint = self.font_small.render(
            "Press ENTER to type instead of speaking", True, config.DIM_TEXT_COLOR
        )
        self.screen.blit(hint, (44, config.HEIGHT - self.footer_h - 38))

    def _draw_text_input_box(self):
        box_w, box_h = 900, 74
        rect = pygame.Rect(0, 0, box_w, box_h)
        rect.center = (config.WIDTH // 2, config.HEIGHT - self.footer_h - 60)
        theme.draw_card(self.screen, rect, radius=16, fill=config.CARD_FILL_ALT,
                         glow_border=config.ACCENT_COLOR)

        cursor = "|" if int(time.time() * 2) % 2 == 0 else ""
        if self.text_input_buffer:
            text_surf = self.font_subtitle.render(self.text_input_buffer + cursor, True, config.TEXT_COLOR)
        else:
            text_surf = self.font_subtitle.render("Type what you'd say…" + cursor, True, config.DIM_TEXT_COLOR)
        self.screen.blit(text_surf, (rect.x + 26, rect.centery - text_surf.get_height() // 2))

        hint = self.font_small.render("Enter to submit  •  Esc to cancel", True, config.DIM_TEXT_COLOR)
        self.screen.blit(hint, hint.get_rect(midtop=(rect.centerx, rect.bottom + 10)))

    def _apply_transition(self):
        """Cross-fade the previous state's frame out over the new one
        instead of a hard cut between states."""
        if self._prev_frame is None or self._transition_start is None:
            return
        elapsed = time.time() - self._transition_start
        if elapsed >= self._TRANSITION_DURATION:
            self._prev_frame = None
            self._transition_start = None
            return
        alpha = int(255 * (1 - elapsed / self._TRANSITION_DURATION))
        self._prev_frame.set_alpha(alpha)
        self.screen.blit(self._prev_frame, (0, 0))

    def _present(self):
        win_w, win_h = self.window.get_size()
        scale = min(win_w / config.WIDTH, win_h / config.HEIGHT)
        new_w = max(1, int(config.WIDTH * scale))
        new_h = max(1, int(config.HEIGHT * scale))
        scaled = pygame.transform.smoothscale(self.screen, (new_w, new_h))
        self.window.fill((0, 0, 0))
        self.window.blit(scaled, ((win_w - new_w) // 2, (win_h - new_h) // 2))
        pygame.display.flip()

    def _draw_header(self):
        header_h = self.header_h
        bar = pygame.Surface((config.WIDTH, header_h), pygame.SRCALPHA)
        pygame.draw.rect(bar, (8, 9, 15, 205), (0, 0, config.WIDTH, header_h))
        self.screen.blit(bar, (0, 0))

        mid_y = header_h // 2
        ring_rect = self.logo_ring.get_rect(midleft=(40, mid_y))
        self.screen.blit(self.logo_ring, ring_rect)
        pygame.draw.circle(self.screen, (8, 9, 15), ring_rect.center, 21)
        pygame.draw.circle(self.screen, config.ACCENT_COLOR, ring_rect.center, 5)

        logo = self.font_wordmark.render("AXON", True, config.TEXT_COLOR)
        logo_pos = (ring_rect.right + 20, mid_y - logo.get_height() // 2)
        self.screen.blit(logo, logo_pos)

        tag_rect = pygame.Rect(0, 0, 128, 32)
        tag_rect.midleft = (logo_pos[0] + logo.get_width() + 18, mid_y)
        theme.draw_pill(self.screen, tag_rect, (17, 20, 33), alpha=235, border=config.CARD_BORDER_COLOR)
        tag = self.font_small.render("AI BOOTH", True, config.DIM_TEXT_COLOR)
        self.screen.blit(tag, tag.get_rect(center=tag_rect.center))

        if self.text_input_active:
            self._draw_status_pill("Typing…", config.ACCENT_COLOR_2, config.WIDTH - 40, mid_y)
        elif self.listening:
            self._draw_status_pill("Listening…", config.ACCENT_GREEN, config.WIDTH - 40, mid_y)
        elif self.audio.is_speaking:
            self._draw_status_pill("Speaking…", config.ACCENT_COLOR, config.WIDTH - 40, mid_y)
        else:
            idle_rect = pygame.Rect(0, 0, 172, 32)
            idle_rect.midright = (config.WIDTH - 40, mid_y)
            theme.draw_pill(self.screen, idle_rect, (17, 20, 33), alpha=220, border=config.CARD_BORDER_COLOR)
            pygame.draw.circle(self.screen, (90, 96, 116), (idle_rect.x + 22, idle_rect.centery), 5)
            idle_label = self.font_small.render("Standing by", True, config.DIM_TEXT_COLOR)
            self.screen.blit(idle_label, (idle_rect.x + 38, idle_rect.centery - idle_label.get_height() // 2))

        lang_label = next(
            (l["label"] for l in config.LANGUAGES if l["code"] == self.language), "English"
        )
        lang_text = self.font_small.render(lang_label.upper(), True, config.DIM_TEXT_COLOR)
        pill_rect = pygame.Rect(0, 0, lang_text.get_width() + 60, 32)
        pill_rect.midright = (config.WIDTH - 232, mid_y)
        theme.draw_pill(self.screen, pill_rect, (17, 20, 33), alpha=220, border=config.CARD_BORDER_COLOR)
        self.screen.blit(lang_text, lang_text.get_rect(center=pill_rect.center))

        self.screen.blit(self.brand_hline, (0, header_h - 3))

    def _draw_footer(self):
        footer_h = self.footer_h
        y = config.HEIGHT - footer_h
        bar = pygame.Surface((config.WIDTH, footer_h), pygame.SRCALPHA)
        pygame.draw.rect(bar, (8, 9, 15, 175), (0, 0, config.WIDTH, footer_h))
        self.screen.blit(bar, (0, y))
        self.screen.blit(self.brand_hline, (0, y))

    def _draw_status_pill(self, label, color, right_x, y):
        """Animated 'Listening…' / 'Speaking…' pill — replaces the old tiny
        static header dot so visitors get real feedback about when the
        booth is hearing them vs. talking."""
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(time.time() * 6.0))
        text_surf = self.font_small.render(label, True, color)
        pill_rect = pygame.Rect(0, 0, text_surf.get_width() + 54, 34)
        pill_rect.midright = (right_x, y)
        dot_pos = (pill_rect.x + 24, pill_rect.centery)
        glow = theme.radial_glow(30, color, max_alpha=int(140 * pulse))
        self.screen.blit(glow, glow.get_rect(center=dot_pos))
        theme.draw_pill(self.screen, pill_rect, (30, 34, 54), alpha=225, border=color)
        pygame.draw.circle(self.screen, color, dot_pos, 5)
        self.screen.blit(text_surf, (dot_pos[0] + 16, pill_rect.centery - text_surf.get_height() // 2))

    def _draw_title(self, text, color=None, subtitle=None):
        """Titles are long in some languages and the canvas width is fixed,
        so wrap onto multiple lines rather than let text run off both
        edges — the block is anchored so a single-line title still lands
        exactly where it always has."""
        max_width = config.WIDTH - 220
        lines = text_render.wrap_lines(text, self.language, config.FONT_TITLE_SIZE,
                                        max_width, bold=True)
        font = text_render.get_font(config.FONT_TITLE_SIZE, self.language, bold=True)
        line_h = font.get_linesize()
        # Single-line titles stay anchored where they've always sat;
        # multi-line ones grow downward from just under the header instead
        # of upward into it.
        if len(lines) == 1:
            first_center = 158
        else:
            first_center = self.header_h + 20 + line_h // 2
        for i, line in enumerate(lines):
            surf = text_render.render(line, self.language, config.FONT_TITLE_SIZE,
                                       color or config.TEXT_COLOR, bold=True)
            self.screen.blit(surf, surf.get_rect(center=(config.WIDTH // 2, first_center + i * line_h)))
        if subtitle:
            sub_y = first_center + (len(lines) - 1) * line_h + line_h // 2 + 26
            sub_surf = self.font_small.render(subtitle, True, config.DIM_TEXT_COLOR)
            self.screen.blit(sub_surf, sub_surf.get_rect(center=(config.WIDTH // 2, sub_y)))

    def _draw_ambient_glow(self, pos):
        self.screen.blit(self.glow_accent, self.glow_accent.get_rect(center=pos))

    def _draw_option_list(self, items, mascot_img, list_top=340, card_w=840, card_h=104, gap=22):
        mascot_x = 1180
        mascot_y = list_top + max(0, (len(items) * (card_h + gap) - gap - mascot_img.get_height()) // 2)
        glow = theme.radial_glow(260, config.ACCENT_COLOR_2, max_alpha=26)
        self.screen.blit(glow, glow.get_rect(center=(mascot_x + mascot_img.get_width() // 2,
                                                       mascot_y + mascot_img.get_height() // 2)))
        self.screen.blit(mascot_img, (mascot_x, mascot_y))

        y = list_top
        n = len(items)
        for i, text in enumerate(items, start=1):
            card = pygame.Rect(140, y, card_w, card_h)
            accent = theme.brand_color((i - 1) / max(n, 1), config.BRAND_GRADIENT)
            theme.draw_card(self.screen, card, radius=20, fill=config.CARD_FILL, accent_bar=accent)
            badge_center = (card.x + 66, card.centery)
            theme.draw_badge(self.screen, badge_center, 28, i, self.font_card,
                              ring_stops=config.BRAND_GRADIENT)
            label = self.font_card.render(text, True, config.TEXT_COLOR)
            self.screen.blit(label, (card.x + 118, card.centery - label.get_height() // 2))
            y += card_h + gap

    def _draw_idle(self):
        cx, cy = config.WIDTH // 2, config.HEIGHT // 2 - 40
        self._draw_ambient_glow((cx, cy))
        self._draw_title(config.t(self.language, "idle_banner"))

        t = time.time()
        # Two slow concentric rainbow rings breathing outward behind the
        # mascot — reads as "alive" and draws the eye from across a hall,
        # rather than a static portrait nobody's sure is actually running.
        # Radius is quantized so `conic_ring` (cached, ~140 polygon draws
        # to build) is actually reused frame-to-frame instead of rebuilt
        # every frame as a continuously-changing size would force; alpha is
        # applied to the cached surface directly (no per-frame copy — a
        # large SRCALPHA surface copy every frame was the previous cost
        # here, and blit area/count is the other lever, hence 2 rings
        # capped at a smaller max radius rather than 3 growing larger).
        for k in range(2):
            phase = (t * 0.18 + k / 2) % 1.0
            radius = int(round((200 + phase * 200) / 6) * 6)
            alpha = int(90 * (1 - phase))
            if alpha <= 0:
                continue
            ring = theme.conic_ring(radius * 2, config.BRAND_GRADIENT, thickness=3)
            ring.set_alpha(alpha)
            self.screen.blit(ring, ring.get_rect(center=(cx, cy - 60)))

        # Subtle breathing/bob so the booth reads as "alive" while idle —
        # picks a precomputed frame instead of scaling live every frame.
        frame_i = int(t * 1.6 / (2 * math.pi) * len(self._idle_breath_frames)) % len(self._idle_breath_frames)
        scaled = self._idle_breath_frames[frame_i]
        bob = math.sin(t * 1.6) * 10
        h = self.img_axon_mischievous.get_height()
        cy2 = config.HEIGHT // 2 - 100 + h // 2
        self.screen.blit(scaled, (cx - scaled.get_width() // 2, cy2 - scaled.get_height() // 2 + bob))

        self._draw_cta_pill("STEP FORWARD TO BEGIN", cx, config.HEIGHT - 140)
        hint = self.font_small.render("Axon is watching  •  ESC resets anytime", True, config.DIM_TEXT_COLOR)
        self.screen.blit(hint, hint.get_rect(center=(cx, config.HEIGHT - 68)))

    def _draw_cta_pill(self, label, cx, cy):
        """Pulsing gradient-ringed call-to-action — the one thing on the
        idle screen a visitor across the aisle should be able to read."""
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(time.time() * 2.4))
        text_surf = self.font_subtitle.render(label, True, config.TEXT_COLOR)
        pill_rect = pygame.Rect(0, 0, text_surf.get_width() + 76, 66)
        pill_rect.center = (cx, cy)
        # Alpha quantized to steps of 5 so the cached radial_glow surface
        # is actually reused across frames instead of rebuilt continuously.
        glow_alpha = int(70 * pulse) // 5 * 5
        glow = theme.radial_glow(int(pill_rect.width * 0.7), config.ACCENT_COLOR, max_alpha=glow_alpha)
        self.screen.blit(glow, glow.get_rect(center=pill_rect.center))
        theme.draw_card(self.screen, pill_rect, radius=33, fill=(16, 19, 32),
                         glow_border=config.ACCENT_COLOR, border_width=2, shadow=True)
        self.screen.blit(text_surf, text_surf.get_rect(center=pill_rect.center))

    def _draw_lang_select(self):
        self._draw_ambient_glow((1400, 500))
        self._draw_title(config.t(self.language, "lang_prompt"))
        items = [lang["label"] for lang in config.LANGUAGES]
        self._draw_option_list(items, self.img_axon_waving)

    def _draw_game_menu(self):
        self._draw_ambient_glow((1400, 500))
        self._draw_title(config.t(self.language, "game_menu_title"))
        items = [
            "Where is Axon Hiding?",
            "AI Myth vs. Fact",
            "Spin the Swag Wheel",
        ]
        self._draw_option_list(items, self.img_axon_thinking, card_h=120, gap=30)

    def _draw_game_hiding(self):
        revealed = self.hiding_choice is not None
        title_key = "hiding_reveal_title" if revealed else "hiding_title"
        self._draw_title(config.t(self.language, title_key),
                          config.ACCENT_COLOR if revealed else None)

        for i, b in enumerate(self.buildings):
            pos = self.grid_positions[i]
            card_rect = pygame.Rect(pos[0], pos[1], *config.CARD_SIZE)
            is_winner = revealed and i == self.hiding_choice

            theme.blit_shadow(self.screen, card_rect, radius=18,
                               spread=30 if is_winner else 18)
            self.screen.blit(b["card_img"], pos)

            border_color = config.CARD_BORDER_HIGHLIGHT if is_winner else config.CARD_BORDER_COLOR
            pygame.draw.rect(self.screen, border_color, card_rect,
                              4 if is_winner else 2, border_radius=18)

            tag_surf = self.font_small.render(b["name"], True, config.TEXT_COLOR)
            tag_rect = pygame.Rect(0, 0, tag_surf.get_width() + 66, 44)
            tag_rect.bottomleft = (card_rect.x + 14, card_rect.bottom - 14)
            theme.draw_pill(self.screen, tag_rect, (10, 12, 22), alpha=205, border=config.CARD_BORDER_COLOR)
            badge_center = (tag_rect.x + 25, tag_rect.centery)
            theme.draw_badge(self.screen, badge_center, 15, i + 1, self.font_small,
                              ring_stops=config.BRAND_GRADIENT)
            self.screen.blit(tag_surf, (badge_center[0] + 20, tag_rect.centery - tag_surf.get_height() // 2))

            if revealed:
                if is_winner:
                    glow = theme.radial_glow(170, config.ACCENT_COLOR, max_alpha=110)
                    self.screen.blit(glow, glow.get_rect(center=card_rect.center))
                costume = b["reveal_costume"]
                cx = pos[0] + config.CARD_SIZE[0] // 2 - costume.get_width() // 2
                cy = pos[1] + config.CARD_SIZE[1] // 2 - costume.get_height() // 2
                self.screen.blit(costume, (cx, cy))

    def _draw_game_myth(self):
        self._draw_ambient_glow((config.WIDTH // 2, 420))
        self._draw_title(config.t(self.language, "myth_question"))
        self.screen.blit(self.img_axon_thinking, (config.WIDTH // 2 - 160, 300))

        hint_rect = pygame.Rect(0, 0, 480, 60)
        hint_rect.center = (config.WIDTH // 2, 740)
        theme.draw_pill(self.screen, hint_rect, (30, 34, 54), alpha=210, border=config.CARD_BORDER_COLOR)
        hint = self.font_subtitle.render("Press T for True  •  F for False", True, config.DIM_TEXT_COLOR)
        self.screen.blit(hint, hint.get_rect(center=hint_rect.center))

        if self.myth_answer is not None:
            key = "myth_true_reaction" if self.myth_answer else "myth_false_reaction"
            reaction_card = pygame.Rect(0, 0, 1140, 96)
            reaction_card.center = (config.WIDTH // 2, 850)
            theme.draw_card(self.screen, reaction_card, radius=20, fill=config.CARD_FILL_ALT,
                             glow_border=config.ACCENT_COLOR)
            reaction = text_render.render(config.t(self.language, key), self.language,
                                           config.FONT_SUBTITLE_SIZE, config.ACCENT_COLOR)
            self.screen.blit(reaction, reaction.get_rect(center=reaction_card.center))

    def _draw_game_wheel(self):
        self._draw_ambient_glow((config.WIDTH // 2, 590))
        self._draw_title(config.t(self.language, "wheel_title"))
        self._draw_wheel(center=(config.WIDTH // 2, 600), radius=280, angle_deg=self.wheel_angle)

        if not self.wheel_spinning and self.wheel_result_index is None:
            hint_rect = pygame.Rect(0, 0, 320, 60)
            hint_rect.center = (config.WIDTH // 2, 965)
            theme.draw_pill(self.screen, hint_rect, (30, 34, 54), alpha=210, border=config.CARD_BORDER_COLOR)
            hint = self.font_subtitle.render("Press S to spin!", True, config.DIM_TEXT_COLOR)
            self.screen.blit(hint, hint.get_rect(center=hint_rect.center))
        elif not self.wheel_spinning and self.wheel_result_index is not None:
            prize = config.WHEEL_PRIZES[self.wheel_result_index]
            result_card = pygame.Rect(0, 0, 660, 96)
            result_card.center = (config.WIDTH // 2, 965)
            theme.draw_card(self.screen, result_card, radius=20, fill=config.CARD_FILL_ALT,
                             glow_border=config.ACCENT_COLOR)
            result = self.font_banner.render(f"You won: {prize}!", True, config.ACCENT_COLOR)
            self.screen.blit(result, result.get_rect(center=result_card.center))

    def _draw_wheel(self, center, radius, angle_deg):
        n = len(config.WHEEL_PRIZES)
        slice_deg = 360.0 / n
        cx, cy = center

        shadow_glow = theme.radial_glow(radius + 50, (0, 0, 0), max_alpha=90)
        self.screen.blit(shadow_glow, shadow_glow.get_rect(center=(cx, cy + 18)))

        for i in range(n):
            start = math.radians(angle_deg + i * slice_deg)
            end = math.radians(angle_deg + (i + 1) * slice_deg)
            points = [center]
            steps = 12
            for s in range(steps + 1):
                a = start + (end - start) * (s / steps)
                points.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
            pygame.draw.polygon(self.screen, config.WHEEL_COLORS[i % len(config.WHEEL_COLORS)], points)
            pygame.draw.polygon(self.screen, (12, 14, 24), points, 2)

            mid_a = math.radians(angle_deg + i * slice_deg + slice_deg / 2)
            label_pos = (cx + radius * 0.66 * math.cos(mid_a), cy + radius * 0.66 * math.sin(mid_a))
            label_surf = self.font_small.render(config.WHEEL_PRIZES[i], True, (255, 255, 255))
            pill_rect = pygame.Rect(0, 0, label_surf.get_width() + 20, label_surf.get_height() + 10)
            pill_rect.center = label_pos
            theme.draw_pill(self.screen, pill_rect, (10, 12, 22), alpha=150)
            self.screen.blit(label_surf, label_surf.get_rect(center=label_pos))

        rim = theme.conic_ring(radius * 2 + 44, config.BRAND_GRADIENT, thickness=18)
        self.screen.blit(rim, rim.get_rect(center=center))
        pygame.draw.circle(self.screen, (222, 226, 236), center, radius, 5)
        pygame.draw.circle(self.screen, (140, 146, 168), center, radius, 1)

        hub_ring = theme.conic_ring(84, config.BRAND_GRADIENT, thickness=7)
        self.screen.blit(hub_ring, hub_ring.get_rect(center=center))
        pygame.draw.circle(self.screen, (12, 14, 24), center, 33)
        pygame.draw.circle(self.screen, config.ACCENT_COLOR_2, center, 10)

        pointer = [(cx - 22, cy - radius - 8), (cx + 22, cy - radius - 8), (cx, cy - radius + 30)]
        theme.blit_shadow(self.screen, pygame.Rect(cx - 22, cy - radius - 8, 44, 38), radius=8, spread=10)
        pygame.draw.polygon(self.screen, (242, 244, 250), pointer)
        pygame.draw.polygon(self.screen, (140, 146, 168), pointer, 2)

    def _draw_handoff(self):
        self._draw_ambient_glow((config.WIDTH // 2, 550))
        self._draw_title(config.t(self.language, "handoff_banner"), config.ACCENT_COLOR,
                          subtitle="Resetting in a few seconds…")
        self.screen.blit(self.img_axon_jumping, (config.WIDTH // 2 - 160, 400))
        self._draw_countdown_ring(
            center=(config.WIDTH // 2, 940), radius=34,
            elapsed=time.time() - self.state_entered_at, duration=config.HANDOFF_TIMEOUT,
        )

    def _draw_countdown_ring(self, center, radius, elapsed, duration):
        """Radial progress ring that depletes over `duration` seconds —
        gives a visible, non-abrupt cue for an auto-reset instead of the
        state just vanishing without warning."""
        progress = max(0.0, min(elapsed / duration, 1.0))
        remaining = max(0, math.ceil(duration - elapsed))
        pygame.draw.circle(self.screen, (40, 46, 68), center, radius, 5)
        if progress < 1.0:
            rect = pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)
            start_angle = math.pi / 2
            end_angle = start_angle + (1 - progress) * 2 * math.pi
            pygame.draw.arc(self.screen, config.ACCENT_COLOR, rect, start_angle, end_angle, 5)
        label = self.font_small.render(str(int(remaining)), True, config.TEXT_COLOR)
        self.screen.blit(label, label.get_rect(center=center))

    # ------------------------------------------------------------------
    def run(self):
        try:
            while self.running:
                dt = self.clock.tick(config.FPS) / 1000.0
                for event in pygame.event.get():
                    self.handle_event(event)
                self.update(dt)
                self.draw()
        finally:
            self.vision.stop()
            pygame.quit()


if __name__ == "__main__":
    app = BoothApp()
    app.run()
    sys.exit()
