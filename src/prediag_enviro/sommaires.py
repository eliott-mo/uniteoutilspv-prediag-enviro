# -*- coding: utf-8 -*-
"""Les numéros de page des sommaires, calculés par Word.

Les sommaires du prédiagnostic sont des champs `TOC` : leurs numéros de page
dépendent de la mise en page, que python-docx ignore. Le document demandait à
Word de les recalculer à l'ouverture, et cela tournait mal. Ouvert depuis une
pièce jointe, le document passe par le mode protégé ; au clic sur « Activer la
modification », Word recalculait avant d'avoir mis le document en pages, et
écrivait « 1 » à chaque entrée. Ouvert directement, il décalait tout d'une
page, car le sommaire, une fois rempli, repousse ce qui le suit (Bédarieux,
12 novembre 2026).

On les fait donc calculer une fois pour toutes, au moment de produire le
document. Word, lancé en arrière-plan et sans fenêtre, ouvre une copie
locale, remplit les sommaires, puis remet leurs numéros de page d'aplomb. Il
enregistre et se referme. Il faut une minute pour les 186 pages du prédiag de
Bédarieux. Ensuite, le document ne demande plus rien à Word.

Word ne s'automatise que par COM, sous Windows. Plutôt que d'ajouter pywin32
aux dépendances, on passe par PowerShell, comme `outils/excel_appliquer.ps1`
le fait pour Excel.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

#: Au-delà, Word est tenu pour figé : le prédiag de Bédarieux, 186 pages,
#: demande une minute.
DELAI_S = 600.0

#: Ce que PowerShell exécute. En ASCII seulement : un script sans BOM est lu
#: en cp1252 par PowerShell 5 (on l'écrit tout de même avec BOM).
_SCRIPT = r"""
param([string]$Chemin)
# Calcule les numeros de page des sommaires d'un document, puis l'enregistre.
# Ecrit "SOMMAIRES <n>" si c'est fait, "ERREUR <message>" sinon.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$word = $null; $doc = $null; $avant = 0; $visible = $true; $code = 0
function Texte($doc) {
    $t = ''
    foreach ($x in $doc.TablesOfContents) { $t += $x.Range.Text }
    foreach ($x in $doc.TablesOfFigures) { $t += $x.Range.Text }
    $t
}
try {
    $word = New-Object -ComObject Word.Application
    # Une instance que l'utilisateur aurait deja ouverte n'est pas refermee.
    $avant = $word.Documents.Count
    $visible = $word.Visible
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($Chemin, $false, $false, $false)
    $doc.ActiveWindow.View.Type = 3
    # Remplir : les numeros sont alors ceux d'avant le remplissage...
    foreach ($x in $doc.TablesOfContents) { $x.Update() }
    foreach ($x in $doc.TablesOfFigures) { $x.Update() }
    # ...puis les remettre d'aplomb, jusqu'a ce qu'ils ne bougent plus.
    $precedent = Texte $doc
    for ($i = 0; $i -lt 3; $i++) {
        foreach ($x in $doc.TablesOfContents) { $x.UpdatePageNumbers() }
        foreach ($x in $doc.TablesOfFigures) { $x.UpdatePageNumbers() }
        $texte = Texte $doc
        if ($texte -eq $precedent) { break }
        $precedent = $texte
    }
    $doc.Save()
    'SOMMAIRES ' + ($doc.TablesOfContents.Count + $doc.TablesOfFigures.Count)
}
catch {
    'ERREUR ' + $_.Exception.Message
    $code = 1
}
finally {
    if ($doc) { $doc.Close(0) }
    if ($word) {
        # Quitter sans rien enregistrer : ni le document, deja ferme, ni le
        # modele Normal.
        if ($avant -eq 0 -and -not $visible) { $word.Quit([ref]0) }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
}
exit $code
"""

_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def calculer(chemin: Path, delai_s: float = DELAI_S) -> str | None:
    """Fait calculer par Word les numéros de page des sommaires de `chemin`.

    Renvoie None quand c'est fait, sinon ce qui en a empêché Word. Le document
    n'est remplacé qu'en cas de succès. Sinon, il reste tel que l'outil l'a
    écrit, avec à la place des sommaires la consigne pour les calculer.
    """
    chemin = Path(chemin)
    if sys.platform != "win32":
        return "Word ne s'automatise que sous Windows."
    with tempfile.TemporaryDirectory(prefix="prediag_sommaires_",
                                     ignore_cleanup_errors=True) as dossier:
        # Word travaille sur une copie locale. Sous OneDrive, il passerait en
        # enregistrement automatique ; et un échec laisserait l'original à
        # moitié écrit.
        copie = Path(dossier) / "document.docx"
        shutil.copyfile(chemin, copie)
        script = Path(dossier) / "sommaires.ps1"
        script.write_text(_SCRIPT, encoding="utf-8-sig")
        debut = datetime.now()
        try:
            fin = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Chemin", str(copie)],
                capture_output=True, timeout=delai_s,
                creationflags=_SANS_FENETRE)
        except subprocess.TimeoutExpired:
            _arreter_word_lance_apres(debut)
            return (f"Word n'avait pas fini au bout de {delai_s / 60:.0f} min ; "
                    "il a été arrêté.")
        except OSError as erreur:
            return f"PowerShell n'a pas pu être lancé ({erreur})."
        sortie = _texte(fin.stdout)
        if fin.returncode != 0 or "SOMMAIRES" not in sortie:
            return "Word n'a pas pu les calculer : " + _raison(
                sortie, _texte(fin.stderr), fin.returncode)
        shutil.copyfile(copie, chemin)
    return None


def _texte(flux) -> str:
    if isinstance(flux, bytes):
        return flux.decode("utf-8", errors="replace")
    return flux or ""


def _raison(sortie: str, erreurs: str, code: int) -> str:
    """La ligne qui dit pourquoi : celle du script, sinon celle de PowerShell."""
    for ligne in sortie.splitlines():
        if ligne.startswith("ERREUR "):
            return ligne[len("ERREUR "):].strip()
    for ligne in erreurs.splitlines():
        if ligne.strip():
            return ligne.strip()
    return f"PowerShell s'est arrêté sur le code {code}."


def _arreter_word_lance_apres(debut: datetime) -> None:
    """Arrête le Word sans fenêtre lancé pour le calcul, s'il s'est figé.

    Un Word lancé par COM ne dépend pas de PowerShell : arrêter PowerShell
    le laisse tourner, invisible, avec le document verrouillé. On arrête donc
    les Word d'automatisation (« /Automation ») apparus depuis `debut`, et
    jamais celui que l'utilisateur a ouvert lui-même.
    """
    depuis = (debut - timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%S")
    commande = (
        "Get-CimInstance Win32_Process -Filter \"Name='WINWORD.EXE'\" | "
        "Where-Object { $_.CommandLine -match '/Automation' -and "
        f"$_.CreationDate -ge [datetime]'{depuis}' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", commande],
                       capture_output=True, timeout=60,
                       creationflags=_SANS_FENETRE)
    except (OSError, subprocess.SubprocessError):
        pass
