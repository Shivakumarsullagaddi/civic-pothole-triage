"""Step 7 of the report pipeline: rule-based severity from detected pothole boxes.

Severity is an estimate: box size depends on how far the camera is from the pothole, so the
report screen asks people to stand 1 to 2 m away. Rules are deliberately simple and explained.
"""

from dataclasses import dataclass

from app.pipeline.detect import Detection

LEVELS = ["low", "medium", "high", "critical"]
# Largest box as a share of the whole frame -> base level.
AREA_STEPS = [(0.15, "critical"), (0.06, "high"), (0.02, "medium"), (0.0, "low")]
MANY_POTHOLES = 3
LOW_CONFIDENCE = 0.4


@dataclass
class Severity:
    level: str | None
    reasons: list[str]


def score_severity(det: Detection) -> Severity:
    if not det.boxes:
        return Severity(None, ["no pothole detected"])
    frame_area = det.width * det.height
    largest = max(b.area() for b in det.boxes) / frame_area
    level = next(name for threshold, name in AREA_STEPS if largest >= threshold)
    reasons = [f"largest pothole covers {largest:.1%} of the frame -> {level}"]

    i = LEVELS.index(level)
    if len(det.boxes) >= MANY_POTHOLES and i < len(LEVELS) - 1:
        i += 1
        reasons.append(f"{len(det.boxes)} potholes in view -> raised to {LEVELS[i]}")
    if det.best_score < LOW_CONFIDENCE and i > 1:
        i = 1
        reasons.append(f"low model confidence ({det.best_score:.2f}) -> capped at medium")
    return Severity(LEVELS[i], reasons)
