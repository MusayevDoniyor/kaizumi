import numpy as np

from vision.ocr_engine import CodeReader, OCREngine, OCRConfig


def test_ocr_without_native_tesseract_is_safe():
    engine = OCREngine(OCRConfig(languages="eng"))
    result = engine.extract(np.zeros((40, 80, 3), dtype=np.uint8))
    assert result == []
    assert engine.error is not None or engine.is_ready


def test_code_reader_handles_empty_frame():
    reader = CodeReader()
    assert reader.read(None) == []

