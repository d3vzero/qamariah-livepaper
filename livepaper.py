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
Config: ~/.config/qamariah-livepaper/config.ini (lihat config.example.ini)
"""
import configparser
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# ── konfigurasi ─────────────────────────────────────────────────────────────
DEFAULTS = {
    "lat": "-6.2",          # Jakarta; ganti dengan lokasi sendiri
    "lon": "106.8",
    "fps": "12",
    "horizon": "0.68",      # posisi cakrawala (0..1 dari atas)
    "drift": "yes",         # geser anti burn-in
    "waves": "10",          # jumlah garis gelombang
    "moon_daytime": "yes",  # no = bulan disembunyikan selama matahari di atas cakrawala
    "stars": "yes",         # bintang sesuai lokasi di malam hari
    "star_limit": "4.5",    # magnitudo terlemah (kota terang ~3, desa gelap 4.5)
    "body_size": "0.02",    # jari-jari matahari, pecahan lebar layar
    "planets": "mercury,venus,mars,jupiter,saturn",   # kosong = tanpa planet
    "weather": "live",      # live | sim | clear | cloudy | rain | storm | fog
    "weather_refresh": "20",  # menit antar ambil data cuaca (live)
    "clouds_max": "16",     # jumlah awan saat mendung penuh
    "lightning": "yes",     # kilat redup saat badai
    "sky_fps": "4",         # fps langit saat ada awan (hujan memakai fps laut)
    "scene": "sea",         # sea | valley (pemandangan di bawah cakrawala)
}


def load_config():
    cp = configparser.ConfigParser()
    cp.read_dict({"livepaper": DEFAULTS})
    base = os.path.expanduser(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
    path = os.path.join(base, "qamariah-livepaper", "config.ini")
    old = os.path.join(base, "aro-livepaper", "config.ini")
    if not os.path.exists(path) and os.path.exists(old):
        print("qamariah-livepaper: memakai config lama %s (pindahkan ke %s)" % (old, path),
              file=sys.stderr)
        path = old
    cp.read(path)
    c = cp["livepaper"]
    scene = c.get("scene").strip().lower()
    if scene not in SCENES:
        print("qamariah-livepaper: scene tidak dikenal '%s', memakai sea" % scene,
              file=sys.stderr)
        scene = "sea"
    return {
        "lat": c.getfloat("lat"), "lon": c.getfloat("lon"),
        "fps": max(1, min(30, c.getint("fps"))),
        "horizon": max(0.4, min(0.85, c.getfloat("horizon"))),
        "drift": c.getboolean("drift"),
        "waves": max(4, min(20, c.getint("waves"))),
        "moon_daytime": c.getboolean("moon_daytime"),
        "stars": c.getboolean("stars"),
        "star_limit": max(1.0, min(4.5, c.getfloat("star_limit"))),
        "body_size": max(0.008, min(0.05, c.getfloat("body_size"))),
        "planets": [p.strip().lower() for p in c.get("planets").split(",") if p.strip()],
        "weather": c.get("weather").strip().lower(),
        "weather_refresh": max(5, c.getint("weather_refresh")),
        "clouds_max": max(0, min(40, c.getint("clouds_max"))),
        "lightning": c.getboolean("lightning"),
        "sky_fps": max(1, min(30, c.getint("sky_fps"))),
        "scene": scene,
    }


def load_stars():
    stars = []
    try:
        with open(os.path.join(HERE, "stars.dat")) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                ra, dec, mag = (float(v) for v in line.split())
                stars.append((math.radians(ra), math.radians(dec), mag))
    except OSError:
        pass
    return stars


# ── astronomi ───────────────────────────────────────────────────────────────
D2R = math.pi / 180
MOON_SUN_RATIO = 0.518 / 0.533     # diameter tampak rata-rata bulan / matahari


def julian(now):
    return now.astimezone(timezone.utc).timestamp() / 86400 + 2440587.5


def lst_rad(jd, lon):
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0)
    return ((gmst + lon) % 360) * D2R


def altaz(ra, dec, lst, lat):
    """→ (altitude, azimuth dari utara ke timur), radian."""
    h = lst - ra
    sl, cl = math.sin(lat), math.cos(lat)
    sd, cd = math.sin(dec), math.cos(dec)
    alt = math.asin(max(-1, min(1, sl * sd + cl * cd * math.cos(h))))
    az = math.atan2(-cd * math.sin(h), sd * cl - cd * sl * math.cos(h))
    return alt, az % (2 * math.pi)


def ecl_to_eq(lam, beta, eps):
    x = math.cos(beta) * math.cos(lam)
    y = math.cos(eps) * math.cos(beta) * math.sin(lam) - math.sin(eps) * math.sin(beta)
    z = math.sin(eps) * math.cos(beta) * math.sin(lam) + math.cos(eps) * math.sin(beta)
    return math.atan2(y, x), math.asin(z)


def sun_ecl(n):
    """bujur ekliptika matahari (rad), Astronomical Almanac ringkas."""
    L = 280.460 + 0.9856474 * n
    g = (357.528 + 0.9856003 * n) * D2R
    return (L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) * D2R


def moon_ecl(T):
    """(bujur, lintang, paralaks) bulan, rad — Meeus/Almanac ringkas (~0,3°)."""
    s = lambda a, b: math.sin((a + b * T) * D2R)
    c = lambda a, b: math.cos((a + b * T) * D2R)
    lam = (218.32 + 481267.881 * T + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74)
           - 0.19 * s(357.5, 35999.05) - 0.11 * s(186.5, 966404.03))
    beta = (5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89)
            - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21))
    par = (0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.36)
           + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.74))
    return lam * D2R, beta * D2R, par * D2R


def astro(now, lat, lon):
    jd = julian(now)
    n = jd - 2451545.0
    T = n / 36525
    eps = (23.439 - 0.0000004 * n) * D2R
    lst = lst_rad(jd, lon)
    la = lat * D2R

    ls = sun_ecl(n)
    s_ra, s_dec = ecl_to_eq(ls, 0.0, eps)
    s_alt, s_az = altaz(s_ra, s_dec, lst, la)
    s_alt += 0.0145 if s_alt > -0.02 else 0          # refraksi di cakrawala (~0,83°)

    lm, bm, par = moon_ecl(T)
    m_ra, m_dec = ecl_to_eq(lm, bm, eps)
    m_alt, m_az = altaz(m_ra, m_dec, lst, la)
    m_alt -= par * math.cos(m_alt)                   # paralaks topokentris (s.d. ~1°)

    elong = (lm - ls) % (2 * math.pi)                # 0 baru, π purnama
    phase = elong / (2 * math.pi)
    illum = (1 - math.cos(elong)) / 2
    moon_km = 6378.14 / math.sin(par)

    # 0 = siang, 1 = malam (bintang mulai saat matahari < -3°, penuh < -12°)
    night = max(0.0, min(1.0, (-s_alt / D2R - 3) / 9))
    h_moon = (lst - m_ra) % (2 * math.pi)            # sudut jam bulan
    tide = math.cos(2 * h_moon)                      # +1 pasang (transit atas/bawah)
    spring = math.cos(2 * elong)                     # +1 purnama/baru, -1 perbani
    return {
        "lst": lst, "lat": la,
        "sun": (s_alt, s_az), "moon": (m_alt, m_az),
        "phase": phase, "illum": illum, "moon_km": moon_km, "night": night,
        "wave_dir": 1 if phase < 0.5 else -1,
        "wave_amp": (0.78 + 0.22 * tide) * (1.0 + 0.25 * spring),
    }


# ── planet (elemen Kepler pendekatan JPL, berlaku 1800–2050) ────────────────
#        a, e, I, L, varpi, Omega   |   laju per abad
PLANET_EL = {
    "mercury": ((0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
                (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    "venus":   ((0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
                (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "earth":   ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
                (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "mars":    ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
                (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "jupiter": ((5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "saturn":  ((9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
                (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
}


def helio(name, T):
    el, rate = PLANET_EL[name]
    a, e, inc, L, varpi, om = (el[i] + rate[i] * T for i in range(6))
    M = math.radians((L - varpi + 180) % 360 - 180)
    w, inc, om = math.radians(varpi - om), math.radians(inc), math.radians(om)
    E = M + e * math.sin(M)
    for _ in range(6):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    xp, yp = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    cw, sw, co, so, ci, si = (math.cos(w), math.sin(w), math.cos(om), math.sin(om),
                              math.cos(inc), math.sin(inc))
    x = (cw * co - sw * so * ci) * xp + (-sw * co - cw * so * ci) * yp
    y = (cw * so + sw * co * ci) * xp + (-sw * so + cw * co * ci) * yp
    z = (sw * si) * xp + (cw * si) * yp
    return x, y, z


def planet_mag(name, r, d, i):
    lg = 5 * math.log10(r * d)
    return {
        "mercury": -0.42 + lg + 0.038 * i - 0.000273 * i * i + 0.000002 * i ** 3,
        "venus": -4.40 + lg + 0.0009 * i + 0.000239 * i * i - 0.00000065 * i ** 3,
        "mars": -1.52 + lg + 0.016 * i,
        "jupiter": -9.40 + lg + 0.005 * i,
        "saturn": -8.88 + lg,
    }[name]


def planets(now, lat, lon, names):
    """→ [(nama, alt, az, magnitudo)]"""
    jd = julian(now)
    T = (jd - 2451545.0) / 36525
    eps = 23.43928 * D2R
    lst, la = lst_rad(jd, lon), lat * D2R
    ex, ey, ez = helio("earth", T)
    out = []
    for name in names:
        if name not in PLANET_EL or name == "earth":
            continue
        px, py, pz = helio(name, T)
        gx, gy, gz = px - ex, py - ey, pz - ez
        d = math.sqrt(gx * gx + gy * gy + gz * gz)
        r = math.sqrt(px * px + py * py + pz * pz)
        rs = math.sqrt(ex * ex + ey * ey + ez * ez)
        cos_i = max(-1, min(1, (r * r + d * d - rs * rs) / (2 * r * d)))
        lam, beta = math.atan2(gy, gx), math.asin(gz / d)
        ra, dec = ecl_to_eq(lam, beta, eps)
        alt, az = altaz(ra, dec, lst, la)
        out.append((name, alt, az, planet_mag(name, r, d, math.degrees(math.acos(cos_i)))))
    return out


# ── cuaca ───────────────────────────────────────────────────────────────────
WEATHER_FIXED = {   # cover 0..1, rain 0..1, angin km/j, arah DARI (derajat)
    "clear":  dict(cover=0.1, rain=0.0, wind=8, wind_from=90, thunder=False, fog=False),
    "cloudy": dict(cover=0.55, rain=0.0, wind=14, wind_from=90, thunder=False, fog=False),
    "rain":   dict(cover=0.85, rain=0.6, wind=18, wind_from=250, thunder=False, fog=False),
    "storm":  dict(cover=1.0, rain=1.0, wind=32, wind_from=250, thunder=True, fog=False),
    "fog":    dict(cover=0.85, rain=0.0, wind=4, wind_from=90, thunder=False, fog=True),
}


def _smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def weather_sim(now):
    """pola tropis harian (deterministik per tanggal): pagi cerah, awan tumbuh
    siang, peluang hujan sore, malam reda. Angin siang dari timur (awan ke kanan),
    malam berbalik pelan (awan ke kiri)."""
    import random
    rng = random.Random(now.toordinal())
    wet = rng.random()
    peak = 14.5 + 2.5 * rng.random()
    h = now.hour + now.minute / 60
    cover = 0.12 + 0.15 * wet
    cover += (0.45 + 0.4 * wet) * _smooth(10, 14.5, h) * (1 - 0.7 * _smooth(18, 23, h))
    rain = 0.0
    if wet > 0.55:
        rain = (wet - 0.55) / 0.45 * max(0.0, 1 - abs(h - peak) / 1.6)
        cover = max(cover, 0.6 + 0.4 * rain)
    day = 9 <= h < 19
    wind = (6 + 14 * _smooth(9, 14, h) * (1 - _smooth(16, 19, h))) if day else 4
    return dict(cover=min(1.0, cover), rain=rain, wind=wind + 10 * rain,
                wind_from=90 if day else 270, thunder=rain > 0.6, fog=False, source="sim")


def weather_from_api(cur):
    code = int(cur.get("weather_code", 0))
    rain_mm = float(cur.get("precipitation", 0) or 0)
    rain = min(1.0, rain_mm / 4.0)
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        rain = max(rain, {51: .15, 53: .25, 55: .35, 61: .35, 63: .55, 65: .85,
                          80: .4, 81: .65, 82: .95}.get(code, 0.5))
    return dict(cover=float(cur.get("cloud_cover", 0)) / 100, rain=rain,
                wind=float(cur.get("wind_speed_10m", 0)),
                wind_from=float(cur.get("wind_direction_10m", 90)),
                thunder=code >= 95, fog=code in (45, 48), source="live", code=code)


class Weather:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = cfg["weather"]
        self.live = None
        self.next_try = 0
        self.cache = os.path.expanduser("~/.cache/qamariah-livepaper/weather.json")

    def _fetch(self):
        import json
        import urllib.request
        lat, lon = round(self.cfg["lat"], 2), round(self.cfg["lon"], 2)   # ~1 km
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=cloud_cover,precipitation,weather_code,wind_speed_10m,"
               "wind_direction_10m&timezone=auto" % (lat, lon))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qamariah-livepaper"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
            self.live = (time.time(), weather_from_api(data["current"]))
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            with open(self.cache, "w") as f:
                json.dump({"t": self.live[0], "w": self.live[1]}, f)
            self.next_try = time.time() + self.cfg["weather_refresh"] * 60
        except Exception as e:                       # offline / API gagal → coba lagi 5 menit
            print("qamariah-livepaper: cuaca live gagal:", e, file=sys.stderr)
            self.next_try = time.time() + 300

    def poll(self, background=True):
        if self.mode != "live" or time.time() < self.next_try:
            return
        if self.live is None:
            try:
                import json
                with open(self.cache) as f:
                    c = json.load(f)
                if time.time() - c["t"] < self.cfg["weather_refresh"] * 60:
                    self.live = (c["t"], c["w"])
                    self.next_try = c["t"] + self.cfg["weather_refresh"] * 60
                    return
            except Exception:
                pass
        self.next_try = time.time() + 60             # cegah tumpang tindih
        if background:
            import threading
            threading.Thread(target=self._fetch, daemon=True).start()
        else:
            self._fetch()

    def get(self, now):
        if self.mode in WEATHER_FIXED:
            return dict(WEATHER_FIXED[self.mode], source=self.mode)
        if self.mode == "live" and self.live and time.time() - self.live[0] < 3 * 3600:
            return self.live[1]
        return weather_sim(now)                      # sim, atau cadangan live


# ── gambar ──────────────────────────────────────────────────────────────────
def drift(t, on):
    if not on:
        return 0.0, 0.0
    return 6 * math.sin(2 * math.pi * t / 3600), 4 * math.sin(2 * math.pi * t / 5400)


def project(alt, az, w, h_sky):
    """langit dibentangkan: komponen timur-barat → x (timur kiri), altitude → y."""
    east = math.sin(az) * max(0.0, math.cos(alt)) ** 0.4   # +1 timur, -1 barat (diperhalus dekat zenit)
    m = w * 0.05
    x = m + (1 - east) / 2 * (w - 2 * m)
    y = h_sky - (alt / (math.pi / 2)) * (h_sky * 0.88)
    return x, y


def radii(w, a, cfg):
    """jari-jari matahari & bulan; bulan sesuai jarak aktual (supermoon ±7%)."""
    r_sun = w * cfg["body_size"]
    return r_sun, r_sun * MOON_SUN_RATIO * (384400 / a["moon_km"])


def sun_up(a):
    return a["sun"][0] > -0.6 * D2R


def moon_visible(a, cfg):
    return a["moon"][0] > -0.6 * D2R and (cfg["moon_daytime"] or not sun_up(a))


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
    veil = max(0.0, (cover - 0.6) / 0.4) ** 1.5 * (0.7 if wx["rain"] > 0 else 0.5)
    if wx["fog"]:
        veil = max(veil, 0.6)
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


def _frac(x):
    return x - math.floor(x)


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


def wind_px(wx, w):
    """kecepatan horizontal di layar (px/detik); timur di kiri."""
    toward = math.radians(wx["wind_from"] + 180)
    east = math.sin(toward)
    return -east * wx["wind"] * (w / 2560) * 0.8


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


def _cloud_sprites(w, h, n, heavy, line_al):
    """awan dirender sekali ke sprite; per frame cukup ditempel (hemat CPU)."""
    import cairo
    import random
    key = (w, h, n, round(heavy, 2), round(line_al, 3))
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
    n = round(cover * cfg["clouds_max"])
    if n == 0:
        return
    vx = wind_px(wx, w)
    moon_lit = a["illum"] if (a["moon"][0] > 0 and a["night"] > 0) else 0
    # garis awan: terang di siang hari, redup di malam (lebih jelas saat bulan terang)
    line_al = 0.75 * (1 - a["night"]) + a["night"] * (0.28 + 0.35 * moon_lit)
    line_al *= 1.0 if wx["rain"] == 0 else 0.8
    heavy = 1 + 0.35 * wx["rain"]
    for surf, ox, oy, x0, cy, speed_f, scale in _cloud_sprites(w, h, n, heavy, line_al):
        span = w + 7 * scale
        cx = (x0 * span + vx * speed_f * t) % span - 3.5 * scale
        ctx.set_source_surface(surf, cx - ox, cy - oy)
        ctx.paint()


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
    for rx, ry, sp in _rain_drops(n):
        y = (ry * h_total + vy * sp * t) % h_total
        if y < y0 - length or y >= y1:
            continue
        x = (rx * w + vx * t) % w
        ctx.move_to(x, y - y0)
        ctx.line_to(x + sx, y - y0 + length)
    ctx.stroke()


def draw_lightning(ctx, wx, t, cfg):
    if not (wx["thunder"] and cfg["lightning"]):
        return
    k = math.floor(t / 6.0)                         # tiap ~6 detik ada peluang kilat
    if _frac(math.sin(k * 91.7) * 5531.3) < 0.25 and _frac(t / 6.0) * 6.0 < 0.18:
        ctx.set_source_rgba(1, 1, 1, 0.07)
        ctx.paint()


def draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total):
    draw_clouds(ctx, w, h, a, wx, t, cfg)
    draw_rain(ctx, w, 0, h, h_total, wx, t)
    draw_lightning(ctx, wx, t, cfg)


def draw_sky(ctx, w, h, a, t, cfg, wx=None, h_total=None):
    draw_sky_base(ctx, w, h, a, t, cfg, wx)
    if wx:
        draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total or h)


def scene_lum(a, cfg, wx):
    """kecerahan garis pemandangan: redup di malam hari (lebih terang saat bulan terang),
    saat mendung, dan saat kabut."""
    moon_up = moon_visible(a, cfg)
    lum = 1.0 - a["night"] * (0.38 - 0.25 * (a["illum"] if moon_up else 0))
    lum *= 1 - 0.45 * max(0.0, (wx["cover"] - 0.5) / 0.5) - (0.3 if wx["fog"] else 0)
    return lum


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
    rough = min(1.0, max(0.0, (wx["wind"] - 10) / 25) + 0.5 * wx["rain"])
    amp0 = h * 0.035 * a["wave_amp"] * (1 + 1.1 * rough)
    direc = a["wave_dir"]
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

# bukit tengah (samar, memudar ke kabut): garis atas sebagai pecahan (x, y)
V_MID_LEFT = [(0.00, 0.47), (0.04, 0.43), (0.08, 0.41), (0.12, 0.43), (0.16, 0.40),
              (0.20, 0.35), (0.235, 0.31), (0.26, 0.30), (0.285, 0.33), (0.30, 0.38),
              (0.33, 0.45), (0.37, 0.52), (0.40, 0.58), (0.43, 0.655), (0.455, 0.70)]
V_MID_LEFT2 = [(0.12, 0.56), (0.16, 0.52), (0.20, 0.50), (0.24, 0.53), (0.28, 0.58),
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
    g = {"mid": [(P(V_MID_LEFT, 0.006), 0.20), (P(V_MID_RIGHT, 0.006), 0.18),
                 (P(V_PILLAR, 0.003, 4), 0.24), (P(V_MID_LEFT2, 0.005), 0.26)],
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
    lake_mist(ctx, W, H, t, night, 1.0 if fog else 0.0, lum)
    for kind, x, y, k, data in g["trees"]:
        (_v_willow if kind == "willow" else _v_bamboo)(ctx, x, y, k, data, t, wind, s, lum)
    if birds:
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


# ── awan: sapuan kuas tinta yang lembut ──────────────────────────────────────
_V_INK = {}


def _v_ink_sprite(W, seed, heavy):
    """satu gumpalan awan: beberapa elips bergradasi lembut yang memanjang
    mendatar, tanpa garis tepi. Disimpan sebagai gambar (dibuat sekali)."""
    import cairo
    key = (W, seed, round(heavy, 1))
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
    _V_INK[key] = (surf, w, h)
    return _V_INK[key]


def ink_clouds(ctx, W, h_sky, cover, rain, night, moon_lit, vx, t, lum=1.0):
    """awan tinta; cover 0..1, vx = kecepatan angin di layar (px/detik)."""
    n = round(cover * 9)
    if n == 0:
        return
    heavy = 1 + 0.6 * rain
    # siang jelas, malam samar (lebih terlihat saat bulan terang)
    alpha = (0.42 * (1 - night) + night * (0.10 + 0.22 * moon_lit)) * (1 + 0.4 * rain) * lum
    for i in range(n):
        surf, w, h = _v_ink_sprite(W, 100 + i, heavy)
        r = random.Random(500 + i)
        span = W + w
        x = (r.random() * span + vx * (0.6 + 0.5 * r.random()) * t) % span - w
        y = (0.06 + 0.62 * r.random()) * h_sky - h / 2
        ctx.set_source_surface(surf, x, y)
        ctx.paint_with_alpha(min(1.0, alpha * (0.7 + 0.5 * r.random())))


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


_V_FRAME = {}


def draw_valley_frame(ctx, W, H, a, wx, t, cfg, gen=0):
    """scene valley: satu bingkai layar penuh (langit, awan, bukit, danau, pohon, hujan).
    gen naik setiap data langit berganti (20 detik) -> langit dasar digambar ulang."""
    import cairo
    h_sky = int(H * VALLEY_HORIZON)
    lum = round(scene_lum(a, cfg, wx), 3)
    dx, dy = (round(v) for v in drift(t, cfg["drift"]))
    cache = _V_FRAME.setdefault((W, H), {"sky": (None, None), "static": (None, None)})
    # 1. langit dasar (bintang, planet, matahari, bulan): cache per gen
    if cache["sky"][0] != gen:
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, h_sky)
        draw_sky_base(cairo.Context(surf), W, h_sky, a, t, cfg, wx)
        cache["sky"] = (gen, surf)
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    ctx.set_source_surface(cache["sky"][1], 0, 0)
    ctx.paint()
    # 2. awan tinta (menggantikan awan garis)
    moon_lit = a["illum"] if (a["moon"][0] > 0 and a["night"] > 0) else 0
    ink_clouds(ctx, W, h_sky, wx["cover"], wx["rain"], a["night"], moon_lit, wind_px(wx, W), t)
    # 3. bukit, batu, danau: gambar transparan, dicat setelah awan (bukit menutupi awan & bintang)
    key = (lum, dx, dy)
    if cache["static"][0] != key:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        c = cairo.Context(surf)
        c.translate(dx, dy)
        valley_static(c, W, H, lum)
        cache["static"] = (key, surf)
    ctx.set_source_surface(cache["static"][1], 0, 0)
    ctx.paint()
    # 4. animasi: pantulan, kabut danau, pohon, burung
    r_sun, r_moon = radii(W, a, cfg)
    fade = max(0.0, 1 - wx["cover"] / 0.7)          # mendung -> pantulan hilang
    bodies = []
    if sun_up(a):
        x, y = project(*a["sun"], W, h_sky)
        bodies.append((x, y, r_sun, 0.9 * fade))
    if moon_visible(a, cfg):
        x, y = project(*a["moon"], W, h_sky)
        bodies.append((x, y, r_moon, a["illum"] * fade))
    birds = sun_up(a) and wx["cover"] < 0.5 and wx["rain"] == 0
    ctx.save()
    ctx.translate(dx, dy)
    valley_anim(ctx, W, H, t, lum, wind=wx["wind"], birds=birds, bodies=bodies,
                night=a["night"], fog=wx["fog"])
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
    h_sky = int(h * cfg["horizon"])
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    ctx = cairo.Context(surf)
    if SCENES[cfg["scene"]] is not None:
        SCENES[cfg["scene"]](ctx, w, h, a, wx, t, cfg)
    else:
        draw_sky(ctx, w, h_sky, a, t, cfg, wx, h)
        ctx.save()
        ctx.translate(0, h_sky)
        ctx.rectangle(0, 0, w, h - h_sky)
        ctx.clip()
        draw_sea(ctx, w, h - h_sky, a, t, cfg, h_sky, wx)
        ctx.restore()
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
def run():
    import cairo
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    gi.require_foreign("cairo")
    from gi.repository import Gdk, GLib, Gtk
    from gi.repository import Gtk4LayerShell as Layer

    cfg = load_config()
    weather = Weather(cfg)
    state = {"a": full_state(datetime.now().astimezone(), cfg), "wx": None, "gen": 0}

    def refresh():
        now = datetime.now().astimezone()
        state["a"] = full_state(now, cfg)
        weather.poll()
        state["wx"] = weather.get(now)
        state["gen"] += 1                            # langit dasar perlu digambar ulang
        return True
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
            area.set_draw_func(lambda _a, c, w, h: render(c, w, h, state["a"], state["wx"] or
                                                          WEATHER_FIXED["clear"], time.time(), cfg, state["gen"]))
            win.set_child(area)
            last_f = {"t": 0}

            def tick_full(_w, clock):
                now = clock.get_frame_time()
                if now - last_f["t"] >= 1_000_000 / cfg["fps"]:
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
            key = (w, h, state["gen"])
            if cache["key"] != key:                  # bintang/planet/matahari/bulan: tiap 20 dtk
                surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
                draw_sky_base(cairo.Context(surf), w, h, state["a"], t, cfg, state["wx"])
                cache["surf"], cache["key"] = surf, key
            c.set_source_surface(cache["surf"], 0, 0)
            c.paint()
            if state["wx"]:
                draw_sky_overlay(c, w, h, state["a"], state["wx"], t, cfg, geo.height)

        sky.set_draw_func(draw_sky_cb)
        sea.set_draw_func(lambda _a, c, w, h: draw_sea(c, w, h, state["a"], time.time(), cfg,
                                                       sky.get_height(), state["wx"]))
        box.append(sky); box.append(sea)
        win.set_child(box)

        last = {"sea": 0, "sky": 0, "gen": -1}

        def tick(_w, clock):        # berhenti sendiri kalau compositor tidak meminta frame
            now = clock.get_frame_time()
            if now - last["sea"] >= 1_000_000 / cfg["fps"]:
                last["sea"] = now
                sea.queue_draw()
            wx = state["wx"] or {}
            if wx.get("rain", 0) > 0 or wx.get("thunder"):
                sky_us = 1_000_000 / cfg["fps"]
            elif wx.get("cover", 0) > 0 or wx.get("fog"):
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
    if args and args[0] == "--preview":
        out = args[1] if len(args) > 1 else "livepaper-preview.png"
        size = args[args.index("--size") + 1] if "--size" in args else "2560x1600"
        when = args[args.index("--time") + 1] if "--time" in args else None
        wthr = args[args.index("--weather") + 1] if "--weather" in args else None
        scn = args[args.index("--scene") + 1] if "--scene" in args else None
        preview(out, size, when, wthr, scn)
    else:
        run()
