#!/usr/bin/env python3
"""qamariah-livepaper — live wallpaper OLED untuk aro (layer-shell background).

Langit hitam pekat dengan posisi benda langit SEBENARNYA untuk lokasi & waktu:
  - matahari & bulan: altitude/azimuth dihitung (bulan: rumus Meeus ringkas,
    ketelitian ~0,3°), fase & ukuran tampak bulan dari geometri aktual
  - bintang: 904 bintang Yale Bright Star Catalog (V <= 4,5) pada posisi
    sebenarnya; terang sesuai magnitudo, redup dekat cakrawala, kalah oleh
    cahaya bulan dan senja
  - planet: Merkurius, Venus, Mars, Jupiter, Saturnus (elemen orbit JPL,
    ketelitian ~1°), terang sesuai magnitudo, tidak berkelip
  - cuaca: cerah / berawan / hujan / badai — "live" dari Open-Meteo sesuai
    lokasi (tanpa API key; cadangan simulasi kalau offline) atau simulasi
    pola tropis (awan siang, hujan sore, angin siang/malam berbalik)
Proyeksi: langit "dibentangkan" timur (kiri) → barat (kanan), tinggi = altitude.
Laut di bawah: garis gelombang putih tipis, bergerak pelan:
  - arah gelombang : bulan membesar → ke kanan, mengecil → ke kiri
  - tinggi gelombang: pasang-surut dari sudut jam bulan (2x sehari) dan
                      pasang purnama/perbani dari fase
Pantulan matahari/bulan berkilau di permukaan laut.

Hemat OLED: >95% piksel hitam, seluruh gambar bergeser beberapa piksel per jam
(anti burn-in). Langit digambar ulang tiap 20 detik, laut sesuai FPS (default 12)
dan berhenti sendiri saat tertutup window.

Pakai:
  qamariah-livepaper                    jalankan (dari `exec =` di config aro)
  qamariah-livepaper --preview out.png  render satu gambar (tanpa GTK)
      [--size 2560x1600] [--time "2026-10-20 19:30"]
      [--weather clear|cloudy|rain|storm|fog|sim|live]
      [--scene sea|valley]
  qamariah-livepaper --list-scenes      daftar scene (dipakai qamariah-livepaper-menu)
  qamariah-livepaper --demo-weather storm,clear,rain,fog,cloudy [--demo-period 60]
                                        uji transisi: cuaca bergantian tiap DETIK
                                        (tanpa data live; durasi transisi =
                                        min(weather_transition, 0.4 x demo-period)
                                        supaya selesai sebelum kondisi berikutnya)
Config: ~/.config/qamariah-livepaper/config.ini (lihat config.example.ini)
"""
import configparser
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from qlp.config import DEFAULTS
from qlp.astro import (
    HERE, load_stars, D2R, MOON_SUN_RATIO, julian, lst_rad, altaz, ecl_to_eq, sun_ecl,
    moon_ecl, astro, PLANET_EL, helio, planet_mag, planets, drift, project, radii, sun_up,
    moon_visible,
)
from qlp.weather import (
    WEATHER_FIXED, _smooth, weather_sim, weather_from_api, Weather, V_CLOUDS_MAX, RAIN_EPS,
    BLEND_KEYS, sea_rough, _moved, _Motion, WeatherBlend, wind_px, demo_transition,
)
from qlp.sky import (
    draw_moon, STARS, draw_stars, draw_planets, _cloud_veil, draw_sky_base, scene_lum,
)
from qlp.clouds import (
    _CLOUD_CACHE, _cloud_cluster, _cloud_sprites, draw_clouds, _V_INK, _v_ink_sprite,
    ink_clouds,
)
from qlp.precip import _frac, _RAIN_CACHE, _rain_drops, draw_rain, draw_lightning
from qlp.scenes.sea import _SEA_XS, _sea_xs, draw_sea
from qlp.scenes.valley import (
    VALLEY_HORIZON, VALLEY_SLOW_FPS, V_MID_LEFT, V_MID_LEFT2, V_MID_RIGHT, V_PILLAR,
    V_FRONT_LEFT, V_FRONT_ISLAND, V_FRONT_RIGHT, V_SMALL_ROCK, V_TREES, _V_GEO, _v_rough,
    _v_smooth, _v_interp, _v_geometry, _v_fill_hill, valley_static, _v_willow, _v_bamboo,
    _v_reflection, valley_anim, valley_birds, _v_skyline, _V_MIST, _v_mist_sprite, lake_mist,
    valley_birds_on, _V_FRAME, draw_valley_frame,
)
from qlp.scenes import SCENES, load_config
from qlp.render import draw_sky_overlay, draw_sky, draw_frame, full_state


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


# ── GTK4 + layer-shell ──────────────────────────────────────────────────────
def run(demo=None, period=60):
    """demo: daftar kondisi WEATHER_FIXED yang bergantian tiap period detik (uji visual)."""
    import cairo
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    gi.require_foreign("cairo")
    from gi.repository import Gdk, GLib, Gtk
    from gi.repository import Gtk4LayerShell as Layer

    cfg = load_config()
    if demo:
        cfg["weather_transition"] = demo_transition(cfg["weather_transition"], period)
    weather = Weather(cfg)
    blend = WeatherBlend(cfg)                        # data baru -> transisi halus
    state = {"a": full_state(datetime.now().astimezone(), cfg), "gen": 0}

    def refresh():
        now = datetime.now().astimezone()
        state["a"] = full_state(now, cfg)
        if not demo:
            weather.poll()
            blend.set(weather.get(now), time.time())
        state["gen"] += 1                            # langit dasar perlu digambar ulang
        return True

    def demo_next():
        state["demo"] = (state.get("demo", -1) + 1) % len(demo)
        name = demo[state["demo"]]
        print("qamariah-livepaper: demo cuaca -> %s (%s)" % (name, datetime.now().strftime("%H:%M:%S")),
              file=sys.stderr, flush=True)
        blend.set(dict(WEATHER_FIXED[name], source=name), time.time())
        return True
    if demo:
        demo_next()
    refresh()

    css = Gtk.CssProvider()
    rule = "window, box, drawingarea { background: #000000; }"
    try:
        css.load_from_string(rule)                  # GTK >= 4.12
    except AttributeError:
        css.load_from_data(rule.encode())

    def on_activate(app):
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        monitors = Gdk.Display.get_default().get_monitors()
        for idx in range(monitors.get_n_items()):
            make_window(app, monitors.get_item(idx))
        GLib.timeout_add_seconds(20, refresh)
        if demo:
            GLib.timeout_add_seconds(period, demo_next)

    def make_window(app, monitor):
        win = Gtk.ApplicationWindow(application=app)
        Layer.init_for_window(win)
        Layer.set_namespace(win, "qamariah-livepaper")
        Layer.set_layer(win, Layer.Layer.BACKGROUND)
        Layer.set_monitor(win, monitor)
        for edge in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(win, edge, True)
        Layer.set_exclusive_zone(win, -1)
        Layer.set_keyboard_mode(win, Layer.KeyboardMode.NONE)

        geo = monitor.get_geometry()
        render = SCENES[cfg["scene"]]
        if render:
            area = Gtk.DrawingArea()
            area.set_hexpand(True); area.set_vexpand(True)
            def draw_full(_a, c, w, h):
                t = time.time()
                render(c, w, h, state["a"], blend.get(t), t, cfg, state["gen"])
            area.set_draw_func(draw_full)
            win.set_child(area)
            last_f = {"t": 0}

            def tick_full(_w, clock):
                now = clock.get_frame_time()
                wx = blend.get(time.time())
                fast = valley_birds_on(state["a"], wx) or wx["rain"] > 0 or wx["thunder"]
                period = 1_000_000 / (cfg["fps"] if fast else VALLEY_SLOW_FPS)
                if now - last_f["t"] >= period:
                    last_f["t"] = now
                    area.queue_draw()
                return True
            area.add_tick_callback(tick_full)
            win.present()
            return
        h_sky = int(geo.height * cfg["horizon"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sky, sea = Gtk.DrawingArea(), Gtk.DrawingArea()
        sky.set_content_height(h_sky)
        sea.set_vexpand(True); sky.set_hexpand(True); sea.set_hexpand(True)
        cache = {"surf": None, "key": None}

        def draw_sky_cb(_a, c, w, h):
            t = time.time()
            wx = blend.get(t)
            key = (w, h, state["gen"], round(_cloud_veil(wx), 2))   # veil berubah halus saat transisi
            if cache["key"] != key:                  # bintang/planet/matahari/bulan: tiap 20 dtk
                surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
                draw_sky_base(cairo.Context(surf), w, h, state["a"], t, cfg, wx)
                cache["surf"], cache["key"] = surf, key
            c.set_source_surface(cache["surf"], 0, 0)
            c.paint()
            draw_sky_overlay(c, w, h, state["a"], wx, t, cfg, geo.height)

        sky.set_draw_func(draw_sky_cb)
        def draw_sea_cb(_a, c, w, h):
            t = time.time()
            draw_sea(c, w, h, state["a"], t, cfg, sky.get_height(), blend.get(t))
        sea.set_draw_func(draw_sea_cb)
        box.append(sky); box.append(sea)
        win.set_child(box)

        last = {"sea": 0, "sky": 0, "gen": -1}

        def tick(_w, clock):        # berhenti sendiri kalau compositor tidak meminta frame
            now = clock.get_frame_time()
            if now - last["sea"] >= 1_000_000 / cfg["fps"]:
                last["sea"] = now
                sea.queue_draw()
            wx = blend.get(time.time())
            if wx["rain"] > 0 or wx["thunder"]:
                sky_us = 1_000_000 / cfg["fps"]
            elif wx["cover"] > 0 or wx["fog"] or "_mo" in wx:
                sky_us = 1_000_000 / cfg["sky_fps"]
            else:
                sky_us = None                        # cerah: cukup saat data berganti
            if (sky_us and now - last["sky"] >= sky_us) or last["gen"] != state["gen"]:
                last["sky"], last["gen"] = now, state["gen"]
                sky.queue_draw()
            return True
        sea.add_tick_callback(tick)
        win.present()

    app = Gtk.Application(application_id="id.aro.livepaper")
    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
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
