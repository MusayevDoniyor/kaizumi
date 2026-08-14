@echo off
rem start_tunnel.cmd — starts the Kaizumi public tunnel (cloudflared quick
rem tunnel to localhost:8765), saves the public URL to logs\remote_url.txt.
setlocal
set ROOT=C:\dev\kaizumi
set LOGFILE=%ROOT%\logs\tunnel.log
set URLFILE=%ROOT%\logs\remote_url.txt

if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
del "%LOGFILE%" 2>nul
del "%URLFILE%" 2>nul

echo Starting cloudflared tunnel to http://localhost:8765 ...
start "KaizumiTunnel" /min "%ROOT%\run_cloudflared.cmd"

rem Poll cloudflared output for the assigned trycloudflare.com URL.
set URL=
for /L %%i in (1,1,45) do (
  ping -n 2 127.0.0.1 >nul
  for /f "usebackq tokens=*" %%u in (`findstr /c:".trycloudflare.com" "%LOGFILE%"`) do set URL=%%u
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