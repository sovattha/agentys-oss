@echo off
title Build Agentys Backend EXE
echo.
echo ========================================
echo   Build Agentys-Backend.exe
echo ========================================
echo.

REM Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python n'est pas installe ou pas dans le PATH
    pause
    exit /b 1
)

REM Installer PyInstaller si necessaire
echo 📦 Installation de PyInstaller...
pip install pyinstaller --quiet

REM Lancer le build
echo.
echo 🔨 Build en cours...
python build_windows_exe.py

echo.
pause
