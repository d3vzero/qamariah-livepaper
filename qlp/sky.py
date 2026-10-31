"""langit: bintang, planet, matahari, bulan, selubung mendung, kecerahan pemandangan."""
import math

from qlp.astro import D2R, altaz, drift, load_stars, moon_visible, project, radii, sun_up
from qlp.weather import RAIN_EPS


def draw_moon(ctx, cx, cy, r, phase, toward):
    """toward: sudut (rad) arah matahari di layar; sisi terang menghadap ke sana."""
    ctx.set_source_rgba(1, 1, 1, 0.10)               # lingkar redup (earthshine)
    ctx.set_line_width(1.5)
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.stroke()
    if phase < 0.01 or phase > 0.99:
        return
    k = math.cos(2 * math.pi * phase)                # 1 baru → -1 purnama → 1 baru
    if abs(k) < 1e-3:
        k = 1e-3
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(toward)                               # sumbu +x = arah matahari
    ctx.arc(0, 0, r, -math.pi / 2, math.pi / 2)      # tepi terang, atas → bawah
    ctx.save(); ctx.scale(k, 1)                      # terminator, bawah → atas
    ctx.arc_negative(0, 0, r, math.pi / 2, -math.pi / 2)
    ctx.restore()
    ctx.close_path()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ctx.restore()


STARS = None


def draw_stars(ctx, w, h, a, t, cfg, moon_xy, r_moon):
    global STARS
    if not cfg["stars"] or a["night"] <= 0:
        return
    if STARS is None:
        STARS = load_stars()
    wash = 1 - 0.55 * a["illum"] if moon_xy else 1.0  # bulan terang menenggelamkan bintang
    limit = cfg["star_limit"] - (1.5 * a["illum"] if moon_xy else 0)
    lst, lat = a["lst"], a["lat"]
    for i, (ra, dec, mag) in enumerate(STARS):
        if mag > limit:
            continue
        alt, az = altaz(ra, dec, lst, lat)
        if alt <= 0:
            continue
        x, y = project(alt, az, w, h)
        if moon_xy and math.hypot(x - moon_xy[0], y - moon_xy[1]) < r_moon * 3:
            continue
        b = max(0.0, min(1.0, (limit + 0.5 - mag) / (limit + 2)))   # magnitudo → terang
        ext = min(1.0, alt / (12 * D2R))                             # redup dekat cakrawala
        al = (0.15 + 0.85 * b) * a["night"] * wash * (0.4 + 0.6 * ext)
        al *= 0.85 + 0.15 * math.sin(t * 0.05 + i * 2.4)            # kelip pelan
        if al < 0.05:
            continue
        size = 1.2 + 2.2 * b * b
        ctx.set_source_rgba(1, 1, 1, al)
        ctx.arc(x, y, size / 2, 0, 2 * math.pi)
        ctx.fill()


def draw_planets(ctx, w, h, a, cfg, moon_xy, r_moon):
    if not cfg["planets"]:
        return
    sun_alt = a["sun"][0] / D2R
    for name, alt, az, mag in a.get("planets", []):
        if alt <= 0:
            continue
        # planet terang (Venus/Jupiter) sudah tampak saat senja; yang redup perlu lebih gelap
        need = -1 - 2.5 * max(0.0, mag + 1)          # derajat matahari di bawah cakrawala
        vis = max(0.0, min(1.0, (need - sun_alt) / 3))
        if vis <= 0:
            continue
        x, y = project(alt, az, w, h)
        if moon_xy and math.hypot(x - moon_xy[0], y - moon_xy[1]) < r_moon * 1.5:
            continue
        b = max(0.0, min(1.0, (2.5 - mag) / 7))      # Venus -4.5 → 1, Saturnus +1 → 0.2
        ext = min(1.0, alt / (8 * D2R))
        al = (0.35 + 0.65 * b) * vis * (0.5 + 0.5 * ext)
        rad = 1.6 + 2.6 * b
        if b > 0.6:                                  # pendar tipis untuk Venus/Jupiter
            ctx.set_source_rgba(1, 1, 1, al * 0.12)
            ctx.arc(x, y, rad * 2.6, 0, 2 * math.pi)
            ctx.fill()
        ctx.set_source_rgba(1, 1, 1, al)
        ctx.arc(x, y, rad, 0, 2 * math.pi)
        ctx.fill()


def _cloud_veil(wx):
    """mendung tebal meredupkan bintang/bulan/matahari secara merata."""
    if not wx:
        return 0.0
    cover = wx["cover"]
    veil = max(0.0, (cover - 0.6) / 0.4) ** 1.5 * (0.7 if wx["rain"] >= RAIN_EPS else 0.5 + 0.2 * wx["rain"] / RAIN_EPS)
    veil = max(veil, 0.6 * wx["fog"])
    return veil


def draw_sky_base(ctx, w, h, a, t, cfg, wx=None):
    """bagian langit yang berubah lambat: bintang, planet, matahari, bulan."""
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    dx, dy = drift(t, cfg["drift"])
    ctx.save()
    ctx.translate(dx, dy)
    r_sun, r_moon = radii(w, a, cfg)
    sun_xy = project(*a["sun"], w, h)
    moon_xy = project(*a["moon"], w, h) if moon_visible(a, cfg) else None
    draw_stars(ctx, w, h, a, t, cfg, moon_xy, r_moon)
    draw_planets(ctx, w, h, a, cfg, moon_xy, r_moon)
    if sun_up(a):
        x, y = sun_xy
        for k, al in ((2.4, 0.03), (1.7, 0.06)):     # pendar: pembeda matahari dari bulan
            ctx.set_source_rgba(1, 1, 1, al)
            ctx.arc(x, y, r_sun * k, 0, 2 * math.pi)
            ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        ctx.arc(x, y, r_sun, 0, 2 * math.pi)
        ctx.fill()
    if moon_xy:
        toward = math.atan2(sun_xy[1] - moon_xy[1], sun_xy[0] - moon_xy[0])
        draw_moon(ctx, moon_xy[0], moon_xy[1], r_moon, a["phase"], toward)
    ctx.restore()
    veil = _cloud_veil(wx)                           # ikut cache: hanya berubah bersama wx
    if veil > 0:
        ctx.set_source_rgba(0, 0, 0, veil)
        ctx.paint()


def scene_lum(a, cfg, wx):
    """kecerahan garis pemandangan: redup di malam hari (lebih terang saat bulan terang),
    saat mendung, dan saat kabut."""
    moon_up = moon_visible(a, cfg)
    lum = 1.0 - a["night"] * (0.38 - 0.25 * (a["illum"] if moon_up else 0))
    lum *= 1 - 0.45 * max(0.0, (wx["cover"] - 0.5) / 0.5) - 0.3 * wx["fog"]
    return lum
