# Start Bahmni & OpenELIS Implementation Portal on Port 8001
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Starting Bahmni & OpenELIS Implementation Portal" -ForegroundColor Green
Write-Host "  Listening on: http://localhost:8001" -ForegroundColor Yellow
Write-Host "  Security: Restricted to OpenELIS Maintenance Users" -ForegroundColor Magenta
Write-Host "========================================================" -ForegroundColor Cyan

python "$ScriptDir\implementation_service.py"
