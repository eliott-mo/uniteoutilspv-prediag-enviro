@echo off
rem ===========================================================================
rem  Pre-diagnostic environnemental - lancement
rem
rem  Double-clic depuis le dossier Outils. Au premier lancement, prepare
rem  l'environnement Python sur la machine (quelques minutes) ; ensuite,
rem  demarre en quelques secondes.
rem
rem  L'environnement et les donnees vont dans %LOCALAPPDATA%, jamais dans le
rem  dossier partage : OneDrive synchroniserait sinon des centaines de Mo pour
rem  chaque personne, et les fichiers ecrits pendant l'execution produiraient
rem  des copies de conflit.
rem
rem  Pas d'accents dans ce fichier : le code page d'une console Windows n'est
rem  pas garanti, et un message d'erreur illisible est pire que pas d'accents.
rem ===========================================================================

chcp 65001 > nul 2>&1
title Prediag environnemental - NE PAS FERMER CETTE FENETRE
setlocal

set "APPLI=%~dp0"
set "DONNEES=%LOCALAPPDATA%\prediag-enviro"
set "VENV=%DONNEES%\venv"
set "PORT=8521"

echo.
echo   ================================================================
echo     PREDIAG ENVIRONNEMENTAL
echo   ================================================================
echo.

rem --- 1. Trouver Python -----------------------------------------------------
set "PY="
py -3 --version > nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version > nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo   Python n'est pas installe sur ce poste.
    echo.
    echo   L'outil en a besoin pour fonctionner. Deux options :
    echo     - l'installer depuis https://www.python.org/downloads/
    echo       en cochant "Add python.exe to PATH" a la premiere etape ;
    echo     - ou demander son installation au service informatique.
    echo.
    echo   Version requise : 3.11 ou superieure.
    echo.
    pause
    exit /b 1
)

rem --- 2. Preparer l'environnement, une fois -------------------------------
if not exist "%VENV%\Scripts\python.exe" (
    echo   Premier lancement : preparation de l'environnement.
    echo   Comptez 2 a 5 minutes. Les lancements suivants seront immediats.
    echo.
    if not exist "%DONNEES%" mkdir "%DONNEES%"
    %PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo   La creation de l'environnement a echoue.
        echo   Verifiez que Python est complet ^(le module venv est parfois
        echo   absent des installations minimales^).
        echo.
        pause
        exit /b 1
    )
    echo   Installation des composants...
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet
    "%VENV%\Scripts\python.exe" -m pip install -r "%APPLI%requirements.txt" --quiet
    if errorlevel 1 (
        echo.
        echo   L'installation des composants a echoue.
        echo.
        echo   Cause la plus frequente : le reseau de l'entreprise bloque
        echo   l'acces a pypi.org. Montrez ce message au service informatique,
        echo   il saura quoi autoriser.
        echo.
        rmdir /s /q "%VENV%" 2> nul
        pause
        exit /b 1
    )
    echo   Environnement pret.
    echo.
)

rem --- 3. Lancer --------------------------------------------------------------
echo   Ouverture dans votre navigateur...
echo.
echo   ----------------------------------------------------------------
echo     Laissez cette fenetre ouverte tant que vous utilisez l'outil.
echo     Pour quitter : fermez-la.
echo   ----------------------------------------------------------------
echo.

start "" "http://localhost:%PORT%"
"%VENV%\Scripts\python.exe" -m streamlit run "%APPLI%app.py" ^
    --server.port %PORT% ^
    --server.headless true ^
    --browser.gatherUsageStats false

endlocal
