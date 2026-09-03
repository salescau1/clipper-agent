# Peluncur GUI Clipper Agent.
#
# Tidak lagi menghardcode "C:\Clipper Agent\clipper" maupun ".venv": skrip ini
# bekerja dari folder tempat ia berada, dan memilih interpreter dengan urutan
# prioritas yang SAMA dengan `bundled_paths.resolve_python_exe()`:
#   1. python-embed\python.exe        (dibawa installer portabel)
#   2. .venv\Scripts\python.exe       (folder pengembangan — perilaku lama)
# Di hasil installer `.venv` MASIH ADA tapi pyvenv.cfg-nya menunjuk Python yang
# tidak terpasang di komputer tujuan, jadi python-embed harus menang.
Set-Location $PSScriptRoot

$kandidat = @(
    (Join-Path $PSScriptRoot "python-embed\python.exe"),
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")
)
$python = $kandidat | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    Write-Host "Interpreter Python tidak ditemukan. Dicari di:" -ForegroundColor Red
    $kandidat | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

& $python (Join-Path $PSScriptRoot "clipper_gui.py")
