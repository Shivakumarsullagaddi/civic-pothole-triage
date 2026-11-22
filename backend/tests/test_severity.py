from app.pipeline.detect import Box, Detection
from app.pipeline.severity import score_severity


def det(*boxes, w=1000, h=1000):
    return Detection([Box(*b) for b in boxes], w, h, 1.0)


def test_no_boxes_has_no_severity():
    assert score_severity(det()).level is None


def test_area_sets_base_level():
    assert score_severity(det((0, 0, 100, 100, 0.9))).level == "low"        # 1%
    assert score_severity(det((0, 0, 200, 200, 0.9))).level == "medium"     # 4%
    assert score_severity(det((0, 0, 300, 300, 0.9))).level == "high"       # 9%
    assert score_severity(det((0, 0, 500, 500, 0.9))).level == "critical"   # 25%


def test_many_potholes_raise_one_level():
    s = score_severity(det((0, 0, 100, 100, 0.9), (200, 200, 250, 250, 0.9), (400, 400, 450, 450, 0.9)))
    assert s.level == "medium"
    assert any("3 potholes" in r for r in s.reasons)


def test_low_confidence_caps_at_medium():
    s = score_severity(det((0, 0, 500, 500, 0.3)))
    assert s.level == "medium"
    assert any("low model confidence" in r for r in s.reasons)
