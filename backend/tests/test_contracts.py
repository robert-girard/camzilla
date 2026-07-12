import pytest
from pydantic import ValidationError

from app.contracts import NormalizedBox


def test_normalized_box_rejects_overflow() -> None:
    with pytest.raises(ValidationError, match="within normalized"):
        NormalizedBox(x=0.8, y=0.1, width=0.3, height=0.2)


def test_normalized_box_accepts_frame_edge() -> None:
    assert NormalizedBox(x=0.8, y=0.8, width=0.2, height=0.2).width == 0.2
