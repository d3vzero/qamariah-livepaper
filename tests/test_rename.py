"""Test rename aro-livepaper → qamariah-livepaper dan migrasi config lama.

Jalankan: python3 -m unittest discover tests
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD, NEW = "aro-livepaper", "qamariah-livepaper"


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
    return [f for f in out if not f.startswith("tests/") and f != "stars.dat"]


def run_load_config(xdg):
    """Jalankan load_config() di proses terpisah; kembalikan (lat, stdout, stderr)."""
    code = ("import sys; sys.path.insert(0, %r); from qlp.scenes import load_config; "
            "print(load_config()['lat'])" % ROOT)
    env = dict(os.environ, XDG_CONFIG_HOME=xdg)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, check=True)
    lines = p.stdout.splitlines()
    return float(lines[-1]), lines[:-1], p.stderr.splitlines()


def write_cfg(xdg, name, lat):
    d = os.path.join(xdg, name)
    os.makedirs(d)
    with open(os.path.join(d, "config.ini"), "w") as f:
        f.write("[livepaper]\nlat = %s\n" % lat)


class Rename(unittest.TestCase):
    def test_launcher_renamed(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, OLD)))
        path = os.path.join(ROOT, NEW)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.access(path, os.X_OK))
        with open(path) as f:
            src = f.read()
        self.assertIn("'%s/livepaper.py'" % NEW, src)          # pola pgrep
        self.assertIn("/usr/local/share/%s/livepaper.py" % NEW, src)

    def test_install_paths(self):
        with open(os.path.join(ROOT, "install.sh")) as f:
            src = f.read()
        for name in ("livepaper.py", "config.example.ini", "stars.dat"):
            self.assertIn("/usr/local/share/%s/%s" % (NEW, name), src)
        self.assertIn("/usr/local/bin/%s" % NEW, src)
        self.assertIn("exec = %s" % NEW, src)

    def test_no_old_name_left(self):
        # nama lama hanya boleh tersisa di qlp/config.py, untuk path migrasi config
        for f in tracked_files():
            with open(os.path.join(ROOT, f)) as fh:
                for n, line in enumerate(fh, 1):
                    if OLD in line:
                        self.assertEqual(f, "qlp/config.py", "%s:%d: %s" % (f, n, line))
        with open(os.path.join(ROOT, "qlp", "config.py")) as fh:
            old_lines = [l for l in fh if OLD in l]
        self.assertLessEqual(len(old_lines), 2, old_lines)
        for l in old_lines:
            self.assertNotIn("/usr/local", l)
            self.assertNotIn(".cache", l)


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xdg = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_neither(self):
        sys.path.insert(0, ROOT)
        from qlp.config import DEFAULTS
        lat, out, err = run_load_config(self.xdg)
        self.assertEqual(lat, float(DEFAULTS["lat"]))
        self.assertEqual((out, err), ([], []))

    def test_new_only(self):
        write_cfg(self.xdg, NEW, "1.25")
        lat, out, err = run_load_config(self.xdg)
        self.assertEqual(lat, 1.25)
        self.assertEqual((out, err), ([], []))

    def test_old_only_used_with_notice(self):
        write_cfg(self.xdg, OLD, "2.5")
        lat, out, err = run_load_config(self.xdg)
        self.assertEqual(lat, 2.5)
        self.assertEqual(len(out) + len(err), 1, (out, err))
        self.assertIn(os.path.join(self.xdg, OLD, "config.ini"), (out + err)[0])
        # migrasi tidak memindahkan/menghapus file apa pun
        self.assertFalse(os.path.exists(os.path.join(self.xdg, NEW)))
        self.assertTrue(os.path.exists(os.path.join(self.xdg, OLD, "config.ini")))

    def test_both_prefers_new(self):
        write_cfg(self.xdg, OLD, "2.5")
        write_cfg(self.xdg, NEW, "1.25")
        lat, out, err = run_load_config(self.xdg)
        self.assertEqual(lat, 1.25)
        self.assertEqual((out, err), ([], []))


class Preview(unittest.TestCase):
    def test_preview_runs(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.png")
            env = dict(os.environ, XDG_CONFIG_HOME=d)
            subprocess.run([sys.executable, os.path.join(ROOT, "livepaper.py"),
                            "--preview", out, "--size", "1280x800", "--weather", "clear"],
                           check=True, env=env, timeout=120)
            with open(out, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
