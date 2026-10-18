# Production check through the live governor-launched server (port 10001): greedy fingerprint + 3-seed sustained.
param([string]$Label = 'prod-check')
$d = 'C:\AI\bench\ab-20261018'
$lock = 'C:\AI\locks\qwen-lock.ps1'
& powershell -NoProfile -ExecutionPolicy Bypass -File $lock acquire -Kind bench -HolderPid $PID -WaitS 900 -Note "production check (Claude)"
if ($LASTEXITCODE -ne 0) { 'engine busy'; exit 1 }
try {
    $env:QWEN_BASE = 'http://127.0.0.1:10001'
    $py = (Get-Command python).Source
    $ctx = (Invoke-RestMethod http://127.0.0.1:10001/props -TimeoutSec 10).default_generation_settings.n_ctx
    & $py "$d\greedy_check.py" $Label
    & $py "$d\sustained.py" --label $Label --output "$d\$Label.sustained.json" --runs 3 --expected-context $ctx 2>&1 | Out-Null
    $rows = Get-Content "$d\$Label.sustained.json" | ? { $_.Trim() } | % { $_ | ConvertFrom-Json }
    $tps = $rows | % { [math]::Round($_.timings.predicted_per_second, 2) }
    $mspr = $rows | % { [math]::Round($_.timings.predicted_ms / $_.native_counter_deltas.n_decode_total, 1) }
    $set = (Get-Counter '\GPU Process Memory(*)\Shared Usage').CounterSamples | ? { $_.InstanceName -like ("pid_{0}_*" -f (Get-Process llama-server | Select -First 1).Id) }
    "{0} ctx={1} tps={2} mean={3} ms/round={4} llama_shared={5:N2}GiB" -f $Label, $ctx, ($tps -join '/'), [math]::Round(($tps | measure -Average).Average, 2), ($mspr -join '/'), (($set | measure CookedValue -Sum).Sum / 1GB)
} finally {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $lock release -HolderPid $PID | Out-Null
}
