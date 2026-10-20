"""Test render `livepaper.py --preview` dan bandingkan dengan gambar acuan.

Jalankan test:
    python3 -m unittest tests.test_render

Perbarui gambar acuan (generate ulang):
    UPDATE_REF=1 python3 -m unittest tests.test_render
"""
import os
import subprocess
import sys
import tempfile
import unittest

import cairo
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "tests", "ref")
SIZE = (2560, 1600)    # ukuran layar sebenarnya
CASES = [
    ("siang",          "2026-10-20 12:00", "clear"),
    ("senja",          "2026-10-20 18:05", "clear"),
    ("malam",          "2026-10-20 22:00", "clear"),
    ("purnama",        "2026-10-26 22:00", "clear"),
    ("siang-berawan",  "2026-10-20 12:00", "cloudy"),
    ("senja-hujan",    "2026-10-20 18:05", "rain"),
    ("malam-badai",    "2026-10-20 22:00", "storm"),
    ("purnama-kabut",  "2026-10-26 22:00", "fog"),
    ("sore-sim",       "2026-10-20 15:30", "sim"),
]
# toleransi perbandingan dengan acuan
MAX_DIFF_PIXELS = 0.0005   # pecahan piksel yang boleh berbeda
MAX_CHANNEL_DIFF = 24      # selisih terbesar satu kanal (0..255)


def render(out, when, weather, size=SIZE):
    cmd = [
        sys.executable,
        os.path.join(ROOT, "livepaper.py"),
        "--preview", out,
        "--size", "%dx%d" % size,
        "--time", when,
        "--weather", weather,
    ]
    tmpconfig = tempfile.mkdtemp()
    env = dict(os.environ)
    env["TZ"] = "Asia/Jakarta"
    env["XDG_CONFIG_HOME"] = tmpconfig
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       timeout=120, env=env)
    finally:
        import shutil
        shutil.rmtree(tmpconfig, ignore_errors=True)


def load(path):
    surf = cairo.ImageSurface.create_from_png(path)
    w, h = surf.get_width(), surf.get_height()
    stride = surf.get_stride()
    raw = np.frombuffer(surf.get_data(), np.uint8).reshape(h, stride)
    arr = raw[:, :w * 4].reshape(h, w, 4)[:, :, :3].copy()
    return (w, h, arr)


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        for nama, when, weather in CASES:
            render(os.path.join(cls.tmpdir.name, "%s.png" % nama), when, weather)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_no_error_and_size(self):
        for nama, when, weather in CASES:
            with self.subTest(nama=nama):
                path = os.path.join(self.tmpdir.name, "%s.png" % nama)
                self.assertTrue(os.path.isfile(path), "%s tidak ada" % path)
                w, h, _ = load(path)
                self.assertEqual((w, h), SIZE,
                                 "%s ukuran (%d,%d) != %s" % (nama, w, h, SIZE))

    def test_mostly_black(self):
        for nama, when, weather in CASES:
            with self.subTest(nama=nama):
                path = os.path.join(self.tmpdir.name, "%s.png" % nama)
                w, h, arr = load(path)
                black = np.sum((arr == 0).all(axis=2))
                total = w * h
                pct = black / total * 100
                self.assertGreater(pct, 95,
                                   "%s hanya %.2f%% piksel hitam (butuh >95%%)"
                                   % (nama, pct))

    def test_matches_reference(self):
        update = os.environ.get("UPDATE_REF") == "1"
        if update:
            os.makedirs(REF, exist_ok=True)
            for nama, when, weather in CASES:
                src = os.path.join(self.tmpdir.name, "%s.png" % nama)
                dst = os.path.join(REF, "%s.png" % nama)
                with open(src, "rb") as sf, open(dst, "wb") as df:
                    df.write(sf.read())
            self.skipTest("acuan diperbarui")

        for nama, when, weather in CASES:
            with self.subTest(nama=nama):
                ref_path = os.path.join(REF, "%s.png" % nama)
                self.assertTrue(os.path.isfile(ref_path),
                                "acuan belum ada, jalankan UPDATE_REF=1 untuk membuat: %s"
                                % ref_path)
                _, _, got = load(os.path.join(self.tmpdir.name, "%s.png" % nama))
                _, _, ref = load(ref_path)
                diff = np.abs(got.astype(np.int16) - ref.astype(np.int16)).max(axis=2)
                frac = (diff > 0).mean()
                worst = diff.max()
                self.assertLessEqual(frac, MAX_DIFF_PIXELS,
                                     "%s frac=%.6f > %s" % (nama, frac, MAX_DIFF_PIXELS))
                self.assertLessEqual(worst, MAX_CHANNEL_DIFF,
                                     "%s worst=%.0f > %s" % (nama, worst, MAX_CHANNEL_DIFF))


if __name__ == "__main__":
    unittest.main()
