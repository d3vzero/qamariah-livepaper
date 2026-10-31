"""Test WeatherBlend — lapisan transisi cuaca halus.

Jalankan test:
    python3 -m unittest tests.test_blend
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

tmpconfig = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = tmpconfig.name
os.environ["TZ"] = "Asia/Jakarta"

from qlp.scenes import load_config
from qlp.weather import WEATHER_FIXED, WeatherBlend, demo_transition, wind_px

_A = WEATHER_FIXED["storm"]
_B = WEATHER_FIXED["clear"]
_C = WEATHER_FIXED["fog"]


def _target(blend, wx):
    out = dict(wx)
    out["fog"] = float(out["fog"])
    out["thunder"] = float(out["thunder"])
    out["clouds"] = round(wx["cover"] * blend.m)
    return out


class TestWeatherBlend(unittest.TestCase):
    def setUp(self):
        cfg = load_config()
        cfg["weather_transition"] = 100
        self.cfg = cfg

    def test_1_set_and_get(self):
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        result = blend.get(1000)
        tgt = _target(blend, _A)
        for k in ("cover", "rain", "wind", "wind_from", "clouds"):
            self.assertEqual(result[k], tgt[k], "get(1000)[%s]" % k)
        self.assertEqual(result["fog"], tgt["fog"])
        self.assertEqual(result["thunder"], tgt["thunder"])
        self.assertNotIn("_mo", result, "get(1000) tidak boleh punya _mo")

    def test_2_blend_progress(self):
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        r_start = blend.get(2000)
        self.assertEqual(r_start["cover"], _target(blend, _A)["cover"])

        r_mid = blend.get(2050)
        expected_mid = (_target(blend, _A)["cover"] + _target(blend, _B)["cover"]) / 2
        self.assertAlmostEqual(r_mid["cover"], expected_mid, places=10,
                               msg="cover di pertengahan bukan rata-rata")

        r_end = blend.get(2100)
        tgt_b = _target(blend, _B)
        self.assertEqual(r_end["cover"], tgt_b["cover"])
        self.assertEqual(r_end["rain"], tgt_b["rain"])
        self.assertEqual(r_end["wind"], tgt_b["wind"])
        self.assertEqual(r_end["clouds"], tgt_b["clouds"])
        self.assertEqual(r_end["thunder"], 0.0)
        self.assertNotIn("_mo", r_end)

        r_late = blend.get(5000)
        self.assertEqual(r_late["cover"], tgt_b["cover"])
        self.assertEqual(r_late["rain"], tgt_b["rain"])
        self.assertEqual(r_late["wind"], tgt_b["wind"])
        self.assertEqual(r_late["clouds"], tgt_b["clouds"])

    def test_3_monotonic_smooth(self):
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        cover_vals = [blend.get(t)["cover"] for t in range(2000, 2101)]
        for i in range(1, len(cover_vals)):
            self.assertLessEqual(cover_vals[i], cover_vals[i - 1] + 1e-12,
                                    "cover naik di step %d" % i)
        max_step = 1.5 * abs(_target(blend, _A)["cover"] - _target(blend, _B)["cover"]) / 100 + 1e-12
        for i in range(1, len(cover_vals)):
            diff = abs(cover_vals[i] - cover_vals[i - 1])
            self.assertLessEqual(diff, max_step,
                                 "selisih %.6f > batas %.6f" % (diff, max_step))

    def test_4_interruption(self):
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        v0 = blend.get(2040)
        blend.set(_C, 2040)
        v1 = blend.get(2040.001)
        for k in ("cover", "rain", "wind", "fog", "thunder", "clouds"):
            self.assertLess(abs(v0[k] - v1[k]), 1e-3,
                            "diskontinuitas %s: %.6f vs %.6f" % (k, v0[k], v1[k]))
        self.assertAlmostEqual(blend.get(2140)["cover"], _target(blend, _C)["cover"], places=10)

    def test_5_same_data_no_blend(self):
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(dict(_A), 2000)
        result = blend.get(2001)
        self.assertNotIn("_mo", result)
        self.assertEqual(result["cover"], _target(blend, _A)["cover"])

    def test_6_zero_duration(self):
        self.cfg["weather_transition"] = 0
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        result = blend.get(2000.5)
        tgt_b = _target(blend, _B)
        self.assertEqual(result["cover"], tgt_b["cover"])
        self.assertNotIn("_mo", result)

    def test_7_motion(self):
        self.cfg["weather_transition"] = 100
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        mo = blend.get(2000.5)["_mo"]
        track = lambda wx, t: wind_px(wx, 2560) * 1.3 * t / 3000.0
        for t in range(2000, 2100):
            for dt in (0, 0.5):
                p = mo.pos("k", track, t + dt)
                if dt == 0.5:
                    diff = abs(p - mo.pos("k", track, t + dt - 0.5))
                    self.assertLess(diff * 3000, 60,
                                    "lompat di t=%.1f: %.4f" % (t + dt, diff))
        p0 = mo.pos("k", track, 2000)
        expected0 = track(_A, 2000)
        self.assertEqual(p0, expected0)
        for t in (2100, 2150):
            p = mo.pos("k", track, t)
            expected = track(_B, t)
            diff = ((p - expected) + 0.5) % 1 - 0.5
            self.assertLess(abs(diff), 1e-6,
                            "t=%d: diff=%.10f" % (t, diff))

    def test_7b_motion_no_overshoot(self):
        """kecepatan saat transisi tidak melebihi angin tercepat + koreksi < 1 periode."""
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        mo = blend.get(2000.5)["_mo"]
        track = lambda wx, t: wind_px(wx, 2560) * 1.3 * t / 3000.0
        speed = lambda wx: abs(track(wx, 1) - track(wx, 0))
        vmax = max(speed(_A), speed(_B)) + 1.5 / 100 * 0.5 + 1e-9
        for k in range(200):
            t = 2000 + k * 0.5
            d = mo.pos("k", track, t + 0.5) - mo.pos("k", track, t)
            v = abs((d + 0.5) % 1 - 0.5) / 0.5          # posisi dipakai modulo 1 periode
            self.assertLessEqual(v, vmax, "t=%.1f kecepatan %.5f > %.5f" % (t, v, vmax))

    def test_8_motion_interruption(self):
        C = dict(WEATHER_FIXED["clear"], wind=40, wind_from=270,
                 cover=0.1, rain=0.0, thunder=False, fog=False)
        blend = WeatherBlend(self.cfg)
        blend.set(_A, 1000)
        blend.set(_B, 2000)
        track2 = lambda wx, t: wind_px(wx, 2560) * 1.3 * t / 3000.0
        p_before = blend.get(2040)["_mo"].pos("k", track2, 2040)
        blend.set(C, 2040)
        mo_after = blend.get(2040.001)["_mo"]
        p_after = mo_after.pos("k", track2, 2040.001)
        self.assertLess(abs(p_after - p_before) * 3000, 1, "posisi melompat saat interupsi")
        p = mo_after.pos("k", track2, 2140)
        expected = track2(C, 2140)
        diff = ((p - expected) + 0.5) % 1 - 0.5
        self.assertLess(abs(diff), 1e-6, "t=2140 tidak ≡ track(C,2140) mod 1")



class TestDemoTransition(unittest.TestCase):
    def test_capped_to_40_percent_of_period(self):
        for transition, period, want in [(180, 120, 48), (180, 60, 24), (10, 60, 10),
                                         (24, 60, 24), (0, 60, 0), (180, 1, 0.4)]:
            with self.subTest(transition=transition, period=period):
                got = demo_transition(transition, period)
                self.assertAlmostEqual(got, want)
                self.assertLess(got, period)

    def test_blend_done_before_next_condition(self):
        cfg = load_config()
        cfg["weather_transition"] = demo_transition(180, 60)
        blend = WeatherBlend(cfg)
        blend.set(_A, 0)
        blend.set(_B, 1000)
        self.assertNotEqual(blend.get(1000 + 12), blend.get(1000 + 1000))   # masih transisi
        self.assertEqual(blend.get(1000 + 60), blend.get(1000 + 1000))


if __name__ == "__main__":
    unittest.main()
