"""Build kaggle/job/ (train_job.py with our tools embedded + kernel-metadata.json).

Usage (from the project root, backend venv):
    backend\\.venv\\Scripts\\python kaggle\\make_job.py
    backend\\.venv\\Scripts\\kaggle kernels push -p kaggle\\job          # start on Kaggle
    backend\\.venv\\Scripts\\kaggle kernels status <user>/civic-pothole-yolo11s
    backend\\.venv\\Scripts\\kaggle kernels output <user>/civic-pothole-yolo11s -p kaggle\\output
"""
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "backend" / "tools"
NEEDED = ["fetch_rdd_india.py", "prepare_rdd.py", "build_training_set.py", "shrink_dataset.py", "train_detector.py"]
SLUG = "civic-pothole-yolo11s"


def username() -> str:
    return json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]


def main():
    job = HERE / "job"
    job.mkdir(exist_ok=True)
    tools = {n: base64.b64encode((TOOLS / n).read_bytes()).decode() for n in NEEDED}
    src = (HERE / "job_template.py").read_text(encoding="utf-8")
    src = src.replace("TOOLS_B64 = {}", "TOOLS_B64 = " + json.dumps(tools), 1)
    (job / "train_job.py").write_text(src, encoding="utf-8")
    (job / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{username()}/{SLUG}",
        "title": SLUG,
        "code_file": "train_job.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": ["chitholian/annotated-potholes-dataset", "rajdalsaniya/pothole-detection-dataset",
                            "farzadnekouei/pothole-image-segmentation-dataset",
                            "lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes"],
        "competition_sources": [],
        "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    print(f"Wrote {job / 'train_job.py'} ({len(src) // 1024} KB) and kernel-metadata.json for {username()}/{SLUG}")


if __name__ == "__main__":
    main()
