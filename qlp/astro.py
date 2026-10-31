"""astronomi: posisi matahari/bulan/planet, katalog bintang, proyeksi ke layar, drift anti burn-in."""
import math
import os
from datetime import timezone


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # folder induk qlp/: stars.dat


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
