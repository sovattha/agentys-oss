@echo off
:: Installe Agentys Backend comme tâche planifiée Windows (redémarre au login)
:: Lance en mode administrateur si besoin

set TASK_NAME=AgentysBackend
set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
set SCRIPT=%~dp0run_api.py
set WORKDIR=%~dp0

:: Supprimer l'ancienne tâche si elle existe
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

:: Créer la tâche : démarre au login de l'utilisateur courant
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /it ^
  /f

echo.
echo [OK] Tache planifiee "%TASK_NAME%" creee.
echo      Le backend demarrera automatiquement au prochain login.
echo.
echo Pour demarrer maintenant :
echo   schtasks /run /tn "%TASK_NAME%"
echo.
pause
