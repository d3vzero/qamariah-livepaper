"""presipitasi: hujan dan petir (kabut danau ada di scenes/valley.py: memakai garis danau valley)."""
import math

from qlp.weather import wind_px


def _frac(x):
    return x - math.floor(x)


_RAIN_CACHE = []


def _rain_drops(n):
    """(rx, ry, sp) tiap butir hujan; hanya bergantung pada indeks."""
    while len(_RAIN_CACHE) < n:
        i = len(_RAIN_CACHE)
        rx, ry = _frac(math.sin(i * 12.9898) * 43758.5453), _frac(math.sin(i * 78.233) * 12345.678)
        _RAIN_CACHE.append((rx, ry, 0.8 + 0.4 * _frac(rx * 7.31)))
    return _RAIN_CACHE[:n]


def draw_rain(ctx, w, y0, y1, h_total, wx, t):
    """garis hujan dalam koordinat layar global [y0, y1) digambar relatif ke y0."""
    n = int(wx["rain"] * 380)
    if n == 0:
        return
    vy = 1100 * h_total / 1600
    vx = wind_px(wx, w) * 2.5
    length = 26 * h_total / 1600
    sx = vx / vy * length
    ctx.set_line_width(1.2)
    ctx.set_source_rgba(1, 1, 1, 0.10 + 0.14 * wx["rain"])
    mo = wx.get("_mo")
    if mo:
        shift = (mo.pos(("rain", w), lambda m, t: wind_px(m, w) * 2.5 * t / w, t) % 1.0) * w
    for rx, ry, sp in _rain_drops(n):
        y = (ry * h_total + vy * sp * t) % h_total
        if y < y0 - length or y >= y1:
            continue
        if mo:
            x = (rx * w + shift) % w
        else:
            x = (rx * w + vx * t) % w
        ctx.move_to(x, y - y0)
        ctx.line_to(x + sx, y - y0 + length)
    ctx.stroke()


def draw_lightning(ctx, wx, t, cfg):
    if not (wx["thunder"] and cfg["lightning"]):
        return
    k = math.floor(t / 6.0)                         # tiap ~6 detik ada peluang kilat
    if _frac(math.sin(k * 91.7) * 5531.3) < 0.25 and _frac(t / 6.0) * 6.0 < 0.18:
        ctx.set_source_rgba(1, 1, 1, 0.07 * wx["thunder"])
        ctx.paint()
