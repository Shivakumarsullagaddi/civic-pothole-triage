"""Kaggle batch job: rebuild the v2 pothole dataset from public sources and train YOLO11s.

Generated into kaggle/job/train_job.py by kaggle/make_job.py (which embeds backend/tools).
Runs unattended on Kaggle's GPU. Results are copied to /kaggle/working/out/:
  pothole_y11s_v2_640.onnx, best.pt, results.csv, results.png, confusion_matrix.png
"""
import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

KAGGLE_DATASETS = ["chitholian/annotated-potholes-dataset", "rajdalsaniya/pothole-detection-dataset",
                   "farzadnekouei/pothole-image-segmentation-dataset",
                   "lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes"]
TOOLS_B64 = {}  # filled in by make_job.py: {"build_training_set.py": "<base64>", ...}

WORK = Path("/kaggle/working")
CT = Path("/kaggle/temp/ct") if Path("/kaggle/temp").exists() else WORK / "ct"  # big files outside /kaggle/working
TOOLS = CT / "backend" / "tools"
RAW = CT / "data" / "raw"
OUT = WORK / "out"
PY = sys.executable
os.environ["YOLO_AUTOINSTALL"] = "False"
os.environ["PYTHONUNBUFFERED"] = "1"
T0 = time.time()


def log(msg):
    print(f"[{(time.time() - T0) / 60:6.1f} min] {msg}", flush=True)


def step(name, cmd):
    log(f"START {name}")
    r = subprocess.run(cmd, cwd=CT / "backend")
    log(f"END {name}: exit {r.returncode}")
    if r.returncode != 0:
        sys.exit(f"step failed: {name}")


def main():
    log("installing packages")
    subprocess.run([PY, "-m", "pip", "install", "-q", "ultralytics==8.3.170", "remotezip==0.12.3",
                    "ImageHash==4.3.2", "onnxslim==0.1.59"], check=True)
    import torch

    gpus = torch.cuda.device_count()
    log(f"GPUs: {[torch.cuda.get_device_name(i) for i in range(gpus)]}")

    TOOLS.mkdir(parents=True, exist_ok=True)
    (CT / "data" / "runs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    for name, b64 in TOOLS_B64.items():
        (TOOLS / name).write_bytes(base64.b64decode(b64))

    for c in ["India", "Japan", "Czech", "United_States"]:
        out = RAW / f"rdd2022_{c.lower()}"
        step(f"download RDD {c}", [PY, "tools/fetch_rdd_india.py", "--country", c, "--out", str(out)])
        for z in out.glob("*.zip"):
            z.unlink()

    # Batch jobs cannot download Kaggle datasets on the fly: they are attached in
    # kernel-metadata.json (dataset_sources) and mounted read-only under /kaggle/input.
    for slug in KAGGLE_DATASETS:
        name = slug.split("/")[1]
        found = [p for p in Path("/kaggle/input").rglob(name) if p.is_dir()]
        if not found:
            sys.exit(f"dataset not mounted: {slug} (check dataset_sources)")
        dst = RAW / "kaggle" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(found[0], target_is_directory=True)
        log(f"linked {slug} -> {found[0]}")

    for c in ["India", "Japan", "Czech", "United_States"]:
        step(f"prepare {c}", [PY, "tools/prepare_rdd.py", "--country", c])
    v2 = CT / "data/datasets/pothole_mix_v2"
    step("build v2 dataset", [PY, "tools/build_training_set.py", "--out", str(v2)])
    step("shrink to 640", [PY, "tools/shrink_dataset.py", str(v2), str(v2) + "_640", "--max-side", "640"])

    device = ",".join(str(i) for i in range(gpus)) if gpus else "cpu"
    batch = 16 * max(gpus, 1)
    step("train YOLO11s", [PY, "tools/train_detector.py", "--base", "yolo11s.pt",
                           "--data", str(v2) + "_640/dataset.yaml", "--epochs", "60", "--imgsz", "640",
                           "--batch", str(batch), "--workers", "4", "--cache", "ram", "--device", device,
                           "--patience", "15", "--name", "pothole_y11s_v2"])

    run = CT / "data/runs/pothole_y11s_v2"
    for f in [CT / "backend/models/pothole_y11s_v2_640.onnx", run / "weights/best.pt", run / "results.csv",
              run / "results.png", run / "confusion_matrix.png", run / "args.yaml"]:
        if f.exists():
            shutil.copy2(f, OUT / f.name)
    log(f"DONE. Outputs: {sorted(p.name for p in OUT.iterdir())}")
    if CT.is_relative_to(WORK):
        shutil.rmtree(CT, ignore_errors=True)  # keep only /kaggle/working/out as the saved output


if __name__ == "__main__":
    main()
