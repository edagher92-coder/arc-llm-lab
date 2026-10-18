# qwen-lock.ps1 - one Qwen job at a time on ELZYDLAB (18 Oct 2026).
# The single llama-server slot is shared: two jobs interleave requests and each runs at about half speed.
# Lock file: C:\AI\locks\qwen-engine.lock  (JSON: pid, kind, started, note)
#   acquire -Kind codex|claude|runner|bench|other -HolderPid <pid> [-WaitS 600] [-Note text]
#       waits while another LIVE holder owns the lock (status line to stderr every ~30 s); exit 0 = acquired,
#       exit 3 = still busy after WaitS. A holder is stale (lock taken over) when its PID is dead, or, for kind
#       codex, when it is older than 60 s and no codex.exe/claude.exe runs under it (the launcher window outlived Codex).
#   release -HolderPid <pid>     removes the lock only if <pid> owns it
#   status                       prints the holder (or "free") and whether it is live
param(
    [Parameter(Position = 0)][ValidateSet('acquire', 'release', 'status')][string]$Action = 'status',
    [string]$Kind = 'other',
    [int]$HolderPid = 0,
    [int]$WaitS = 600,
    [string]$Note = ''
)
$ErrorActionPreference = 'Stop'
$LockPath = 'C:\AI\locks\qwen-engine.lock'

function Read-Lock {
    if (-not (Test-Path $LockPath)) { return $null }
    try { $l = Get-Content $LockPath -Raw | ConvertFrom-Json; if ($l -and $l.pid) { return $l } } catch {}
    # empty or half-written: another acquirer is writing it right now (CreateNew, then write) - treat as live for 10 s
    return [pscustomobject]@{ pid = 0; kind = 'writing'; started = (Get-Item $LockPath).LastWriteTime.ToString('s') }
}

function Test-Live($lock) {
    if ($lock -and $lock.kind -eq 'writing') { try { return (((Get-Date) - [datetime]$lock.started).TotalSeconds -lt 10) } catch { return $false } }
    if (-not $lock -or -not $lock.pid) { return $false }
    if (-not (Get-Process -Id ([int]$lock.pid) -ErrorAction SilentlyContinue)) { return $false }
    $exe = @{ codex = 'codex.exe'; claude = 'claude.exe' }[[string]$lock.kind]
    if (-not $exe) { return $true }
    $age = 0
    try { $age = ((Get-Date) - [datetime]$lock.started).TotalSeconds } catch { $age = 9999 }
    if ($age -lt 60) { return $true }
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
        if ($l -and [int]$l.pid -eq $HolderPid) { Remove-Item $LockPath -Force -ErrorAction SilentlyContinue }
        exit 0
    }
    'acquire' {
        if ($HolderPid -le 0) { [Console]::Error.WriteLine('qwen-lock: -HolderPid required'); exit 2 }
        New-Item -ItemType Directory -Force (Split-Path $LockPath) | Out-Null
        $t0 = Get-Date; $lastSaid = -999
        while ($true) {
            $l = Read-Lock
            if ($l -and [int]$l.pid -eq $HolderPid) { exit 0 }                   # already ours
            if ($l -and -not (Test-Live $l)) { Remove-Item $LockPath -Force -ErrorAction SilentlyContinue; $l = $null }
            if (-not $l) {
                $json = ([pscustomobject]@{ pid = $HolderPid; kind = $Kind; started = (Get-Date).ToString('s'); note = $Note } | ConvertTo-Json -Compress)
                try {
                    $fs = [IO.File]::Open($LockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                    $bytes = [Text.Encoding]::UTF8.GetBytes($json); $fs.Write($bytes, 0, $bytes.Length); $fs.Close()
                    exit 0
                } catch [System.IO.IOException] { continue }                      # lost a race: re-read
            }
            $el = [int]((Get-Date) - $t0).TotalSeconds
            if ($el -ge $WaitS) { [Console]::Error.WriteLine("qwen-lock: Qwen still busy after ${el}s: $(Describe $l)"); exit 3 }
            if ($el - $lastSaid -ge 30) { [Console]::Error.WriteLine("qwen-lock: waiting for Qwen - in use by $(Describe $l) (${el}s)"); $lastSaid = $el }
            Start-Sleep -Seconds 3
        }
    }
}



