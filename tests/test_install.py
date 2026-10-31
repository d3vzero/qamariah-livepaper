"""Test instalasi install.sh: verifikasi paket qlp/ terpasang dan livepaper.py berjalan.

Jalankan: python3 -m unittest tests.test_install -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_test_script(src_lines, tmp_dir):
    """Buat versi uji dari install.sh.

    - baris yang diawali "pacman " dihapus (diganti baris kosong)
    - cd "$(dirname "$0")" diganti dengan cd '<ROOT>'
    - setiap "/usr/local" diganti "<tmp>/usr/local"
    """
    root_str = ROOT
    tmp_str = tmp_dir
    out = []
    for line in src_lines:
        stripped = line.lstrip()
        if stripped.startswith("pacman "):
            out.append("")
            continue
        if 'cd "$(dirname "$0")"' in line:
            line = line.replace('cd "$(dirname "$0")"', "cd '%s'" % root_str)
        line = line.replace("/usr/local", tmp_str + "/usr/local")
        out.append(line)
    # PENGAMAN: setiap baris yang masih memuat "/usr/local" harus juga memuat tmp
    for i, line in enumerate(out):
        if "/usr/local" in line and tmp_str not in line:
            raise AssertionError(
                "PENGAMAN: baris %d memuat /usr/local tanpa path tmp: %s" % (i + 1, line)
            )
    return "\n".join(out) + "\n"


class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.tmp_dir = cls.tmp.name
        cls.installed_dir = os.path.join(cls.tmp_dir, "usr/local/share/qamariah-livepaper")
        cls.scenes_dir = os.path.join(cls.installed_dir, "qlp/scenes")

        # baca install.sh asli
        with open(os.path.join(ROOT, "install.sh")) as f:
            src_lines = f.read().splitlines()

        # buat versi uji
        test_script = make_test_script(src_lines, cls.tmp_dir)

        # buat file basi lama.py (simulasi scene dari versi lama)
        os.makedirs(cls.scenes_dir, exist_ok=True)
        with open(os.path.join(cls.scenes_dir, "lama.py"), "w") as f:
            f.write('NAME = "lama"\ndraw = None\n')

        # tulis dan jalankan install-test.sh
        test_sh = os.path.join(cls.tmp_dir, "install-test.sh")
        with open(test_sh, "w") as f:
            f.write(test_script)
        subprocess.run(
            ["sh", test_sh],
            check=True, capture_output=True, text=True, timeout=60
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_installs_package(self):
        """File berikut ada di <tmp>/usr/local/share/qamariah-livepaper/:
        livepaper.py, stars.dat, config.example.ini,
        qlp/__init__.py, qlp/cli.py, qlp/scenes/__init__.py,
        qlp/scenes/sea.py, qlp/scenes/valley.py;
        dan qlp/scenes/lama.py TIDAK ada lagi.
        """
        base = self.installed_dir
        must_exist = [
            "livepaper.py",
            "stars.dat",
            "config.example.ini",
            "qlp/__init__.py",
            "qlp/cli.py",
            "qlp/scenes/__init__.py",
            "qlp/scenes/sea.py",
            "qlp/scenes/valley.py",
        ]
        for rel in must_exist:
            path = os.path.join(base, rel)
            self.assertTrue(os.path.exists(path), "Harus ada: %s" % rel)

        # lama.py harus sudah dihapus
        lama = os.path.join(self.scenes_dir, "lama.py")
        self.assertFalse(os.path.exists(lama), "lama.py harus sudah terhapus")

    def test_installed_runs(self):
        """Jalankan livepaper.py --list-scenes dan --preview di folder instalasi."""
        base = self.installed_dir
        lp = os.path.join(base, "livepaper.py")

        # --list-scenes
        env = dict(os.environ, XDG_CONFIG_HOME=self.tmp_dir)
        p = subprocess.run(
            [sys.executable, lp, "--list-scenes"],
            capture_output=True, text=True, env=env, cwd=self.tmp_dir,
            check=True
        )
        self.assertEqual(p.stdout.splitlines(), ["sea", "valley"])

        # --preview
        png_path = os.path.join(self.tmp_dir, "x.png")
        p = subprocess.run(
            [sys.executable, lp, "--preview", png_path, "--size", "320x200",
             "--weather", "clear"],
            capture_output=True, text=True, env=env, cwd=self.tmp_dir,
            check=True
        )
        self.assertEqual(p.returncode, 0)
        with open(png_path, "rb") as f:
            header = f.read(8)
        self.assertEqual(header, b"\x89PNG\r\n\x1a\n")

    def test_installed_finds_stars(self):
        """load_stars() dari qlp/ terpasang menemukan stars.dat (gagal diam-diam kalau path salah)."""
        code = "import sys; sys.path.insert(0, %r); from qlp.astro import load_stars; print(len(load_stars()))"
        p = subprocess.run([sys.executable, "-c", code % self.installed_dir],
                           capture_output=True, text=True, cwd=self.tmp_dir, check=True)
        self.assertGreater(int(p.stdout), 800)


if __name__ == "__main__":
    unittest.main()
