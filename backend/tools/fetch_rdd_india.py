"""Download one country of RDD2022 from the figshare archive (default India).

The full archive is 13.3 GB and contains one zip per country. We read its index over HTTP
and download only that country's `RDD2022/<Country>.zip` entry (India about 527 MB), then unpack it.

Source: RDD2022, figshare article 21431547, licence CC BY 4.0.
Cite: Arya et al., "RDD2022: A multi-national image dataset for automatic road damage
detection", Geoscience Data Journal, 2024.

Usage:
    python tools/fetch_rdd_india.py --out ../data/raw/rdd2022_india
    python tools/fetch_rdd_india.py --country Japan --out ../data/raw/rdd2022_japan
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from remotezip import RemoteZip

ARCHIVE_URL = "https://ndownloader.figshare.com/files/38030910"
COUNTRIES = ["India", "Japan", "Czech", "United_States", "China_MotorBike", "China_Drone", "Norway"]


def safe_extract(zip_path: Path, out: Path) -> int:
    out_resolved = out.resolve()
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (out / info.filename).resolve()
            if not target.is_relative_to(out_resolved):
                raise ValueError(f"Unsafe path in archive: {info.filename}")
            if info.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                while block := src.read(1 << 20):
                    dst.write(block)
            count += 1
    return count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--country", default="India", choices=COUNTRIES)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    MEMBER = f"RDD2022/{args.country}.zip"

    inner = args.out / f"{args.country}.zip"
    if not inner.exists():
        print(f"Downloading {MEMBER} from the RDD2022 archive...")
        with RemoteZip(ARCHIVE_URL) as rz:
            info = rz.getinfo(MEMBER)
            tmp = args.out / f"{args.country}.zip.part"
            with rz.open(info) as src, tmp.open("wb") as dst:
                done = 0
                while block := src.read(1 << 20):
                    dst.write(block)
                    done += len(block)
                    print(f"\r  {done / 1e6:8.1f} / {info.file_size / 1e6:.1f} MB", end="", flush=True)
            print()
            tmp.rename(inner)

    n = safe_extract(inner, args.out)
    print(f"Extracted {n} files to {args.out}")


if __name__ == "__main__":
    main()
