# start_kaizumi.ps1 — single-instance Kaizumi launcher.
# Auto-detects the Python interpreter (venv first, then system python).
$ErrorActionPreference = "Stop"

$ROOT   = Split-Path -Parent $MyInvocation.MyCommand.Path

# Pick the interpreter: prefer the local venv, then pythonw/python on PATH.
$PY = ""
foreach ($candidate in @(
    (Join-Path $ROOT ".venv\Scripts\pythonw.exe"),
    (Join-Path $ROOT ".venv\Scripts\python.exe"),
    "pythonw.exe",
    "python.exe"
)) {
    $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($resolved) {
        $PY = $resolved.Source
        break
    }
}
if (-not $PY) {
    Write-Error "Python not found. Create a venv first:  python -m venv .venv"
    exit 1
}

# Kill any existing Kaizumi instances (single instance).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*main.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

Start-Process -FilePath $PY `
    -ArgumentList @("-u", (Join-Path $ROOT "main.py"), "--remote") `
    -WorkingDirectory $ROOT `
    -WindowStyle Hidden

Write-Output "Kaizumi started (single instance)."
