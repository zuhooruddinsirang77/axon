"""
Drawing helpers that give the booth a consistent, premium "designed" look —
soft shadows, glass-style gradient panels, gradient-filled headline type,
gradient rings and buttons — instead of flat single-color rectangles and
generic dashboard chrome (grid textures, HUD corner brackets, pill-boxed
labels). The brand mascot's signature look (neon green->cyan->blue->purple
ring glow on near-black) is reused throughout via `brand_color()`,
`conic_ring()` and `gradient_text()` so every accent and headline in the
booth reads as one family, not a template with a color swapped in.
"""
import math

import numpy as np
import pygame


def vertical_gradient(size, top_color, bottom_color):
    w, h = size
    surf = pygame.Surface(size)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
        pygame.draw.line(surf, color, (0, y), (w, y))
    return surf


def horizontal_gradient_surface(size, stops):
    """Left-to-right multi-stop gradient (`stops` = list of RGB colors,
    evenly spaced). Used for rainbow divider lines / gradient fills."""
    w, h = size
    surf = pygame.Surface(size, pygame.SRCALPHA)
    n = len(stops) - 1
    for x in range(w):
        t = x / max(w - 1, 1)
        color = brand_color(t, stops, loop=False)
        pygame.draw.line(surf, color, (x, 0), (x, h))
    return surf


def brand_color(t, stops, loop=True):
    """Interpolate a color at position `t` (0..1) across `stops` (a list of
    RGB tuples). With `loop=True` the last stop blends back into the first,
    so it can be sampled repeatedly (badge numbers, wheel slices, etc.) and
    always stay within the brand palette."""
    n = len(stops)
    span = n if loop else n - 1
    t = t % 1.0 if loop else max(0.0, min(t, 1.0))
    pos = t * span
    i = int(pos) % n
    frac = pos - int(pos)
    a = stops[i]
    b = stops[(i + 1) % n]
    return tuple(int(a[c] + (b[c] - a[c]) * frac) for c in range(3))


_ring_cache = {}


def conic_ring(size, stops, thickness=10, steps=140, start_deg=-90):
    """A smooth ring that sweeps through `stops` around its circumference —
    the same gradient-ring language as the mascot's glowing eye visor.
    Cached since it's expensive to rebuild every frame."""
    key = (size, tuple(stops), thickness, steps, start_deg)
    cached = _ring_cache.get(key)
    if cached is not None:
        return cached

    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size / 2
    outer_r = size / 2 - 1
    inner_r = max(0.0, outer_r - thickness)
    start = math.radians(start_deg)
    for i in range(steps):
        t0 = i / steps
        t1 = (i + 1) / steps
        color = brand_color((t0 + t1) / 2, stops)
        a0 = start + t0 * 2 * math.pi
        a1 = start + t1 * 2 * math.pi + 0.02  # tiny overlap avoids seam gaps
        pts = [
            (cx + outer_r * math.cos(a0), cy + outer_r * math.sin(a0)),
            (cx + outer_r * math.cos(a1), cy + outer_r * math.sin(a1)),
            (cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1)),
            (cx + inner_r * math.cos(a0), cy + inner_r * math.sin(a0)),
        ]
        pygame.draw.polygon(surf, color, pts)
    _ring_cache[key] = surf
    return surf


_vignette_cache = {}


def vignette(size, max_alpha=150):
    """Darkens the screen edges/corners so the center of the canvas reads as
    the focal point on a big, bright event display."""
    key = (size, max_alpha)
    cached = _vignette_cache.get(key)
    if cached is not None:
        return cached

    w, h = size
    cx, cy = w / 2, h / 2
    max_dist = math.hypot(cx, cy)
    # Downsample for speed, then scale up — a per-pixel loop at 1920x1080
    # is wasteful for a soft radial falloff nobody needs pixel-accurate.
    step = 8
    small_w, small_h = w // step + 1, h // step + 1
    y, x = np.ogrid[:small_h, :small_w]
    dist = np.sqrt((x * step - cx) ** 2 + (y * step - cy) ** 2)
    t = np.clip((dist / max_dist - 0.45) / 0.55, 0, 1)
    alpha = (max_alpha * t ** 1.6).astype(np.uint8)

    small = pygame.Surface((small_w, small_h), pygame.SRCALPHA)
    alpha_view = pygame.surfarray.pixels_alpha(small)
    alpha_view[:, :] = alpha.T
    del alpha_view
    surf = pygame.transform.smoothscale(small, size)
    _vignette_cache[key] = surf
    return surf


_glow_cache = {}


def radial_glow(radius, color, max_alpha=110):
    """A soft round glow, brightest at center, fading to nothing at radius.

    Computed as an exact per-pixel alpha gradient (not stacked translucent
    circles — compositing many overlapping alpha layers of the same color
    washes out to near-full opacity at the center well before max_alpha).
    """
    key = (radius, color, max_alpha)
    cached = _glow_cache.get(key)
    if cached is not None:
        return cached

    size = radius * 2
    y, x = np.ogrid[:size, :size]
    dist = np.sqrt((x - radius) ** 2 + (y - radius) ** 2)
    t = np.clip(dist / radius, 0, 1)
    alpha = (max_alpha * (1 - t) ** 2).astype(np.uint8)  # shape (size, size), symmetric so [y,x]==[x,y]

    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    rgb_view = pygame.surfarray.pixels3d(surf)
    alpha_view = pygame.surfarray.pixels_alpha(surf)
    rgb_view[:, :, 0] = color[0]
    rgb_view[:, :, 1] = color[1]
    rgb_view[:, :, 2] = color[2]
    alpha_view[:, :] = alpha
    del rgb_view, alpha_view  # release the surface locks held by these array views

    _glow_cache[key] = surf
    return surf


def round_corners(surface, radius):
    """Return a copy of `surface` with its alpha masked to rounded corners."""
    size = surface.get_size()
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, *size), border_radius=radius)
    out = surface.copy()
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def gradient_text(text_surf, stops):
    """Recolor a rendered text surface (white glyphs, transparent elsewhere)
    with a left-to-right brand gradient — the signature move that makes a
    headline read as *this brand's* type instead of generic white-on-dark
    UI text. Same alpha-mask trick as `round_corners`: multiplying a solid
    gradient by the glyph mask keeps the gradient's color everywhere the
    glyph is opaque and drops to transparent everywhere it isn't, edges
    included since antialiased pixels carry partial alpha."""
    w, h = text_surf.get_size()
    grad = horizontal_gradient_surface((max(w, 1), max(h, 1)), stops)
    grad.blit(text_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return grad


_panel_cache = {}


def glass_panel(size, radius, top_color, bottom_color, top_alpha=255, bottom_alpha=255):
    """A soft vertical-gradient rounded panel — reads as a lit glass/card
    surface rather than a flat color swatch. Cached since card sizes repeat
    across a screen."""
    key = (size, radius, top_color, bottom_color, top_alpha, bottom_alpha)
    cached = _panel_cache.get(key)
    if cached is not None:
        return cached
    w, h = size
    surf = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
        a = int(top_alpha + (bottom_alpha - top_alpha) * t)
        pygame.draw.line(surf, (*color, a), (0, y), (w, y))
    out = round_corners(surf, radius)
    _panel_cache[key] = out
    return out


_button_cache = {}


def gradient_button(size, stops, radius):
    """A solid brand-gradient pill/rounded-rect fill — for the one or two
    moments per screen that should read as an unmissable, premium action
    rather than an outlined box."""
    key = (size, tuple(stops), radius)
    cached = _button_cache.get(key)
    if cached is not None:
        return cached
    grad = horizontal_gradient_surface(size, stops)
    out = round_corners(grad, radius)
    _button_cache[key] = out
    return out


_ellipse_cache = {}


def soft_ellipse(size, color=(0, 0, 0), max_alpha=120):
    """A soft blurred ellipse — grounds a floating character/object on a
    surface (a stage shadow) instead of it hanging in a void."""
    key = (size, color, max_alpha)
    cached = _ellipse_cache.get(key)
    if cached is not None:
        return cached
    circle = radial_glow(max(size), color, max_alpha)
    out = pygame.transform.smoothscale(circle, size)
    _ellipse_cache[key] = out
    return out


def make_shadow(size, radius=16, color=(0, 0, 0), max_alpha=110, spread=20):
    """Precompute a soft drop-shadow surface sized to fit `size` + spread margin."""
    w, h = size
    shadow_surf = pygame.Surface((w + spread * 2, h + spread * 2), pygame.SRCALPHA)
    layers = 14
    for i in range(layers, 0, -1):
        t = i / layers
        alpha = max(1, int(max_alpha * (1 - t) ** 1.6 / layers * 2.2))
        pad = int(spread * t)
        rect = pygame.Rect(spread - pad, spread - pad, w + pad * 2, h + pad * 2)
        pygame.draw.rect(shadow_surf, (*color, alpha), rect, border_radius=radius + pad // 2)
    return shadow_surf


_shadow_cache = {}


def blit_shadow(surface, rect, radius=16, spread=20, offset=(0, 10)):
    key = (rect.width, rect.height, radius, spread)
    shadow_surf = _shadow_cache.get(key)
    if shadow_surf is None:
        shadow_surf = make_shadow((rect.width, rect.height), radius=radius, spread=spread)
        _shadow_cache[key] = shadow_surf
    surface.blit(shadow_surf, (rect.x - spread + offset[0], rect.y - spread + offset[1]))


def draw_card(surface, rect, radius=16, fill=(22, 26, 42), fill_bottom=None,
              border=(70, 82, 116), border_width=2, shadow=True, specular=True,
              glow_border=None):
    """A glass-style panel: soft vertical gradient fill (reads as a lit
    surface, not a flat swatch) plus a small soft highlight blob near the
    top-left corner, like light catching an edge — instead of a uniform
    translucent band across the whole top half."""
    if shadow:
        blit_shadow(surface, rect, radius=radius)
    bottom = fill_bottom or tuple(max(0, c - 10) for c in fill)
    panel = glass_panel((rect.width, rect.height), radius, fill, bottom)
    surface.blit(panel, (rect.x, rect.y))
    if specular:
        # Plain alpha blit, not BLEND_RGBA_ADD: `radial_glow` stores flat
        # white RGB and puts its falloff entirely in the alpha channel, and
        # ADD ignores source alpha for the RGB channels — it was painting a
        # hard-edged solid white disc instead of a soft highlight.
        glow = radial_glow(int(rect.height * 0.85), (255, 255, 255), max_alpha=15)
        spot = (rect.x + int(rect.width * 0.2), rect.y + int(rect.height * 0.18))
        surface.blit(glow, glow.get_rect(center=spot))
    if glow_border:
        pygame.draw.rect(surface, glow_border, rect, border_width + 1, border_radius=radius)
    elif border_width:
        pygame.draw.rect(surface, border, rect, border_width, border_radius=radius)


def draw_badge(surface, center, radius, text, font, ring_color=(0, 220, 255),
                fill=(12, 15, 26), text_color=(255, 255, 255), ring_stops=None):
    if ring_stops:
        ring = conic_ring(radius * 2 + 8, ring_stops, thickness=4)
        surface.blit(ring, ring.get_rect(center=center))
        pygame.draw.circle(surface, fill, center, radius - 1)
    else:
        pygame.draw.circle(surface, fill, center, radius)
        pygame.draw.circle(surface, ring_color, center, radius, 3)
    label = font.render(str(text), True, text_color)
    surface.blit(label, label.get_rect(center=center))


def draw_fading_hline(surface, y, x_center, half_width, color, max_alpha=160):
    line_surf = pygame.Surface((half_width * 2, 2), pygame.SRCALPHA)
    for x in range(half_width * 2):
        t = abs(x - half_width) / half_width
        alpha = int(max_alpha * (1 - t))
        line_surf.set_at((x, 0), (*color, alpha))
        line_surf.set_at((x, 1), (*color, alpha))
    surface.blit(line_surf, (x_center - half_width, y))


def draw_pill(surface, rect, fill, alpha=200, border=None):
    pill = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(pill, (*fill, alpha), (0, 0, rect.width, rect.height), border_radius=rect.height // 2)
    if border:
        pygame.draw.rect(pill, border, (0, 0, rect.width, rect.height), 1, border_radius=rect.height // 2)
    surface.blit(pill, (rect.x, rect.y))
