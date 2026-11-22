"""Turn the RDD2022 India subset into a pothole-only YOLO dataset.

Input:  data/raw/rdd2022_india/India/train/{images,annotations/xmls}
Output: data/datasets/rdd_india_pothole/
          images/{train,val,test}/*.jpg   (full original frames, never cropped)
          labels/{train,val,test}/*.txt   (YOLO: class cx cy w h, normalised; class 0 = pothole)
          manifest.csv                    (every image, its split and category)
          dataset.yaml                    (for training / evaluation tools)

Rules:
- Only RDD class D40 (pothole) becomes a box. Cracks (D00, D10, D20) are dropped.
- Image categories: `pothole` (has >= 1 D40 box), `other_damage` (only cracks: kept as hard
  negatives with an empty label file), `clean` (no annotated damage: negative).
- Splits are by blocks of consecutive image IDs, not random images, because consecutive
  frames come from the same drive and would leak between train and test.
- Images are hard-linked when possible (no extra disk), otherwise copied. Never cropped,
  resized or masked.

Source: RDD2022 (figshare 21431547), CC BY 4.0. Cite Arya et al., Geoscience Data Journal, 2024.

Usage (from backend/):
    python tools/prepare_rdd_india.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = ROOT / "data" / "raw" / "rdd2022_india" / "India" / "train"
DEFAULT_OUT = ROOT / "data" / "datasets" / "rdd_india_pothole"
POTHOLE = "D40"
BLOCK = 50  # consecutive IDs per split block


def split_for(image_id: int) -> str:
    block = image_id // BLOCK
    h = int(hashlib.sha1(f"rdd-india-{block}".encode()).hexdigest(), 16) % 100
    return "train" if h < 80 else "val" if h < 90 else "test"


def parse(xml_path: Path):
    root = ET.parse(xml_path).getroot()
    w = float(root.findtext("size/width"))
    h = float(root.findtext("size/height"))
    objects = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        bb = obj.find("bndbox")
        box = tuple(float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax"))
        objects.append((name, box))
    return w, h, objects


def to_yolo(box, w, h) -> str | None:
    x0, y0, x1, y1 = box
    x0, x1 = max(0.0, min(x0, x1)), min(w, max(x0, x1))
    y0, y1 = max(0.0, min(y0, y1)), min(h, max(y0, y1))
    bw, bh = x1 - x0, y1 - y0
    if bw < 2 or bh < 2:
        return None
    return f"0 {(x0 + bw / 2) / w:.6f} {(y0 + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}"


def place(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    xml_dir, img_dir = args.src / "annotations" / "xmls", args.src / "images"
    for s in ("train", "val", "test"):
        (args.out / "images" / s).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / s).mkdir(parents=True, exist_ok=True)

    class_counts: Counter = Counter()
    summary: Counter = Counter()
    rows = []
    for xml_path in sorted(xml_dir.glob("*.xml")):
        img = img_dir / (xml_path.stem + ".jpg")
        if not img.exists():
            summary["missing_image"] += 1
            continue
        m = re.search(r"(\d+)$", xml_path.stem)
        image_id = int(m.group(1)) if m else 0
        w, h, objects = parse(xml_path)
        class_counts.update(name for name, _ in objects)

        lines = [ln for name, box in objects if name == POTHOLE if (ln := to_yolo(box, w, h))]
        category = "pothole" if lines else ("other_damage" if objects else "clean")
        split = split_for(image_id)

        place(img, args.out / "images" / split / img.name)
        (args.out / "labels" / split / (img.stem + ".txt")).write_text("\n".join(lines))
        rows.append({"image": img.name, "split": split, "category": category,
                     "pothole_boxes": len(lines), "width": int(w), "height": int(h)})
        summary[(split, category)] += 1
        summary[("boxes", split)] += len(lines)

    with (args.out / "manifest.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    (args.out / "dataset.yaml").write_text(
        f"path: {args.out.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: pothole\n"
        "# Source: RDD2022 India subset (figshare 21431547), CC BY 4.0.\n"
    )

    print("RDD class counts (all boxes):", dict(sorted(class_counts.items())))
    print(f"{'split':6} {'pothole':>8} {'other':>8} {'clean':>8} {'boxes':>8}")
    for s in ("train", "val", "test"):
        print(f"{s:6} {summary[(s, 'pothole')]:8} {summary[(s, 'other_damage')]:8} "
              f"{summary[(s, 'clean')]:8} {summary[('boxes', s)]:8}")
    if summary["missing_image"]:
        print("Missing images:", summary["missing_image"])
    print("Written to", args.out)


if __name__ == "__main__":
    main()
