#!/usr/bin/env python3
"""qamariah-livepaper — live wallpaper OLED untuk aro (layer-shell background).

Langit hitam pekat dengan posisi benda langit SEBENARNYA untuk lokasi & waktu:
  - matahari & bulan: altitude/azimuth dihitung (bulan: rumus Meeus ringkas,
    ketelitian ~0,3°), fase & ukuran tampak bulan dari geometri aktual
  - bintang: 904 bintang Yale Bright Star Catalog (V <= 4,5) pada posisi
    sebenarnya; terang sesuai magnitudo, redup dekat cakrawala, kalah oleh
    cahaya bulan dan senja
  - planet: Merkurius, Venus, Mars, Jupiter, Saturnus (elemen orbit JPL,
    ketelitian ~1°), terang sesuai magnitudo, tidak berkelip
  - cuaca: cerah / berawan / hujan / badai — "live" dari Open-Meteo sesuai
    lokasi (tanpa API key; cadangan simulasi kalau offline) atau simulasi
    pola tropis (awan siang, hujan sore, angin siang/malam berbalik)
Proyeksi: langit "dibentangkan" timur (kiri) → barat (kanan), tinggi = altitude.
Laut di bawah: garis gelombang putih tipis, bergerak pelan:
  - arah gelombang : bulan membesar → ke kanan, mengecil → ke kiri
  - tinggi gelombang: pasang-surut dari sudut jam bulan (2x sehari) dan
                      pasang purnama/perbani dari fase
Pantulan matahari/bulan berkilau di permukaan laut.

Hemat OLED: >95% piksel hitam, seluruh gambar bergeser beberapa piksel per jam
(anti burn-in). Langit digambar ulang tiap 20 detik, laut sesuai FPS (default 12)
dan berhenti sendiri saat tertutup window.

Pakai:
  qamariah-livepaper                    jalankan (dari `exec =` di config aro)
  qamariah-livepaper --preview out.png  render satu gambar (tanpa GTK)
      [--size 2560x1600] [--time "2026-10-20 19:30"]
      [--weather clear|cloudy|rain|storm|fog|sim|live]
      [--scene sea|valley]
  qamariah-livepaper --list-scenes      daftar scene (dipakai qamariah-livepaper-menu)
  qamariah-livepaper --demo-weather storm,clear,rain,fog,cloudy [--demo-period 60]
                                        uji transisi: cuaca bergantian tiap DETIK
                                        (tanpa data live; durasi transisi =
                                        min(weather_transition, 0.4 x demo-period)
                                        supaya selesai sebelum kondisi berikutnya)
Config: ~/.config/qamariah-livepaper/config.ini (lihat config.example.ini)
"""
import configparser
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from qlp import config as _config
from qlp.config import DEFAULTS
from qlp.astro import (
    HERE, load_stars, D2R, MOON_SUN_RATIO, julian, lst_rad, altaz, ecl_to_eq, sun_ecl,
    moon_ecl, astro, PLANET_EL, helio, planet_mag, planets, drift, project, radii, sun_up,
    moon_visible,
)
from qlp.weather import (
    WEATHER_FIXED, _smooth, weather_sim, weather_from_api, Weather, V_CLOUDS_MAX, RAIN_EPS,
    BLEND_KEYS, sea_rough, _moved, _Motion, WeatherBlend, wind_px, demo_transition,
)
from qlp.sky import (
    draw_moon, STARS, draw_stars, draw_planets, _cloud_veil, draw_sky_base, scene_lum,
)
from qlp.clouds import (
    _CLOUD_CACHE, _cloud_cluster, _cloud_sprites, draw_clouds, _V_INK, _v_ink_sprite,
    ink_clouds,
)
from qlp.precip import _frac, _RAIN_CACHE, _rain_drops, draw_rain, draw_lightning


def load_config():
    return _config.load_config(SCENES)


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


def draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total):
    draw_clouds(ctx, w, h, a, wx, t, cfg)
    draw_rain(ctx, w, 0, h, h_total, wx, t)
    draw_lightning(ctx, wx, t, cfg)


def draw_sky(ctx, w, h, a, t, cfg, wx=None, h_total=None):
    draw_sky_base(ctx, w, h, a, t, cfg, wx)
    if wx:
        draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total or h)


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


# scene: None = langit dan laut digambar terpisah (jalur lama), selain itu fungsi
# yang menggambar satu bingkai layar penuh
SCENES = {
    "sea": None,
    "valley": draw_valley_frame,
}


def draw_frame(ctx, w, h, a, wx, t, cfg, gen=0):
    """satu bingkai layar penuh untuk scene cfg['scene'] (dipakai preview dan test)."""
    h_sky = int(h * cfg["horizon"])
    if SCENES[cfg["scene"]] is not None:
        SCENES[cfg["scene"]](ctx, w, h, a, wx, t, cfg, gen)
    else:
        draw_sky(ctx, w, h_sky, a, t, cfg, wx, h)
        ctx.save()
        ctx.translate(0, h_sky)
        ctx.rectangle(0, 0, w, h - h_sky)
        ctx.clip()
        draw_sea(ctx, w, h - h_sky, a, t, cfg, h_sky, wx)
        ctx.restore()


# ── preview (tanpa GTK) ─────────────────────────────────────────────────────
def full_state(now, cfg):
    a = astro(now, cfg["lat"], cfg["lon"])
    a["planets"] = planets(now, cfg["lat"], cfg["lon"], cfg["planets"])
    return a


def preview(out, size, when, weather=None, scene=None):
    import cairo
    cfg = load_config()
    cfg["lightning"] = False                         # kilat hanya sesaat; jangan ikut di gambar diam
    if weather:
        cfg["weather"] = weather
    if scene is not None:
        if scene not in SCENES:
            sys.exit("scene tidak dikenal: %s" % scene)
        cfg["scene"] = scene
    w, h = (int(v) for v in size.lower().split("x"))
    now = (datetime.strptime(when, "%Y-%m-%d %H:%M").astimezone() if when
           else datetime.now().astimezone())
    a = full_state(now, cfg)
    wthr = Weather(cfg)
    wthr.poll(background=False)
    wx = wthr.get(now)
    t = now.timestamp()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    ctx = cairo.Context(surf)
    draw_frame(ctx, w, h, a, wx, t, cfg)
    surf.write_to_png(out)
    deg = lambda r: r / D2R
    print(f"{out}: {now:%Y-%m-%d %H:%M}  matahari alt {deg(a['sun'][0]):5.1f}° az {deg(a['sun'][1]):5.1f}°, "
          f"bulan alt {deg(a['moon'][0]):5.1f}° az {deg(a['moon'][1]):5.1f}°, "
          f"fase {a['phase']:.2f} (terang {a['illum']:.0%}), jarak {a['moon_km']/1000:.0f} rb km, "
          f"malam {a['night']:.0%}, gelombang {'→' if a['wave_dir'] > 0 else '←'} x{a['wave_amp']:.2f}")
    vis = [f"{n} {alt / D2R:.0f}° m{mag:+.1f}" for n, alt, az, mag in a["planets"] if alt > 0]
    print(f"   planet di atas cakrawala: {', '.join(vis) or '-'}")
    print(f"   cuaca ({wx.get('source')}): awan {wx['cover']:.0%}, hujan {wx['rain']:.0%}, "
          f"angin {wx['wind']:.0f} km/j dari {wx['wind_from']:.0f}°"
          f"{', badai' if wx['thunder'] else ''}{', kabut' if wx['fog'] else ''}")


# ── GTK4 + layer-shell ──────────────────────────────────────────────────────
def run(demo=None, period=60):
    """demo: daftar kondisi WEATHER_FIXED yang bergantian tiap period detik (uji visual)."""
    import cairo
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    gi.require_foreign("cairo")
    from gi.repository import Gdk, GLib, Gtk
    from gi.repository import Gtk4LayerShell as Layer

    cfg = load_config()
    if demo:
        cfg["weather_transition"] = demo_transition(cfg["weather_transition"], period)
    weather = Weather(cfg)
    blend = WeatherBlend(cfg)                        # data baru -> transisi halus
    state = {"a": full_state(datetime.now().astimezone(), cfg), "gen": 0}

    def refresh():
        now = datetime.now().astimezone()
        state["a"] = full_state(now, cfg)
        if not demo:
            weather.poll()
            blend.set(weather.get(now), time.time())
        state["gen"] += 1                            # langit dasar perlu digambar ulang
        return True

    def demo_next():
        state["demo"] = (state.get("demo", -1) + 1) % len(demo)
        name = demo[state["demo"]]
        print("qamariah-livepaper: demo cuaca -> %s (%s)" % (name, datetime.now().strftime("%H:%M:%S")),
              file=sys.stderr, flush=True)
        blend.set(dict(WEATHER_FIXED[name], source=name), time.time())
        return True
    if demo:
        demo_next()
    refresh()

    css = Gtk.CssProvider()
    rule = "window, box, drawingarea { background: #000000; }"
    try:
        css.load_from_string(rule)                  # GTK >= 4.12
    except AttributeError:
        css.load_from_data(rule.encode())

    def on_activate(app):
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        monitors = Gdk.Display.get_default().get_monitors()
        for idx in range(monitors.get_n_items()):
            make_window(app, monitors.get_item(idx))
        GLib.timeout_add_seconds(20, refresh)
        if demo:
            GLib.timeout_add_seconds(period, demo_next)

    def make_window(app, monitor):
        win = Gtk.ApplicationWindow(application=app)
        Layer.init_for_window(win)
        Layer.set_namespace(win, "qamariah-livepaper")
        Layer.set_layer(win, Layer.Layer.BACKGROUND)
        Layer.set_monitor(win, monitor)
        for edge in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(win, edge, True)
        Layer.set_exclusive_zone(win, -1)
        Layer.set_keyboard_mode(win, Layer.KeyboardMode.NONE)

        geo = monitor.get_geometry()
        render = SCENES[cfg["scene"]]
        if render:
            area = Gtk.DrawingArea()
            area.set_hexpand(True); area.set_vexpand(True)
            def draw_full(_a, c, w, h):
                t = time.time()
                render(c, w, h, state["a"], blend.get(t), t, cfg, state["gen"])
            area.set_draw_func(draw_full)
            win.set_child(area)
            last_f = {"t": 0}

            def tick_full(_w, clock):
                now = clock.get_frame_time()
                wx = blend.get(time.time())
                fast = valley_birds_on(state["a"], wx) or wx["rain"] > 0 or wx["thunder"]
                period = 1_000_000 / (cfg["fps"] if fast else VALLEY_SLOW_FPS)
                if now - last_f["t"] >= period:
                    last_f["t"] = now
                    area.queue_draw()
                return True
            area.add_tick_callback(tick_full)
            win.present()
            return
        h_sky = int(geo.height * cfg["horizon"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sky, sea = Gtk.DrawingArea(), Gtk.DrawingArea()
        sky.set_content_height(h_sky)
        sea.set_vexpand(True); sky.set_hexpand(True); sea.set_hexpand(True)
        cache = {"surf": None, "key": None}

        def draw_sky_cb(_a, c, w, h):
            t = time.time()
            wx = blend.get(t)
            key = (w, h, state["gen"], round(_cloud_veil(wx), 2))   # veil berubah halus saat transisi
            if cache["key"] != key:                  # bintang/planet/matahari/bulan: tiap 20 dtk
                surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
                draw_sky_base(cairo.Context(surf), w, h, state["a"], t, cfg, wx)
                cache["surf"], cache["key"] = surf, key
            c.set_source_surface(cache["surf"], 0, 0)
            c.paint()
            draw_sky_overlay(c, w, h, state["a"], wx, t, cfg, geo.height)

        sky.set_draw_func(draw_sky_cb)
        def draw_sea_cb(_a, c, w, h):
            t = time.time()
            draw_sea(c, w, h, state["a"], t, cfg, sky.get_height(), blend.get(t))
        sea.set_draw_func(draw_sea_cb)
        box.append(sky); box.append(sea)
        win.set_child(box)

        last = {"sea": 0, "sky": 0, "gen": -1}

        def tick(_w, clock):        # berhenti sendiri kalau compositor tidak meminta frame
            now = clock.get_frame_time()
            if now - last["sea"] >= 1_000_000 / cfg["fps"]:
                last["sea"] = now
                sea.queue_draw()
            wx = blend.get(time.time())
            if wx["rain"] > 0 or wx["thunder"]:
                sky_us = 1_000_000 / cfg["fps"]
            elif wx["cover"] > 0 or wx["fog"] or "_mo" in wx:
                sky_us = 1_000_000 / cfg["sky_fps"]
            else:
                sky_us = None                        # cerah: cukup saat data berganti
            if (sky_us and now - last["sky"] >= sky_us) or last["gen"] != state["gen"]:
                last["sky"], last["gen"] = now, state["gen"]
                sky.queue_draw()
            return True
        sea.add_tick_callback(tick)
        win.present()

    app = Gtk.Application(application_id="id.aro.livepaper")
    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--list-scenes":
        for name in SCENES:
            print(name)
        sys.exit(0)
    if args and args[0] == "--preview":
        out = args[1] if len(args) > 1 else "livepaper-preview.png"
        size = args[args.index("--size") + 1] if "--size" in args else "2560x1600"
        when = args[args.index("--time") + 1] if "--time" in args else None
        wthr = args[args.index("--weather") + 1] if "--weather" in args else None
        scn = args[args.index("--scene") + 1] if "--scene" in args else None
        preview(out, size, when, wthr, scn)
    elif "--demo-weather" in args:
        demo = [w.strip().lower() for w in args[args.index("--demo-weather") + 1].split(",") if w.strip()]
        bad = [w for w in demo if w not in WEATHER_FIXED]
        if not demo or bad:
            sys.exit("--demo-weather: kondisi tidak dikenal %s (pilih dari %s)"
                     % (",".join(bad) or "(kosong)", ",".join(WEATHER_FIXED)))
        period = int(args[args.index("--demo-period") + 1]) if "--demo-period" in args else 60
        if period < 1:
            sys.exit("--demo-period harus >= 1 detik")
        run(demo, period)
    else:
        run()
