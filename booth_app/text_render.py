"""
Rendering helper for multilingual on-screen text.

Pygame/SDL_ttf draws Devanagari (Hindi) correctly out of the box *if* a
Devanagari-capable font is used — the "unclear" Hindi text was actually
just tofu boxes from "Segoe UI, Arial" having no Devanagari glyphs, fixed
by picking "Nirmala UI" (config.FONT_NAME_BY_LANG).

Arabic and Urdu are the scripts that genuinely need work: they're
cursive-joining and right-to-left, so hand SDL_ttf a raw logical-order
string and it draws each letter in its isolated form, left to right —
disconnected and backwards. `shape()` fixes both: arabic_reshaper swaps
each letter for its correct initial/medial/final presentation-form glyph
(so adjacent letters visually connect), and python-bidi reorders the
string into visual (left-to-right-drawable) order.
"""
import arabic_reshaper
from bidi.algorithm import get_display
import pygame

import config

_RESHAPE_LANGS = {"ar", "ur"}
_font_cache = {}


def get_font(size, lang_code, bold=False):
    """Cached SysFont using the right family for `lang_code`."""
    family = config.FONT_NAME_BY_LANG.get(lang_code, config.FONT_NAME)
    key = (size, family, bold)
    font = _font_cache.get(key)
    if font is None:
        font = pygame.font.SysFont(family, size, bold=bold)
        _font_cache[key] = font
    return font


def shape(text, lang_code):
    """Reshape+reorder RTL text for correct display; no-op otherwise."""
    if lang_code in _RESHAPE_LANGS:
        return get_display(arabic_reshaper.reshape(text))
    return text


def render(text, lang_code, size, color, bold=False):
    """Render localized `text` with the correct font/shaping for `lang_code`."""
    font = get_font(size, lang_code, bold=bold)
    return font.render(shape(text, lang_code), True, color)


def wrap_lines(text, lang_code, size, max_width, bold=False):
    """Split `text` into logical-order lines that each fit `max_width` at
    the given size — titles are long, screens are fixed-width, and a title
    that doesn't fit needs to wrap rather than run off both edges.

    Word-wrapping happens on the unshaped, logical-order string (word
    order is the same regardless of script), and each finished line is
    shaped independently when rendered — a fine approximation for a kiosk
    display, even though it can't join letters exactly at a line break for
    Arabic/Urdu.
    """
    font = get_font(size, lang_code, bold=bold)
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and font.size(trial)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [text]
