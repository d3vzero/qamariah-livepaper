"""Test fungsi pengubah config di qamariah-livepaper-menu (bash).

Jalankan:
    python3 -m unittest tests.test_menu
"""
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "qamariah-livepaper-menu")

SAMPLE = """\
# ~/.config/qamariah-livepaper/config.ini — semua baris opsional
[livepaper]
# lokasi pengamat (desimal; selatan & barat negatif)
lat = -6.2
lon   =   106.8
# fps = 30   (komentar, jangan diubah)
fps = 12
horizon = 0.68
;scene = valley
weather = live

[lain]
scene = jangan-diubah
"""


def bash(script, *args):
    """jalankan potongan bash setelah men-source script menu (tanpa main)."""
    return subprocess.run(["bash", "-c", 'source "$0"; ' + script, MENU, *args],
                          capture_output=True, text=True, timeout=10)


class ConfigSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.ini")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def set(self, key, value):
        r = bash('config_set "$1" "$2" "$3"', self.path, key, value)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_source_does_not_run_menu(self):
        r = bash("declare -F config_set")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "config_set")

    def test_replace_existing_keeps_other_lines(self):
        self.write(SAMPLE)
        self.set("lat", "-7.25")
        self.set("lon", "112.75")
        self.set("fps", "8")
        want = (SAMPLE.replace("lat = -6.2\n", "lat = -7.25\n")
                      .replace("lon   =   106.8\n", "lon = 112.75\n")
                      .replace("fps = 12\n", "fps = 8\n"))
        self.assertEqual(self.read(), want)

    def test_add_missing_key_into_livepaper_section(self):
        self.write(SAMPLE)
        self.set("scene", "valley")
        self.set("render_scale", "0.75")
        got = self.read().splitlines()
        # baris lama tetap ada dan urutannya sama
        old = SAMPLE.splitlines()
        self.assertEqual([l for l in got if l in old], old)
        self.assertEqual(len(got), len(old) + 2)
        # baris baru ada di bagian [livepaper], bukan [lain]
        lain = got.index("[lain]")
        self.assertIn("scene = valley", got[:lain])
        self.assertIn("render_scale = 0.75", got[:lain])
        self.assertGreater(got.index("scene = valley"), got.index("[livepaper]"))
        self.assertEqual(got[lain + 1:], ["scene = jangan-diubah"])
        self.assertIn(";scene = valley", got)

    def test_idempotent(self):
        self.write(SAMPLE)
        for _ in range(3):
            self.set("scene", "valley")
            self.set("fps", "15")
        once = self.read()
        self.set("scene", "valley")
        self.assertEqual(self.read(), once)
        self.assertEqual(once.splitlines().count("scene = valley"), 1)

    def test_missing_file_and_section(self):
        self.set("fps", "24")
        self.assertEqual(self.read(), "[livepaper]\nfps = 24\n")
        os.remove(self.path)
        self.write("# hanya komentar\n[lain]\nx = 1\n")
        self.set("fps", "24")
        got = self.read()
        self.assertTrue(got.startswith("# hanya komentar\n[lain]\nx = 1\n"), got)
        self.assertIn("[livepaper]\nfps = 24\n", got)

    def test_missing_directory(self):
        self.path = os.path.join(self.tmp.name, "baru", "dir", "config.ini")
        self.set("scene", "valley")
        self.assertEqual(self.read(), "[livepaper]\nscene = valley\n")

    def test_header_with_spaces_and_duplicates(self):
        self.write("  [livepaper]  \nfps = 1\nfps = 2\n[lain]\nfps = 3\n")
        self.set("fps", "8")
        self.assertEqual(self.read(), "  [livepaper]  \nfps = 8\nfps = 2\n[lain]\nfps = 3\n")

    def test_no_leftover_temp_files_and_mode_kept(self):
        self.write(SAMPLE)
        os.chmod(self.path, 0o644)
        self.set("fps", "8")
        self.assertEqual(os.listdir(self.tmp.name), ["config.ini"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_no_trailing_newline_and_special_values(self):
        self.write("[livepaper]\nlat = 1\nlon = 2")      # tanpa newline akhir
        self.set("lat", "-6.914744")
        self.set("lon", r"107.6\n&|/")
        self.assertEqual(self.read(), "[livepaper]\nlat = -6.914744\nlon = 107.6\\n&|/\n")


class LatLon(unittest.TestCase):
    def check(self, text):
        return bash('parse_latlon "$1"', text)

    def test_valid(self):
        for text, want in [("-6.2,106.8", "-6.2;106.8"),
                           (" -6.2 , 106.8 ", "-6.2;106.8"),
                           ("0,0", "0;0"),
                           ("90,-180", "90;-180"),
                           ("-90.0,180.0", "-90.0;180.0")]:
            with self.subTest(text=text):
                r = self.check(text)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), want)

    def test_invalid(self):
        for text in ["", "abc", "-6.2", "-6.2,", ",106.8", "91,0", "0,181",
                     "-6.2;106.8x", "1e3,2", "-6.2,106.8,3", "--1,2", "1..2,3",
                     "1 2,3", "-6.2,10 6.8", "- 6.2,106.8"]:
            with self.subTest(text=text):
                self.assertNotEqual(self.check(text).returncode, 0)


if __name__ == "__main__":
    unittest.main()
