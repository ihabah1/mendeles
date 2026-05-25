# Mandeles – Django :8000 + אופציונלי שירותי לוטו Flask
param(
    [switch]$Legacy
)

$ErrorActionPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

Write-Host "Stopping old servers on port 8000..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

if ($Legacy) {
    Write-Host "Starting legacy lotto services (start_all.py)..." -ForegroundColor Yellow
    Start-Process python -ArgumentList "start_all.py" -WorkingDirectory $PSScriptRoot -WindowStyle Minimized
    Start-Sleep -Seconds 3
}

$manifestPath = Join-Path $PSScriptRoot 'static\frontend\.vite\manifest.json'
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $keepJs = Split-Path $manifest.'index.html'.file -Leaf
    Get-ChildItem "$PSScriptRoot\static\frontend\assets\index-*.js" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $keepJs } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "  Project:  250526 (Django + React + Legacy bridge)" -ForegroundColor Green
Write-Host "  Site:     http://127.0.0.1:8000/" -ForegroundColor Cyan
Write-Host "  Manage:   http://127.0.0.1:8000/manage/customers/" -ForegroundColor Yellow
Write-Host "  Classic:  http://127.0.0.1:8000/classic/new_stite.html" -ForegroundColor Magenta
Write-Host "  Integr.:  http://127.0.0.1:8000/manage/integration/" -ForegroundColor DarkGray
Write-Host "  Login:    admin@admin.com / admin" -ForegroundColor DarkGray
if ($Legacy) {
    Write-Host "  Legacy:   auth/lotto/api proxied on same port 8000" -ForegroundColor DarkGray
}
Write-Host ""

python manage.py runserver 8000
