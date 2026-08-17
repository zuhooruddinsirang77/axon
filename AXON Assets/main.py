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
"""
import math
import os
import random
import sys
import time

import pygame

import config
from audio_service import AudioService
from vision_service import VisionService

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
        self.screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT))
        pygame.display.set_caption("Axon Interactive AI Booth")
        self.clock = pygame.time.Clock()

        self.font_title = pygame.font.SysFont(config.FONT_NAME, config.FONT_TITLE_SIZE, bold=True)
        self.font_subtitle = pygame.font.SysFont(config.FONT_NAME, config.FONT_SUBTITLE_SIZE)
        self.font_card = pygame.font.SysFont(config.FONT_NAME, config.FONT_CARD_SIZE, bold=True)
        self.font_banner = pygame.font.SysFont(config.FONT_NAME, config.FONT_BANNER_SIZE, bold=True)
        self.font_small = pygame.font.SysFont(config.FONT_NAME, config.FONT_SMALL_SIZE)

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

        self.buildings = []
        for b in c.BUILDINGS:
            self.buildings.append({
                **b,
                "card_img": load_asset(b["img"], c.CARD_SIZE, mode="cover"),
                "reveal_costume": load_asset(b["reveal_img"], c.REVEAL_COSTUME_SIZE, mode="contain"),
            })

        self.grid_positions = []
        sx, sy = c.GRID_START
        gx, gy = c.GRID_GAP
        for i in range(6):
            col, row = i % 3, i // 3
            self.grid_positions.append((sx + col * gx, sy + row * gy))

    # ------------------------------------------------------------------
    # State transition helper
    # ------------------------------------------------------------------
    def goto(self, new_state):
        self.state = new_state
        self.state_entered_at = time.time()
        self._spoken_for_state = False
        self._listen_started = False
        self.pending_transcript = None
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
            self.audio.speak(config.t(self.language, key), self.language)

    def start_listening_once(self):
        if self._listen_started or not self.audio.voice_input_available:
            return
        self._listen_started = True
        self.listening = True

        def _cb(transcript):
            self.pending_transcript = transcript or ""
            self.listening = False

        self.audio.listen_async(_cb)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type != pygame.KEYDOWN:
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
                self.audio.speak(config.t(self.language, "reveal_pitch"), self.language)

    def _answer_myth(self, answer_true):
        if self.myth_answer is not None:
            return
        self.myth_answer = answer_true
        key = "myth_true_reaction" if answer_true else "myth_false_reaction"
        self.audio.speak(config.t(self.language, key), self.language)

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
            for i, lang in enumerate(config.LANGUAGES):
                if any(k in text for k in lang["keywords"]):
                    self.language = lang["code"]
                    self.goto(GAME_MENU)
                    return
            self.language = config.DEFAULT_LANGUAGE
            self.goto(GAME_MENU)

        elif self.state == GAME_MENU:
            if "1" in text or "hid" in text:
                self.goto(GAME_HIDING)
            elif "2" in text or "myth" in text:
                self.goto(GAME_MYTH)
            elif "3" in text or "spin" in text or "wheel" in text:
                self.goto(GAME_WHEEL)

        elif self.state == GAME_HIDING and self.hiding_choice is None:
            for n in "123456":
                if n in text:
                    self._handle_number(int(n))
                    return

        elif self.state == GAME_WHEEL and not self.wheel_spinning:
            if "spin" in text:
                self._start_wheel_spin()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self):
        self.screen.fill(config.BG_COLOR)
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

        pygame.display.flip()

    def _draw_header(self):
        logo = self.font_subtitle.render("AXON AI BOOTH", True, config.ACCENT_COLOR)
        self.screen.blit(logo, (30, 20))

        lang_label = next(
            (l["label"] for l in config.LANGUAGES if l["code"] == self.language), "English"
        )
        lang_text = self.font_small.render(f"Language: {lang_label}", True, config.DIM_TEXT_COLOR)
        self.screen.blit(lang_text, (config.WIDTH - 420, 26))

        mic_color = (0, 255, 120) if self.listening else (90, 95, 110)
        pygame.draw.circle(self.screen, mic_color, (config.WIDTH - 40, 38), 12)

    def _draw_title(self, text, color=None):
        surf = self.font_title.render(text, True, color or config.TEXT_COLOR)
        self.screen.blit(surf, surf.get_rect(center=(config.WIDTH // 2, 110)))

    def _draw_idle(self):
        self._draw_title(config.t(self.language, "idle_banner"))
        img = self.img_axon_mischievous
        self.screen.blit(img, (config.WIDTH // 2 - img.get_width() // 2, config.HEIGHT // 2 - 100))

    def _draw_lang_select(self):
        self._draw_title(config.t(self.language, "lang_prompt"))
        self.screen.blit(self.img_axon_waving, (1200, 350))

        y = 320
        for i, lang in enumerate(config.LANGUAGES, start=1):
            card = pygame.Rect(150, y, 700, 80)
            pygame.draw.rect(self.screen, (25, 30, 48), card, border_radius=10)
            pygame.draw.rect(self.screen, config.CARD_BORDER_COLOR, card, 2, border_radius=10)
            label = self.font_card.render(f"{i}. {lang['label']}", True, config.TEXT_COLOR)
            self.screen.blit(label, (card.x + 24, card.y + 24))
            y += 100

    def _draw_game_menu(self):
        self._draw_title(config.t(self.language, "game_menu_title"))
        self.screen.blit(self.img_axon_thinking, (1200, 350))

        options = [
            "1. Where is Axon Hiding?",
            "2. AI Myth vs. Fact",
            "3. Spin the Swag Wheel",
        ]
        y = 350
        for opt in options:
            card = pygame.Rect(150, y, 800, 100)
            pygame.draw.rect(self.screen, (25, 30, 48), card, border_radius=10)
            pygame.draw.rect(self.screen, config.CARD_BORDER_COLOR, card, 2, border_radius=10)
            label = self.font_card.render(opt, True, config.TEXT_COLOR)
            self.screen.blit(label, (card.x + 24, card.y + 34))
            y += 130

    def _draw_game_hiding(self):
        revealed = self.hiding_choice is not None
        title_key = "hiding_reveal_title" if revealed else "hiding_title"
        self._draw_title(config.t(self.language, title_key),
                          config.ACCENT_COLOR if revealed else None)

        for i, b in enumerate(self.buildings):
            pos = self.grid_positions[i]
            self.screen.blit(b["card_img"], pos)
            border_color = (
                config.CARD_BORDER_HIGHLIGHT
                if revealed and i == self.hiding_choice
                else config.CARD_BORDER_COLOR
            )
            pygame.draw.rect(
                self.screen, border_color,
                (pos[0], pos[1], *config.CARD_SIZE), 3, border_radius=8
            )
            label = self.font_small.render(f"{i + 1}. {b['name']}", True, config.DIM_TEXT_COLOR)
            self.screen.blit(label, (pos[0] + 10, pos[1] + config.CARD_SIZE[1] + 8))

            if revealed:
                costume = b["reveal_costume"]
                cx = pos[0] + config.CARD_SIZE[0] // 2 - costume.get_width() // 2
                cy = pos[1] + config.CARD_SIZE[1] // 2 - costume.get_height() // 2
                self.screen.blit(costume, (cx, cy))

    def _draw_game_myth(self):
        self._draw_title(config.t(self.language, "myth_question"))
        self.screen.blit(self.img_axon_thinking, (config.WIDTH // 2 - 150, 300))

        hint = self.font_subtitle.render(
            "Press T for True or F for False", True, config.DIM_TEXT_COLOR
        )
        self.screen.blit(hint, hint.get_rect(center=(config.WIDTH // 2, 720)))

        if self.myth_answer is not None:
            key = "myth_true_reaction" if self.myth_answer else "myth_false_reaction"
            reaction = self.font_subtitle.render(config.t(self.language, key), True, config.ACCENT_COLOR)
            self.screen.blit(reaction, reaction.get_rect(center=(config.WIDTH // 2, 800)))

    def _draw_game_wheel(self):
        self._draw_title(config.t(self.language, "wheel_title"))
        self._draw_wheel(center=(config.WIDTH // 2, 620), radius=280, angle_deg=self.wheel_angle)

        if not self.wheel_spinning and self.wheel_result_index is None:
            hint = self.font_subtitle.render("Press S to spin!", True, config.DIM_TEXT_COLOR)
            self.screen.blit(hint, hint.get_rect(center=(config.WIDTH // 2, 980)))
        elif not self.wheel_spinning and self.wheel_result_index is not None:
            prize = config.WHEEL_PRIZES[self.wheel_result_index]
            result = self.font_banner.render(f"You won: {prize}!", True, config.ACCENT_COLOR)
            self.screen.blit(result, result.get_rect(center=(config.WIDTH // 2, 980)))

    def _draw_wheel(self, center, radius, angle_deg):
        n = len(config.WHEEL_PRIZES)
        slice_deg = 360.0 / n
        cx, cy = center

        for i in range(n):
            start = math.radians(angle_deg + i * slice_deg)
            end = math.radians(angle_deg + (i + 1) * slice_deg)
            points = [center]
            steps = 12
            for s in range(steps + 1):
                a = start + (end - start) * (s / steps)
                points.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
            pygame.draw.polygon(self.screen, config.WHEEL_COLORS[i % len(config.WHEEL_COLORS)], points)

            mid_a = math.radians(angle_deg + i * slice_deg + slice_deg / 2)
            label_pos = (cx + radius * 0.65 * math.cos(mid_a), cy + radius * 0.65 * math.sin(mid_a))
            label = self.font_small.render(config.WHEEL_PRIZES[i], True, (10, 10, 20))
            self.screen.blit(label, label.get_rect(center=label_pos))

        pygame.draw.circle(self.screen, (230, 230, 240), center, radius, 6)
        pygame.draw.circle(self.screen, config.BG_COLOR, center, 24)
        pygame.draw.circle(self.screen, config.ACCENT_COLOR, center, 24, 3)

        pointer = [(cx - 18, cy - radius - 10), (cx + 18, cy - radius - 10), (cx, cy - radius + 18)]
        pygame.draw.polygon(self.screen, (255, 255, 255), pointer)

    def _draw_handoff(self):
        self._draw_title(config.t(self.language, "handoff_banner"), config.ACCENT_COLOR)
        self.screen.blit(self.img_axon_jumping, (config.WIDTH // 2 - 150, 400))

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
