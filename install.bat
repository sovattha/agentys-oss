@echo off
REM Script d'installation Agentys pour Windows
REM
REM Usage:
REM   install.bat          - Installation standard
REM   install.bat --dev    - Installation avec dépendances de développement
REM

setlocal EnableDelayedExpansion

REM Variables
set "PYTHON_MIN_VERSION=3.10"
set "INSTALL_DIR=%~dp0"
set "VENV_DIR=%INSTALL_DIR%venv"
set "DEV_MODE=false"

REM Parse arguments
if "%1"=="--dev" set "DEV_MODE=true"
if "%1"=="--help" goto :show_help
if "%1"=="-h" goto :show_help

REM Bannière
echo.
echo ====================================================
echo          Agentys Installation - Windows
echo      Pipeline Multi-Agents IA pour Email
echo ====================================================
echo.

REM Vérifier Python
echo [INFO] Vérification de Python...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python n'est pas installé ou n'est pas dans le PATH.
    echo         Veuillez installer Python %PYTHON_MIN_VERSION% ou supérieur.
    echo         https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [SUCCESS] %PYTHON_VERSION% trouvé

REM Vérifier la version de Python
for /f "tokens=2 delims= " %%a in ('python --version') do set "FULL_VERSION=%%a"
for /f "tokens=1,2 delims=." %%a in ("%FULL_VERSION%") do (
    set "MAJOR=%%a"
    set "MINOR=%%b"
)

if %MAJOR% LSS 3 (
    echo [ERROR] Python 3.10 ou supérieur est requis.
    exit /b 1
)
if %MAJOR% EQU 3 if %MINOR% LSS 10 (
    echo [ERROR] Python 3.10 ou supérieur est requis.
    exit /b 1
)

REM Créer l'environnement virtuel
echo [INFO] Création de l'environnement virtuel...
if exist "%VENV_DIR%" (
    echo [WARNING] Environnement virtuel existant trouvé.
    set /p "RECREATE=Voulez-vous le recréer? (o/n): "
    if /i "!RECREATE!"=="o" (
        rmdir /s /q "%VENV_DIR%"
        python -m venv "%VENV_DIR%"
    )
) else (
    python -m venv "%VENV_DIR%"
)
echo [SUCCESS] Environnement virtuel créé

REM Activer l'environnement virtuel
echo [INFO] Activation de l'environnement virtuel...
call "%VENV_DIR%\Scripts\activate.bat"

REM Mettre à jour pip
echo [INFO] Mise à jour de pip...
python -m pip install --upgrade pip >nul 2>&1

REM Installer les dépendances
echo [INFO] Installation des dépendances...
pip install -r "%INSTALL_DIR%requirements.txt"
echo [SUCCESS] Dépendances installées

REM Installer les dépendances de développement si demandé
if "%DEV_MODE%"=="true" (
    echo [INFO] Installation des dépendances de développement...
    pip install pytest pytest-cov black flake8 mypy
    echo [SUCCESS] Dépendances de développement installées
)

REM Créer les répertoires nécessaires
echo [INFO] Création des répertoires...
if not exist "%INSTALL_DIR%data" mkdir "%INSTALL_DIR%data"
if not exist "%INSTALL_DIR%logs" mkdir "%INSTALL_DIR%logs"
if not exist "%INSTALL_DIR%knowledge" mkdir "%INSTALL_DIR%knowledge"
if not exist "%INSTALL_DIR%agents" mkdir "%INSTALL_DIR%agents"

REM Créer le fichier .env s'il n'existe pas
if not exist "%INSTALL_DIR%.env" (
    echo [INFO] Création du fichier .env...
    (
        echo # Configuration Agentys
        echo # Copiez ce fichier et remplissez les valeurs
        echo.
        echo # LLM Provider ^(claude ou ollama^)
        echo LLM_PROVIDER=claude
        echo LLM_MODEL=claude-opus-4-7
        echo.
        echo # Clé API Anthropic ^(requis si LLM_PROVIDER=claude^)
        echo ANTHROPIC_API_KEY=
        echo.
        echo # Email Provider ^(GMAIL, OUTLOOK, ou IMAP^)
        echo EMAIL_PROVIDER_TYPE=GMAIL
        echo.
        echo # Intervalle de polling en secondes
        echo DAEMON_POLL_INTERVAL=60
        echo.
        echo # Budget mensuel ^(USD^)
        echo MONTHLY_BUDGET_USD=50
        echo.
        echo # Notifications
        echo NOTIFICATIONS_ENABLED=true
    ) > "%INSTALL_DIR%.env"
    echo [SUCCESS] Fichier .env créé
)

REM Créer le fichier de mémoire s'il n'existe pas
if not exist "%INSTALL_DIR%knowledge\memoire.md" (
    echo [INFO] Création du fichier de mémoire...
    (
        echo # Base de Connaissances Agentys
        echo.
        echo ## Informations Générales
        echo.
        echo Bienvenue dans Agentys. Cette base de connaissances contient les informations
        echo que l'IA utilisera pour générer des réponses personnalisées.
        echo.
        echo ## Style de Réponse
        echo.
        echo - Ton professionnel et courtois
        echo - Réponses concises mais complètes
        echo - Toujours proposer de l'aide supplémentaire
        echo.
        echo ## FAQ
        echo.
        echo Ajoutez ici les questions fréquentes et leurs réponses.
    ) > "%INSTALL_DIR%knowledge\memoire.md"
    echo [SUCCESS] Fichier de mémoire créé
)

REM Instructions finales
echo.
echo ====================================================
echo   Installation terminée avec succès!
echo ====================================================
echo.
echo Prochaines étapes:
echo.
echo 1. Configurez votre fichier .env:
echo    notepad .env
echo.
echo 2. Lancez le setup interactif:
echo    venv\Scripts\activate
echo    python setup.py
echo.
echo 3. Démarrez le daemon:
echo    python run_daemon.py
echo.
echo 4. (Optionnel) Lancez le dashboard:
echo    python -c "from app.dashboard import run_dashboard; run_dashboard()"
echo.
goto :eof

:show_help
echo Usage: install.bat [OPTIONS]
echo.
echo Options:
echo   --dev       Install development dependencies
echo   --help      Show this help message
goto :eof
