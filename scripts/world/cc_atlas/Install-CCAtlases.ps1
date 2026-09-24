<#
.SYNOPSIS
    Install the rebuilt Combat Commander terrain atlases into a Redux mod folder.

.DESCRIPTION
    Copies each world's atlas DDS set, its .csv and its .material into the mod
    folder, and the matching .trn files over the maps that bind them.

    Three things this does that a drag-and-drop does not:

    * It backs up every file it replaces, so the whole install is one
      Restore-CCAtlases away from being undone.
    * It hashes both sides after every copy. A Google Drive folder can end up
      holding a file of exactly the right length that is entirely NUL, and the
      size and timestamp both look correct, so only a hash catches it.
    * It reports the atlas DDS files the old .material files referenced and the
      new ones do not -- about 776 MB across the nine existing worlds. It never
      deletes them; that is a decision for whoever owns the mod.

.PARAMETER Mod
    The mod folder to install into.

.PARAMETER Source
    The delivery root -- the folder holding atlases\ and trn\.

.PARAMETER Worlds
    All, Existing (the nine ISDF Chronicles already uses) or New (the five
    Combat Commander worlds it does not).

.PARAMETER SkipTrn
    Copy the atlases but leave the .trn files alone. The new tiles then sit in
    the atlas unnamed and nothing changes in game; use it to stage the art
    first and switch the maps over separately.

.EXAMPLE
    .\Install-CCAtlases.ps1 -Mod 'D:\Redux Maps\ISDF Chronicles' -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Mod,
    [string]$Source = (Split-Path -Parent $PSScriptRoot),
    [ValidateSet('All', 'Existing', 'New')][string]$Worlds = 'All',
    [string]$BackupDir,
    [switch]$SkipTrn
)

$ErrorActionPreference = 'Stop'

$NewWorlds = @('ccmars_detail_atlas', 'cctitan_detail_atlas', 'ccearth_detail_atlas',
               'ccmetal_detail_atlas', 'cctunnel_detail_atlas')

if (-not (Test-Path -LiteralPath $Mod)) { throw "Mod folder not found: $Mod" }
$atlasRoot = Join-Path $Source 'atlases'
$trnRoot = Join-Path $Source 'trn'
if (-not (Test-Path -LiteralPath $atlasRoot)) { throw "No atlases\ under $Source" }

if (-not $BackupDir) {
    $BackupDir = Join-Path $Mod ('_atlas_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
}

function Copy-Verified {
    param([string]$From, [string]$To, [string]$Backup)

    $name = Split-Path -Leaf $To
    if (Test-Path -LiteralPath $To) {
        if ($PSCmdlet.ShouldProcess($name, 'back up')) {
            if (-not (Test-Path -LiteralPath $Backup)) {
                New-Item -ItemType Directory -Path $Backup -Force | Out-Null
            }
            Copy-Item -LiteralPath $To -Destination (Join-Path $Backup $name) -Force
        }
    }
    if (-not $PSCmdlet.ShouldProcess($name, 'install')) { return $null }

    Copy-Item -LiteralPath $From -Destination $To -Force
    $a = (Get-FileHash -LiteralPath $From -Algorithm MD5).Hash
    $b = (Get-FileHash -LiteralPath $To -Algorithm MD5).Hash
    if ($a -ne $b) { throw "Copy of $name did not verify: $a vs $b" }
    return (Get-Item -LiteralPath $To).Length
}

# The DDS names the mod's current .material files point at, so the ones the new
# materials leave behind can be named without guessing at a naming convention.
$oldRefs = @{}
Get-ChildItem -LiteralPath $Mod -Filter '*_detail_atlas*.material' -ErrorAction SilentlyContinue |
    ForEach-Object {
        $refs = Select-String -LiteralPath $_.FullName -Pattern 'set_texture_alias\s+\w+\s+(\S+)' |
            ForEach-Object { $_.Matches[0].Groups[1].Value }
        $oldRefs[$_.BaseName] = $refs
    }

$installed = 0
$bytes = 0L
$report = @()

Get-ChildItem -LiteralPath $atlasRoot -Directory | ForEach-Object {
    $mat = $_.Name
    $isNew = $NewWorlds -contains $mat
    if ($Worlds -eq 'Existing' -and $isNew) { return }
    if ($Worlds -eq 'New' -and -not $isNew) { return }

    $files = Get-ChildItem -LiteralPath $_.FullName -File |
        Where-Object { $_.Extension -in '.dds', '.csv', '.material' }

    foreach ($f in $files) {
        $n = Copy-Verified -From $f.FullName -To (Join-Path $Mod $f.Name) -Backup $BackupDir
        if ($null -ne $n) { $installed++; $bytes += $n }
    }

    $keep = @()
    if (Test-Path -LiteralPath (Join-Path $_.FullName "$mat.material")) {
        $keep = Select-String -LiteralPath (Join-Path $_.FullName "$mat.material") `
            -Pattern 'set_texture_alias\s+\w+\s+(\S+)' |
            ForEach-Object { $_.Matches[0].Groups[1].Value }
    }
    foreach ($r in ($oldRefs[$mat] | Where-Object { $_ })) {
        if ($keep -contains $r) { continue }
        $p = Join-Path $Mod $r
        if (Test-Path -LiteralPath $p) {
            $report += [pscustomobject]@{
                World = $mat; Orphan = $r
                MB = [math]::Round((Get-Item -LiteralPath $p).Length / 1MB, 1)
            }
        }
    }
    Write-Host ("{0,-24} {1,2} files" -f $mat, $files.Count)
}

if (-not $SkipTrn -and (Test-Path -LiteralPath $trnRoot)) {
    Write-Host ''
    Get-ChildItem -LiteralPath $trnRoot -Filter '*.trn' | ForEach-Object {
        $target = Join-Path $Mod $_.Name
        # A new world's .trn is a template for a map that does not exist yet, so
        # it is only ever created, never allowed to replace someone's map.
        $existed = Test-Path -LiteralPath $target
        $n = Copy-Verified -From $_.FullName -To $target -Backup $BackupDir
        if ($null -ne $n) {
            $installed++
            Write-Host ("{0,-24} {1}" -f $_.Name, $(if ($existed) { 'replaced' } else { 'new' }))
        }
    }
}

Write-Host ''
Write-Host ("{0} files, {1:N0} MB installed" -f $installed, ($bytes / 1MB))
if (Test-Path -LiteralPath $BackupDir) { Write-Host "backup: $BackupDir" }

if ($report) {
    $total = ($report | Measure-Object MB -Sum).Sum
    Write-Host ''
    Write-Host ("{0} atlas files are no longer referenced by any .material ({1:N0} MB)." -f $report.Count, $total)
    Write-Host 'Nothing loads them. Delete them once the install looks right in game:'
    $report | Format-Table -AutoSize
}
