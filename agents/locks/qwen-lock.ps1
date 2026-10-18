# qwen-lock.ps1 - one Qwen job at a time on ELZYDLAB (18 Oct 2026; hardened 18 Oct 23:30 after a code review).
# The single llama-server slot is shared: two jobs interleave requests and each runs at about half speed.
# Lock file: C:\AI\locks\qwen-engine.lock  (JSON: pid, pstart, kind, started, grace, note)
#   acquire -Kind codex|claude|runner|bench|other -HolderPid <pid> [-WaitS 600] [-Note text]
#       waits while another LIVE holder owns the lock (status line to stderr every ~30 s); exit 0 = acquired,
#       exit 3 = still busy after WaitS. A holder is stale (lock taken over) when its PID is dead, when the PID now
#       belongs to a different process (start time differs: PID reuse), or, for kinds codex/claude, when it is older than
#       its grace (WaitS + 120 s, so the launcher's own slot wait is covered) and no codex.exe/claude.exe runs under it.
#   release -HolderPid <pid>     removes the lock only if <pid> owns it
#   status                       prints the holder (or "free") and whether it is live
# A stale lock is removed only if the file still holds exactly what was judged stale (compare-and-delete under an
# exclusive handle), so two waiters cannot both take over and delete each other's fresh lock.
param(
    [Parameter(Position = 0)][ValidateSet('acquire', 'release', 'status')][string]$Action = 'status',
    [string]$Kind = 'other',
    [int]$HolderPid = 0,
    [int]$WaitS = 600,
    [string]$Note = ''
)
$ErrorActionPreference = 'Stop'
$LockPath = 'C:\AI\locks\qwen-engine.lock'
if ($env:QWEN_LOCK_PATH) { $LockPath = $env:QWEN_LOCK_PATH }   # tests only (test-qwen-lock.ps1)

function Read-LockRaw {
    try {
        $fs = [IO.File]::Open($LockPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        try { return (New-Object IO.StreamReader($fs)).ReadToEnd() } finally { $fs.Dispose() }
    } catch [System.IO.FileNotFoundException] { return $null }
    catch [System.IO.DirectoryNotFoundException] { return $null }
    catch { return '' }   # held exclusively for a moment (being written or removed): treat like a half-written file
}

function Read-Lock {
    if (-not (Test-Path $LockPath)) { return $null }
    $raw = Read-LockRaw
    if ($null -eq $raw) { return $null }
    try { $l = $raw | ConvertFrom-Json; if ($l -and $l.pid) { $l | Add-Member -NotePropertyName raw -NotePropertyValue $raw -Force; return $l } } catch {}
    # empty or half-written: another acquirer is writing it right now (CreateNew, then write) - treat as live for 10 s
    $when = (Get-Date).ToString('s'); try { $when = (Get-Item $LockPath).LastWriteTime.ToString('s') } catch {}
    return [pscustomobject]@{ pid = 0; kind = 'writing'; started = $when; raw = $raw }
}

function Get-StartStamp([int]$id) {
    try { return (Get-Process -Id $id -ErrorAction Stop).StartTime.ToUniversalTime().ToString('o') } catch { return $null }
}

function Test-Live($lock) {
    if ($lock -and $lock.kind -eq 'writing') { try { return (((Get-Date) - [datetime]$lock.started).TotalSeconds -lt 10) } catch { return $false } }
    if (-not $lock -or -not $lock.pid) { return $false }
    if (-not (Get-Process -Id ([int]$lock.pid) -ErrorAction SilentlyContinue)) { return $false }
    if ($lock.pstart) { $now = Get-StartStamp ([int]$lock.pid); if ($now -and $now -ne [string]$lock.pstart) { return $false } }   # PID reused
    $exe = @{ codex = 'codex.exe'; claude = 'claude.exe' }[[string]$lock.kind]
    if (-not $exe) { return $true }
    $age = 0
    try { $age = ((Get-Date) - [datetime]$lock.started).TotalSeconds } catch { $age = 99999 }
    $grace = 60; if ($lock.grace) { $grace = [int]$lock.grace }
    if ($age -lt $grace) { return $true }
    # Agent launcher (codex-qwen / claude-qwen): live only while its agent exe runs somewhere under it.
    $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name
    $kids = @{}
    foreach ($p in $all) { $k = [int]$p.ParentProcessId; if (-not $kids[$k]) { $kids[$k] = @() }; $kids[$k] += $p }
    $queue = New-Object System.Collections.Queue; $queue.Enqueue([int]$lock.pid); $seen = @{}
    while ($queue.Count) {
        $id = $queue.Dequeue(); if ($seen[$id]) { continue }; $seen[$id] = $true
        foreach ($c in @($kids[$id])) { if (-not $c) { continue }; if ($c.Name -ieq $exe) { return $true }; $queue.Enqueue([int]$c.ProcessId) }
    }
    return $false
}

# Delete the lock only if it still holds exactly $expectRaw. The exclusive handle (sharing Delete only) stops anyone
# else from rewriting it between the comparison and the delete.
function Remove-LockIfUnchanged([string]$expectRaw) {
    try {
        $fs = [IO.File]::Open($LockPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Delete)
        try {
            $now = (New-Object IO.StreamReader($fs)).ReadToEnd()
            if ($now -eq $expectRaw) { [IO.File]::Delete($LockPath) }
        } finally { $fs.Dispose() }
    } catch {}
}

function Describe($lock) { "$($lock.kind) pid $($lock.pid) since $($lock.started)$(if ($lock.note) { " ($($lock.note))" })" }

switch ($Action) {
    'status' {
        $l = Read-Lock
        if (-not $l) { 'free'; exit 0 }
        if (Test-Live $l) { "busy: $(Describe $l)" } else { "stale: $(Describe $l)" }
        exit 0
    }
    'release' {
        $l = Read-Lock
        if ($l -and $l.pid -and [int]$l.pid -eq $HolderPid) { Remove-LockIfUnchanged $l.raw }
        exit 0
    }
    'acquire' {
        if ($HolderPid -le 0) { [Console]::Error.WriteLine('qwen-lock: -HolderPid required'); exit 2 }
        New-Item -ItemType Directory -Force (Split-Path $LockPath) | Out-Null
        $pstart = Get-StartStamp $HolderPid
        $t0 = Get-Date; $lastSaid = -999
        while ($true) {
            $l = Read-Lock
            if ($l -and $l.pid -and [int]$l.pid -eq $HolderPid -and (-not $l.pstart -or $l.pstart -eq $pstart)) { exit 0 }   # already ours
            if ($l -and -not (Test-Live $l)) { Remove-LockIfUnchanged $l.raw; $l = Read-Lock }
            if (-not $l) {
                $json = ([pscustomobject]@{ pid = $HolderPid; pstart = $pstart; kind = $Kind; started = (Get-Date).ToString('s'); grace = ($WaitS + 120); note = $Note } | ConvertTo-Json -Compress)
                try {
                    $fs = [IO.File]::Open($LockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                    $bytes = [Text.Encoding]::UTF8.GetBytes($json); $fs.Write($bytes, 0, $bytes.Length); $fs.Close()
                    exit 0
                } catch [System.IO.IOException] { continue }                      # lost a race: re-read
                catch [System.UnauthorizedAccessException] { Start-Sleep -Milliseconds 200; continue }   # file is delete-pending
            }
            $el = [int]((Get-Date) - $t0).TotalSeconds
            if ($el -ge $WaitS) { [Console]::Error.WriteLine("qwen-lock: Qwen still busy after ${el}s: $(Describe $l)"); exit 3 }
            if ($el - $lastSaid -ge 30) { [Console]::Error.WriteLine("qwen-lock: waiting for Qwen - in use by $(Describe $l) (${el}s)"); $lastSaid = $el }
            Start-Sleep -Seconds 3
        }
    }
}
