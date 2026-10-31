"""scene: pemandangan di bawah cakrawala, satu modul per scene; daftar SCENES dan load_config yang memvalidasi scene."""
from qlp import config as _config
from qlp.scenes.valley import draw_valley_frame


# scene: None = langit dan laut digambar terpisah (jalur lama), selain itu fungsi
# yang menggambar satu bingkai layar penuh
SCENES = {
    "sea": None,
    "valley": draw_valley_frame,
}


def load_config():
    """config.load_config dengan validasi scene = terhadap SCENES."""
    return _config.load_config(SCENES)
