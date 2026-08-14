# start_kaizumi.ps1 — single-instance Kaizumi launcher.
# Uses the base pythonw + venv site-packages to avoid the venv launcher
# spawning a duplicate child process on this machine.
$ErrorActionPreference = "Stop"

$PY          = "C:\Users\doniy\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
$SITE        = "C:\dev\kaizumi\.venv\Lib\site-packages"
$MAIN        = "C:\dev\kaizumi\main.py"
$WORKDIR     = "C:\dev\kaizumi"

# Kill any existing Kaizumi instances (single instance).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*main.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$env:PYTHONPATH = $SITE
Start-Process -FilePath $PY `
    -ArgumentList @("-u", $MAIN, "--remote") `
    -WorkingDirectory $WORKDIR `
    -WindowStyle Minimized

Write-Output "Kaizumi started (single instance)."
