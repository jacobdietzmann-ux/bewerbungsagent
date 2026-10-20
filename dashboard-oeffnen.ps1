<#
    Bewerbungsagent-Dashboard unter Windows starten.

    Windows-Ersatz fuer dashboard-oeffnen.sh:
      - startet ggf. server.py (venv des Agents)
      - wartet auf http://127.0.0.1:8766/healthz
      - oeffnet das Dashboard im Standardbrowser
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$Here        = Split-Path -Parent $MyInvocation.MyCommand.Path
# Dieser Launcher liegt in 00_Dashboard; der Server und seine Daten in 04_Agent.
$AgentDir    = Join-Path (Split-Path -Parent $Here) '04_Agent'
$Url         = 'http://127.0.0.1:8766/00_Dashboard/dashboard.html'
$HealthUrl   = 'http://127.0.0.1:8766/healthz'
$DataDir     = Join-Path $AgentDir 'data'
$LauncherLog = Join-Path $DataDir 'launcher.log'
$ServerOut   = Join-Path $DataDir 'server.log'
$ServerErr   = Join-Path $DataDir 'server.err.log'

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-LauncherLog([string]$Line) {
    try {
        Add-Content -LiteralPath $LauncherLog -Encoding UTF8 `
            -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'), $Line)
    } catch { }
}

Write-LauncherLog 'Launcher gestartet'

# Python-Interpreter des Agents finden.
$Venv = Join-Path $env:USERPROFILE '.venvs\bewerbungsagent\Scripts\python.exe'
if (Test-Path -LiteralPath $Venv) {
    $Py = $Venv
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Py = $cmd.Source } else { $Py = $null }
}

if (-not $Py) {
    Write-LauncherLog 'FEHLER: Python 3 wurde nicht gefunden.'
    Write-Error 'Python 3 wurde nicht gefunden.'
    exit 1
}

function Test-Healthy {
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (-not (Test-Healthy)) {
    Write-LauncherLog ("Serverstart angefordert: {0}" -f $Py)
    # Relativer Dateiname (nicht Join-Path): Start-Process quotet Leerzeichen im
    # Argument nicht, und der Pfad enthält Leerzeichen ("Meine Ablage").
    Start-Process -FilePath $Py -ArgumentList @('server.py') `
        -WorkingDirectory $AgentDir -WindowStyle Hidden `
        -RedirectStandardOutput $ServerOut -RedirectStandardError $ServerErr
    Start-Sleep -Milliseconds 500
}

$ready = $false
for ($i = 0; $i -lt 50; $i++) {
    if (Test-Healthy) { $ready = $true; break }
    Start-Sleep -Milliseconds 200
}

if (-not $ready) {
    Write-LauncherLog ("FEHLER: Dashboard-Server nicht erreichbar. Siehe {0} / {1}" -f $ServerOut, $ServerErr)
    Write-Error ("Dashboard-Server wurde nicht erreichbar. Siehe {0}" -f $ServerOut)
    exit 1
}

Start-Process $Url
Write-LauncherLog ("Browser geoeffnet: {0}" -f $Url)
