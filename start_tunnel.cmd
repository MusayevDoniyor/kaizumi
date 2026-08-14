@echo off
rem Kaizumi remote tunnel — exposes the local bridge (port 8765) on the internet.
rem Saves the public URL to logs\remote_url.txt and prints it.
setlocal
set CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe
set ROOT=C:\dev\kaizumi
set LOGFILE=%ROOT%\logs\tunnel.log
set URLFILE=%ROOT%\logs\remote_url.txt

if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
del "%LOGFILE%" 2>nul
del "%URLFILE%" 2>nul

echo Starting cloudflared tunnel to http://localhost:8765 ...
start "" /min cmd /c ""%CLOUDFLARED%" tunnel --no-autoupdate --url http://localhost:8765 > "%LOGFILE%" 2>&1"

rem Poll cloudflared output for the assigned trycloudflare.com URL.
set URL=
for /L %%i in (1,1,40) do (
  ping -n 2 127.0.0.1 >nul
  for /f "tokens=*" %%u in ('findstr /c:".trycloudflare.com" "%LOGFILE%" 2^>nul') do set URL=%%u
  if defined URL goto :found
)
goto :failed

:found
echo.
echo PUBLIC URL: %URL%
echo %URL%> "%URLFILE%"
echo Saved to %URLFILE%
goto :eof

:failed
echo Failed to get a tunnel URL. See %LOGFILE%
exit /b 1