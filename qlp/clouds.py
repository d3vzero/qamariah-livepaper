"""awan: awan garis (scene sea) dan awan tinta (scene valley), dengan cache sprite."""
import math
import random

from qlp.weather import RAIN_EPS, V_CLOUDS_MAX, wind_px


_CLOUD_CACHE = {}


def _cloud_cluster(c, ox, base, scale, r, line_al, lw):
    """satu gumpalan awan bergaya garis: kontur luar putih, isi hitam (menutupi bintang),
    dasar datar berupa garis horizontal yang memanjang keluar dari awan."""
    import cairo
    k = 5 + r.randint(0, 4)
    width = scale * 2.0
    puffs = []
    for j in range(k):
        u = j / (k - 1)
        rad = scale * (0.18 + 0.36 * math.sin(math.pi * u) ** 0.8 * r.uniform(0.75, 1.1))
        puffs.append((ox + (u - 0.5) * width + r.uniform(-0.06, 0.06) * scale,
                      base - rad * r.uniform(0.35, 0.65), rad))
    for _ in range(r.randint(0, 2)):                # gumpalan puncak
        rad = scale * r.uniform(0.2, 0.32)
        puffs.append((ox + r.uniform(-0.35, 0.35) * width, base - scale * r.uniform(0.55, 0.8), rad))

    def circles(shrink=0.0):
        for px, py, pr in puffs:
            c.new_sub_path()
            c.arc(px, py, max(1.0, pr - shrink), 0, 2 * math.pi)

    c.save()
    c.rectangle(ox - width * 2, base - scale * 3, width * 4, scale * 3)
    c.clip()                                         # dasar awan datar
    c.set_operator(cairo.OPERATOR_SOURCE)            # ganti (bukan tumpuk) → garis awan
    circles()                                        # di belakangnya benar-benar tertutup
    c.set_source_rgb(0, 0, 0)                 # tutup bintang/bulan di belakang
    c.fill()
    c.set_operator(cairo.OPERATOR_OVER)
    circles()
    c.set_source_rgba(1, 1, 1, line_al)
    c.set_line_width(lw)
    c.stroke()
    c.set_operator(cairo.OPERATOR_SOURCE)            # hapus lengkung di dalam awan
    circles(lw * 0.75)
    c.set_source_rgb(0, 0, 0)
    c.fill()
    c.set_operator(cairo.OPERATOR_OVER)
    c.restore()

    left = min(px - pr for px, py, pr in puffs)
    right = max(px + pr for px, py, pr in puffs)
    c.set_source_rgba(1, 1, 1, line_al)
    c.set_line_width(lw)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    ext_l, ext_r = scale * r.uniform(0.0, 0.9), scale * r.uniform(0.2, 1.1)
    c.move_to(left - ext_l, base)                    # garis dasar memanjang keluar
    c.line_to(right + ext_r, base)
    c.stroke()
    if r.random() < 0.6:                             # garis angin pendek di bawahnya
        y = base + scale * r.uniform(0.10, 0.22)
        x1 = r.uniform(left - scale * 0.8, left + width * 0.3)
        c.move_to(x1, y)
        c.line_to(x1 + scale * r.uniform(0.5, 1.4), y)
        c.stroke()


def _cloud_sprites(w, h, n, heavy, line_al, quant=False):
    """awan dirender sekali ke sprite; per frame cukup ditempel (hemat CPU)."""
    import cairo
    import random
    key = (w, h, n, round(heavy, 2), round(line_al, 3), quant)
    if key in _CLOUD_CACHE:
        return _CLOUD_CACHE[key]
    lw = max(1.5, w / 1000)
    sprites = []
    for i in range(n):
        r = random.Random(i * 7919 + 13)
        scale = w * (0.035 + 0.05 * r.random()) * heavy
        cy = h * (0.10 + 0.58 * r.random())
        speed_f = (0.6 + 0.8 * r.random()) * (1.3 - cy / h)    # awan rendah lebih cepat
        x0 = r.random()
        sw, sh = int(scale * 7), int(scale * 2.2)
        ox, oy = sw / 2, sh - scale * 0.45          # titik dasar awan di dalam sprite
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
        c = cairo.Context(surf)
        _cloud_cluster(c, ox, oy, scale, r, line_al, lw)
        if r.random() < 0.55:                        # gumpalan kedua di depan (kesan kedalaman)
            _cloud_cluster(c, ox + r.choice((-1, 1)) * scale * r.uniform(0.7, 1.3),
                           oy + scale * r.uniform(0.08, 0.2), scale * r.uniform(0.5, 0.75),
                           r, line_al, lw)
        # potong ke isi sebenarnya (alpha > 0) + margin 2px
        surf.flush()
        import numpy as np
        sh_s = surf.get_height()
        sw_s = surf.get_width()
        stride = surf.get_stride()
        a = np.frombuffer(surf.get_data(), np.uint8).reshape(sh_s, stride)[:, :sw_s*4].reshape(sh_s, sw_s, 4)[:, :, 3]
        mask = a > 0
        if mask.any():
            y0m, y1m = np.where(mask.any(axis=1))[0][[0, -1]]
            x0m, x1m = np.where(mask.any(axis=0))[0][[0, -1]]
            x0m = max(0, x0m - 2)
            x1m = min(sw_s - 1, x1m + 2)
            y0m = max(0, y0m - 2)
            y1m = min(sh_s - 1, y1m + 2)
            new_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, x1m - x0m + 1, y1m - y0m + 1)
            c2 = cairo.Context(new_surf)
            c2.set_operator(cairo.OPERATOR_SOURCE)
            c2.set_source_surface(surf, -x0m, -y0m)
            c2.paint()
            surf = new_surf
            ox -= x0m
            oy -= y0m
        sprites.append((surf, ox, oy, x0, cy, speed_f, scale))
    if len(_CLOUD_CACHE) > 8:
        _CLOUD_CACHE.clear()
    _CLOUD_CACHE[key] = sprites
    return sprites


def draw_clouds(ctx, w, h, a, wx, t, cfg):
    cover = wx["cover"]
    n = wx.get("clouds", round(cover * cfg["clouds_max"]))
    if n <= 0:
        return
    vx = wind_px(wx, w)
    moon_lit = a["illum"] if (a["moon"][0] > 0 and a["night"] > 0) else 0
    # garis awan: terang di siang hari, redup di malam (lebih jelas saat bulan terang)
    line_al = 0.75 * (1 - a["night"]) + a["night"] * (0.28 + 0.35 * moon_lit)
    line_al *= 1.0 - 0.2 * min(1.0, wx["rain"] / RAIN_EPS)
    heavy = 1 + 0.35 * wx["rain"]
    quant = "_mo" in wx
    if quant:
        heavy, line_al = round(heavy, 2), round(line_al, 3)   # saat transisi: sprite tidak dibuat ulang tiap frame
    sprites = _cloud_sprites(w, h, math.ceil(n), heavy, line_al, quant)
    mo = wx.get("_mo")
    for i, (surf, ox, oy, x0, cy, speed_f, scale) in enumerate(sprites):
        span = w + 7 * scale
        if mo:
            base = scale / heavy
            track = lambda m, t, x0=x0, k=speed_f, base=base: x0 + wind_px(m, w) * k * t / (w + 7 * base * (1 + 0.35 * m["rain"]))
            cx = (mo.pos(("cloud", w, h, i), track, t) % 1.0) * span - 3.5 * scale
        else:
            cx = (x0 * span + vx * speed_f * t) % span - 3.5 * scale
        ctx.set_source_surface(surf, cx - ox, cy - oy)
        fade = min(1.0, n - i)                       # awan terakhir memudar masuk/keluar
        if fade >= 1.0:
            ctx.paint()
        else:
            ctx.paint_with_alpha(fade)


# ── awan: sapuan kuas tinta yang lembut ──────────────────────────────────────
_V_INK = {}


def _v_ink_sprite(W, seed, heavy, quant=False):
    """satu gumpalan awan: beberapa elips bergradasi lembut yang memanjang
    mendatar, tanpa garis tepi. Disimpan sebagai gambar (dibuat sekali)."""
    import cairo
    key = (W, seed, round(heavy, 1), quant)
    if key in _V_INK:
        return _V_INK[key]
    rng = random.Random(seed)
    s = W / 2560
    w, h = int(rng.uniform(420, 760) * s * heavy), int(rng.uniform(110, 190) * s * heavy)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c = cairo.Context(surf)
    for _ in range(int(11 * heavy) + 5):
        # tiap elips muat utuh di dalam gambar: tepi tetap lembut, tidak terpotong
        rx, ry = rng.uniform(0.09, 0.22) * w, rng.uniform(0.16, 0.34) * h
        cx = rng.uniform(rx, w - rx)
        cy = min(h - ry, max(ry, h * (0.62 - 0.35 * (1 - abs(cx / w - 0.5) * 2) * rng.random())))
        al = rng.uniform(0.3, 0.75)
        c.save()
        c.translate(cx, cy); c.scale(rx, ry)
        gr = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
        gr.add_color_stop_rgba(0.0, 1, 1, 1, al)
        gr.add_color_stop_rgba(0.6, 1, 1, 1, al * 0.35)
        gr.add_color_stop_rgba(1.0, 1, 1, 1, 0)
        c.set_source(gr); c.arc(0, 0, 1, 0, 2 * math.pi); c.fill()
        c.restore()
    # serat kuas: goresan mendatar tipis di bagian bawah gumpalan
    c.set_line_cap(1)
    for _ in range(int(10 * heavy)):
        y = rng.uniform(0.62, 0.8) * h
        x0 = rng.uniform(0.12, 0.45) * w
        c.move_to(x0, y); c.line_to(min(w * 0.9, x0 + rng.uniform(0.2, 0.4) * w), y + rng.uniform(-2, 2) * s)
        c.set_source_rgba(1, 1, 1, rng.uniform(0.15, 0.35)); c.set_line_width(rng.uniform(1, 3) * s)
        c.stroke()
    if len(_V_INK) > 200:
        _V_INK.clear()
    _V_INK[key] = (surf, w, h)
    return _V_INK[key]


def ink_clouds(ctx, W, h_sky, wx, night, moon_lit, t, lum=1.0):
    """awan tinta; wx = cuaca (boleh hasil transisi)."""
    n = wx.get("clouds", round(wx["cover"] * V_CLOUDS_MAX))
    if n <= 0:
        return
    rain = wx["rain"]
    vx = wind_px(wx, W)
    heavy = 1 + 0.6 * rain
    # siang jelas, malam samar (lebih terlihat saat bulan terang)
    alpha = (0.42 * (1 - night) + night * (0.10 + 0.22 * moon_lit)) * (1 + 0.4 * rain) * lum
    mo = wx.get("_mo")
    if mo:                                          # saat transisi: campur dua sprite heavy terdekat
        lo = math.floor(heavy * 10) / 10            # (kelipatan 0,1), bukan dibuat ulang tiap frame
        f = heavy * 10 - lo * 10
        mix = [(hq, wq) for hq, wq in ((round(lo, 1), 1 - f), (round(lo + 0.1, 1), f)) if wq > 1e-6]
    for i in range(math.ceil(n)):
        r = random.Random(500 + i)
        if not mo:
            surf, w, h = _v_ink_sprite(W, 100 + i, heavy)
            span = W + w
            x = (r.random() * span + vx * (0.6 + 0.5 * r.random()) * t) % span - w
            y = (0.06 + 0.62 * r.random()) * h_sky - h / 2
            ctx.set_source_surface(surf, x, y)
            ctx.paint_with_alpha(min(1.0, alpha * (0.7 + 0.5 * r.random())) * min(1.0, n - i))
            continue
        x0 = r.random()
        k = 0.6 + 0.5 * r.random()
        yr = r.random()
        al = min(1.0, alpha * (0.7 + 0.5 * r.random())) * min(1.0, n - i)
        track = lambda m, t, i=i, x0=x0, k=k: x0 + wind_px(m, W) * k * t / (
            W + _v_ink_sprite(W, 100 + i, round(1 + 0.6 * m["rain"], 1), True)[1])
        q = mo.pos(("ink", W, i), track, t) % 1.0
        for hq, wq in mix:
            surf, w, h = _v_ink_sprite(W, 100 + i, hq, True)
            ctx.set_source_surface(surf, q * (W + w) - w, (0.06 + 0.62 * yr) * h_sky - h / 2)
            ctx.paint_with_alpha(al * wq)
