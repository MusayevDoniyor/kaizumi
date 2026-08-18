import numpy as np

from vision.image_enhancement import ImageColorizer, SuperResolution


def test_super_resolution_fallback_doubles_image():
    frame = np.zeros((10, 12, 3), dtype=np.uint8)
    result = SuperResolution(scale=2).upscale(frame)
    assert result.shape == (20, 24, 3)


def test_colorizer_converts_grayscale_to_color():
    frame = np.zeros((10, 12), dtype=np.uint8)
    result = ImageColorizer().colorize(frame)
    assert result.shape == (10, 12, 3)
