# Cloud deployment (Google Cloud, serverless)

Project `ideaforge-pothole-triage` (Gmail account), region `us-central1`.
All commands use the gcloud configuration **`hackathon`**; never the default one.

| Piece | Service | Notes |
|---|---|---|
| App (API + website + AI model) | Cloud Run `pothole-triage` | Scales to zero; 1 vCPU, 2 GiB; runs as `pothole-run@…` |
| Photos | Cloud Storage `ideaforge-pothole-triage-photos` | Private, uniform access, public access blocked |
| Database | Neon Postgres + PostGIS (AWS US East 2) | Connection string in Secret Manager `database-url` |
| Secrets | Secret Manager `database-url`, `secret-key`, `internal-token` | Only `pothole-run` can read them |
| Hourly escalation | Cloud Scheduler → `POST /internal/escalate` | Sends `X-Internal-Token` |

## Redeploy after code changes

```powershell
cd D:\nxtwave\hackathon\civic-pothole-triage
.\deploy\deploy.ps1
```

It builds the website, then `gcloud run deploy --source backend` (Cloud Build builds the
container in the cloud; no Docker on the laptop). `.gcloudignore` uploads only the app, the
current model and the built site.

## Rotate a secret (for example after resetting the Neon password)

```powershell
# write the new value to a file first (no trailing newline), then:
gcloud secrets versions add database-url --data-file=<file> --configuration=hackathon
.\deploy\deploy.ps1      # new revision picks up :latest
```

## Staff accounts in the cloud database

```powershell
cd backend
$env:DATABASE_URL = (Get-Content .env.cloud | Select-String '^NEON_URL=').Line.Substring(9) -replace '^postgresql://','postgresql+psycopg://'
.venv\Scripts\python tools\create_user.py --email someone@example.org --name "Name" --role admin
Remove-Item Env:DATABASE_URL
```
Admins can then add officers from the Admin page.

## Costs (keep at ₹0)
- Cloud Run, Cloud Storage (US region), Cloud Scheduler (1 of 3 free jobs), Secret Manager,
  Cloud Build: within free tiers at hackathon traffic.
- Artifact Registry stores built images (0.5 GB free): delete old images occasionally.
- A budget alert (₹100) is set on the billing account.
