"""
Small set of drawing helpers that give the booth a consistent, "designed"
look — soft card shadows, gradients, rounded-corner image masking, badges,
brand-gradient rings/frames — instead of flat single-color rectangles
everywhere. The brand mascot's signature look (neon green->cyan->blue->
purple ring glow on near-black) is reused throughout via `brand_color()`
and `conic_ring()` so every accent in the booth reads as one family.
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


_grid_cache = {}


def tech_grid(size, color, spacing=64, alpha=14):
    """Faint dot grid for ambient texture — reads as "designed tech
    surface" instead of a flat void behind the content."""
    key = (size, color, spacing, alpha)
    cached = _grid_cache.get(key)
    if cached is not None:
        return cached
    w, h = size
    surf = pygame.Surface(size, pygame.SRCALPHA)
    for gy in range(0, h, spacing):
        for gx in range(0, w, spacing):
            pygame.draw.circle(surf, (*color, alpha), (gx, gy), 1)
    _grid_cache[key] = surf
    return surf


def draw_corner_frame(surface, size, stops, margin=28, arm=64, thickness=3):
    """Four HUD-style corner brackets in the brand gradient — the kind of
    framing device that reads as "built for a stage/booth display" rather
    than a plain rectangle of content floating on a background."""
    w, h = size
    corners = [
        ((margin, margin), (1, 1), 0.02),
        ((w - margin, margin), (-1, 1), 0.27),
        ((margin, h - margin), (1, -1), 0.52),
        ((w - margin, h - margin), (-1, -1), 0.77),
    ]
    for (ox, oy), (sx, sy), t in corners:
        color = brand_color(t, stops)
        pygame.draw.line(surface, color, (ox, oy), (ox + arm * sx, oy), thickness)
        pygame.draw.line(surface, color, (ox, oy), (ox, oy + arm * sy), thickness)


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


def draw_card(surface, rect, radius=16, fill=(22, 26, 42), border=(70, 82, 116),
              border_width=2, shadow=True, top_highlight=True, glow_border=None,
              accent_bar=None):
    if shadow:
        blit_shadow(surface, rect, radius=radius)
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if top_highlight:
        hl = pygame.Surface((rect.width, rect.height // 2), pygame.SRCALPHA)
        pygame.draw.rect(hl, (255, 255, 255, 12), (0, 0, rect.width, rect.height // 2),
                          border_top_left_radius=radius, border_top_right_radius=radius)
        surface.blit(hl, (rect.x, rect.y))
    if accent_bar:
        # A slim brand-colored spine down the left edge — gives each card
        # its own identity without redrawing the whole border in color.
        bar = pygame.Surface((5, rect.height - 20), pygame.SRCALPHA)
        pygame.draw.rect(bar, accent_bar, (0, 0, 5, rect.height - 20), border_radius=3)
        surface.blit(bar, (rect.x + 10, rect.y + 10))
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
