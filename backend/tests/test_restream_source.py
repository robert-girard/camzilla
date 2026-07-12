import pytest

from app.pipeline import OpenCvRestreamSource


@pytest.mark.asyncio
async def test_restream_source_reports_unavailable_without_exposing_url() -> None:
    source = OpenCvRestreamSource("rtsp://go2rtc:8554/front-door", 5)
    with pytest.raises(RuntimeError, match="restream"):
        await anext(source.frames())
