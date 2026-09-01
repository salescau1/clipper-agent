Set-Location "C:\Clipper Agent\clipper"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Virtualenv tidak ditemukan." -ForegroundColor Red
    exit 1
}
.\.venv\Scripts\python.exe .\clipper_gui.py
