# Soak: the baked kq2 scratch engine (no env knobs) through 3 consecutive warm A/B cycles (9 seeds + 9 greedy prompts).
$ErrorActionPreference = 'Continue'
$dir = 'C:\AI\bench\ab-20261018'
$exe = 'D:\build\vk-tune-20261018-build\bin\llama-server.exe'
$log = "$dir\soak-kq2.log"
foreach ($k in 'GGML_VK_TUNE_RM_KQ_INT', 'GGML_VK_TUNE_MMVQ_WG', 'GGML_VK_PERF_LOGGER', 'GGML_VK_PERF_LOGGER_FREQUENCY') { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
foreach ($i in 1..3) {
    $label = "S$i-kq2-baked"
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\run-ab.ps1" -Label $label -Kv f16 -Ctx 32768 -Runs 3 -Exe $exe -Greedy | Out-Null
    try { $r = Get-Content "$dir\$label.result.json" -Raw | ConvertFrom-Json } catch { $r = $null }
    "$(Get-Date -Format HH:mm:ss) ${label}: tps=$($r.tps -join '/') mean=$($r.tps_mean) ms/round=$($r.ms_per_round -join '/') pp=$(($r.pp | % { $_.prompt_tps }) -join '/') greedy=$($r.greedy.hashes -join ',') | $($r.oc)" | Tee-Object -FilePath $log -Append
}
"done" | Tee-Object -FilePath $log -Append
