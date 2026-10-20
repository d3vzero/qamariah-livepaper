#!/usr/bin/env python3
"""Benchmark: waktu render per frame untuk tiap kasus cuaca."""

import argparse
import datetime
import inspect
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- Setup environment sebelum import livepaper ---
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()   # config default
os.environ["TZ"] = "Asia/Jakarta"
time.tzset()

import cairo
import livepaper


def parse_size(s):
    w, h = s.split("x", 1)
    return int(w), int(h)


def bench(cases, size, frames):
    w, h = size
    cfg = livepaper.load_config()
    cfg["lightning"] = False
    h_sky = int(h * cfg["horizon"])

    # Cek apakah draw_sky_base menerima wx
    sig = inspect.signature(livepaper.draw_sky_base)
    wx_in_base = "wx" in sig.parameters

    results = []

    for name, waktu, cuaca in cases:
        now = datetime.datetime.strptime(waktu, "%Y-%m-%d %H:%M").astimezone()
        a = livepaper.full_state(now, cfg)
        wx = dict(livepaper.WEATHER_FIXED[cuaca], source=cuaca)
        t0 = now.timestamp()

        # --- base ---
        base_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h_sky)
        if wx_in_base:
            livepaper.draw_sky_base(cairo.Context(base_surf), w, h_sky, a, t0, cfg, wx)
        else:
            livepaper.draw_sky_base(cairo.Context(base_surf), w, h_sky, a, t0, cfg)
        t_start = time.perf_counter()
        ctx_b = cairo.Context(base_surf)
        if wx_in_base:
            livepaper.draw_sky_base(ctx_b, w, h_sky, a, t0, cfg, wx)
        else:
            livepaper.draw_sky_base(ctx_b, w, h_sky, a, t0, cfg)
        base_ms = (time.perf_counter() - t_start) * 1000

        # --- sea ---
        sea_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h - h_sky)
        # warmup
        livepaper.draw_sea(cairo.Context(sea_surf), w, h - h_sky, a, t0, cfg, h_sky, wx)
        # measure
        sea_total = 0.0
        for k in range(frames):
            t_start = time.perf_counter()
            livepaper.draw_sea(
                cairo.Context(sea_surf), w, h - h_sky, a,
                t0 + k / cfg["fps"], cfg, h_sky, wx
            )
            sea_total += time.perf_counter() - t_start
        sea_ms = (sea_total / frames) * 1000

        # --- sky ---
        sky_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h_sky)
        # warmup
        ctx_s = cairo.Context(sky_surf)
        ctx_s.set_source_surface(base_surf, 0, 0)
        ctx_s.paint()
        livepaper.draw_sky_overlay(ctx_s, w, h_sky, a, wx, t0, cfg, h)
        # measure
        sky_total = 0.0
        for k in range(frames):
            t_start = time.perf_counter()
            ctx_s = cairo.Context(sky_surf)           # seperti draw_sky_cb di run()
            ctx_s.set_source_surface(base_surf, 0, 0)
            ctx_s.paint()
            livepaper.draw_sky_overlay(
                ctx_s, w, h_sky, a, wx, t0 + k / cfg["fps"], cfg, h
            )
            sky_total += time.perf_counter() - t_start
        sky_ms = (sky_total / frames) * 1000

        # --- frame rate langit per detik (logika tick) ---
        if wx["rain"] > 0 or wx["thunder"]:
            sky_per_s = cfg["fps"]
        elif wx["cover"] > 0 or wx["fog"]:
            sky_per_s = cfg["sky_fps"]
        else:
            sky_per_s = 0

        # --- CPU render per detik (ms) ---
        render_ms = sea_ms * cfg["fps"] + sky_ms * sky_per_s + base_ms / 20
        pct_core = render_ms / 10.0

        results.append((name, base_ms, sea_ms, sky_ms, sky_per_s, render_ms, pct_core))

    return results


def print_table(results, size, frames, repeat):
    print(f"ukuran {size[0]}x{size[1]}, {frames} frame, terbaik dari {repeat}")
    print(
        f"{'kasus':<14}{'base ms':>9}  {'laut ms/frame':>13}  "
        f"{'langit ms/frame':>15}  {'langit fps':>10}  "
        f"{'render ms/detik':>16}  {'% core':>7}"
    )
    for name, base_ms, sea_ms, sky_ms, sky_fps, render_ms, pct in results:
        print(
            f"{name:<14}{base_ms:>9.2f}  {sea_ms:>13.2f}  "
            f"{sky_ms:>15.2f}  {sky_fps:>10d}  "
            f"{render_ms:>16.1f}  {pct:>6.1f}"
        )


def main():
    cases = [
        ("siang cerah",  "2026-10-20 12:00", "clear"),
        ("malam cerah",  "2026-10-20 22:00", "clear"),
        ("berawan",      "2026-10-20 12:00", "cloudy"),
        ("hujan",        "2026-10-20 18:05", "rain"),
        ("badai",        "2026-10-20 22:00", "storm"),
    ]

    parser = argparse.ArgumentParser(description="Benchmark render livepaper")
    parser.add_argument("--size", default="2560x1600", type=parse_size,
                        help="LebarxTinggi (default: 2560x1600)")
    parser.add_argument("--frames", type=int, default=120,
                        help="Jumlah frame per pengukuran (default: 120)")
    parser.add_argument("--repeat", type=int, default=3,
                        help="Ulangi pengukuran, ambil tercepat (default: 3)")
    args = parser.parse_args()

    best = None
    best_total = float("inf")

    for r in range(args.repeat):
        res = bench(cases, args.size, args.frames)
        total = sum(r_[5] for r_ in res)
        if total < best_total:
            best_total = total
            best = res

    print_table(best, args.size, args.frames, args.repeat)


if __name__ == "__main__":
    main()
