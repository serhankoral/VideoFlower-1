param(
    [switch]$SkipBrowser,
    [switch]$SkipTools,
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"

function Info([string]$Message) {
    Write-Host "[setup] $Message" -ForegroundColor Cyan
}

function Warn([string]$Message) {
    Write-Host "[warn]  $Message" -ForegroundColor Yellow
}

function Ok([string]$Message) {
    Write-Host "[ok]    $Message" -ForegroundColor Green
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $VenvPath)) {
    Info "Python virtual environment olusturuluyor (.venv)..."
    py -3 -m venv .venv
    Ok "Virtual environment olusturuldu."
} else {
    Info "Var olan virtual environment kullaniliyor (.venv)."
}

if (-not (Test-Path $PythonExe)) {
    throw "Python executable bulunamadi: $PythonExe"
}

Info "Pip guncelleniyor..."
& $PythonExe -m pip install --upgrade pip

Info "Python bagimliliklari yukleniyor (requirements.txt)..."
& $PythonExe -m pip install -r requirements.txt

if (-not $SkipBrowser) {
    Info "Playwright browser paketleri yukleniyor (chromium)..."
    & $PythonExe -m playwright install chromium
    Ok "Playwright browser kurulumu tamamlandi."
} else {
    Warn "Playwright browser kurulumu atlandi (--SkipBrowser)."
}

if (-not $SkipTools) {
    Info "Harici arac kontrolleri yapiliyor (yt-dlp, ffprobe)..."

    try {
        & yt-dlp --version | Out-Null
        Ok "yt-dlp komutu bulundu."
    } catch {
        Warn "yt-dlp komutu PATH'te bulunamadi. Python paketi yuklendi ama komut tanimli olmayabilir."
    }

    try {
        & ffprobe -version | Out-Null
        Ok "ffprobe bulundu."
    } catch {
        Warn "ffprobe bulunamadi. ffmpeg/ffprobe kurmalisin (or. winget install Gyan.FFmpeg)."
    }
} else {
    Warn "Harici arac kontrolleri atlandi (--SkipTools)."
}

if ($RunTests) {
    Info "Testler calistiriliyor..."
    & $PythonExe -m pytest -q
}

Ok "Kurulum tamam."
Write-Host "Aktivasyon: .\\.venv\\Scripts\\Activate.ps1" -ForegroundColor Gray
Write-Host "Calistirma ornegi:" -ForegroundColor Gray
Write-Host '.\.venv\Scripts\python.exe .\video_interceptor.py "<URL>" --debug --providers-config providers.json' -ForegroundColor Gray
