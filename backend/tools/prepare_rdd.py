"""Turn one RDD2022 country into a pothole-only YOLO dataset, with categorised negatives.

Input:  data/raw/rdd2022_<country>/<Country>/train/{images,annotations/xmls}
Output: data/datasets/rdd_<country>_pothole/{images,labels}/{train,val,test}, manifest.csv

Image categories (used to pick hard negatives on purpose):
  pothole       has >= 1 D40 box (only D40 becomes a box; class 0)
  marking       no pothole; has D43 (crosswalk blur) or D44 (white-line blur) - lane paint
  manhole       no pothole; has D50 (manhole / utility cover)
  other_damage  no pothole; only cracks (D00, D10, D20, ...)
  clean         no annotated damage
Splits are by blocks of 50 consecutive image ids (frames from one drive stay together).
The split hash for India matches the earlier prepare_rdd_india.py, so India splits are unchanged.
Images are hard-linked (never cropped or resized).

Source: RDD2022 (figshare 21431547), CC BY 4.0. Cite Arya et al., Geoscience Data Journal, 2024.

Usage (from backend/):
    python tools/prepare_rdd.py --country Japan
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
POTHOLE = "D40"
MARKING = {"D43", "D44"}
MANHOLE = {"D50"}
BLOCK = 50


def split_for(country: str, image_id: int) -> str:
    block = image_id // BLOCK
    h = int(hashlib.sha1(f"rdd-{country.lower()}-{block}".encode()).hexdigest(), 16) % 100
    return "train" if h < 80 else "val" if h < 90 else "test"


def parse(xml_path: Path):
    root = ET.parse(xml_path).getroot()
    w = float(root.findtext("size/width") or 0)
    h = float(root.findtext("size/height") or 0)
    objects = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        bb = obj.find("bndbox")
        if bb is None:
            continue
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


def category(names: set[str], has_pothole: bool) -> str:
    if has_pothole:
        return "pothole"
    if names & MARKING:
        return "marking"
    if names & MANHOLE:
        return "manhole"
    return "other_damage" if names else "clean"


def place(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="India, Japan, Czech, United_States, ...")
    args = ap.parse_args()
    key = args.country.lower()
    src = ROOT / "data" / "raw" / f"rdd2022_{key}" / args.country / "train"
    out = ROOT / "data" / "datasets" / f"rdd_{key}_pothole"
    xml_dir, img_dir = src / "annotations" / "xmls", src / "images"
    if out.exists():
        shutil.rmtree(out)
    for s in ("train", "val", "test"):
        (out / "images" / s).mkdir(parents=True)
        (out / "labels" / s).mkdir(parents=True)

    class_counts, summary, rows = Counter(), Counter(), []
    for xml_path in sorted(xml_dir.glob("*.xml")):
        img = img_dir / (xml_path.stem + ".jpg")
        if not img.exists():
            continue
        m = re.search(r"(\d+)$", xml_path.stem)
        image_id = int(m.group(1)) if m else 0
        w, h, objects = parse(xml_path)
        if not w or not h:
            continue
        class_counts.update(n for n, _ in objects)
        lines = [ln for n, box in objects if n == POTHOLE if (ln := to_yolo(box, w, h))]
        cat = category({n for n, _ in objects}, bool(lines))
        split = split_for(args.country, image_id)
        place(img, out / "images" / split / img.name)
        (out / "labels" / split / (img.stem + ".txt")).write_text("\n".join(lines))
        rows.append({"image": img.name, "split": split, "category": cat, "pothole_boxes": len(lines),
                     "width": int(w), "height": int(h)})
        summary[(split, cat)] += 1

    with (out / "manifest.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    cats = ["pothole", "marking", "manhole", "other_damage", "clean"]
    print(f"{args.country}: classes {dict(sorted(class_counts.items()))}")
    print(f"{'split':6} " + " ".join(f"{c:>13}" for c in cats))
    for s in ("train", "val", "test"):
        print(f"{s:6} " + " ".join(f"{summary[(s, c)]:13}" for c in cats))


if __name__ == "__main__":
    main()
