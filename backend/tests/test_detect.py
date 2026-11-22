import numpy as np
import pytest

from app.config import get_settings
from app.pipeline.detect import Detector, decode_end2end, decode_yolo_v8, letterbox, nms


def test_letterbox_keeps_whole_frame_and_pads():
    img = np.full((480, 960, 3), 200, np.uint8)  # wide frame
    out, scale, pad_x, pad_y = letterbox(img, 640)
    assert out.shape == (640, 640, 3)
    assert scale == pytest.approx(640 / 960)
    assert pad_x == 0 and pad_y == 160
    # All image content survives: rows 160..479 are image, the rest is grey padding.
    assert (out[160:480] == 200).all() and (out[:160] == 114).all() and (out[480:] == 114).all()


def test_decode_v8_picks_pothole_class_and_converts_centre_boxes():
    out = np.zeros((4 + 5, 3), np.float32)  # 5 classes, 3 candidates
    out[:4, 0] = [100, 100, 40, 20]; out[4 + 3, 0] = 0.9   # pothole
    out[:4, 1] = [300, 300, 40, 20]; out[4 + 0, 1] = 0.95  # crack, ignored
    out[:4, 2] = [500, 500, 40, 20]; out[4 + 3, 2] = 0.1   # pothole below conf
    boxes = decode_yolo_v8(out, [3], 0.25)
    assert len(boxes) == 1
    x1, y1, x2, y2, s = boxes[0]
    assert (x1, y1, x2, y2) == (80, 90, 120, 110) and s == pytest.approx(0.9)


def test_decode_end2end_filters_class_and_score():
    out = np.array([[10, 10, 50, 50, 0.8, 3], [0, 0, 5, 5, 0.9, 1], [1, 1, 9, 9, 0.1, 3]], np.float32)
    assert len(decode_end2end(out, [3], 0.25)) == 1


def test_nms_removes_overlaps():
    boxes = [(0, 0, 100, 100, 0.9), (5, 5, 105, 105, 0.8), (300, 300, 350, 350, 0.7)]
    assert len(nms(boxes, 0.5)) == 2


def test_real_model_runs_on_cpu_if_present():
    path = get_settings().resolve(get_settings().model_path)
    if not path.exists():
        pytest.skip("model file not downloaded")
    det = Detector(path)
    result = det.detect(np.full((720, 1280, 3), 128, np.uint8))
    assert (result.width, result.height) == (1280, 720)
    assert result.ms > 0
    assert det.class_ids, "model must expose a pothole class"
