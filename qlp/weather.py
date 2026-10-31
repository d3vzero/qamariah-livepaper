"""cuaca: tetap (WEATHER_FIXED), simulasi tropis, live Open-Meteo, transisi halus (WeatherBlend), demo."""
import math
import os
import sys
import time


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


V_CLOUDS_MAX = 9          # jumlah awan tinta saat langit tertutup penuh (scene valley)

RAIN_EPS = 0.05   # hujan di bawah ini: efek hujan memudar, bukan hilang mendadak

BLEND_KEYS = ("cover", "rain", "wind", "fog", "thunder", "clouds")


def sea_rough(wx):
    """0 tenang ... 1 badai: dari angin dan hujan."""
    return min(1.0, max(0.0, (wx["wind"] - 10) / 25) + 0.5 * wx["rain"])


def _moved(a, b):
    """True kalau gerak (angin, gelombang, ukuran awan) berubah cukup besar."""
    return (abs(wind_px(a, 2560) - wind_px(b, 2560)) > 1.0
            or abs(sea_rough(a) - sea_rough(b)) > 0.03
            or abs(a["rain"] - b["rain"]) > 0.03)


class _Motion:
    """lintasan posisi benda yang digeser angin; berpindah halus dari lintasan prev
    ke lintasan cuaca wx, lalu tepat sama dengan lintasan wx (modulo 1 periode)."""

    def __init__(self, wx, prev, t0, dur):
        self.wx, self.prev, self.t0, self.t1, self.dur = wx, prev, t0, t0 + dur, dur
        self.memo = {}

    def pos(self, key, track, t):
        if self.prev is None or t >= self.t1:
            return track(self.wx, t)
        if key not in self.memo:
            # kecepatan berpindah halus va -> vb (bukan posisi yang dicampur: itu membuat
            # benda melaju terlalu cepat); d0 = sisa kurang dari 1 periode agar di t1 tepat
            # di lintasan wx
            pa0 = self.prev.pos(key, track, self.t0)
            va = self.prev.pos(key, track, self.t0 + 1) - pa0
            vb = track(self.wx, self.t0 + 1) - track(self.wx, self.t0)
            end = self.prev.pos(key, track, self.t1) + (vb - va) * self.dur / 2
            d0 = (track(self.wx, self.t1) - end + 0.5) % 1 - 0.5
            self.memo[key] = (va, vb, d0)
        va, vb, d0 = self.memo[key]
        x = (t - self.t0) / self.dur
        s = _smooth(0, 1, x)
        return self.prev.pos(key, track, t) + (vb - va) * self.dur * (x ** 3 - x ** 4 / 2) + s * d0


class WeatherBlend:
    def __init__(self, cfg):
        self.dur = cfg["weather_transition"]
        self.m = V_CLOUDS_MAX if cfg["scene"] == "valley" else cfg["clouds_max"]
        self.node = None

    def _target(self, wx):
        out = dict(wx)
        out["fog"] = float(out["fog"])
        out["thunder"] = float(out["thunder"])
        out["clouds"] = round(wx["cover"] * self.m)
        return out

    def set(self, wx, now):
        tgt = self._target(wx)
        if self.node is not None:
            tk = BLEND_KEYS + ("wind_from",)
            if all(tgt[k] == self.node[1][k] for k in tk):
                return
        if self.node is None:
            self.node = (None, tgt, now, _Motion(tgt, None, now, self.dur))
        else:
            start = self.get(now)
            mo = self.node[3]
            m = mo
            while m is not None:                     # lintasan yang sudah selesai: lepas rantainya
                if now >= m.t1:
                    m.prev = None
                    m.memo.clear()
                m = m.prev
            if _moved(mo.wx, tgt):
                mo = _Motion(tgt, mo, now, self.dur)
            self.node = (start, tgt, now, mo)

    def get(self, now):
        if self.node is None:
            return None
        start, tgt, t0, mo = self.node
        if start is not None and now <= t0:
            return start
        if start is None or self.dur <= 0 or now >= t0 + self.dur:
            out = dict(tgt)
        else:
            s = _smooth(0, 1, (now - t0) / self.dur)
            out = dict(tgt)
            for k in BLEND_KEYS:
                out[k] = start[k] + (tgt[k] - start[k]) * s
            d = (tgt["wind_from"] - start["wind_from"] + 180) % 360 - 180
            out["wind_from"] = start["wind_from"] + d * s
        out.pop("_mo", None)
        if mo.wx is not tgt or (mo.prev is not None and now < mo.t1):
            out["_mo"] = mo                          # tanpa "_mo": rumus lama, identik tanpa transisi
        return out


def wind_px(wx, w):
    """kecepatan horizontal di layar (px/detik); timur di kiri."""
    toward = math.radians(wx["wind_from"] + 180)
    east = math.sin(toward)
    return -east * wx["wind"] * (w / 2560) * 0.8


def demo_transition(transition, period):
    """durasi transisi mode demo: selesai sebelum kondisi berikutnya datang."""
    return min(transition, period * 0.4)
