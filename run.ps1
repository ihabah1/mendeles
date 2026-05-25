# Mandeles – שרת Django על פורט 8000 (אתר React + דשבורד /manage/)
$ErrorActionPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

Write-Host "Stopping old servers on port 8000..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$manifestPath = Join-Path $PSScriptRoot 'static\frontend\.vite\manifest.json'
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $keepJs = Split-Path $manifest.'index.html'.file -Leaf
    Get-ChildItem "$PSScriptRoot\static\frontend\assets\index-*.js" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $keepJs } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "  Project:  250526 (Django + React)" -ForegroundColor Green
Write-Host "  Site:     http://127.0.0.1:8000/" -ForegroundColor Cyan
Write-Host "  Manage:   http://127.0.0.1:8000/manage/customers/" -ForegroundColor Yellow
Write-Host "  Login:    admin@admin.com / admin" -ForegroundColor DarkGray
Write-Host ""

python manage.py runserver 8000
