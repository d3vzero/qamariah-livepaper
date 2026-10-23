"""Test qamariah-livepaper-menu (bash): pengubah config, validasi lat,lon, dan
alur menu lengkap dengan fuzzel/pgrep/setsid/notify-send palsu.

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


# pengaman: kalau source tidak sengaja menjalankan main, perintah yang berefek
# (fuzzel, restart wallpaper, notifikasi) dan config sungguhan tidak tersentuh
SAFE = tempfile.mkdtemp(prefix="qlp-menu-test-")
for _name in ("fuzzel", "pgrep", "setsid", "notify-send"):
    with open(os.path.join(SAFE, _name), "w") as _f:
        _f.write("#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(SAFE, _name), 0o755)


def bash(script, *args):
    """jalankan potongan bash setelah men-source script menu (tanpa main)."""
    env = dict(os.environ, PATH=SAFE + os.pathsep + os.environ["PATH"], XDG_CONFIG_HOME=SAFE)
    # $0 sengaja bukan path script: guard `BASH_SOURCE[0] == $0` tidak boleh menjalankan main
    return subprocess.run(["bash", "-c", 'm=$1; shift; source "$m"; ' + script, "bash", MENU, *args],
                          capture_output=True, text=True, timeout=10, env=env,
                          stdin=subprocess.DEVNULL)


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
        self.set("waves", "14")
        got = self.read().splitlines()
        # baris lama tetap ada dan urutannya sama
        old = SAMPLE.splitlines()
        self.assertEqual([l for l in got if l in old], old)
        self.assertEqual(len(got), len(old) + 2)
        # baris baru ada di bagian [livepaper], bukan [lain]
        lain = got.index("[lain]")
        self.assertIn("scene = valley", got[:lain])
        self.assertIn("waves = 14", got[:lain])
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


STUBS = {
    # fuzzel: jawaban ke-n dari file answers ("ESC" = batal); stdin dicatat ke log
    "fuzzel": r'''#!/bin/bash
n=$(( $(cat "$FAKE/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE/n"
echo "== $*" >> "$FAKE/fuzzel.log"
[[ "$*" == *--prompt-only* ]] || cat >> "$FAKE/fuzzel.log"
ans=$(sed -n "${n}p" "$FAKE/answers")
[[ "$ans" == ESC || -z "$ans" ]] && exit 1
printf '%s\n' "$ans"
''',
    # pgrep: PID "wallpaper" palsu (proses sleep milik test) selama masih hidup
    "pgrep": r'''#!/bin/bash
echo "$*" >> "$FAKE/pgrep.log"
for p in $(cat "$FAKE/pids" 2>/dev/null); do kill -0 "$p" 2>/dev/null && echo "$p"; done
exit 0
''',
    "setsid": '#!/bin/bash\necho "$*" >> "$FAKE/setsid.log"\n',
    "notify-send": '#!/bin/bash\necho "$*" >> "$FAKE/notify.log"\n',
}


class Menu(unittest.TestCase):
    """main() end-to-end dengan fuzzel, pgrep, setsid, notify-send palsu."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = os.path.join(self.tmp.name, "fake")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.xdg = os.path.join(self.tmp.name, "xdg")
        os.makedirs(self.fake); os.makedirs(self.bin)
        os.makedirs(os.path.join(self.xdg, "qamariah-livepaper"))
        for name, body in STUBS.items():
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.config = os.path.join(self.xdg, "qamariah-livepaper", "config.ini")
        with open(self.config, "w") as f:
            f.write(SAMPLE)
        # "wallpaper" yang sedang berjalan: proses milik test sendiri
        self.wall = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)"])
        with open(os.path.join(self.fake, "pids"), "w") as f:
            f.write("%d\n" % self.wall.pid)

    def tearDown(self):
        if self.wall.poll() is None:
            self.wall.kill()
        self.wall.wait()
        self.tmp.cleanup()

    def run_menu(self, *answers):
        n = os.path.join(self.fake, "n")             # hitungan jawaban fuzzel mulai dari awal
        if os.path.exists(n):
            os.remove(n)
        with open(os.path.join(self.fake, "answers"), "w") as f:
            f.write("\n".join(answers) + "\n")
        env = dict(os.environ, FAKE=self.fake, XDG_CONFIG_HOME=self.xdg,
                   PATH=self.bin + os.pathsep + os.environ["PATH"],
                   QLP_LIVEPAPER=os.path.join(ROOT, "livepaper.py"))
        return subprocess.run(["bash", MENU], env=env, capture_output=True, text=True,
                              timeout=20, stdin=subprocess.DEVNULL)

    def log(self, name):
        p = os.path.join(self.fake, name)
        if not os.path.exists(p):
            return ""
        with open(p) as f:
            return f.read()

    def read_config(self):
        with open(self.config) as f:
            return f.read()

    def test_full_flow(self):
        r = self.run_menu("1", "1", "2")            # valley, Bandung, 15 FPS
        self.assertEqual(r.returncode, 0, r.stderr)
        want = (SAMPLE.replace("lat = -6.2\n", "lat = -6.914\n")
                      .replace("lon   =   106.8\n", "lon = 107.609\n")
                      .replace("fps = 12\n", "fps = 15\n"))
        got = self.read_config().splitlines()
        self.assertEqual([l for l in got if l != "scene = valley"], want.splitlines())
        lain = got.index("[lain]")
        self.assertIn("scene = valley", got[:lain])
        # menu menandai nilai aktif dan menampilkan ukuran sebenarnya
        log = self.log("fuzzel.log")
        for s in ["● sea", "● Jakarta", "   Bandung", "Isi manual…", "● 12 FPS", "   24 FPS"]:
            self.assertIn(s, log)
        self.assertEqual(log.count("== "), 3)       # tiga langkah
        self.assertNotIn("render_scale", self.read_config())
        # wallpaper lama dihentikan lewat PID, lalu dijalankan ulang
        self.wall.wait(timeout=5)
        self.assertIn("qamariah-livepaper/livepaper.py", self.log("pgrep.log"))
        self.assertEqual(self.log("setsid.log").split(), ["-f", "qamariah-livepaper"])
        self.assertIn("valley · Bandung · 15 FPS", self.log("notify.log"))

    def test_escape_each_step_changes_nothing(self):
        for step in range(3):
            with self.subTest(step=step + 1):
                for name in ("fuzzel.log", "setsid.log", "notify.log"):
                    p = os.path.join(self.fake, name)
                    if os.path.exists(p):
                        os.remove(p)
                r = self.run_menu(*(["0"] * step + ["ESC"]))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.read_config(), SAMPLE)
                self.assertIsNone(self.wall.poll(), "wallpaper tidak boleh dihentikan")
                self.assertEqual(self.log("setsid.log"), "")
                self.assertEqual(self.log("fuzzel.log").count("== "), step + 1)

    def test_manual_location(self):
        r = self.run_menu("0", "12", "abc", "91,0", " -7.5 , 110.1 ", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.read_config()
        self.assertIn("lat = -7.5\n", cfg)
        self.assertIn("lon = 110.1\n", cfg)
        notes = self.log("notify.log")
        self.assertEqual(notes.count("Lokasi tidak valid"), 2)
        self.assertIn("sea · -7.5, 110.1 · 12 FPS", notes)

    def test_restart_only_kills_python(self):
        """pgrep -f juga cocok dengan proses lain (mis. editor yang membuka livepaper.py)."""
        other = subprocess.Popen(["sleep", "30"])
        try:
            with open(os.path.join(self.fake, "pids"), "a") as f:
                f.write("%d\n" % other.pid)
            r = self.run_menu("0", "0", "1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.wall.wait(timeout=5)
            self.assertIsNone(other.poll(), "proses non-python tidak boleh dihentikan")
        finally:
            other.kill()
            other.wait()

    def test_marks_numeric_values(self):
        with open(self.config, "w") as f:
            f.write("[livepaper]\nlat = -6.20\nlon = 106.80\nfps = 15.0\n")
        self.run_menu("0", "0", "ESC")
        log = self.log("fuzzel.log")
        self.assertIn("● Jakarta", log)
        self.assertIn("● 15 FPS", log)
        self.assertIn("   12 FPS", log)

    def test_manual_location_escape(self):
        r = self.run_menu("0", "12", "ESC")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_config(), SAMPLE)
        self.assertEqual(self.log("setsid.log"), "")

    def test_creates_locations_and_skips_bad_lines(self):
        locs = os.path.join(self.xdg, "qamariah-livepaper", "locations.txt")
        self.run_menu("ESC")
        self.assertFalse(os.path.exists(locs), "langkah 1 dibatalkan: belum perlu dibuat")
        self.run_menu("0", "ESC")
        with open(locs) as f:
            text = f.read()
        self.assertIn("Jakarta;-6.2;106.8", text)
        self.assertGreaterEqual(len([l for l in text.splitlines() if l and not l.startswith("#")]), 8)
        with open(locs, "w") as f:
            f.write("# komentar\nKota A;1;2\nrusak;abc;1\n\nKota B;-3.5;100\n")
        r = self.run_menu("0", "1", "0")            # Kota B
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lat = -3.5\n", self.read_config())
        self.assertNotIn("rusak", self.log("fuzzel.log"))


if __name__ == "__main__":
    unittest.main()
