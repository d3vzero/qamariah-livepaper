"""scene valley: lukisan tinta (bukit, danau, pohon, burung, kabut danau), satu bingkai layar penuh."""
import math
import random

from qlp.astro import drift, moon_visible, project, radii, sun_up
from qlp.clouds import ink_clouds
from qlp.precip import draw_lightning, draw_rain
from qlp.sky import _cloud_veil, draw_sky_base, scene_lum
from qlp.weather import RAIN_EPS


# ── scene valley: lukisan tinta ────────────────────────────────────────────
# Scene valley (gaya lukisan tinta / shan shui, dibalik untuk layar hitam).
#
# Bukit dan batu berupa isian abu-abu bergradasi yang memudar ke kabut di kaki-
# nya, danau kosong di bawah cakrawala (hanya pantulan matahari dan bulan),
# pohon dedalu dan rumpun bambu yang bergoyang tertiup angin, gerombolan
# burung saat cerah, awan berupa sapuan kuas tinta yang lembut, dan kabut yang
# melayang di atas danau (tebal malam hari, tipis siang hari).
# Koordinat = pecahan layar penuh (W x H), (0,0) kiri atas.
#
# Urutan gambar per frame:
#   1. langit (cache) -> 2. ink_clouds() -> 3. valley_static() (cache, bukit
#   menutupi awan & bintang) -> 4. valley_anim() (pantulan, kabut danau, pohon,
#   burung) -> 5. hujan
#   VALLEY_HORIZON = garis danau (batas langit untuk project()).
VALLEY_HORIZON = 0.70

VALLEY_SLOW_FPS = 4        # awan, pantulan, kabut danau, pohon: diperbarui 4x per detik

# bukit tengah (samar, memudar ke kabut): garis atas sebagai pecahan (x, y)
V_MID_LEFT = [(0.00, 0.47), (0.04, 0.43), (0.08, 0.41), (0.12, 0.43), (0.16, 0.40),
              (0.20, 0.35), (0.235, 0.31), (0.26, 0.30), (0.285, 0.33), (0.30, 0.38),
              (0.33, 0.45), (0.37, 0.52), (0.40, 0.58), (0.43, 0.655), (0.455, 0.70)]

V_MID_LEFT2 = [(0.07, 0.70), (0.12, 0.56), (0.16, 0.52), (0.20, 0.50), (0.24, 0.53), (0.28, 0.58),
               (0.32, 0.62), (0.36, 0.665), (0.40, 0.70)]

V_MID_RIGHT = [(0.635, 0.70), (0.665, 0.65), (0.70, 0.58), (0.74, 0.52), (0.77, 0.47), (0.80, 0.445),
               (0.83, 0.46), (0.86, 0.50), (0.90, 0.53), (0.94, 0.55), (1.00, 0.57)]

V_PILLAR = [(0.575, 0.70), (0.585, 0.66), (0.588, 0.55), (0.595, 0.47), (0.607, 0.425), (0.622, 0.41),
            (0.636, 0.43), (0.645, 0.48), (0.652, 0.56), (0.656, 0.66), (0.665, 0.70)]

# batu depan (lebih terang = lebih dekat), menyentuh danau
V_FRONT_LEFT = [(0.00, 0.50), (0.04, 0.53), (0.08, 0.57), (0.12, 0.585), (0.16, 0.565),
                (0.20, 0.555), (0.23, 0.58), (0.27, 0.615), (0.31, 0.635), (0.36, 0.655),
                (0.42, 0.675), (0.48, 0.69), (0.52, 0.70)]

V_FRONT_ISLAND = [(0.615, 0.70), (0.618, 0.655), (0.63, 0.615), (0.66, 0.595),
                  (0.70, 0.60), (0.73, 0.63), (0.745, 0.665), (0.76, 0.70)]

V_FRONT_RIGHT = [(0.74, 0.70), (0.78, 0.665), (0.83, 0.645), (0.88, 0.65), (0.93, 0.635),
                 (0.97, 0.645), (1.00, 0.655)]

V_SMALL_ROCK = [(0.44, 0.70), (0.455, 0.675), (0.475, 0.665), (0.495, 0.672), (0.51, 0.70)]

# pohon: (jenis, x, y akar, tinggi relatif)
V_TREES = [("willow", 0.685, 0.598, 1.00),
           ("willow", 0.478, 0.667, 0.62),
           ("bamboo", 0.075, 0.565, 1.00),
           ("bamboo", 0.865, 0.648, 0.70)]

_V_GEO = {}


def _v_rough(poly, rng, amp, n=5):
    out = [poly[0]]
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        for k in range(1, n + 1):
            f = k / n
            jit = 0 if k == n else rng.uniform(-amp, amp)
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f + jit))
    return out


def _v_smooth(ctx, pts):
    ctx.move_to(*pts[0])
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        ctx.curve_to(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                     p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, *p2)


def _v_interp(poly, x):
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0 or 1)
    return None


def _v_geometry(W, H, seed=11):
    key = (W, H, seed)
    if key in _V_GEO:
        return _V_GEO[key]
    rng = random.Random(seed)
    P = lambda poly, amp=0.004, n=5: [(x * W, y * H) for x, y in _v_rough(poly, rng, amp, n)]
    mid = [(P(V_MID_LEFT, 0.006), 0.20), (P(V_MID_RIGHT, 0.006), 0.18), (P(V_PILLAR, 0.003, 4), 0.24)]
    # lereng kiri MID_LEFT2 (segmen pertama) memakai rng sendiri: jitter bukit dan batu lain tidak bergeser
    slope = [(x * W, y * H) for x, y in _v_rough(V_MID_LEFT2[:2], random.Random(seed + 1), 0.005)]
    mid.append((slope[:-1] + P(V_MID_LEFT2[1:], 0.005), 0.26))
    g = {"mid": mid,
         "front": [(P(V_FRONT_LEFT, 0.005), 0.34), (P(V_FRONT_ISLAND, 0.004, 4), 0.38),
                   (P(V_FRONT_RIGHT, 0.004), 0.30), (P(V_SMALL_ROCK, 0.003, 3), 0.32)]}
    # sapuan kuas kering di batu depan: garis hitam pendek miring (tekstur tinta)
    g["texture"] = []
    for poly, _ in g["front"]:
        xs = [p[0] for p in poly]
        for _ in range(int(len(poly) * 4 * W / 2560)):
            x = rng.uniform(min(xs), max(xs))
            top = _v_interp([(p[0] / W, p[1] / H) for p in poly], x / W)
            if top is None:
                continue
            y = rng.uniform(top + 0.008, VALLEY_HORIZON - 0.004) * H
            ln = rng.uniform(8, 30) * W / 2560
            ang = rng.uniform(-0.9, -0.2)
            g["texture"].append((x, y, ln, ang, rng.uniform(0.5, 1.0)))
    # burung: 2 gerombolan, posisi relatif tiap burung
    g["flocks"] = []
    for fx, fy, n in ((0.22, 0.12, 26), (0.70, 0.20, 18)):
        birds = [(rng.gauss(0, 0.06), rng.gauss(0, 0.03), rng.uniform(0, 6.3),
                  rng.uniform(0.6, 1.0)) for _ in range(n)]
        g["flocks"].append((fx, fy, birds, rng.uniform(0.002, 0.004)))
    # pohon: helai dedalu / batang dan daun bambu
    g["trees"] = []
    for kind, x, y, k in V_TREES:
        if kind == "willow":
            strands = [(rng.uniform(-1, 1), rng.uniform(0.6, 1.0), rng.uniform(0, 6.3))
                       for _ in range(int(80 * k) + 16)]
            g["trees"].append((kind, x * W, y * H, k, strands))
        else:
            stalks = []
            for i in range(int(6 * k) + 2):
                dx = rng.uniform(-0.012, 0.012) * W
                hgt = rng.uniform(0.10, 0.17) * H * k
                lean = rng.uniform(-0.12, 0.12)
                leaves = [(rng.uniform(0.35, 1.0), rng.choice((-1, 1)), rng.uniform(0.6, 1.0),
                           rng.uniform(0, 6.3)) for _ in range(9)]
                stalks.append((dx, hgt, lean, leaves))
            g["trees"].append((kind, x * W, y * H, k, stalks))
    _V_GEO[key] = g
    return g


def _v_fill_hill(ctx, pts, H, a_top, lum, fade_to):
    """isi bukit: hitam pekat (menutupi langit), lalu gradasi abu-abu yang
    memudar ke bawah (kabut di kaki bukit)."""
    import cairo
    base = VALLEY_HORIZON * H
    _v_smooth(ctx, pts)
    W = ctx.get_target().get_width()
    x0 = pts[0][0] - (12 if pts[0][0] <= 0 else 0)      # tepi layar: perpanjang keluar
    x1 = pts[-1][0] + (12 if pts[-1][0] >= W else 0)    # supaya geser anti burn-in tidak bercelah
    ctx.line_to(x1, pts[-1][1]); ctx.line_to(x1, base)
    ctx.line_to(x0, base); ctx.line_to(x0, pts[0][1]); ctx.close_path()
    path = ctx.copy_path()
    ctx.set_source_rgb(0, 0, 0); ctx.fill()
    top = min(p[1] for p in pts)
    gr = cairo.LinearGradient(0, top, 0, base)
    gr.add_color_stop_rgba(0.0, 1, 1, 1, a_top * lum)
    gr.add_color_stop_rgba(0.55, 1, 1, 1, a_top * lum * 0.55)
    gr.add_color_stop_rgba(1.0, 1, 1, 1, a_top * lum * fade_to)
    ctx.new_path(); ctx.append_path(path)
    ctx.set_source(gr); ctx.fill()
    # garis tepi tipis: seperti goresan tinta di punggung bukit
    _v_smooth(ctx, pts)
    ctx.set_source_rgba(1, 1, 1, min(1.0, a_top * 2.2) * lum)
    ctx.set_line_width(1.2 * ctx.get_target().get_width() / 2560)
    ctx.stroke()


def valley_static(ctx, W, H, lum=1.0):
    g = _v_geometry(W, H)
    s = W / 2560
    ctx.set_line_cap(1); ctx.set_line_join(1)
    for pts, a in g["mid"]:
        _v_fill_hill(ctx, pts, H, a, lum, 0.0)          # bukit tengah: hilang dalam kabut
    for pts, a in g["front"]:
        _v_fill_hill(ctx, pts, H, a, lum, 0.35)         # batu depan: tetap terlihat
    # tekstur kuas kering: goresan hitam di atas batu terang
    for x, y, ln, ang, k in g["texture"]:
        ctx.move_to(x, y); ctx.line_to(x + ln * math.cos(ang), y + ln * math.sin(ang))
        ctx.set_source_rgba(0, 0, 0, 0.55 * k); ctx.set_line_width(2.2 * s * k); ctx.stroke()
    # kabut tipis di garis danau
    import cairo
    yb = VALLEY_HORIZON * H
    gr = cairo.LinearGradient(0, yb - 0.035 * H, 0, yb + 0.02 * H)
    gr.add_color_stop_rgba(0, 1, 1, 1, 0)
    gr.add_color_stop_rgba(0.65, 1, 1, 1, 0.10 * lum)
    gr.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.rectangle(0, yb - 0.035 * H, W, 0.055 * H); ctx.set_source(gr); ctx.fill()
    # danau: kosong, hitam (pantulan matahari/bulan digambar di valley_anim)
    ctx.rectangle(0, yb + 0.02 * H, W, H); ctx.set_source_rgb(0, 0, 0); ctx.fill()


def _v_willow(ctx, x, y, k, strands, t, wind, s, lum):
    """dedalu: batang miring bercabang, tajuk melengkung, helai menjuntai panjang
    yang ujungnya diayun angin (makin ke ujung makin jauh)."""
    hgt = 165 * s * k
    R = 78 * s * k                                   # setengah lebar tajuk
    top = y - hgt
    ctx.move_to(x, y)
    ctx.curve_to(x - 8 * s * k, y - hgt * 0.35, x + 10 * s * k, y - hgt * 0.65, x + 2 * s * k, top + 10 * s * k)
    ctx.set_source_rgba(1, 1, 1, 0.8 * lum); ctx.set_line_width(4.0 * s * k); ctx.stroke()
    for sgn, f in ((-1, 0.55), (1, 0.68), (-1, 0.80), (1, 0.88)):   # cabang ke tajuk
        bx, by = x + 2 * s * k, y - hgt * f
        ctx.move_to(bx, by)
        ctx.curve_to(bx + sgn * R * 0.3, by - hgt * 0.10, bx + sgn * R * 0.6, by - hgt * 0.14,
                     bx + sgn * R * (0.75 + 0.2 * f), by - hgt * 0.10)
    ctx.set_source_rgba(1, 1, 1, 0.6 * lum); ctx.set_line_width(2.0 * s * k); ctx.stroke()
    amp = (3 + 22 * min(1.0, wind / 30.0)) * s * k
    for u, ln, ph in strands:
        sx = x + u * R * 1.05
        sy = top + (u * u) * hgt * 0.22 + 6 * s * k     # tajuk melengkung (tinggi di tengah)
        L = hgt * (0.55 + 0.45 * abs(u)) * ln           # helai pinggir lebih panjang
        sw = amp * math.sin(t * (0.8 + 0.25 * ln) + ph) + amp * 0.5
        ctx.move_to(sx, sy)
        ctx.curve_to(sx + u * R * 0.18, sy - 4 * s * k,
                     sx + u * R * 0.30 + sw * 0.25, sy + L * 0.35,
                     sx + u * R * 0.28 + sw, sy + L)
    ctx.set_source_rgba(1, 1, 1, 0.40 * lum); ctx.set_line_width(1.0 * s); ctx.stroke()


def _v_bamboo(ctx, x, y, k, stalks, t, wind, s, lum):
    sway = (0.01 + 0.06 * min(1.0, wind / 30.0))
    for dx, hgt, lean, leaves in stalks:
        bend = lean + sway * math.sin(t * 0.8 + dx * 0.05)
        x0, y0 = x + dx, y
        x1, y1 = x0 + bend * hgt, y0 - hgt
        ctx.move_to(x0, y0); ctx.curve_to(x0, y0 - hgt * 0.4, x0 + bend * hgt * 0.5, y0 - hgt * 0.75, x1, y1)
        ctx.set_source_rgba(1, 1, 1, 0.55 * lum); ctx.set_line_width(2.4 * s); ctx.stroke()
        for f in (0.22, 0.42, 0.6, 0.76):            # ruas
            nx = x0 + bend * hgt * f * f; ny = y0 - hgt * f
            ctx.move_to(nx - 3 * s, ny); ctx.line_to(nx + 3 * s, ny)
        ctx.set_source_rgba(1, 1, 1, 0.55 * lum); ctx.set_line_width(1.2 * s); ctx.stroke()
        for f, side, lk, ph in leaves:                # daun lancip, bergoyang
            px = x0 + bend * hgt * f * f; py = y0 - hgt * f
            ang = (-0.35 if side > 0 else math.pi + 0.35) + 0.25 * math.sin(t * 1.6 + ph) * (0.4 + wind / 30)
            ln = 34 * s * lk * k
            tx, ty = px + math.cos(ang) * ln, py + math.sin(ang) * ln * 0.55 + ln * 0.25
            nx_, ny_ = -(ty - py), (tx - px)
            nrm = math.hypot(nx_, ny_) or 1
            wdt = 3.5 * s * lk
            mx, my = (px + tx) / 2, (py + ty) / 2
            ctx.move_to(px, py)
            ctx.curve_to(mx + nx_ / nrm * wdt, my + ny_ / nrm * wdt, mx + nx_ / nrm * wdt, my + ny_ / nrm * wdt, tx, ty)
            ctx.curve_to(mx - nx_ / nrm * wdt, my - ny_ / nrm * wdt, mx - nx_ / nrm * wdt, my - ny_ / nrm * wdt, px, py)
        ctx.set_source_rgba(1, 1, 1, 0.38 * lum); ctx.fill()


def _v_reflection(ctx, x, top, bot, size, alpha, t, s):
    """kolom pantulan: garis-garis datar yang makin pendek dan pudar ke bawah."""
    y = top + 4 * s
    i = 0
    while y < bot and alpha > 0.02:
        f = (y - top) / (bot - top)
        half = size * (1.0 - 0.6 * f) * (0.7 + 0.3 * math.sin(t * 1.3 + i * 1.7))
        off = 3 * s * math.sin(t * 0.9 + i * 0.8)
        ctx.move_to(x - half + off, y); ctx.line_to(x + half + off, y)
        ctx.set_source_rgba(1, 1, 1, alpha * (1 - f) ** 1.4)
        ctx.set_line_width(1.6 * s); ctx.stroke()
        y += (7 + 10 * f) * s
        i += 1


def valley_anim(ctx, W, H, t, lum, wind=8.0, birds=False, bodies=(), night=0.0, fog=False):
    """bodies: (x, y, r, alpha) matahari/bulan di langit -> pantulan di danau;
    night 0..1 dan fog -> ketebalan kabut di atas danau."""
    g = _v_geometry(W, H)
    s = W / 2560
    ctx.set_line_cap(1)
    yb = VALLEY_HORIZON * H
    for x, y, r, al in bodies:
        top = _v_skyline(W, H, x)                         # tertutup bukit -> tanpa pantulan
        if y < yb and y + r < top and al > 0.02:
            _v_reflection(ctx, x, yb + 0.02 * H, H, r * 1.6, al * 0.55 * lum, t, s)
    lake_mist(ctx, W, H, t, night, float(fog), lum)
    for kind, x, y, k, data in g["trees"]:
        (_v_willow if kind == "willow" else _v_bamboo)(ctx, x, y, k, data, t, wind, s, lum)
    if birds:
        valley_birds(ctx, W, H, t, lum)


def valley_birds(ctx, W, H, t, lum):
    """gerombolan burung (saat cerah); dikepak per frame."""
    g = _v_geometry(W, H)
    s = W / 2560
    ctx.set_line_cap(1)
    for fx, fy, flock, v in g["flocks"]:
        cx = ((fx + t * v) % 1.4 - 0.2) * W
        cy = (fy + 0.01 * math.sin(t * 0.07 + fx * 9)) * H
        for dx, dy, ph, k in flock:
            bx = cx + dx * W + 4 * s * math.sin(t * 0.5 + ph)
            by = cy + dy * H + 3 * s * math.sin(t * 0.7 + ph * 1.3)
            span = 7 * s * k
            flap = math.sin(t * 7 + ph) * 0.6 + 0.2
            ctx.move_to(bx - span, by - span * flap)
            ctx.curve_to(bx - span * 0.5, by - span * 0.3, bx - 1, by, bx, by)
            ctx.curve_to(bx + 1, by, bx + span * 0.5, by - span * 0.3, bx + span, by - span * flap)
        ctx.set_source_rgba(1, 1, 1, 0.65 * lum); ctx.set_line_width(1.3 * s); ctx.stroke()


def _v_skyline(W, H, x):
    """y (piksel) tepi atas bukit/batu tertinggi di kolom x (cakrawala kalau kosong)."""
    best = VALLEY_HORIZON
    for poly in (V_MID_LEFT, V_MID_LEFT2, V_MID_RIGHT, V_PILLAR, V_FRONT_LEFT, V_FRONT_ISLAND,
                 V_FRONT_RIGHT, V_SMALL_ROCK):
        y = _v_interp(poly, x / W)
        if y is not None:
            best = min(best, y)
    return best * H


# ── kabut di atas danau ──────────────────────────────────────────────────────
_V_MIST = {}


def _v_mist_sprite(W, H, k):
    import cairo
    key = (W, H, k)
    if key in _V_MIST:
        return _V_MIST[key]
    rng = random.Random(900 + k)
    w, h = int(W * rng.uniform(0.45, 0.8)), int(H * rng.uniform(0.04, 0.08))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c = cairo.Context(surf)
    for _ in range(6):
        rx, ry = rng.uniform(0.15, 0.3) * w, rng.uniform(0.3, 0.48) * h
        cx, cy = rng.uniform(rx, w - rx), rng.uniform(ry, h - ry)
        c.save(); c.translate(cx, cy); c.scale(rx, ry)
        gr = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
        gr.add_color_stop_rgba(0, 1, 1, 1, 0.5)
        gr.add_color_stop_rgba(1, 1, 1, 1, 0)
        c.set_source(gr); c.arc(0, 0, 1, 0, 2 * math.pi); c.fill(); c.restore()
    _V_MIST[key] = (surf, w, h)
    return _V_MIST[key]


def lake_mist(ctx, W, H, t, night, fog, lum=1.0):
    """pita kabut yang melayang pelan di atas danau: tebal malam, tipis siang."""
    alpha = (0.05 + 0.30 * night + 0.25 * fog) * lum
    if alpha < 0.02:
        return
    yb = VALLEY_HORIZON * H
    for k in range(5):
        surf, w, h = _v_mist_sprite(W, H, k)
        r = random.Random(950 + k)
        span = W + w
        x = (r.random() * span + (4 + 6 * r.random()) * (W / 2560) * t * (1 if k % 2 else -1)) % span - w
        y = yb + (-0.008 + 0.10 * (k / 4) ** 1.3) * H - h / 2
        ctx.set_source_surface(surf, x, y)
        ctx.paint_with_alpha(min(1.0, alpha * (1 - 0.15 * k)))


def valley_birds_on(a, wx):
    """kekuatan 0..1 burung: terbang saat matahari terbit, tidak mendung, tidak hujan."""
    if not sun_up(a):
        return 0.0
    return max(0.0, min(1.0, (0.5 - wx["cover"]) / 0.1)) * (1.0 - min(1.0, wx["rain"] / RAIN_EPS))


_V_FRAME = {}


def draw_valley_frame(ctx, W, H, a, wx, t, cfg, gen=0):
    """scene valley: satu bingkai layar penuh (langit, awan, bukit, danau, pohon, hujan).
    gen naik setiap data langit berganti (20 detik) -> langit dasar digambar ulang."""
    import cairo
    h_sky = int(H * VALLEY_HORIZON)
    lum = round(scene_lum(a, cfg, wx), 3)
    dx, dy = (round(v) for v in drift(t, cfg["drift"]))
    cache = _V_FRAME.setdefault((W, H), {"sky": (None, None), "static": (None, None),
                                          "frame": (None, None)})
    # kuantisasi waktu: elemen lambat diperbarui 4x/detik, elemen cepat per frame
    tq = math.floor(t * VALLEY_SLOW_FPS) / VALLEY_SLOW_FPS
    key = (gen, tq, lum, dx, dy)
    if cache["frame"][0] != key:
        surf = cache["frame"][1] or cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        c = cairo.Context(surf)                      # dipakai ulang: hemat alokasi 16 MB
        c.set_source_rgb(0, 0, 0)
        c.paint()
        # 1. langit dasar (bintang, planet, matahari, bulan): cache per gen
        skykey = (gen, round(_cloud_veil(wx), 2))   # veil berubah halus saat transisi
        if cache["sky"][0] != skykey:
            sky_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, h_sky)
            draw_sky_base(cairo.Context(sky_surf), W, h_sky, a, t, cfg, wx)
            cache["sky"] = (skykey, sky_surf)
        c.set_source_surface(cache["sky"][1], 0, 0)
        c.paint()
        # 2. awan tinta (menggantikan awan garis)
        moon_lit = a["illum"] if (a["moon"][0] > 0 and a["night"] > 0) else 0
        ink_clouds(c, W, h_sky, wx, a["night"], moon_lit, tq)
        # 3. bukit, batu, danau: gambar transparan, dicat setelah awan (bukit menutupi awan & bintang)
        skey = (lum, dx, dy)
        if cache["static"][0] != skey:
            s_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            s_ctx = cairo.Context(s_surf)
            s_ctx.translate(dx, dy)
            valley_static(s_ctx, W, H, lum)
            cache["static"] = (skey, s_surf)
        c.set_source_surface(cache["static"][1], 0, 0)
        c.paint()
        # 4. animasi: pantulan, kabut danau, pohon (tanpa burung)
        r_sun, r_moon = radii(W, a, cfg)
        fade = max(0.0, 1 - wx["cover"] / 0.7)      # mendung -> pantulan hilang
        bodies = []
        if sun_up(a):
            bx, by = project(*a["sun"], W, h_sky)
            bodies.append((bx, by, r_sun, 0.9 * fade))
        if moon_visible(a, cfg):
            bx, by = project(*a["moon"], W, h_sky)
            bodies.append((bx, by, r_moon, a["illum"] * fade))
        c.save()
        c.translate(dx, dy)
        valley_anim(c, W, H, tq, lum, wind=wx["wind"], birds=False, bodies=bodies,
                    night=a["night"], fog=wx["fog"])
        c.restore()
        cache["frame"] = (key, surf)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_SOURCE)
    ctx.set_source_surface(cache["frame"][1], 0, 0)
    ctx.paint()
    ctx.restore()
    birds = valley_birds_on(a, wx)
    if birds > 0:                                    # burung: per frame (kepak sayap cepat)
        ctx.save()
        ctx.translate(dx, dy)
        valley_birds(ctx, W, H, t, lum * birds)
        ctx.restore()
    # 5. hujan
    draw_rain(ctx, W, 0, H, H, wx, t)
    draw_lightning(ctx, wx, t, cfg)


# antarmuka scene (lihat qlp/scenes/sea.py)
NAME = "valley"
draw = draw_valley_frame
