# -*- coding: utf-8 -*-
<#
Éprouve la saisie des classeurs modifiés comme la responsable environnement
s'en sert : sur une copie jetable, un nom d'espèce est tapé dans « Saisie
étude », Excel recalcule, et chaque cellule lue est comparée à l'attendu.
Rien n'est enregistré ; la copie est supprimée.

    powershell -NoProfile -ExecutionPolicy Bypass -File excel_eprouver_saisie.ps1 -Essais essais.json
#>
param([Parameter(Mandatory = $true)][string]$Essais)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$liste = Get-Content -Raw -Encoding UTF8 $Essais | ConvertFrom-Json
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.ScreenUpdating = $false; $xl.EnableEvents = $false
$ecarts = 0
try {
    foreach ($e in $liste) {
        Copy-Item $e.fichier $e.copie -Force
        $wb = $xl.Workbooks.Open($e.copie, 0, $false)
        try { $wb.AutoSaveOn = $false } catch { }
        try {
            $ws = $wb.Worksheets.Item($e.feuille)
            foreach ($s in $e.saisies) { $ws.Cells.Item([int]$s[0], [int]$s[1]).Value2 = [string]$s[2] }
            $xl.CalculateFull()
            $ok = 0
            foreach ($l in $e.lectures) {
                $lu = [string]$ws.Cells.Item([int]$l[0], [int]$l[1]).Text
                if ($lu -eq [string]$l[2]) { $ok++ } else {
                    $ecarts++
                    Write-Output ("   ✗ " + $e.nom + " " + $ws.Cells.Item([int]$l[0], [int]$l[1]).Address(0, 0) + " : « " + $lu + " » au lieu de « " + $l[2] + " »")
                }
            }
            Write-Output ("{0} : {1}/{2} cellules de saisie conformes" -f $e.nom, $ok, $e.lectures.Count)
        } finally {
            $wb.Close($false)
            Remove-Item $e.copie -Force -ErrorAction SilentlyContinue
        }
    }
} finally {
    $xl.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
exit $ecarts
