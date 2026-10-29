"""Test transisi cuaca halus (WeatherBlend) melalui render — tanpa lonjakan piksel.

Diuji:
  - Saat transisi A→B, setiap langkah berurutan hanya mengubah pecahan piksel
    kecil (≤ limit = 1.5 × steady + 0.002).
  - Frame awal identik dengan render A; frame akhir identik dengan render B.
  - Ada lonjakan aktual di awal transisi (kontrol: jump(A, B) > limit).

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
JUMP = 32


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


def jump(f1, f2):
    frac = (np.abs(f1.astype(np.int16) - f2.astype(np.int16)).max(axis=2) > JUMP).mean()
    return frac


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

                    # Batas: variasi steady antar frame identik
                    steady = max(jump(render(cfg, a, X, t0 + k), render(cfg, a, X, t0 + k + 1))
                                 for X in (A, B) for k in range(3))
                    limit = 1.5 * steady + 0.002

                    # Kontrol: transisi langsung (tanpa blend) harus melonjak
                    A_jump_B = jump(render(cfg, a, A, t0), render(cfg, a, B, t0 + 1))
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
                            j = jump(prev, f)
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
