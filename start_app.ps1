# SineAI - Backend (FastAPI) & Frontend (React/Vite) Tek Komutla Başlatma Scripti
$RootDir = $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SineAI - PostgreSQL + Backend + Frontend Baslatiliyor" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

# 1. PostgreSQL Docker konteyneri kapaliysa baslat
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $pgStatus = docker inspect -f "{{.State.Running}}" film-kesif-pg 2>$null
    if ($pgStatus -ne "true") {
        Write-Host "[*] PostgreSQL konteyneri (film-kesif-pg) baslatiliyor..." -ForegroundColor Yellow
        docker start film-kesif-pg | Out-Null
    } else {
        Write-Host "[+] PostgreSQL konteyneri zaten calisiyor." -ForegroundColor Green
    }
}

# 2. FastAPI Backend (port 8000) yeni pencerede baslat
Write-Host "[*] FastAPI Backend baslatiliyor (http://localhost:8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\backend'; .\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000"

# 3. React + Vite Frontend (port 5173) yeni pencerede baslat
Write-Host "[*] React Frontend baslatiliyor (http://localhost:5173)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\frontend'; npm run dev"

Write-Host "`n[+] Her iki sunucu da ayri terminallerde baslatildi!" -ForegroundColor Green
Write-Host "    - Frontend : http://localhost:5173/" -ForegroundColor White
Write-Host "    - Backend  : http://localhost:8000/docs" -ForegroundColor White
