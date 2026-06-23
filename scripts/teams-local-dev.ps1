param(
  [int]$BackendPort = 8000,
  [string]$Tunnel = "ngrok"
)

$ErrorActionPreference = "Stop"

Write-Host "Teams local development"
Write-Host "Backend URL: http://127.0.0.1:$BackendPort"
Write-Host "Teams endpoint: http://127.0.0.1:$BackendPort/api/v1/teams/messages"
Write-Host ""
Write-Host "Terminal 1:"
Write-Host "  cd D:\finops-ai\backend"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  uvicorn main:app --reload --host 127.0.0.1 --port $BackendPort"
Write-Host ""

if ($Tunnel -eq "devtunnel") {
  Write-Host "Terminal 2:"
  Write-Host "  devtunnel host -p $BackendPort --allow-anonymous"
  Write-Host ""
  Write-Host "Set Azure Bot Messaging endpoint to:"
  Write-Host "  https://<your-devtunnel-host>/api/v1/teams/messages"
}
else {
  Write-Host "Terminal 2:"
  Write-Host "  ngrok http $BackendPort"
  Write-Host ""
  Write-Host "Set Azure Bot Messaging endpoint to:"
  Write-Host "  https://<your-ngrok-host>/api/v1/teams/messages"
}

Write-Host ""
Write-Host "For Bot Framework Emulator only, set BOT_VALIDATE_AUTH=false in backend/.env."
Write-Host "For Teams/ngrok testing, keep BOT_VALIDATE_AUTH=true and use the Azure Bot App ID/secret."
