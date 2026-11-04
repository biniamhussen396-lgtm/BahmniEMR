# =====================================================================
#  Bahmni & OpenELIS Implementation Portal - permanent supervisor
#
#  Started at every logon by:
#    %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
#        BahmniImplementationPortal.vbs   (hidden, no console window)
#
#  Behaviour:
#    * Idempotent - exits cleanly if port 8001 is already served
#    * Keeps implementation_service.py alive: crashes are restarted
#      after 10 s, forever, without manual intervention
#    * Two log files on purpose (they are never written concurrently):
#        implementation_portal.log         - supervisor lifecycle
#        implementation_portal.app.log     - portal stdout/stderr
#      Both rotate at 5 MB, keeping one history file (*.log.1)
#
#  NOTE: $ErrorActionPreference is deliberately NOT "SilentlyContinue"
#  here - silent failures previously hid supervisor messages while the
#  portal held an exclusive write handle on the shared log file.
# =====================================================================

$ServiceDir = "C:\Users\COMPUTER\Documents\emr\bahmni-docker\bahmni-standard"
$PythonExe  = "C:\Users\COMPUTER\AppData\Local\Programs\Python\Python312\python.exe"
$Service    = Join-Path $ServiceDir "implementation_service.py"
$LogDir     = "C:\Users\COMPUTER\Documents\emr\logs"
$SupLog     = Join-Path $LogDir "implementation_portal.log"        # supervisor only
$AppLog     = Join-Path $LogDir "implementation_portal.app.log"    # portal output only
$RestartDelaySeconds = 10
$MaxLogBytes = 5MB

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    # Supervisor owns $SupLog exclusively, but guard anyway: a failed
    # write must never be silent - surface it on stderr and fall back.
    try {
        [System.IO.File]::AppendAllText($SupLog, $line + [Environment]::NewLine)
    } catch {
        Write-Error "supervisor: could not write to ${SupLog}: $($_.Exception.Message)"
        try { [System.IO.File]::AppendAllText("$SupLog.fallback", $line + [Environment]::NewLine) } catch { }
    }
}

function Rotate-LogFile([string]$path) {
    try {
        if ((Test-Path $path) -and ((Get-Item $path).Length -gt $MaxLogBytes)) {
            Move-Item -Path $path -Destination "$path.1" -Force
        }
    } catch {
        Write-Error "supervisor: log rotation failed for ${path}: $($_.Exception.Message)"
    }
}

function Test-PortalPort {
    # An empty result means "not listening"; a real error still surfaces
    # because -ErrorAction only suppresses the "no match" case here.
    $c = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue |
         Select-Object -First 1
    return [bool]$c
}

# --- sanity checks ----------------------------------------------------
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# --- idempotency: another instance already owns port 8001 ------------
if (Test-PortalPort) {
    Write-Log "supervisor: port 8001 already served by another instance - nothing to do, exiting"
    exit 0
}

if (-not (Test-Path $Service)) {
    Write-Log "supervisor: FATAL - service script not found: $Service"
    exit 2
}
if (-not (Test-Path $PythonExe)) {
    Write-Log "supervisor: FATAL - python not found: $PythonExe"
    exit 2
}

Write-Log "supervisor: started (pid $PID) - keeping implementation_service.py alive on port 8001"

# --- supervision loop -------------------------------------------------
while ($true) {
    Rotate-LogFile $SupLog
    Rotate-LogFile $AppLog
    Write-Log "supervisor: launching implementation_service.py"

    # cmd.exe redirection appends raw bytes of stdout/stderr to $AppLog
    # and blocks until the portal exits; $SupLog stays supervisor-owned.
    & cmd.exe /c "`"$PythonExe`" `"$Service`" >> `"$AppLog`" 2>&1"
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = -1 }

    Write-Log ("supervisor: implementation_service.py exited (code {0})" -f $code)

    # If something else took over the port (e.g. a second supervisor),
    # stand down instead of fighting for the port.
    if (Test-PortalPort) {
        Write-Log "supervisor: port 8001 is served by another instance - standing down"
        exit 0
    }

    Write-Log ("supervisor: restarting portal in {0}s" -f $RestartDelaySeconds)
    Start-Sleep -Seconds $RestartDelaySeconds
}
