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

rem --- 2. Preparer l'environnement, quand il le faut ------------------------
rem  Le temoin est une COPIE de requirements.txt, deposee par ce script une
rem  fois l'installation reussie. Trois raisons, chacune constatee :
rem
rem  - tester l'existence de python.exe ne dit rien des paquets. Une
rem    installation interrompue - fenetre fermee, veille, antivirus - laisse
rem    un environnement d'apparence complete mais incomplet, et l'outil
rem    mourait ensuite sur une trace Python sans jamais se reparer ;
rem  - tester un executable comme streamlit.exe ne vaut pas mieux : un
rem    antivirus supprime volontiers les petits .exe ecrits par pip, et le
rem    script reinstallerait a chaque lancement ;
rem  - comparer le contenu de requirements.txt rattrape en plus le cas d'une
rem    dependance ajoutee depuis la derniere publication.
set "TEMOIN=%VENV%\requirements-installes.txt"
set "PREPARER=1"
if exist "%TEMOIN%" (
    fc /b "%TEMOIN%" "%APPLI%requirements.txt" > nul 2>&1
    if not errorlevel 1 set "PREPARER="
)

if defined PREPARER (
    echo   Premier lancement : preparation de l'environnement.
    echo   Comptez 2 a 5 minutes. Les lancements suivants seront immediats.
    echo.
    if not exist "%DONNEES%" mkdir "%DONNEES%"
    rem  On ne recree pas l'environnement s'il est deja la : seuls les paquets
    rem  manquent, et pip reprend sans retelecharger ce qui est en cache.
    rem  Le test d'erreur est imbrique : laisse a plat, "if errorlevel" lirait
    rem  le code de retour de la commande precedente quand la creation est
    rem  sautee, et l'outil abandonnerait sur un environnement pourtant sain.
    if not exist "%VENV%\Scripts\python.exe" (
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
    rem  Le temoin n'est depose qu'ici : tant que l'installation n'est pas
    rem  allee au bout, le prochain lancement la reprendra.
    copy /y "%APPLI%requirements.txt" "%TEMOIN%" > nul
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
