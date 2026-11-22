"""Step 6 of the report pipeline: pothole detection with a local ONNX model on CPU.

Works with Ultralytics-style YOLO detection exports:
- YOLOv8/11 head: output [1, 4 + num_classes, N] (cx, cy, w, h, class scores), needs NMS.
- End-to-end head (YOLOv10/26): output [1, N, 6] (x1, y1, x2, y2, score, class), no NMS.

The whole frame is letterboxed (scaled and padded, never cropped) to the model input size,
so the model always sees the complete field of view.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

POTHOLE_NAMES = {"pothole", "potholes", "d40"}


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def as_dict(self) -> dict:
        return {"x1": round(self.x1, 1), "y1": round(self.y1, 1), "x2": round(self.x2, 1),
                "y2": round(self.y2, 1), "score": round(self.score, 4)}


@dataclass
class Detection:
    boxes: list[Box]
    width: int
    height: int
    ms: float

    @property
    def best_score(self) -> float:
        return max((b.score for b in self.boxes), default=0.0)


def letterbox(img: np.ndarray, size: int) -> tuple[np.ndarray, float, float, float]:
    """Resize the full frame to fit size x size, pad the rest. Returns (img, scale, pad_x, pad_y)."""
    h, w = img.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = round(w * scale), round(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_x, pad_y = (size - nw) / 2, (size - nh) / 2
    top, left = int(round(pad_y - 0.1)), int(round(pad_x - 0.1))
    out = cv2.copyMakeBorder(resized, top, size - nh - top, left, size - nw - left,
                             cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return out, scale, left, top


def decode_yolo_v8(out: np.ndarray, class_ids: list[int], conf: float) -> list[tuple]:
    """[4 + nc, N] -> list of (x1, y1, x2, y2, score) in model-input pixels, before NMS."""
    preds = out.T  # [N, 4 + nc]
    scores = preds[:, 4:][:, class_ids].max(axis=1)
    keep = scores >= conf
    if not keep.any():
        return []
    cx, cy, w, h = preds[keep, 0], preds[keep, 1], preds[keep, 2], preds[keep, 3]
    return list(zip(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, scores[keep]))


def decode_end2end(out: np.ndarray, class_ids: list[int], conf: float) -> list[tuple]:
    """[N, 6] (x1, y1, x2, y2, score, cls) -> list of boxes for the wanted classes."""
    rows = out[(out[:, 4] >= conf) & np.isin(out[:, 5].astype(int), class_ids)]
    return [tuple(r[:5]) for r in rows]


def nms(boxes: list[tuple], iou: float) -> list[tuple]:
    if not boxes:
        return []
    xywh = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes]
    scores = [float(b[4]) for b in boxes]
    idx = cv2.dnn.NMSBoxes(xywh, scores, 0.0, iou)
    return [boxes[i] for i in np.array(idx).flatten()]


class Detector:
    def __init__(self, model_path: Path, conf: float = 0.25, iou: float = 0.5, threads: int = 0):
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if isinstance(inp.shape[2], int) else 640
        meta = self.session.get_modelmeta().custom_metadata_map
        self.names: dict[int, str] = ast.literal_eval(meta["names"]) if "names" in meta else {0: "pothole"}
        self.class_ids = [i for i, n in self.names.items() if n.strip().lower() in POTHOLE_NAMES]
        if not self.class_ids:
            raise ValueError(f"Model has no pothole class; classes are {self.names}")
        self.conf, self.iou = conf, iou
        self.path = model_path

    def detect(self, image_bgr: np.ndarray) -> Detection:
        t0 = time.perf_counter()
        h, w = image_bgr.shape[:2]
        lb, scale, pad_x, pad_y = letterbox(image_bgr, self.size)
        blob = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = self.session.run(None, {self.input_name: blob})[0][0]

        if out.ndim == 2 and out.shape[1] == 6 and out.shape[0] != 6:
            raw = decode_end2end(out, self.class_ids, self.conf)
        else:
            raw = nms(decode_yolo_v8(out, self.class_ids, self.conf), self.iou)

        boxes = []
        for x1, y1, x2, y2, s in raw:
            # Undo letterbox, clip to the original full frame.
            bx1 = float(np.clip((x1 - pad_x) / scale, 0, w))
            by1 = float(np.clip((y1 - pad_y) / scale, 0, h))
            bx2 = float(np.clip((x2 - pad_x) / scale, 0, w))
            by2 = float(np.clip((y2 - pad_y) / scale, 0, h))
            if bx2 - bx1 >= 2 and by2 - by1 >= 2:
                boxes.append(Box(bx1, by1, bx2, by2, float(s)))
        boxes.sort(key=lambda b: b.score, reverse=True)
        return Detection(boxes, w, h, (time.perf_counter() - t0) * 1000)


def decode_image(data: bytes) -> np.ndarray:
    """Decode bytes to a BGR image, applying EXIF orientation to the whole frame."""
    from io import BytesIO

    from PIL import Image, ImageOps

    with Image.open(BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


_detector: Detector | None = None
_detector_error: str | None = None


def get_detector() -> Detector | None:
    """Load the configured model once. Returns None (and records why) if it cannot load."""
    global _detector, _detector_error
    if _detector is None and _detector_error is None:
        from app.config import get_settings

        settings = get_settings()
        path = settings.resolve(settings.model_path)
        try:
            _detector = Detector(path, conf=settings.detector_conf)
        except Exception as exc:  # noqa: BLE001 - reported via /health
            _detector_error = f"{type(exc).__name__}: {exc}"
    return _detector


def detector_status() -> dict:
    det = get_detector()
    if det is None:
        return {"loaded": False, "error": _detector_error}
    return {"loaded": True, "file": det.path.name, "input_px": det.size,
            "pothole_classes": [det.names[i] for i in det.class_ids], "conf": det.conf}
