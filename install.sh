#!/bin/sh
# install.sh — pasang aro-livepaper (root). Pakai: sudo ./install.sh
set -e
cd "$(dirname "$0")"
pacman -S --needed --noconfirm gtk4 gtk4-layer-shell python-gobject python-cairo
install -Dm644 livepaper.py        /usr/local/share/aro-livepaper/livepaper.py
install -Dm644 config.example.ini  /usr/local/share/aro-livepaper/config.example.ini
install -Dm644 stars.dat           /usr/local/share/aro-livepaper/stars.dat
install -Dm755 aro-livepaper       /usr/local/bin/aro-livepaper
echo "Terpasang. Tambahkan ke ~/.config/aro/config:"
echo "  wallpaper = none"
echo "  background = 0x000000ff"
echo "  exec = aro-livepaper"
