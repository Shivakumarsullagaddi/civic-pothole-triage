"""Train a small pothole detector (GPU if available, else CPU) and export it to ONNX for the app.

Runs in the separate training venv (.venv-train: PyTorch CUDA 12.6 + Ultralytics, AGPL-3.0).
The app itself only loads the exported ONNX file with onnxruntime.

Usage (from backend/):
    .venv-train/Scripts/python tools/train_detector.py --epochs 30 --imgsz 640
    .venv-train/Scripts/python tools/train_detector.py --bench          # time a short run only
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
# 640px-max copy (tools/shrink_dataset.py): same labels, much faster decoding.
DATA = ROOT / "data" / "datasets" / "pothole_mix_640" / "dataset.yaml"
RUNS = ROOT / "data" / "runs"
MODELS = Path(__file__).resolve().parents[1] / "models"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="yolo11n.pt", help="official Ultralytics base checkpoint")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--freeze", type=int, default=0, help="freeze the first N layers (10 = backbone)")
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--device", default=None, help="0 for the first GPU, or cpu (default: GPU if available)")
    ap.add_argument("--name", default="pothole_y11n")
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--cache", default="disk", choices=["disk", "ram", "none"],
                    help="disk: decode each image once to .npy (fast loading, low RAM)")
    ap.add_argument("--bench", action="store_true", help="1 epoch on 5%% of the data, no export")
    args = ap.parse_args()

    import torch

    device = args.device or ("0" if torch.cuda.is_available() else "cpu")
    print(f"Training on {'GPU ' + torch.cuda.get_device_name(0) if device != 'cpu' else 'CPU'}")
    model = YOLO(args.base)
    t0 = time.time()
    model.train(
        data=str(args.data),
        epochs=1 if args.bench else args.epochs,
        fraction=0.05 if args.bench else 1.0,
        val=not args.bench,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        cache=False if args.cache == "none" else args.cache,
        device=device,
        project=str(RUNS),
        name=f"{args.name}_bench" if args.bench else args.name,
        exist_ok=True,
        patience=args.patience,
        freeze=args.freeze or None,
        seed=0,
        plots=not args.bench,
        # Full-frame rule: no random cropping of the field of view in augmentation.
        # Mosaic and scale jitter recompose whole frames; translate/scale stay modest.
        degrees=5.0,
        fliplr=0.5,
        close_mosaic=5,
    )
    elapsed = time.time() - t0
    print(f"Training took {elapsed / 60:.1f} min")
    if args.bench:
        return

    best = RUNS / args.name / "weights" / "best.pt"
    exported = Path(YOLO(str(best)).export(format="onnx", imgsz=args.imgsz, simplify=True, opset=17))
    MODELS.mkdir(exist_ok=True)
    target = MODELS / f"{args.name}_{args.imgsz}.onnx"
    shutil.copy2(exported, target)
    print(f"Exported {target}")


if __name__ == "__main__":
    main()
