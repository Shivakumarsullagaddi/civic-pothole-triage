"""Merge all pothole sources into one pothole-only YOLO training set.

Sources (all full frames, never cropped; class 0 = pothole):
  rdd      data/datasets/rdd_india_pothole (prepared by prepare_rdd_india.py)    CC BY 4.0
  chit     kaggle chitholian/annotated-potholes-dataset (Pascal VOC)               DbCL-1.0
  raj      kaggle rajdalsaniya/pothole-detection-dataset (YOLO)                    CC0-1.0
  farzad   kaggle farzadnekouei/pothole-image-segmentation-dataset (polygons)      Apache-2.0 / CC BY 4.0
  rome     kaggle lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes  MIT
           (class 0 pothole kept; crack/manhole-only images become hard negatives)

Rules:
- Near-duplicate images (perceptual hash distance <= 6) across all sources are grouped.
  Exact copies are dropped; every group lands in one split, so a test image never has a
  twin in train.
- RDD keeps its drive-block split. `raj` (pre-augmented) is train-only. Other groups are
  split 80/10/10 by hashing the group.
- RDD negatives are picked by category per country (NEG_CAPS): all lane-marking and manhole
  images up to a cap (hard negatives), plus a sample of crack-only and clean roads.
- Extra test splits `test_closeup` (non-RDD sources) and `test_dashcam` (RDD) are copies of
  `test` partitioned by source, for separate evaluation.

Output: data/datasets/<out>/{images,labels}/{train,val,test,test_closeup,test_dashcam,test_hardneg}
        test_hardneg = RDD lane-marking / manhole images with no pothole (false-alarm check)
        manifest.csv, dataset.yaml, SOURCES.md

Usage (from backend/):  python tools/build_training_set.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import random
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "kaggle"
# RDD2022 countries: dataset folder key -> source name. India keeps "rdd" so test_dashcam
# stays the same India-only split used to evaluate earlier models.
RDD_COUNTRIES = {"india": "rdd", "japan": "rdd_jp", "czech": "rdd_cz", "united_states": "rdd_us"}
OUT = ROOT / "data" / "datasets" / "pothole_mix"
DUP_DIST = 6
# Negatives kept per RDD country and split, by category. Lane paint and manholes are the
# hard negatives (things that look like potholes); cracks and clean roads are sampled.
NEG_CAPS = {
    "marking": {"train": 1200, "val": 150, "test": 300},
    "manhole": {"train": 600, "val": 80, "test": 150},
    "other_damage": {"train": 250, "val": 30, "test": 60},
    "clean": {"train": 300, "val": 40, "test": 80},
}
HARD_NEG = {"marking", "manhole"}
# Pre-augmented (rotated, noised) copies can evade duplicate matching, so these sources
# (and any group containing them) are used for training only, never val/test.
TRAIN_ONLY = {"raj"}


@dataclass
class Item:
    source: str
    path: Path
    boxes: list[tuple[float, float, float, float]]  # normalised cx, cy, w, h
    split: str | None = None  # fixed split (RDD) or None
    phash: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.source}_{self.path.stem}{self.path.suffix.lower()}"


def clamp_box(x0, y0, x1, y1):
    x0, x1 = max(0.0, min(x0, x1)), min(1.0, max(x0, x1))
    y0, y1 = max(0.0, min(y0, y1)), min(1.0, max(y0, y1))
    if x1 - x0 < 0.003 or y1 - y0 < 0.003:
        return None
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)


def yolo_lines(label: Path, keep_class: int = 0) -> tuple[list, bool]:
    """Returns (pothole boxes, had_other_objects) from a YOLO bbox or polygon label file."""
    boxes, other = [], False
    for ln in label.read_text().splitlines() if label.exists() else []:
        parts = ln.split()
        if not parts:
            continue
        cls, vals = int(float(parts[0])), list(map(float, parts[1:]))
        if cls != keep_class:
            other = True
            continue
        if len(vals) == 4:
            cx, cy, w, h = vals
            b = clamp_box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        else:  # polygon x1 y1 x2 y2 ...
            xs, ys = vals[0::2], vals[1::2]
            b = clamp_box(min(xs), min(ys), max(xs), max(ys))
        if b:
            boxes.append(b)
    return boxes, other


def load_rdd() -> list[Item]:
    items = []
    for key, source in RDD_COUNTRIES.items():
        base = ROOT / "data" / "datasets" / f"rdd_{key}_pothole"
        if not (base / "manifest.csv").exists():
            print(f"skip {key}: not prepared (python tools/prepare_rdd.py --country ...)")
            continue
        with (base / "manifest.csv").open() as f:
            rows = list(csv.DictReader(f))
        rng = random.Random(7)
        for split in ("train", "val", "test"):
            chosen = [r for r in rows if r["split"] == split and r["category"] == "pothole"]
            for cat, caps in NEG_CAPS.items():
                negs = [r for r in rows if r["split"] == split and r["category"] == cat]
                rng.shuffle(negs)
                chosen += negs[: caps[split]]
            for r in chosen:
                img = base / "images" / split / r["image"]
                boxes, _ = yolo_lines(base / "labels" / split / (img.stem + ".txt"))
                items.append(Item(source, img, boxes, split=split, meta={"category": r["category"]}))
    return items


def load_chit() -> list[Item]:
    base = RAW / "annotated-potholes-dataset" / "annotated-images"
    items = []
    for xml in sorted(base.glob("*.xml")):
        root = ET.parse(xml).getroot()
        w, h = float(root.findtext("size/width")), float(root.findtext("size/height"))
        boxes = []
        for obj in root.findall("object"):
            if (obj.findtext("name") or "").strip().lower() != "pothole":
                continue
            bb = obj.find("bndbox")
            x0, y0, x1, y1 = (float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax"))
            if b := clamp_box(x0 / w, y0 / h, x1 / w, y1 / h):
                boxes.append(b)
        img = base / (xml.stem + ".jpg")
        if img.exists():
            items.append(Item("chit", img, boxes))
    return items


def load_yolo_tree(source: str, base: Path, label_dir_name: str = "labels") -> list[Item]:
    items = []
    for img in sorted(base.rglob("*.jpg")):
        label = img.parent.parent / label_dir_name / (img.stem + ".txt")
        boxes, other = yolo_lines(label)
        if not boxes and not other and not label.exists():
            continue  # unlabelled image: skip rather than guess it is clean
        items.append(Item(source, img, boxes, meta={"other_objects": other}))
    return items


def load_all() -> list[Item]:
    items = load_rdd() + load_chit()
    items += load_yolo_tree("raj", RAW / "pothole-detection-dataset")
    items += load_yolo_tree("farzad", RAW / "pothole-image-segmentation-dataset")
    items += load_yolo_tree("rome", RAW / "road-damage-dataset-potholes-cracks-and-manholes" / "data",
                            label_dir_name="labels-YOLO")
    return items


def compute_hashes(items: list[Item]) -> None:
    for it in items:
        with Image.open(it.path) as im:
            it.phash = int(str(imagehash.phash(im.convert("RGB"))), 16)


def group_duplicates(items: list[Item]) -> list[int]:
    """Union-find over pairs with Hamming distance <= DUP_DIST. Returns a group id per item."""
    hashes = np.array([it.phash for it in items], dtype=np.uint64)
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items) - 1):
        x = np.bitwise_xor(hashes[i + 1:], hashes[i])
        dist = np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)
        for j in np.nonzero(dist <= DUP_DIST)[0] + i + 1:
            ri, rj = find(i), find(int(j))
            if ri != rj:
                parent[rj] = ri
    return [find(i) for i in range(len(items))]


def split_for_group(key: str) -> str:
    h = int(hashlib.sha1(f"mix-{key}".encode()).hexdigest(), 16) % 100
    return "train" if h < 80 else "val" if h < 90 else "test"


def place(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if args.out.exists():
        shutil.rmtree(args.out)

    items = load_all()
    print(f"Loaded {len(items)} images:", dict(Counter(i.source for i in items)))
    compute_hashes(items)
    groups = group_duplicates(items)

    by_group: dict[int, list[int]] = {}
    for idx, g in enumerate(groups):
        by_group.setdefault(g, []).append(idx)

    kept, dropped = [], 0
    for members in by_group.values():
        group_items = [items[i] for i in members]
        fixed = next((it.split for it in group_items if it.split), None)
        if fixed is None and any(it.source in TRAIN_ONLY for it in group_items):
            fixed = "train"
        split = fixed or split_for_group(str(min(it.phash for it in group_items)))
        # Keep one image per exact-duplicate hash within the group; prefer ones with boxes.
        seen = set()
        for it in sorted(group_items, key=lambda x: -len(x.boxes)):
            if it.phash in seen:
                dropped += 1
                continue
            seen.add(it.phash)
            it.split = split
            kept.append(it)
    multi = sum(1 for m in by_group.values() if len({items[i].source for i in m}) > 1)
    print(f"Duplicates dropped: {dropped}; near-duplicate groups spanning sources: {multi}")

    splits = ["train", "val", "test", "test_closeup", "test_dashcam", "test_hardneg"]
    for s in splits:
        (args.out / "images" / s).mkdir(parents=True)
        (args.out / "labels" / s).mkdir(parents=True)

    rows, stats = [], Counter()
    for it in kept:
        targets = [it.split]
        if it.split == "test":
            if it.source == "rdd":
                targets.append("test_dashcam")
            elif not it.source.startswith("rdd"):
                targets.append("test_closeup")
            if it.source.startswith("rdd") and not it.boxes and it.meta.get("category") in HARD_NEG:
                targets.append("test_hardneg")  # lane paint / manholes: should get no box
        for s in targets:
            place(it.path, args.out / "images" / s / it.name)
            (args.out / "labels" / s / (Path(it.name).stem + ".txt")).write_text(
                "\n".join(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cx, cy, w, h in it.boxes))
        kind = "pothole" if it.boxes else "negative"
        stats[(it.split, it.source, kind)] += 1
        stats[(it.split, "boxes")] += len(it.boxes)
        rows.append({"image": it.name, "source": it.source, "split": it.split, "boxes": len(it.boxes),
                     "phash": f"{it.phash:016x}", "original": str(it.path.relative_to(ROOT))})

    with (args.out / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (args.out / "dataset.yaml").write_text(
        f"path: {args.out.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: pothole\n")
    (args.out / "SOURCES.md").write_text(__doc__.split("Rules:")[0])

    sources = [s for s in [*RDD_COUNTRIES.values(), "chit", "raj", "farzad", "rome"] if any(k[1] == s for k in stats)]
    print(f"\n{'split':6} " + " ".join(f"{s:>14}" for s in sources) + f" {'boxes':>7}")
    for s in ("train", "val", "test"):
        cells = [f"{stats[(s, src, 'pothole')]:>6}+{stats[(s, src, 'negative')]:<5}neg" for src in sources]
        print(f"{s:6} " + " ".join(f"{c:>14}" for c in cells) + f" {stats[(s, 'boxes')]:>7}")
    print("Written to", args.out)


if __name__ == "__main__":
    main()
