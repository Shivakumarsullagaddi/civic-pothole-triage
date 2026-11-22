# Build the website and deploy the app to Cloud Run (project ideaforge-pothole-triage).
# Uses ONLY the "hackathon" gcloud configuration (Gmail account); other configs are never touched.
#
# Usage (PowerShell, from the project root):   .\deploy\deploy.ps1
# One-time setup already done: APIs, bucket, service account, secrets (see deploy\README.md).

# npm and gcloud print progress on stderr; Windows PowerShell 5.1 would treat that as fatal
# under 'Stop', so failures are detected through $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$Root    = Split-Path -Parent $PSScriptRoot
$Project = 'ideaforge-pothole-triage'
$Region  = 'us-central1'                      # Cloud Storage free tier is US-only; keep everything together
$Service = 'pothole-triage'
$SA      = "pothole-run@$Project.iam.gserviceaccount.com"
$Bucket  = 'ideaforge-pothole-triage-photos'
$Cfg     = '--configuration=hackathon'

Write-Host "1/3 Building the website..." -ForegroundColor Cyan
Push-Location "$Root\frontend"
npm run build
if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
Pop-Location
$Static = "$Root\backend\static"
if (Test-Path $Static) { Remove-Item -Recurse -Force $Static }
Copy-Item -Recurse "$Root\frontend\dist" $Static

Write-Host "2/3 Deploying to Cloud Run (build happens in Google Cloud, takes a few minutes)..." -ForegroundColor Cyan
& gcloud run deploy $Service $Cfg --quiet `
  --project=$Project --region=$Region --source="$Root\backend" `
  --service-account=$SA --allow-unauthenticated `
  --cpu=1 --memory=2Gi --min-instances=0 --max-instances=3 --concurrency=20 --timeout=120 `
  --cpu-boost --execution-environment=gen2 `
  --set-env-vars="STORAGE_BUCKET=$Bucket,SCHEDULER_ENABLED=false,COOKIE_SECURE=true,DETECTION_MODE=enforce,MODEL_PATH=models/pothole_y11s_v2_640.onnx,AUTHORITY_TOKEN=" `
  --set-secrets="DATABASE_URL=database-url:latest,SECRET_KEY=secret-key:latest,INTERNAL_TOKEN=internal-token:latest"
if ($LASTEXITCODE -ne 0) { throw 'deploy failed' }

$Url = & gcloud run services describe $Service $Cfg --project=$Project --region=$Region --format='value(status.url)'
Write-Host "3/3 Deployed: $Url" -ForegroundColor Green
Write-Host "    Health: $Url/health"
