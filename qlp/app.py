"""GTK4 + layer-shell: jendela wallpaper per monitor, jadwal gambar ulang, demo cuaca."""
import sys
import time
from datetime import datetime

from qlp.render import draw_sky_overlay, full_state
from qlp.scenes import SCENES, load_config
from qlp.scenes.sea import draw_sea
from qlp.scenes.valley import VALLEY_SLOW_FPS, valley_birds_on
from qlp.sky import _cloud_veil, draw_sky_base
from qlp.weather import WEATHER_FIXED, Weather, WeatherBlend, demo_transition


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
