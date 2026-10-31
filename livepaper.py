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
from qlp.cli import main

if __name__ == "__main__":
    main()
