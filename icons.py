import math
import os
import struct
import zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(BASE_DIR, "static", "icons")

SVG_ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="navyBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#132038"/>
      <stop offset="100%" stop-color="#0b1324"/>
    </linearGradient>
    <linearGradient id="sunGrad" x1="50%" y1="0%" x2="50%" y2="100%">
      <stop offset="0%" stop-color="#fbbf24"/>
      <stop offset="45%" stop-color="#fb923c"/>
      <stop offset="100%" stop-color="#ea580c"/>
    </linearGradient>
    <clipPath id="badgeClip">
      <circle cx="256" cy="256" r="186"/>
    </clipPath>
  </defs>
  <rect width="512" height="512" rx="112" fill="url(#navyBg)"/>
  <circle cx="256" cy="256" r="218" fill="#17253d" opacity="0.55"/>
  <g clip-path="url(#badgeClip)">
    <circle cx="256" cy="256" r="186" fill="url(#sunGrad)"/>
    <path d="M56 266 L152 152 L192 146 L236 186 L284 134 L318 134 L452 266 Z" fill="#2c3a4f"/>
    <path d="M366 266 Q374 232 390 208" fill="none" stroke="#162235" stroke-width="9" stroke-linecap="round"/>
    <path d="M390 208 Q364 196 346 212 Q368 208 390 212 Z" fill="#162235"/>
    <path d="M390 208 Q420 204 432 220 Q412 214 390 212 Z" fill="#162235"/>
    <path d="M62 372 Q256 344 450 372 L450 456 L62 456 Z" fill="#ffffff"/>
    <path d="M62 368 Q256 344 450 368" fill="none" stroke="#0f172a" stroke-width="10" stroke-linecap="round"/>
  </g>
  <g stroke="#0f172a" stroke-width="10" stroke-linejoin="round" stroke-linecap="round">
    <circle cx="164" cy="330" r="42" fill="#1e293b"/>
    <circle cx="164" cy="330" r="22" fill="#ffffff" stroke="#ea580c" stroke-width="8"/>
    <circle cx="352" cy="330" r="42" fill="#1e293b"/>
    <circle cx="352" cy="330" r="22" fill="#ffffff" stroke="#ea580c" stroke-width="8"/>
    <path d="M120 296 L194 334 L184 350 L114 310 Z" fill="#e2e8f0"/>
    <path d="M132 248 L224 252 Q246 278 274 282 L300 250 L282 214 Q282 198 308 198 L340 220 L360 254 Q362 276 336 286 L312 346 L232 346 L186 322 L126 274 Z" fill="#ffffff"/>
    <path d="M148 242 Q204 236 254 268 L244 278 Q196 258 144 256 Z" fill="#1e293b"/>
    <path d="M308 196 L326 184 L348 220 L330 224 Z" fill="#f97316"/>
    <path d="M332 232 L356 244 L350 258 L328 246 Z" fill="#f97316"/>
    <path d="M214 304 L286 312 L278 326 L210 318 Z" fill="#f97316"/>
    <path d="M324 286 Q364 276 384 300 L352 302 Z" fill="#ffffff"/>
    <path d="M262 204 L298 198 L286 178" fill="none" stroke="#ffffff" stroke-width="10"/>
    <ellipse cx="268" cy="172" rx="14" ry="9" fill="#ffffff"/>
  </g>
</svg>
"""


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)


def _write_rgba_png(path: str, size: int, pixel_fn) -> None:
    """Render an RGBA square PNG of given size using pure Python + zlib."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter type 0 (None)
        ny = (y + 0.5) / size
        for x in range(size):
            nx = (x + 0.5) / size
            r, g, b, a = pixel_fn(nx, ny, size)
            rows.extend((r, g, b, a))

    ihdr = struct.pack("!IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(rows), level=6)
    png_data = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png_data)


def _sd_rounded_box(px: float, py: float, bx: float, by: float, r: float) -> float:
    qx = abs(px) - bx + r
    qy = abs(py) - by + r
    return (
        math.hypot(max(qx, 0.0), max(qy, 0.0))
        + min(max(qx, qy), 0.0)
        - r
    )


def _sd_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    denom = bax * bax + bay * bay
    h = 0.0 if denom == 0 else max(0.0, min(1.0, (pax * bax + pay * bay) / denom))
    return math.hypot(pax - bax * h, pay - bay * h)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _blend(bg: tuple[int, int, int], fg: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, alpha))
    return (
        int(round(_lerp(bg[0], fg[0], t))),
        int(round(_lerp(bg[1], fg[1], t))),
        int(round(_lerp(bg[2], fg[2], t))),
    )


def _render_pixel(nx: float, ny: float, size: int, maskable: bool) -> tuple[int, int, int, int]:
    px = nx - 0.5
    py = ny - 0.5
    aa = 1.5 / size
    scale = 0.78 if maskable else 1.0

    # Background slate gradient (#0f172a -> #1e293b)
    grad_t = max(0.0, min(1.0, (nx + ny) * 0.5))
    bg = (
        int(round(_lerp(15, 30, grad_t))),
        int(round(_lerp(23, 41, grad_t))),
        int(round(_lerp(42, 59, grad_t))),
    )

    if maskable:
        outer_alpha = 1.0
    else:
        sd_box = _sd_rounded_box(px, py, 0.5, 0.5, 0.22)
        outer_alpha = max(0.0, min(1.0, 0.5 - sd_box / aa))
        if outer_alpha <= 0.0:
            return (0, 0, 0, 0)

    sx, sy = px / scale, py / scale

    # Subtle inner track ring
    dist_center = math.hypot(sx, sy)
    inner_ring_sd = abs(dist_center - 0.215) - 0.011
    inner_ring_alpha = max(0.0, min(1.0, 0.5 - inner_ring_sd / (aa / scale)))
    color = _blend(bg, (51, 65, 85), inner_ring_alpha)

    # Orange outer wheel/speedometer ring
    outer_ring_sd = abs(dist_center - 0.335) - 0.028
    outer_ring_alpha = max(0.0, min(1.0, 0.5 - outer_ring_sd / (aa / scale)))
    orange_top = (251, 146, 60)
    orange_bot = (234, 88, 12)
    ring_col = (
        int(round(_lerp(orange_top[0], orange_bot[0], grad_t))),
        int(round(_lerp(orange_top[1], orange_bot[1], grad_t))),
        int(round(_lerp(orange_top[2], orange_bot[2], grad_t))),
    )
    color = _blend(color, ring_col, outer_ring_alpha)

    # Top accent dot
    dot_sd = math.hypot(sx, sy + 0.215) - 0.036
    dot_alpha = max(0.0, min(1.0, 0.5 - dot_sd / (aa / scale)))
    color = _blend(color, (251, 146, 60), dot_alpha)

    # Bold white geometric "M" (MotoRide emblem)
    segs = (
        (-0.185, 0.125, -0.115, -0.115),
        (-0.115, -0.115, 0.0, 0.025),
        (0.0, 0.025, 0.115, -0.115),
        (0.115, -0.115, 0.185, 0.125),
    )
    min_d = min(_sd_segment(sx, sy, *seg) for seg in segs) - 0.033
    m_alpha = max(0.0, min(1.0, 0.5 - min_d / (aa / scale)))
    color = _blend(color, (255, 255, 255), m_alpha)

    return (color[0], color[1], color[2], int(round(outer_alpha * 255)))


def ensure_icons(force: bool = False) -> None:
    """Create SVG and PNG PWA icons if they do not already exist."""
    svg_path = os.path.join(ICONS_DIR, "icon.svg")
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable.png", 512, True),
        ("apple-touch-icon.png", 180, False),
    ]
    if not force and os.path.exists(svg_path) and all(
        os.path.exists(os.path.join(ICONS_DIR, filename)) for filename, _, _ in targets
    ):
        return

    os.makedirs(ICONS_DIR, exist_ok=True)
    if force or not os.path.exists(svg_path):
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(SVG_ICON)

    for filename, size, maskable in targets:
        out_path = os.path.join(ICONS_DIR, filename)
        if force or not os.path.exists(out_path):
            _write_rgba_png(
                out_path,
                size,
                lambda nx, ny, s, m=maskable: _render_pixel(nx, ny, s, m),
            )


if __name__ == "__main__":
    ensure_icons(force=True)
    print("Generated icons in", ICONS_DIR)
