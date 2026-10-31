"""konfigurasi: nilai bawaan, baca config.ini, migrasi config lama."""
import configparser
import os
import sys


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
    "weather_transition": "180",  # detik, durasi transisi halus data cuaca (0 = langsung)
    "scene": "sea",         # sea | valley (pemandangan di bawah cakrawala)
}


def load_config(scenes):
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
    if scene not in scenes:
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
        "weather_transition": max(0, c.getint("weather_transition")),
        "scene": scene,
    }
