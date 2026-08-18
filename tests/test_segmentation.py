import numpy as np

from vision.segmentation import ForegroundSegmenter, SegmentationConfig


def test_segmenter_handles_empty_input():
    segmenter = ForegroundSegmenter()
    assert segmenter.segment(None) is None
    assert segmenter.remove_background(None) is None


def test_segmenter_returns_mask_and_transparent_output():
    frame = np.zeros((64, 80, 3), dtype=np.uint8)
    frame[16:48, 24:56] = (255, 255, 255)
    segmenter = ForegroundSegmenter(SegmentationConfig(iterations=1))

    mask = segmenter.segment(frame, bbox=(18, 10, 44, 44))
    output = segmenter.remove_background(frame, bbox=(18, 10, 44, 44))

    assert mask.shape == frame.shape[:2]
    assert output.shape == (64, 80, 4)
