"""scene: pemandangan di bawah cakrawala, satu modul per scene; daftar SCENES dan load_config yang memvalidasi scene."""
import importlib
import pkgutil

from qlp import config as _config

# scene: None = langit dan laut digambar terpisah (jalur lama), selain itu fungsi
# yang menggambar satu bingkai layar penuh. Ditemukan otomatis: setiap modul di folder
# ini yang punya NAME dan draw (urutan nama file; modul berawalan _ dilewati).
SCENES = {}
for _info in pkgutil.iter_modules(__path__):
    if _info.name.startswith("_"):
        continue
    _mod = importlib.import_module("%s.%s" % (__name__, _info.name))
    if hasattr(_mod, "NAME") and hasattr(_mod, "draw"):
        SCENES[_mod.NAME] = _mod.draw


def load_config():
    """config.load_config dengan validasi scene = terhadap SCENES."""
    return _config.load_config(SCENES)
