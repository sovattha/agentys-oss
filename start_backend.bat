@echo off
cd /d "%~dp0"
title Agentys Backend
:loop
echo [%date% %time%] Demarrage du backend Agentys...
python run_api.py
echo [%date% %time%] Backend arrete - redemarrage dans 3 secondes...
timeout /t 3 /nobreak >nul
goto loop
