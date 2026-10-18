# start|stop a benchmark session: hold the engine lock with a sleeper process and switch the governor OFF / back to AUTO.
param([ValidateSet('start', 'stop')][string]$Action)
$flag = 'C:\AI\locks\bench.flag'
$lock = 'C:\AI\locks\qwen-lock.ps1'
if ($Action -eq 'start') {
    Set-Content $flag (Get-Date -Format s)
    $holder = Start-Process powershell -ArgumentList '-NoProfile', '-Command', "while (Test-Path '$flag') { Start-Sleep 5 }" -WindowStyle Hidden -PassThru
    & powershell -NoProfile -ExecutionPolicy Bypass -File $lock acquire -Kind bench -HolderPid $holder.Id -WaitS 900 -Note 'Phase 4 A/B benchmarks (Claude)'
    if ($LASTEXITCODE -ne 0) { Remove-Item $flag; throw 'could not take the engine lock' }
    & C:\AI\governor\qwen.ps1 mode off
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 120) { Start-Sleep 5; if (-not (Get-Process llama-server -ErrorAction SilentlyContinue | ? { $_.Path -like 'C:\AI\llama.cpp\*' })) { break } }
    if (Get-Process llama-server -ErrorAction SilentlyContinue | ? { $_.Path -like 'C:\AI\llama.cpp\*' }) { & C:\AI\governor\qwen.ps1 unload; Start-Sleep 10 }
    "llama-server running: $([bool](Get-Process llama-server -ErrorAction SilentlyContinue))"
    "lock: $(& powershell -NoProfile -File $lock status)"
    $a = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Maximum
    "adapter dedicated used now: $([math]::Round($a.Maximum/1GB,2)) GiB (others only)"
} else {
    Remove-Item $flag -ErrorAction SilentlyContinue
    Start-Sleep 7
    & C:\AI\governor\qwen.ps1 mode auto
    "lock: $(& powershell -NoProfile -File $lock status)"
}
