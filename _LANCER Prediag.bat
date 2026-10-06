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
rem  Le temoin est une COPIE de requirements.txt, deposee une fois
rem  l'installation reussie : tester python.exe ne dit rien des paquets, et
rem  tester un .exe de pip ne vaut pas mieux (un antivirus les supprime).
rem  Comparer le contenu rattrape en plus une dependance ajoutee depuis la
rem  derniere publication.
rem
rem  Tout est ecrit en sauts (goto) et non en blocs parentheses : dans un
rem  bloc, cmd developpe les variables a la lecture et non a l'execution,
rem  ce qui rend les tests enchaines difficiles a relire et a verifier.
set "TEMOIN=%VENV%\requirements-installes.txt"

if not exist "%TEMOIN%" goto preparer
fc /b "%TEMOIN%" "%APPLI%requirements.txt" > nul 2>&1
if errorlevel 1 goto preparer
rem  Le temoin peut etre bon et l'environnement abime depuis. Un import
rem  reel coute un instant et evite de demarrer pour mourir trois lignes
rem  plus loin sur une trace Python.
"%VENV%\Scripts\python.exe" -c "import streamlit" > nul 2>&1
if errorlevel 1 goto preparer
goto lancer

:preparer
echo   Preparation de l'environnement.
echo   Comptez 2 a 5 minutes la premiere fois. Ensuite, demarrage immediat.
echo.
if not exist "%DONNEES%" mkdir "%DONNEES%"
if not exist "%VENV%\Scripts\python.exe" goto creer_venv

rem  pip absent de l'environnement : il est reellement abime, et insister
rem  ne sert a rien. C'est le SEUL cas ou ce script supprime quoi que ce
rem  soit - voir :echec_install pour pourquoi on ne le fait plus ailleurs.
"%VENV%\Scripts\python.exe" -m pip --version > nul 2>&1
if not errorlevel 1 goto installer
echo   Environnement abime : reconstruction.
rmdir /s /q "%VENV%" 2> nul

:creer_venv
%PY% -m venv "%VENV%"
if errorlevel 1 goto echec_venv

:installer
echo   Installation des composants...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%VENV%\Scripts\python.exe" -m pip install -r "%APPLI%requirements.txt" --quiet
if not errorlevel 1 goto installe

rem  Un echec est souvent passager : antivirus qui verrouille un fichier le
rem  temps de l'analyser, coupure reseau breve. On retente une fois.
echo   Echec ; nouvelle tentative...
"%VENV%\Scripts\python.exe" -m pip install -r "%APPLI%requirements.txt" --quiet
if errorlevel 1 goto echec_install

:installe
rem  Le temoin n'est depose qu'ici : tant que l'installation n'est pas allee
rem  au bout, le prochain lancement la reprendra.
copy /y "%APPLI%requirements.txt" "%TEMOIN%" > nul
echo   Environnement pret.
echo.
goto lancer

:echec_venv
echo.
echo   La creation de l'environnement a echoue.
echo   Verifiez que Python est complet ^(le module venv est parfois
echo   absent des installations minimales^).
echo.
pause
exit /b 1

:echec_install
echo.
echo   L'installation des composants a echoue, deux fois de suite.
echo.
echo   Causes possibles :
echo     - le reseau de l'entreprise bloque l'acces a pypi.org ;
echo     - un antivirus verrouille les fichiers pendant l'installation.
echo.
echo   L'environnement n'a PAS ete supprime. Une version anterieure de ce
echo   script l'effacait des le premier echec : 366 Mo refaits pour une
echo   lecture ratee, alors qu'un second essai suffit le plus souvent.
echo.
echo   Pour repartir de zero, si vraiment necessaire :
echo     rmdir /s /q "%VENV%"
echo.
pause
exit /b 1

:lancer

rem --- 3. Lancer --------------------------------------------------------------
echo   Ouverture dans votre navigateur...
echo.
echo   ----------------------------------------------------------------
echo     Laissez cette fenetre ouverte tant que vous utilisez l'outil.
echo     Pour quitter : fermez-la.
echo   ----------------------------------------------------------------
echo.

rem  toolbarMode minimal retire le bouton "Deploy" de Streamlit, qui propose
rem  une mise en ligne sur Streamlit Community Cloud. Cet hebergement ne peut
rem  pas convenir : les referentiels INPN et les extraits departementaux
rem  pesent environ 1,9 Go, absents du depot et impossibles a y mettre. Le
rem  bouton ne menait donc qu'a une impasse.
start "" "http://localhost:%PORT%"
"%VENV%\Scripts\python.exe" -m streamlit run "%APPLI%app.py" ^
    --server.port %PORT% ^
    --server.headless true ^
    --browser.gatherUsageStats false ^
    --client.toolbarMode minimal

endlocal
