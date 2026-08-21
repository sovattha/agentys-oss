@echo off
title Agentys Dev

echo [1/2] Demarrage du backend Python...
start "Agentys Backend" cmd /k "cd /d %~dp0 && python run_api.py"

echo [2/2] Demarrage du frontend Vite...
start "Agentys Frontend" cmd /k "cd /d %~dp0agentys-app && yarn dev"

echo.
echo Backend  : http://localhost:5050
echo Frontend : http://localhost:1420
echo.
timeout /t 4 >nul
start chrome http://localhost:1420
