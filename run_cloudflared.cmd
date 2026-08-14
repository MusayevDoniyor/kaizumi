@echo off
rem run_cloudflared.cmd — launches cloudflared quick tunnel, logging to tunnel.log
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://localhost:8765 > "C:\dev\kaizumi\logs\tunnel.log" 2>&1
