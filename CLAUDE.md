# qamariah-livepaper

Live wallpaper OLED (GTK4 + layer-shell) dengan langit sebenarnya untuk lokasi dan waktu.
`livepaper.py` hanya pintu masuk (docstring = cara pakai) yang memanggil `qlp.cli.main()`;
launcher `qamariah-livepaper` dan menu `qamariah-livepaper-menu` menjalankannya dari
`/usr/local/share/qamariah-livepaper/` (dipasang `install.sh`, termasuk folder `qlp/`).

## Peta modul (`qlp/`)

Import hanya boleh ke lapisan di atasnya dalam daftar ini (satu arah, tanpa import melingkar):

| lapisan | modul | isi |
|---|---|---|
| 0 | `config.py` | `DEFAULTS`, `load_config(scenes)`, migrasi config lama |
| 1 | `astro.py` | matahari/bulan/planet, `load_stars` (stars.dat di folder induk), `project`, `radii`, `drift` |
| 2 | `weather.py` | `WEATHER_FIXED`, sim, live (Open-Meteo), `WeatherBlend` (transisi), `wind_px`, `demo_transition` |
| 3 | `sky.py` | bintang, planet, matahari, bulan, selubung mendung, `scene_lum` |
| 3 | `clouds.py` | awan garis (sea) dan awan tinta (valley), cache sprite |
| 3 | `precip.py` | hujan, petir |
| 4 | `scenes/sea.py`, `scenes/valley.py` | satu modul per scene (kabut danau ada di valley) |
| 5 | `scenes/__init__.py` | `SCENES` (dipindai otomatis), `load_config()` dengan validasi `scene =` |
| 6 | `render.py` | `draw_frame`, `draw_sky`, `draw_sky_overlay`, `full_state` |
| 7 | `app.py` | `run()`: jendela GTK per monitor, jadwal gambar ulang, demo cuaca |
| 8 | `cli.py` | `--preview`, `--list-scenes`, `--demo-weather`, `main()` |

Pakai `qlp.scenes.load_config()` (memvalidasi scene), bukan `qlp.config.load_config` langsung.

## Cara menambah scene

1. Buat `qlp/scenes/<nama>.py`. Import hanya dari lapisan 0–3 (lihat tabel).
2. Di akhir modul, deklarasikan:
   ```python
   NAME = "<nama>"     # nama di config (scene = ...) dan di menu Super+W
   draw = draw_<nama>_frame
   ```
   `draw(ctx, W, H, a, wx, t, cfg, gen=0)` menggambar satu bingkai layar penuh. `a` = `full_state`,
   `wx` = cuaca (boleh hasil transisi, bisa berisi `_mo`), `gen` naik tiap data langit berganti (20 dtk).
   `draw = None` hanya untuk sea (langit dan laut digambar terpisah di `app.py`).
3. Selesai: scene langsung muncul di `--list-scenes`, menu, dan validasi config. Modul berawalan `_`
   atau tanpa `NAME`/`draw` dilewati, jadi modul pembantu boleh diletakkan di folder yang sama.
4. Tambahkan kasus `--scene <nama>` di `tests/test_render.py` dan buat acuannya dengan
   `UPDATE_REF=1 python3 -m unittest tests.test_render`.

Catatan: `app.py` memakai laju frame lambat (`VALLEY_SLOW_FPS`) dan burung dari valley untuk
semua scene full-frame; scene baru dengan kebutuhan lain perlu menyesuaikan `tick_full` di sana.

## Test

- Semua: `python3 -m unittest discover tests` (render 13 gambar acuan di `tests/ref`, transisi,
  menu, pemasangan ke folder sementara, scene tiruan).
- Benchmark: `python3 tests/bench_render.py --scene sea|valley`.
