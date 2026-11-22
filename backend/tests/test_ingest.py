import pytest

from app.pipeline.ingest import InputError, build_input
from tests.conftest import jpeg_bytes

DEVICE = "device-12345"


def test_valid_input_keeps_full_frames():
    inp = build_input([jpeg_bytes()] * 3, 12.97, 77.59, 8.0, None, DEVICE)
    assert len(inp.frames) == 3
    assert (inp.frames[0].width, inp.frames[0].height) == (640, 480)
    assert inp.frames[0].format == "JPEG"


@pytest.mark.parametrize(
    "frames,lat,lng,device,message",
    [
        ([], 12.9, 77.5, DEVICE, "between 1 and 3"),
        ([jpeg_bytes()] * 4, 12.9, 77.5, DEVICE, "between 1 and 3"),
        ([b"not an image"], 12.9, 77.5, DEVICE, "not a readable image"),
        ([jpeg_bytes(100, 100)], 12.9, 77.5, DEVICE, "out of range"),
        ([jpeg_bytes()], 95.0, 77.5, DEVICE, "Latitude"),
        ([jpeg_bytes()], 12.9, 77.5, "bad id!", "device_id"),
    ],
)
def test_invalid_input_is_rejected(frames, lat, lng, device, message):
    with pytest.raises(InputError, match=message):
        build_input(frames, lat, lng, None, None, device)
