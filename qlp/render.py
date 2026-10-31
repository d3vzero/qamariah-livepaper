"""komposisi frame: langit + awan/hujan/petir, bingkai layar penuh per scene, status astronomi."""
from qlp.astro import astro, planets
from qlp.clouds import draw_clouds
from qlp.precip import draw_lightning, draw_rain
from qlp.scenes import SCENES
from qlp.scenes.sea import draw_sea
from qlp.sky import draw_sky_base


def draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total):
    draw_clouds(ctx, w, h, a, wx, t, cfg)
    draw_rain(ctx, w, 0, h, h_total, wx, t)
    draw_lightning(ctx, wx, t, cfg)


def draw_sky(ctx, w, h, a, t, cfg, wx=None, h_total=None):
    draw_sky_base(ctx, w, h, a, t, cfg, wx)
    if wx:
        draw_sky_overlay(ctx, w, h, a, wx, t, cfg, h_total or h)


def draw_frame(ctx, w, h, a, wx, t, cfg, gen=0):
    """satu bingkai layar penuh untuk scene cfg['scene'] (dipakai preview dan test)."""
    h_sky = int(h * cfg["horizon"])
    if SCENES[cfg["scene"]] is not None:
        SCENES[cfg["scene"]](ctx, w, h, a, wx, t, cfg, gen)
    else:
        draw_sky(ctx, w, h_sky, a, t, cfg, wx, h)
        ctx.save()
        ctx.translate(0, h_sky)
        ctx.rectangle(0, 0, w, h - h_sky)
        ctx.clip()
        draw_sea(ctx, w, h - h_sky, a, t, cfg, h_sky, wx)
        ctx.restore()


# ── preview (tanpa GTK) ─────────────────────────────────────────────────────
def full_state(now, cfg):
    a = astro(now, cfg["lat"], cfg["lon"])
    a["planets"] = planets(now, cfg["lat"], cfg["lon"], cfg["planets"])
    return a
