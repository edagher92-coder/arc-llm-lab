# Tests for qwen-lock.ps1 against a scratch lock file (never the live C:\AI\locks\qwen-engine.lock).
$ErrorActionPreference = 'Continue'   # the lock prints waiting lines on stderr; PS 5.1 would turn them into errors
$script = Join-Path $PSScriptRoot 'qwen-lock.ps1'
$dir = Join-Path $env:LOCALAPPDATA "Temp\qwen-lock-test-$PID"
New-Item -ItemType Directory -Force $dir | Out-Null
$env:QWEN_LOCK_PATH = Join-Path $dir 'test.lock'
$fails = 0
function Check($name, $ok) { if ($ok) { "ok   $name" } else { "FAIL $name"; $script:fails++ } }
function Lock { param([Parameter(ValueFromRemainingArguments = $true)]$a) & powershell -NoProfile -ExecutionPolicy Bypass -File $script @a 2>$null; return $LASTEXITCODE }
function Status { (& powershell -NoProfile -ExecutionPolicy Bypass -File $script status) | Select-Object -Last 1 }
function Put($obj) { [IO.File]::WriteAllText($env:QWEN_LOCK_PATH, ($obj | ConvertTo-Json -Compress)) }
$me = $PID
$meStart = (Get-Process -Id $me).StartTime.ToUniversalTime().ToString('o')
try {
    Check 'free at start' ((Status) -eq 'free')
    Check 'acquire free lock' ((Lock acquire -Kind runner -HolderPid $me -WaitS 5) -eq 0)
    Check 'status busy while holder lives' ((Status) -like 'busy: runner*')
    Check 'lock records the holder start time' ((Get-Content $env:QWEN_LOCK_PATH -Raw | ConvertFrom-Json).pstart -eq $meStart)
    Check 're-acquire by the same holder is a no-op' ((Lock acquire -Kind runner -HolderPid $me -WaitS 5) -eq 0)
    $other = Start-Process powershell -ArgumentList '-NoProfile', '-Command', 'Start-Sleep 60' -WindowStyle Hidden -PassThru
    Check 'another holder waits and times out (exit 3)' ((Lock acquire -Kind runner -HolderPid $other.Id -WaitS 4) -eq 3)
    Check 'release by a non-owner does nothing' ((Lock release -HolderPid $other.Id) -eq 0 -and (Test-Path $env:QWEN_LOCK_PATH))
    Check 'release by the owner frees it' ((Lock release -HolderPid $me) -eq 0 -and -not (Test-Path $env:QWEN_LOCK_PATH))

    Put @{ pid = 999999; kind = 'runner'; started = (Get-Date).ToString('s') }
    Check 'dead holder is stale and taken over' ((Lock acquire -Kind runner -HolderPid $other.Id -WaitS 5) -eq 0 -and ((Get-Content $env:QWEN_LOCK_PATH -Raw | ConvertFrom-Json).pid -eq $other.Id))
    Remove-Item $env:QWEN_LOCK_PATH

    Put @{ pid = $me; pstart = '2001-01-01T00:00:00.0000000Z'; kind = 'runner'; started = (Get-Date).ToString('s') }
    Check 'reused PID (start time differs) is stale' ((Status) -like 'stale:*')
    Remove-Item $env:QWEN_LOCK_PATH

    $old = (Get-Date).AddSeconds(-300).ToString('s')
    Put @{ pid = $me; pstart = $meStart; kind = 'codex'; started = $old; grace = 720 }
    Check 'codex holder inside its grace (preflight slot wait) stays live' ((Status) -like 'busy:*')
    Put @{ pid = $me; pstart = $meStart; kind = 'codex'; started = $old; grace = 60 }
    Check 'codex holder past grace with no codex.exe child is stale' ((Status) -like 'stale:*')
    Put @{ pid = $me; pstart = $meStart; kind = 'codex'; started = $old }
    Check 'old-format codex lock keeps the 60 s rule' ((Status) -like 'stale:*')
    Remove-Item $env:QWEN_LOCK_PATH

    # race: two waiters on the same stale lock - exactly one may win
    Put @{ pid = 999999; kind = 'runner'; started = (Get-Date).ToString('s') }
    $h1 = Start-Process powershell -ArgumentList '-NoProfile', '-Command', 'Start-Sleep 60' -WindowStyle Hidden -PassThru
    $h2 = Start-Process powershell -ArgumentList '-NoProfile', '-Command', 'Start-Sleep 60' -WindowStyle Hidden -PassThru
    $j1 = Start-Job { param($s, $p, $l) $env:QWEN_LOCK_PATH = $l; & powershell -NoProfile -ExecutionPolicy Bypass -File $s acquire -Kind runner -HolderPid $p -WaitS 6 2>$null; $LASTEXITCODE } -ArgumentList $script, $h1.Id, $env:QWEN_LOCK_PATH
    $j2 = Start-Job { param($s, $p, $l) $env:QWEN_LOCK_PATH = $l; & powershell -NoProfile -ExecutionPolicy Bypass -File $s acquire -Kind runner -HolderPid $p -WaitS 6 2>$null; $LASTEXITCODE } -ArgumentList $script, $h2.Id, $env:QWEN_LOCK_PATH
    $r = @(Receive-Job $j1 -Wait -AutoRemoveJob | Select-Object -Last 1) + @(Receive-Job $j2 -Wait -AutoRemoveJob | Select-Object -Last 1)
    $winner = (Get-Content $env:QWEN_LOCK_PATH -Raw | ConvertFrom-Json).pid
    Check "stale takeover race: one winner, one waiter (exit codes $($r -join ','))" ((@($r | Where-Object { $_ -eq 0 }).Count -eq 1) -and (@($r | Where-Object { $_ -eq 3 }).Count -eq 1) -and ($winner -in @($h1.Id, $h2.Id)))
    foreach ($p in @($other, $h1, $h2)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
} finally {
    Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
    Remove-Item Env:QWEN_LOCK_PATH -ErrorAction SilentlyContinue
}
if ($fails) { "$fails FAILED"; exit 1 } else { 'QWEN_LOCK_TESTS_PASS'; exit 0 }
