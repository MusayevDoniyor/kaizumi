@echo off
rem run_cloudflared.cmd — launches cloudflared quick tunnel, logging to tunnel.log
set ROOT=%~dp0
set CF=%ROOT%cloudflared.exe
if not exist "%CF%" set CF=cloudflared
"%CF%" tunnel --no-autoupdate --url http://localhost:8765 > "%ROOT%logs\tunnel.log" 2>&1