"""Test penemuan scene otomatis: modul scene tiruan di salinan sementara repo muncul di
--list-scenes dan diterima `scene =` di config; modul tanpa NAME dilewati.

Jalankan: python3 -m unittest tests.test_scenes -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SceneListAndConfig(unittest.TestCase):
    def setUp(self):
        # Direktori kerja sementara (salinan repo)
        self.tmp = tempfile.TemporaryDirectory()
        self.copy = self.tmp.name
        for name in ("livepaper.py", "stars.dat"):
            shutil.copy2(os.path.join(ROOT, name),
                         os.path.join(self.copy, name))
        shutil.copytree(os.path.join(ROOT, "qlp"),
                        os.path.join(self.copy, "qlp"),
                        ignore=shutil.ignore_patterns("__pycache__"))

        # Tulis modul tiruan yang punya NAME + draw → akan muncul di daftar
        tiruan_path = os.path.join(self.copy, "qlp", "scenes", "tiruan.py")
        with open(tiruan_path, "w") as f:
            f.write('NAME = "tiruan"\n'
                    'def draw(ctx, w, h, a, wx, t, cfg, gen=0):\n'
                    '    ctx.set_source_rgb(0, 0, 0)\n'
                    '    ctx.paint()\n')

        # Tulis modul tanpa NAME → harus diabaikan scanner
        pembantu_path = os.path.join(self.copy, "qlp", "scenes", "pembantu.py")
        with open(pembantu_path, "w") as f:
            f.write("X = 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_scenes_includes_fake(self):
        """--list-scenes di salinan harus memuat sea, tiruan, valley (urut nama file)."""
        env = dict(os.environ, XDG_CONFIG_HOME=self.copy)
        p = subprocess.run(
            [sys.executable, os.path.join(self.copy, "livepaper.py"), "--list-scenes"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        self.assertEqual(p.returncode, 0)
        lines = p.stdout.splitlines()
        self.assertEqual(lines, ["sea", "tiruan", "valley"])

    def test_repo_unchanged(self):
        """--list-scenes di repo asli TIDAK boleh memuat tiruan."""
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "livepaper.py"), "--list-scenes"],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, XDG_CONFIG_HOME=self.copy),
        )
        self.assertEqual(p.returncode, 0)
        lines = p.stdout.splitlines()
        self.assertEqual(lines, ["sea", "valley"])

    def test_config_accepts_fake(self):
        """config scene = tiruan → preview berhasil, stderr tanpa pesan error scene."""
        xdg = os.path.join(self.copy, "xdg")
        os.makedirs(os.path.join(xdg, "qamariah-livepaper"))
        with open(os.path.join(xdg, "qamariah-livepaper", "config.ini"), "w") as f:
            f.write("[livepaper]\nscene = tiruan\n")

        out_png = os.path.join(self.copy, "x.png")
        env = dict(os.environ, XDG_CONFIG_HOME=xdg)
        p = subprocess.run(
            [sys.executable, os.path.join(self.copy, "livepaper.py"),
             "--preview", out_png, "--size", "320x200", "--weather", "clear"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("scene tidak dikenal", p.stderr)
        with open(out_png, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_config_rejects_unknown(self):
        """config scene = tidakada → stderr memuat 'scene tidak dikenal 'tidakada''."""
        xdg = os.path.join(self.copy, "xdg")
        os.makedirs(os.path.join(xdg, "qamariah-livepaper"))
        with open(os.path.join(xdg, "qamariah-livepaper", "config.ini"), "w") as f:
            f.write("[livepaper]\nscene = tidakada\n")

        env = dict(os.environ, XDG_CONFIG_HOME=xdg)
        p = subprocess.run(
            [sys.executable, os.path.join(self.copy, "livepaper.py"),
             "--preview", "/dev/null", "--size", "320x200", "--weather", "clear"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        self.assertEqual(p.returncode, 0)                  # tetap jalan dengan sea
        self.assertIn("scene tidak dikenal 'tidakada'", p.stderr)


if __name__ == "__main__":
    unittest.main()
