#!/bin/sh
# install.sh — pasang qamariah-livepaper (root). Pakai: sudo ./install.sh
set -e
cd "$(dirname "$0")"
pacman -S --needed --noconfirm gtk4 gtk4-layer-shell python-gobject python-cairo python-numpy fuzzel libnotify
# paket qlp/: hapus salinan lama dulu supaya modul scene yang sudah dihapus tidak ikut terpindai
rm -rf /usr/local/share/qamariah-livepaper/qlp
for f in qlp/*.py qlp/scenes/*.py; do
    install -Dm644 "$f" "/usr/local/share/qamariah-livepaper/$f"
done
install -Dm644 livepaper.py        /usr/local/share/qamariah-livepaper/livepaper.py
install -Dm644 config.example.ini  /usr/local/share/qamariah-livepaper/config.example.ini
install -Dm644 stars.dat           /usr/local/share/qamariah-livepaper/stars.dat
install -Dm755 qamariah-livepaper  /usr/local/bin/qamariah-livepaper
install -Dm755 qamariah-livepaper-menu /usr/local/bin/qamariah-livepaper-menu
echo "Terpasang. Tambahkan ke ~/.config/aro/config:"
echo "  wallpaper = none"
echo "  background = 0x000000ff"
echo "  exec = qamariah-livepaper"
echo "Menu pengaturan: qamariah-livepaper-menu (mis. pasang di keybinding aro)"
