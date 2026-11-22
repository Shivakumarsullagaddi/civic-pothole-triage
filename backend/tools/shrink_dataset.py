"""Make a copy of a YOLO dataset with every image downscaled so its longest side <= N px.

Whole-frame downscale only: the full field of view is kept (no crop, pad or mask), so the
normalised YOLO labels stay valid and are copied unchanged. Smaller JPEGs decode much
faster, which keeps the GPU fed with fewer data-loader workers (and less RAM).

Usage (from backend/):
    python tools/shrink_dataset.py ../data/datasets/pothole_mix ../data/datasets/pothole_mix_640 --max-side 640
"""

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps


def shrink(src: Path, dst: Path, max_side: int) -> bool:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            im = im.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)
        im.save(dst, "JPEG", quality=92)
        return max(w, h) > max_side


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--max-side", type=int, default=640)
    args = ap.parse_args()
    if args.dst.exists():
        shutil.rmtree(args.dst)

    jobs = []
    for img in (args.src / "images").rglob("*.jpg"):
        rel = img.relative_to(args.src)
        out = args.dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        jobs.append((img, out))
    with ThreadPoolExecutor(max_workers=8) as pool:
        resized = sum(pool.map(lambda j: shrink(j[0], j[1], args.max_side), jobs))

    shutil.copytree(args.src / "labels", args.dst / "labels",
                    ignore=shutil.ignore_patterns("*.cache"))
    for name in ("manifest.csv", "SOURCES.md"):
        if (args.src / name).exists():
            shutil.copy2(args.src / name, args.dst / name)
    yaml = (args.src / "dataset.yaml").read_text().replace(args.src.as_posix(), args.dst.as_posix())
    (args.dst / "dataset.yaml").write_text(yaml)
    print(f"{len(jobs)} images, {resized} downscaled to max {args.max_side}px -> {args.dst}")


if __name__ == "__main__":
    main()
