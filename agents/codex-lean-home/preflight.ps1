# codex-qwen preflight (18 Oct 2026): one Qwen job at a time, then print "<window> <lockHolderPid>" for the launcher.
# 1. Job lock: C:\AI\locks\qwen-lock.ps1 acquire (kind codex, holder = the codex-qwen.cmd process), waiting while
#    another live job (UBOS runner, eval, benchmark, another Codex) owns it.
# 2. Slot check: also waits while the llama-server slot is busy with a job that does not take the lock (ask_local, chats).
# QWEN_WAIT_S (default 600) caps each wait; QWEN_NOWAIT=1 skips both (lock not taken). Messages go to stderr.
param([string]$Kind = 'codex')
$ErrorActionPreference = 'SilentlyContinue'
$key = $env:LOCAL_QWEN_KEY
if (-not $key) { $key = [Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY', 'User') }
$maxWait = 600; if ($env:QWEN_WAIT_S) { $maxWait = [int]$env:QWEN_WAIT_S }
$holder = 0
if ($env:QWEN_NOWAIT -ne '1') {
    # for /f runs this script in a child "cmd /c"; its parent is the cmd.exe executing codex-qwen.cmd.
    $me = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
    $sub = Get-CimInstance Win32_Process -Filter "ProcessId=$($me.ParentProcessId)"
    $launcher = if ($sub -and $sub.Name -ieq 'cmd.exe') { [int]$sub.ParentProcessId } else { [int]$me.ParentProcessId }
    & powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\AI\locks\qwen-lock.ps1' acquire -Kind $Kind -HolderPid $launcher -WaitS $maxWait -Note "$Kind-qwen in $((Get-Location).Path)"
    if ($LASTEXITCODE -eq 0) { $holder = $launcher }
    else { [Console]::Error.WriteLine('codex-qwen: starting without the job lock (expect half speed). Set QWEN_NOWAIT=1 to skip waiting.') }

    $t0 = Get-Date; $said = -999
    while ($true) {
        $busy = $false
        try {
            $s = Invoke-RestMethod 'http://127.0.0.1:8090/upstream/qwen3.8-27b/slots' -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 3
            $busy = [bool](@($s) | Where-Object { $_.is_processing })
        } catch { $busy = $false }   # model not loaded / llama-swap starting: nothing to wait for
        if (-not $busy) { break }
        $el = [int]((Get-Date) - $t0).TotalSeconds
        if ($el -ge $maxWait) { [Console]::Error.WriteLine("codex-qwen: Qwen slot still busy after ${el}s - starting anyway."); break }
        if ($el - $said -ge 30) { [Console]::Error.WriteLine("codex-qwen: Qwen is answering another request - waiting (${el}s)."); $said = $el }
        Start-Sleep -Seconds 3
    }
}
$win = (& 'C:\AI\governor\qwen.ps1' window | Select-Object -Last 1)
if ("$win" -notmatch '^\d+$') { $win = 24576 }
"$win $holder"

