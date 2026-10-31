"""scene sea: garis gelombang laut dan pantulan matahari/bulan (langit digambar terpisah)."""
import math

from qlp.astro import drift, moon_visible, project, sun_up
from qlp.precip import draw_lightning, draw_rain
from qlp.sky import scene_lum
from qlp.weather import WEATHER_FIXED, sea_rough


_SEA_XS = {}


def _sea_xs(w, step):
    """titik x garis gelombang; dijumlah berulang persis seperti loop asli."""
    key = (w, step)
    if key not in _SEA_XS:
        import numpy as np
        xs = []
        x = -step
        while x <= w + step:
            xs.append(x)
            x += step
        _SEA_XS[key] = (xs, np.array(xs))
    return _SEA_XS[key]


def draw_sea(ctx, w, h, a, t, cfg, h_sky, wx=None):
    import numpy as np
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    dx, dy = drift(t, cfg["drift"])
    ctx.save()
    ctx.translate(dx, dy)
    n = cfg["waves"]
    step = max(6.0, w / 360)
    wx = wx or WEATHER_FIXED["clear"]
    # 0 tenang … 1 badai: dari angin dan hujan
    rough = sea_rough(wx)
    amp0 = h * 0.035 * a["wave_amp"] * (1 + 1.1 * rough)
    direc = a["wave_dir"]
    mo = wx.get("_mo")
    ctx.set_line_cap(1)  # ROUND
    moon_up = moon_visible(a, cfg)
    lum = scene_lum(a, cfg, wx)
    xs, X = _sea_xs(w, step)
    for i in range(n):
        u = (i + 1) / n                              # 0 = cakrawala, 1 = depan
        y0 = h * (u ** 1.7) * 0.92 + h * 0.02
        amp = amp0 * (0.12 + 0.88 * u)
        lam = w * (0.035 + 0.11 * u)
        v = direc * (6 + 34 * u) * (1 + 1.2 * rough)  # px/detik; badai lebih cepat
        ph0 = i * 1.37
        ctx.set_source_rgba(1, 1, 1, (0.16 + 0.50 * u) * lum)
        ctx.set_line_width(0.8 + 1.6 * u)
        if mo:
            c = direc * (6 + 34 * u) / lam
            q = mo.pos(("wave", w, i), lambda m, t, c=c: c * (1 + 1.2 * sea_rough(m)) * t, t) % 1.0
            ph = 2 * math.pi * (X / lam - q) + ph0
        else:
            ph = 2 * math.pi * (X - v * t) / lam + ph0
        ys = y0 + amp * (0.65 * np.sin(ph) + 0.35 * np.sin(1.7 * ph + i)
                         + 0.30 * rough * np.sin(3.3 * ph + 2.1 * t + i))   # riak badai
        ys = ys.tolist()
        ctx.move_to(xs[0], ys[0])
        for x, y in zip(xs[1:], ys[1:]):
            ctx.line_to(x, y)
        ctx.stroke()

    # pantulan berkilau di bawah matahari/bulan
    bodies = []
    if sun_up(a):
        bodies.append((a["sun"], 0.9))
    if moon_up:
        bodies.append((a["moon"], a["illum"]))
    clear_sky = 1 - max(0.0, (wx["cover"] - 0.4) / 0.6)     # mendung → pantulan hilang
    for (alt, az), bright in bodies:
        bright *= clear_sky
        if bright < 0.05:
            continue
        bx, _ = project(alt, az, w, h_sky)
        low = 1 - max(0.0, math.sin(alt))            # makin rendah, makin panjang pantulannya
        rows = 26
        for r in range(rows):
            u = (r + 1) / rows
            y = h * (u ** 1.5) * 0.9 + h * 0.03
            if u > 0.55 + 0.45 * low:
                break
            half = (w * 0.006 + w * 0.03 * u) * (0.55 + 0.45 * math.sin(t * 1.3 + r * 2.1))
            jx = w * 0.003 * math.sin(t * 0.9 + r * 1.7)
            ctx.set_source_rgba(1, 1, 1, bright * (0.80 - 0.45 * u))
            ctx.set_line_width(1.2 + 1.0 * u)
            ctx.move_to(bx + jx - half, y)
            ctx.line_to(bx + jx + half, y)
            ctx.stroke()
    ctx.restore()
    draw_rain(ctx, w, h_sky, h_sky + h, h_sky + h, wx, t)
    draw_lightning(ctx, wx, t, cfg)


# antarmuka scene (dipindai qlp/scenes/__init__.py): NAME = nama di config/menu,
# draw = fungsi bingkai layar penuh, atau None = langit dan laut digambar terpisah
NAME = "sea"
draw = None
