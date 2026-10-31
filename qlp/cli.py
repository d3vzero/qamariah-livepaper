"""baris perintah: --preview, --list-scenes, --demo-weather/--demo-period, atau jalankan wallpaper."""
import sys
from datetime import datetime

from qlp.app import run
from qlp.astro import D2R
from qlp.render import draw_frame, full_state
from qlp.scenes import SCENES, load_config
from qlp.weather import WEATHER_FIXED, Weather


def preview(out, size, when, weather=None, scene=None):
    import cairo
    cfg = load_config()
    cfg["lightning"] = False                         # kilat hanya sesaat; jangan ikut di gambar diam
    if weather:
        cfg["weather"] = weather
    if scene is not None:
        if scene not in SCENES:
            sys.exit("scene tidak dikenal: %s" % scene)
        cfg["scene"] = scene
    w, h = (int(v) for v in size.lower().split("x"))
    now = (datetime.strptime(when, "%Y-%m-%d %H:%M").astimezone() if when
           else datetime.now().astimezone())
    a = full_state(now, cfg)
    wthr = Weather(cfg)
    wthr.poll(background=False)
    wx = wthr.get(now)
    t = now.timestamp()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    ctx = cairo.Context(surf)
    draw_frame(ctx, w, h, a, wx, t, cfg)
    surf.write_to_png(out)
    deg = lambda r: r / D2R
    print(f"{out}: {now:%Y-%m-%d %H:%M}  matahari alt {deg(a['sun'][0]):5.1f}° az {deg(a['sun'][1]):5.1f}°, "
          f"bulan alt {deg(a['moon'][0]):5.1f}° az {deg(a['moon'][1]):5.1f}°, "
          f"fase {a['phase']:.2f} (terang {a['illum']:.0%}), jarak {a['moon_km']/1000:.0f} rb km, "
          f"malam {a['night']:.0%}, gelombang {'→' if a['wave_dir'] > 0 else '←'} x{a['wave_amp']:.2f}")
    vis = [f"{n} {alt / D2R:.0f}° m{mag:+.1f}" for n, alt, az, mag in a["planets"] if alt > 0]
    print(f"   planet di atas cakrawala: {', '.join(vis) or '-'}")
    print(f"   cuaca ({wx.get('source')}): awan {wx['cover']:.0%}, hujan {wx['rain']:.0%}, "
          f"angin {wx['wind']:.0f} km/j dari {wx['wind_from']:.0f}°"
          f"{', badai' if wx['thunder'] else ''}{', kabut' if wx['fog'] else ''}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--list-scenes":
        for name in SCENES:
            print(name)
        sys.exit(0)
    if args and args[0] == "--preview":
        out = args[1] if len(args) > 1 else "livepaper-preview.png"
        size = args[args.index("--size") + 1] if "--size" in args else "2560x1600"
        when = args[args.index("--time") + 1] if "--time" in args else None
        wthr = args[args.index("--weather") + 1] if "--weather" in args else None
        scn = args[args.index("--scene") + 1] if "--scene" in args else None
        preview(out, size, when, wthr, scn)
    elif "--demo-weather" in args:
        demo = [w.strip().lower() for w in args[args.index("--demo-weather") + 1].split(",") if w.strip()]
        bad = [w for w in demo if w not in WEATHER_FIXED]
        if not demo or bad:
            sys.exit("--demo-weather: kondisi tidak dikenal %s (pilih dari %s)"
                     % (",".join(bad) or "(kosong)", ",".join(WEATHER_FIXED)))
        period = int(args[args.index("--demo-period") + 1]) if "--demo-period" in args else 60
        if period < 1:
            sys.exit("--demo-period harus >= 1 detik")
        run(demo, period)
    else:
        run()
