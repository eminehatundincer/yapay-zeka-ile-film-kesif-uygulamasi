# Yapay Zeka Film & Dizi Kesif Ajani - Test Calistirma Scripti
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "1. Birim Testleri Calistiriliyor (pytest)..." -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

backend\.venv\Scripts\pytest.exe backend/tests -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Birim testlerinde hata olustu!" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "2. Canli Ajan Router & Wikipedia Testi Calistiriliyor..." -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

backend\.venv\Scripts\python.exe backend/app/agents/router.py

Write-Host "`n[+] Tum testler basariyla tamamlandi!" -ForegroundColor Green
