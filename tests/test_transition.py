"""Test transisi cuaca halus (WeatherBlend) melalui render — tanpa lonjakan piksel.

Diuji (scene sea dan valley; badai -> cerah, lalu angin berbalik arah):
  - Tiap langkah 1 detik selama transisi, perubahan rata-rata kecerahan per blok
    32x32 (tanpa sekitar matahari/bulan) tidak melebihi 1.5 x perubahan saat
    cuaca tetap + 2. Gerak biasa hampir tidak terhitung; awan/hujan yang muncul,
    hilang, atau melompat mendadak terhitung besar.
  - Kontrol: perpindahan langsung A -> B memang melewati batas itu.
  - Frame awal identik dengan render A, frame akhir identik dengan render B.

Cara jalan:
    python3 -m unittest tests.test_transition
"""
import itertools
import os
import sys
import tempfile
import time as _time
import unittest

import cairo
import numpy as np
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

tmpconfig = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = tmpconfig.name
os.environ["TZ"] = "Asia/Jakarta"
_time.tzset()

import livepaper
from livepaper import WEATHER_FIXED, WeatherBlend

SIZE = (1280, 800)
WHEN = "2026-10-20 15:00"
PAIRS = [
    ("badai-cerah", WEATHER_FIXED["storm"], WEATHER_FIXED["clear"]),
    ("angin-berbalik", WEATHER_FIXED["cloudy"],
     dict(WEATHER_FIXED["cloudy"], wind=30, wind_from=270)),
]
SCENES = ("sea", "valley")
BLOCK = 32   # lonjakan = perubahan rata-rata kecerahan per blok BLOCKxBLOCK piksel


_gen_counter = itertools.count(1)   # gen unik per render: cache bingkai valley tidak dipakai ulang


def render(cfg, a, wx, t):
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, SIZE[0], SIZE[1])
    ctx = cairo.Context(surf)
    h, w = SIZE[1], SIZE[0]
    livepaper.draw_frame(ctx, w, h, a, wx, t, cfg, next(_gen_counter))
    surf.flush()
    stride = surf.get_stride()
    arr = np.frombuffer(surf.get_data(), np.uint8).reshape(h, stride)[:, :w * 4]
    arr = arr.reshape(h, w, 4)[:, :, :3].copy()
    return arr


def body_mask(cfg, a):
    """piksel di sekitar matahari/bulan: awan yang lewat di depannya wajar berubah cepat."""
    w, h = SIZE
    h_sky = int(h * (livepaper.VALLEY_HORIZON if cfg["scene"] == "valley" else cfg["horizon"]))
    r_sun, r_moon = livepaper.radii(w, a, cfg)
    yy, xx = np.mgrid[0:h, 0:w]
    mask = np.zeros((h, w), bool)
    for up, body, r in ((livepaper.sun_up(a), a["sun"], r_sun),
                        (livepaper.moon_visible(a, cfg), a["moon"], r_moon)):
        if up:
            x, y = livepaper.project(*body, w, h_sky)
            mask |= (xx - x) ** 2 + (yy - y) ** 2 < (3 * r) ** 2
    return mask


def jump(f1, f2, mask):
    """selisih terbesar rata-rata kecerahan blok: gerak kecil hampir tidak terhitung,
    benda yang muncul/hilang mendadak terhitung besar."""
    g1, g2 = f1.max(axis=2).astype(float), f2.max(axis=2).astype(float)
    g2[mask] = g1[mask]
    h, w = g1.shape
    blocks = lambda g: g[:h // BLOCK * BLOCK, :w // BLOCK * BLOCK].reshape(
        h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean(axis=(1, 3))
    return np.abs(blocks(g1) - blocks(g2)).max()


class Transition(unittest.TestCase):
    def test_smooth(self):
        for scene in SCENES:
            for pair_name, A, B in PAIRS:
                with self.subTest(scene=scene, pair=pair_name):
                    cfg = livepaper.load_config()
                    cfg["lightning"] = False
                    cfg["scene"] = scene
                    dur = cfg["weather_transition"]

                    now = datetime.datetime.strptime(WHEN, "%Y-%m-%d %H:%M").astimezone()
                    a = livepaper.full_state(now, cfg)
                    t0 = now.timestamp()
                    mask = body_mask(cfg, a)

                    # Batas: variasi steady antar frame identik
                    steady = max(jump(render(cfg, a, X, t0 + k), render(cfg, a, X, t0 + k + 1), mask)
                                 for X in (A, B) for k in range(5))
                    limit = 1.5 * steady + 2

                    # Kontrol: transisi langsung (tanpa blend) harus melonjak
                    A_jump_B = jump(render(cfg, a, A, t0), render(cfg, a, B, t0 + 1), mask)
                    self.assertGreater(A_jump_B, limit,
                                       "kontrol gagal: jump(A,B)=%.6f ≤ limit %.6f"
                                       % (A_jump_B, limit))

                    # Setup blend
                    blend = WeatherBlend(cfg)
                    blend.set(A, t0 - 10)
                    blend.set(B, t0)

                    # Loop transisi
                    prev = None
                    worst = (0.0, None)
                    for k in range(dur + 2):
                        t = t0 + k
                        f = render(cfg, a, blend.get(t), t)

                        if k == 0:
                            expected = render(cfg, a, A, t0)
                            self.assertTrue(np.array_equal(f, expected),
                                            "frame awal != render A")

                        if prev is not None:
                            j = jump(prev, f, mask)
                            if j > worst[0]:
                                worst = (j, k)
                        prev = f

                    self.assertLessEqual(worst[0], limit,
                                         "%s %s worst_jump=%.6f at k=%s limit=%.6f"
                                         % (scene, pair_name, worst[0], worst[1], limit))

                    # Frame terakhir harus identik dengan B
                    t_end = t0 + dur + 1
                    f_end = render(cfg, a, blend.get(t_end), t_end)
                    expected_end = render(cfg, a, B, t_end)
                    self.assertTrue(np.array_equal(f_end, expected_end),
                                    "frame akhir != render B")


if __name__ == "__main__":
    unittest.main()
