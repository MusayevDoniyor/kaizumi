@echo off
rem stop_tunnel.cmd — stops the Kaizumi remote tunnel (cloudflared quick tunnel).
taskkill /IM cloudflared.exe /F >nul 2>&1
echo Tunnel stopped.