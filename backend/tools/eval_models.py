"""Compare ONNX pothole detectors on a prepared YOLO dataset split (CPU only).

Reports, per model:
- image level: does the image contain a pothole? precision / recall / F1 at each confidence
- box level: recall and precision at IoU 0.5, AP50 (all-point interpolation)
- speed: median and p90 milliseconds per image on this CPU

Usage (from backend/):
    python tools/eval_models.py models/a.onnx models/b.onnx --split test
    python tools/eval_models.py models/a.onnx --data ../data/datasets/my_bengaluru --split test
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.pipeline.detect import Detector  # noqa: E402

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "datasets" / "rdd_india_pothole"
THRESHOLDS = [0.15, 0.25, 0.35, 0.45, 0.55]


def load_truth(label: Path, w: int, h: int) -> np.ndarray:
    rows = []
    for ln in label.read_text().splitlines() if label.exists() else []:
        _, cx, cy, bw, bh = map(float, ln.split())
        rows.append([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
    return np.array(rows).reshape(-1, 4)


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def match(preds: list, truth: np.ndarray, thr: float = 0.5) -> list[tuple[float, bool]]:
    """Greedy match by score; returns (score, is_true_positive) per prediction."""
    out, used = [], set()
    if not preds:
        return out
    p = np.array([[b.x1, b.y1, b.x2, b.y2] for b in preds])
    ious = iou(p, truth) if len(truth) else np.zeros((len(preds), 0))
    for i, b in enumerate(preds):
        j = int(np.argmax(ious[i])) if ious.shape[1] else -1
        hit = j >= 0 and ious[i, j] >= thr and j not in used
        if hit:
            used.add(j)
        out.append((b.score, hit))
    return out


def ap50(scored: list[tuple[float, bool]], n_truth: int) -> float:
    if not n_truth or not scored:
        return 0.0
    scored = sorted(scored, key=lambda x: -x[0])
    tp = np.cumsum([s[1] for s in scored])
    fp = np.cumsum([not s[1] for s in scored])
    recall = tp / n_truth
    precision = tp / np.maximum(tp + fp, 1)
    mrec = np.concatenate([[0], recall, [1]])
    mpre = np.concatenate([[1], precision, [0]])
    mpre = np.maximum.accumulate(mpre[::-1])[::-1]
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def evaluate(model_path: Path, data: Path, split: str, limit: int | None) -> None:
    det = Detector(model_path, conf=min(THRESHOLDS))
    images = sorted((data / "images" / split).glob("*.jpg"))[:limit]
    scored, n_truth, times = [], 0, []
    per_image = []  # (best_score, has_pothole)
    for img_path in images:
        img = cv2.imread(str(img_path))
        h, w = img.shape[:2]
        truth = load_truth(data / "labels" / split / (img_path.stem + ".txt"), w, h)
        result = det.detect(img)
        times.append(result.ms)
        n_truth += len(truth)
        scored += match(result.boxes, truth)
        per_image.append((result.best_score, len(truth) > 0))

    times = times[3:] or times  # drop warm-up
    pos = sum(1 for _, t in per_image if t)
    print(f"\n=== {model_path.name}  ({split}: {len(images)} images, {pos} with potholes, {n_truth} boxes)")
    print(f"pothole classes used: {[det.names[i] for i in det.class_ids]}   input {det.size}px")
    print(f"speed: median {statistics.median(times):.0f} ms, p90 {np.percentile(times, 90):.0f} ms per image (CPU)")
    print(f"box AP50: {ap50(scored, n_truth):.3f}")
    print(f"{'conf':>5} | {'img P':>6} {'img R':>6} {'img F1':>6} | {'box P':>6} {'box R':>6} | false-alarm images")
    for t in THRESHOLDS:
        tp = sum(1 for s, y in per_image if s >= t and y)
        fp = sum(1 for s, y in per_image if s >= t and not y)
        fn = sum(1 for s, y in per_image if s < t and y)
        p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        btp = sum(1 for s, hit in scored if s >= t and hit)
        bfp = sum(1 for s, hit in scored if s >= t and not hit)
        print(f"{t:5.2f} | {p:6.3f} {r:6.3f} {f1:6.3f} | {btp / max(btp + bfp, 1):6.3f} {btp / max(n_truth, 1):6.3f} | "
              f"{fp} of {len(per_image) - pos}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+", type=Path)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    for m in args.models:
        evaluate(m, args.data, args.split, args.limit)


if __name__ == "__main__":
    main()
