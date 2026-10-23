"""Test render `livepaper.py --preview` dan bandingkan dengan gambar acuan.

Jalankan test:
    python3 -m unittest tests.test_render

Perbarui gambar acuan (generate ulang):
    UPDATE_REF=1 python3 -m unittest tests.test_render

Test render_scale (0.75, 0.5) ada di kelas ScaledRender.
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
    ("valley-siang",   "2026-10-20 12:00", "clear", "valley"),
    ("valley-senja",   "2026-10-20 18:05", "clear", "valley"),
    ("valley-malam",   "2026-10-20 22:00", "clear", "valley"),
    ("valley-hujan",   "2026-10-20 18:05", "rain",  "valley"),
]
# persentase piksel hitam yang diharapkan per scene (valley: lukisan tinta bergradasi)
BLACK_PCT = {"sea": (95, 100), "valley": (60, 80)}
# toleransi perbandingan dengan acuan
MAX_DIFF_PIXELS = 0.0005   # pecahan piksel yang boleh berbeda
MAX_CHANNEL_DIFF = 24      # selisih terbesar satu kanal (0..255)
# render_scale < 1: filter bilinear membuat halo redup di sekitar garis tipis,
# jadi piksel hitam berkurang. Batas: paling banyak turun sekian poin persen
# dari render 1.0 kasus yang sama (batas atas tetap rentang scene).
SCALES = (0.75, 0.5)
SCALED_BLACK_DROP = 6.0


def render(out, when, weather, scene=None, size=SIZE, scale=None):
    cmd = [
        sys.executable,
        os.path.join(ROOT, "livepaper.py"),
        "--preview", out,
        "--size", "%dx%d" % size,
        "--time", when,
        "--weather", weather,
    ]
    if scene:
        cmd += ["--scene", scene]
    if scale is not None:
        cmd += ["--scale", str(scale)]
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


def black_pct(arr):
    return (arr == 0).all(axis=2).mean() * 100


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
        for nama, *args in CASES:
            render(os.path.join(cls.tmpdir.name, "%s.png" % nama), *args)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_no_error_and_size(self):
        for nama, *_ in CASES:
            with self.subTest(nama=nama):
                path = os.path.join(self.tmpdir.name, "%s.png" % nama)
                self.assertTrue(os.path.isfile(path), "%s tidak ada" % path)
                w, h, _ = load(path)
                self.assertEqual((w, h), SIZE,
                                 "%s ukuran (%d,%d) != %s" % (nama, w, h, SIZE))

    def test_mostly_black(self):
        for nama, *args in CASES:
            with self.subTest(nama=nama):
                path = os.path.join(self.tmpdir.name, "%s.png" % nama)
                w, h, arr = load(path)
                black = np.sum((arr == 0).all(axis=2))
                total = w * h
                pct = black / total * 100
                lo, hi = BLACK_PCT[args[2] if len(args) > 2 else "sea"]
                self.assertTrue(lo < pct < hi,
                                "%s %.2f%% piksel hitam (butuh %s..%s%%)"
                                % (nama, pct, lo, hi))

    def test_matches_reference(self):
        update = os.environ.get("UPDATE_REF") == "1"
        if update:
            os.makedirs(REF, exist_ok=True)
            for nama, *_ in CASES:
                src = os.path.join(self.tmpdir.name, "%s.png" % nama)
                dst = os.path.join(REF, "%s.png" % nama)
                with open(src, "rb") as sf, open(dst, "wb") as df:
                    df.write(sf.read())
            self.skipTest("acuan diperbarui")

        for nama, *_ in CASES:
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



class ScaledRender(unittest.TestCase):
    """render_scale: 1.0 identik byte per byte dengan acuan; 0.75 dan 0.5 berjalan,
    ukuran keluaran tetap layar penuh, dan rasio piksel hitam masih wajar."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        for nama, when, weather, *scene in CASES:
            for scale in (1.0,) + SCALES:
                render(cls.path(nama, scale), when, weather, *scene, scale=scale)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    @classmethod
    def path(cls, nama, scale):
        return os.path.join(cls.tmpdir.name, "%s-%s.png" % (nama, scale))

    def test_scale_1_identical_bytes(self):
        for nama, *_ in CASES:
            with self.subTest(nama=nama):
                with open(self.path(nama, 1.0), "rb") as f:
                    got = f.read()
                with open(os.path.join(REF, "%s.png" % nama), "rb") as f:
                    ref = f.read()
                self.assertTrue(got == ref, "%s: --scale 1.0 tidak identik dengan acuan" % nama)

    def test_scaled_size_and_black(self):
        for nama, *args in CASES:
            lo, hi = BLACK_PCT[args[2] if len(args) > 2 else "sea"]
            _, _, full = load(os.path.join(REF, "%s.png" % nama))
            base = black_pct(full)
            for scale in SCALES:
                with self.subTest(nama=nama, scale=scale):
                    w, h, arr = load(self.path(nama, scale))
                    self.assertEqual((w, h), SIZE)
                    pct = black_pct(arr)
                    self.assertTrue(base - SCALED_BLACK_DROP <= pct < hi,
                                    "%s skala %s: %.2f%% piksel hitam (1.0: %.2f%%, butuh %.2f..%s%%)"
                                    % (nama, scale, pct, base, base - SCALED_BLACK_DROP, hi))
                    # gambar bukan hitam polos: masih ada isi
                    self.assertGreater(100 - pct, 0.5, "%s skala %s hampir kosong" % (nama, scale))

    def test_scaled_close_to_full(self):
        """gambar kecil yang diperbesar harus mirip versi penuh (posisi proporsional):
        bandingkan versi yang sama-sama diperkecil 16x (rata-rata blok)."""
        def small(arr):
            h, w = arr.shape[0] // 16 * 16, arr.shape[1] // 16 * 16
            a = arr[:h, :w].astype(np.float32).mean(axis=2)
            return a.reshape(h // 16, 16, w // 16, 16).mean(axis=(1, 3))
        for nama, *_ in CASES:
            _, _, full = load(os.path.join(REF, "%s.png" % nama))
            ref = small(full)
            for scale in SCALES:
                with self.subTest(nama=nama, scale=scale):
                    _, _, arr = load(self.path(nama, scale))
                    diff = np.abs(small(arr) - ref)
                    self.assertLess(diff.mean(), 3.0, "%s skala %s rata-rata selisih %.2f"
                                    % (nama, scale, diff.mean()))


if __name__ == "__main__":
    unittest.main()
