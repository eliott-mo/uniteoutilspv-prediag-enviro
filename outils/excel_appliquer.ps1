# -*- coding: utf-8 -*-
<#
Applique aux classeurs UNITe les plans de modification préparés par
outils/enrichir_classeurs.py — par Excel lui-même, pour ne rien perdre de ce
qu'une bibliothèque Python ne sait pas relire : commentaires, mises en forme
conditionnelles, valeurs calculées des formules de « Saisie étude ».

    powershell -NoProfile -ExecutionPolicy Bypass -File excel_appliquer.ps1 -Plans plans.json

Chaque plan désigne une COPIE de travail : ce script n'ouvre jamais un
classeur de référence en écriture. Un plan qui échoue laisse sa copie
intacte : le classeur est refermé sans être enregistré.
#>
param([Parameter(Mandatory = $true)][string]$Plans, [string]$Journal = "")
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Pas de « $plans » : PowerShell ignore la casse, et cette variable serait
# le paramètre $Plans, typé [string] — la liste y deviendrait une chaîne.
$liste = Get-Content -Raw -Encoding UTF8 $Plans | ConvertFrom-Json

# La virgule empêche PowerShell de « dérouler » la plage en tableau de
# cellules : une plage Excel est énumérable.
function Cellule($ws, $l, $c) { return ,$ws.Cells.Item([int]$l, [int]$c) }
function Plage($ws, $l1, $c1, $l2, $c2) { return ,$ws.Range((Cellule $ws $l1 $c1), (Cellule $ws $l2 $c2)) }
function Commenter($cellule, [string]$texte) {
    if ($null -ne $cellule.Comment) {
        [void]$cellule.Comment.Text($cellule.Comment.Text() + "`n" + $texte)
    } else {
        [void]$cellule.AddComment($texte)
        $cellule.Comment.Shape.TextFrame.AutoSize = $true
    }
}
function Ecrire($cellule, $m) {
    try {
        if ($m.PSObject.Properties.Name -contains 'formule' -and $m.formule) { $cellule.Formula = [string]$m.formule }
        elseif ($m.valeur -is [int] -or $m.valeur -is [long] -or $m.valeur -is [double]) { $cellule.Value2 = [double]$m.valeur }
        else { $cellule.Value2 = [string]$m.valeur }
    } catch {
        throw ("écriture de " + $cellule.Address(0, 0) + " (" + $cellule.Worksheet.Name + ") : " + $_.Exception.Message)
    }
}
# Une même instruction « .Value2 = $v » se fige sur le type de la première
# valeur qu'elle reçoit : PowerShell refuse ensuite une valeur d'un autre type
# (« Impossible d'effectuer un cast d'un objet de type 'System.Double' en type
# 'System.String' »). Le suivi d'une seule ligne, date puis textes, échouait
# ainsi le 6 novembre 2026. Chaque type a donc son affectation : celles d'Ecrire.
function Poser($cellule, $v) { Ecrire $cellule ([pscustomobject]@{ valeur = $v }) }

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.ScreenUpdating = $false
$xl.EnableEvents = $false; $xl.AskToUpdateLinks = $false
$echecs = 0
function Noter([string]$texte) {
    # Un journal qu'on lit pendant qu'il s'écrit ne doit pas faire échouer l'étape.
    if ($Journal) { try { Add-Content -Path $Journal -Encoding UTF8 -Value ((Get-Date).ToString('HH:mm:ss') + '  ' + $texte) } catch { } }
}
try {
    foreach ($p in $liste) {
        $wb = $null
        try {
            $wb = $xl.Workbooks.Open($p.cible, 0, $false)
            # Dans un dossier OneDrive, Office enregistre chaque modification à
            # mesure : sans cela, un plan qui échoue laisserait sa copie à moitié
            # modifiée.
            try { $wb.AutoSaveOn = $false } catch { }

            Noter ('1 cellules · ' + $p.groupe)
            # 1. Corrections et compléments, sur la disposition d'origine
            foreach ($m in $p.cellules) {
                $c = Cellule $wb.Worksheets.Item($m.feuille) $m.ligne $m.colonne
                Ecrire $c $m
                if ($m.commentaire) { Commenter $c $m.commentaire }
            }

            Noter ('2 colonnes de Statuts · ' + $p.groupe)
            # 2. Colonnes ajoutées à Statuts : formats du modèle, puis valeurs du bloc
            $s = $p.statuts
            $st = $wb.Worksheets.Item($s.feuille)
            # Pas de $n et $N : PowerShell ignore la casse, ce serait la même
            # variable — le nombre de lignes devenait le nombre de colonnes.
            $nc = [int]$s.n; $nl = [int]$s.lignes; $d = [int]$s.depart; $f = $d + $nc - 1
            if ($nc -gt 0) {
                $modele = Plage $st 1 $s.modele $nl $s.modele
                for ($c = $d; $c -le $f; $c++) {
                    [void]$modele.Copy((Plage $st 1 $c $nl $c))
                    $st.Columns.Item($c).ColumnWidth = $st.Columns.Item([int]$s.modele).ColumnWidth
                }
                $bloc = Plage $st 1 $d $nl $f
                [void]$bloc.ClearComments()
                if (-not $s.garder_mfc) { [void]$bloc.FormatConditions.Delete() }
                # Les valeurs viennent du plan, cellules non vides seulement. Un
                # classeur intermédiaire s'ouvrait en mode protégé, sans objet rendu.
                $tableau = New-Object 'object[,]' $nl, $nc
                for ($j = 0; $j -lt $nc; $j++) { $tableau[0, $j] = [string]$s.entetes[$j] }
                foreach ($v in $s.valeurs) { $tableau[([int]$v[0] - 1), [int]$v[1]] = $v[2] }
                $bloc.Value2 = $tableau
                foreach ($e in $s.commentaires) { Commenter (Cellule $st 1 $e[0]) ([string]$e[1]) }
                if ($s.filtre) { $st.AutoFilterMode = $false; [void]$st.Range([string]$s.filtre).AutoFilter() }
            }

            Noter ('3 tables · ' + $p.groupe)
            # 3. Tables de correspondance (la « Région d'étude » des amphibiens-reptiles)
            foreach ($t in $p.tables) {
                $ws = $wb.Worksheets.Item($t.feuille)
                if ($t.titre) { (Cellule $ws ($t.ligne - 1) $t.colonne).Value2 = [string]$t.titre }
                for ($i = 0; $i -lt $t.valeurs.Count; $i++) {
                    for ($j = 0; $j -lt $t.valeurs[$i].Count; $j++) {
                        Poser (Cellule $ws ($t.ligne + $i) ($t.colonne + $j)) $t.valeurs[$i][$j]
                    }
                }
            }

            Noter ('4 saisie · ' + $p.groupe)
            # 4. Colonnes insérées dans « Saisie étude »
            $sa = $p.saisie
            if ($null -ne $sa -and [int]$sa.n -gt 0) {
                $ws = $wb.Worksheets.Item($sa.feuille)
                $k = [int]$sa.n; $a = [int]$sa.avant
                [void](Plage $ws 1 $a 1 ($a + $k - 1)).EntireColumn.Insert()
                $modele = Plage $ws $sa.premiere $sa.modele $sa.derniere $sa.modele
                for ($j = 0; $j -lt $k; $j++) {
                    $c = $a + $j
                    [void]$modele.Copy((Plage $ws $sa.premiere $c $sa.derniere $c))
                    $ws.Columns.Item($c).ColumnWidth = $ws.Columns.Item([int]$sa.modele).ColumnWidth
                    $dcl = $sa.declarations[$j]
                    $lignes = @([int]$sa.ligne_index, ([int]$sa.ligne_index + 1), ([int]$sa.ligne_index + 2))
                    for ($r = 0; $r -lt 3; $r++) {
                        $source = $sa.formats[$r]
                        $cible = Cellule $ws $lignes[$r] $c
                        if ($null -ne $source) { [void](Cellule $ws $source[0] $source[1]).Copy($cible) }
                        Ecrire $cible $dcl[$r]
                    }
                }
                foreach ($r in $sa.remplacements) {
                    [void]$ws.UsedRange.Replace([string]$r[0], [string]$r[1], 2, 1, $false)
                }
            }

            Noter ('5 journaux · ' + $p.groupe)
            # 5. Lignes ajoutées : « Textes de référence », « Suivi modifs statuts »
            foreach ($aj in $p.ajouts) {
                $ws = $wb.Worksheets.Item($aj.feuille)
                $k = [int]$aj.colonnes; $last = 1
                for ($c = 1; $c -le $k; $c++) {
                    $r = $ws.Cells.Item($ws.Rows.Count, $c).End(-4162).Row
                    if ($r -gt $last) { $last = $r }
                }
                for ($i = 0; $i -lt $aj.lignes.Count; $i++) {
                    $r = $last + 1 + $i
                    [void](Plage $ws $last 1 $last $k).Copy((Plage $ws $r 1 $r $k))
                    for ($j = 0; $j -lt $k; $j++) {
                        $v = $aj.lignes[$i][$j]
                        if ($j -eq ([int]$aj.colonne_date - 1) -and $v) {
                            $v = ([datetime]::ParseExact([string]$v, 'yyyy-MM-dd', $null)).ToOADate()
                        }
                        Poser (Cellule $ws $r ($j + 1)) $v
                    }
                }
            }

            Noter ('6 calcul · ' + $p.groupe)
            $xl.CalculateFull()
            Noter ('7 enregistrement · ' + $p.groupe)
            $wb.Save()
            $wb.Close($false); $wb = $null
            Write-Output ("OK      " + $p.cible)
            Noter ('fini · ' + $p.groupe)
        } catch {
            $echecs++
            Write-Output ("ÉCHEC   " + $p.cible + " : " + $_.Exception.Message + " (ligne " + $_.InvocationInfo.ScriptLineNumber + ")")
            if ($null -ne $wb) { $wb.Close($false) }
        }
    }
} finally {
    $xl.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
exit $echecs
