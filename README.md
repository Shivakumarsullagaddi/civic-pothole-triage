# Civic Pothole Triage

**Report a pothole in 10 seconds. We make sure it gets fixed.**

Citizens in Bengaluru photograph a pothole with their phone. The system checks the photo is
genuine, finds the pothole with its own AI model, scores how severe it is, merges duplicate
reports, and routes the issue to the responsible ward office of the Greater Bengaluru Authority
(GBA) with a deadline. Missed deadlines escalate automatically, and a later citizen photo proves
whether a repair really happened. A public map and dashboard show progress to everyone.

Built for the **IDEA//FORGE hackathon**, Track 1: Civic Grievance & Infrastructure Triage.

## Features

| | |
|---|---|
| **Snap & send** | Live camera capture (3-frame burst) + GPS. No account needed for citizens. |
| **Fake-report resistance** | Detects reused photos (perceptual hash), photos of screens (moiré analysis), staged frames, implausible GPS; uncertain reports wait for an independent second report. |
| **Own AI detector** | YOLO11s trained on 11,700+ road images, exported to ONNX, runs on a plain CPU in about 0.1 s. No paid AI API. |
| **Severity & confidence** | Severity from pothole size and count; a report is accepted only when the model is confident across all three frames. |
| **Duplicate merging** | Reports within a GPS-aware radius (15–30 m) merge into one pothole. |
| **Ward routing** | PostGIS matches the location to one of 369 GBA wards and its office. |
| **Deadlines & escalation** | Deadline by severity; overdue issues move ward office → zone → city corporation → GBA, hourly. |
| **Repair verification** | A new photo at a "fixed" pothole confirms the repair or reopens it as falsely closed. |
| **Transparency** | Public map, issue pages with full history, dashboard of fakes blocked and escalations. Photos are never public. |
| **Staff console** | Officers review photos with AI boxes and update status; admins manage accounts, delete reports and photos, and run escalation. |

## Model results (held-out test images)

| Test | Before retraining | Current model |
|---|---|---|
| Lane markings & manholes wrongly flagged | 8.8% | **1.8%** |
| Close-up potholes found | 63% | **71%** |
| Dashcam potholes found (India) | 31% | **39%** |

Validation: precision 0.72, recall 0.61, mAP50 0.685.

## Architecture

```
Phone browser ──► Cloud Run (FastAPI + React site + ONNX model, scales to zero)
                     ├── Neon Postgres + PostGIS   (reports, issues, wards, staff)
                     ├── Cloud Storage (private)    (photos)
                     └── Secret Manager             (database URL, keys)
Cloud Scheduler ──► hourly POST /internal/escalate
```

**Stack:** Python 3.13, FastAPI, SQLAlchemy + GeoAlchemy2, PostgreSQL/PostGIS, ONNX Runtime,
OpenCV · React + TypeScript + Vite, MapLibre GL · Google Cloud Run, Cloud Storage, Cloud
Scheduler, Secret Manager · Neon serverless Postgres.

## Project structure

```
backend/
  app/           API, report pipeline, integrity checks, lifecycle, auth
  tests/         pytest suite (needs a throwaway PostGIS database)
  tools/         dataset preparation, training, evaluation, seeding, user management
frontend/        React app (home, report, map, issue, dashboard, staff console, admin)
deploy/          Cloud Run deployment script and guide
kaggle/          remote GPU training job generator
```

## Run locally (Windows)

Needs Python 3.13, Node 24, PostgreSQL 18 with PostGIS.

```powershell
# one-time setup
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env                                # set DATABASE_URL and SECRET_KEY
.venv\Scripts\python tools\init_db.py                 # database + PostGIS
.venv\Scripts\python tools\seed_wards.py --download   # 369 GBA wards
.venv\Scripts\python tools\create_user.py --email you@example.org --name "Your Name" --role admin
cd ..\frontend
npm install
```

```powershell
# every time: two terminals
cd backend;  .venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
cd frontend; npm run dev
```

Open `https://localhost:5173` (accept the self-signed certificate once). On a phone on the same
Wi-Fi: `https://<laptop-IP>:5173`. API docs: `http://localhost:8000/docs`.

The detector model file (`backend/models/*.onnx`) is not stored in git; train it with
`backend/tools/train_detector.py` (or the Kaggle job in `kaggle/`) and set `MODEL_PATH`.

## Deploy to Google Cloud

See [deploy/README.md](deploy/README.md). One command after the one-time setup:
`.\deploy\deploy.ps1`.

## Tests

```powershell
cd backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:PASSWORD@localhost:5432/pothole_test"  # never the app DB
.venv\Scripts\python -m pytest -q
```

## Data sources and licence notices

- RDD2022 road damage dataset (India, Japan, Czech Republic, United States), CC BY 4.0.
- Kaggle pothole image sets used for training: CC0-1.0, MIT, Apache-2.0 and DbCL-1.0 licensed.
- GBA ward boundaries (December 2025), public data of the Greater Bengaluru Authority.
- Map tiles © OpenStreetMap contributors.
- Training uses the Ultralytics library (AGPL-3.0); the app runs exported ONNX models with ONNX Runtime.

## Team

Built by **Shivakumarsullagaddi** for the IDEA//FORGE hackathon.
