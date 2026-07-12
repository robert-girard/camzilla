import pytest

from app.geometry import LetterboxTransform


def test_reverse_letterbox_mapping_preserves_source_coordinates() -> None:
    transform = LetterboxTransform(1280, 720, 640, 640)
    # 640x360 image is vertically padded by 140 pixels in a 640x640 model input.
    box = transform.model_to_normalized(160, 230, 480, 410)
    assert box.x == pytest.approx(0.25)
    assert box.y == pytest.approx(0.25)
    assert box.width == pytest.approx(0.5)
    assert box.height == pytest.approx(0.5)


def test_reverse_letterbox_mapping_clamps_to_source() -> None:
    box = LetterboxTransform(100, 100, 200, 200).model_to_normalized(-5, -5, 205, 205)
    assert box.x == 0
    assert box.y == 0
    assert box.width == 1
    assert box.height == 1
