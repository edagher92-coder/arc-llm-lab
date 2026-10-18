# Warm A/B (every config gets the same warm-up): production exe vs scratch with Intel MMVQ knobs.
$ErrorActionPreference = 'Continue'
$dir = 'C:\AI\bench\ab-20261018'
$prod = 'C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe'
$scr = 'D:\build\vk-tune-20261018-build\bin\llama-server.exe'
$log = "$dir\kernel-ab2.log"
function Say($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -FilePath $log -Append }
$configs = @(
    @{ label = 'W0-production'; exe = $prod; env = @{} },
    @{ label = 'W1-kq2-wg3';    exe = $scr;  env = @{ GGML_VK_TUNE_RM_KQ_INT = '2'; GGML_VK_TUNE_MMVQ_WG = '3' } },
    @{ label = 'W2-kq2';        exe = $scr;  env = @{ GGML_VK_TUNE_RM_KQ_INT = '2' } }
)
foreach ($c in $configs) {
    foreach ($k in 'GGML_VK_TUNE_RM_KQ_INT', 'GGML_VK_TUNE_MMVQ_WG', 'GGML_VK_TUNE_RM_STDQ_INT', 'GGML_VK_TUNE_RM_KQ') { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
    foreach ($k in $c.env.Keys) { Set-Item "env:$k" $c.env[$k] }
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\run-ab.ps1" -Label $c.label -Kv f16 -Ctx 32768 -Runs 3 -Exe $c.exe -Greedy | Out-Null
    try { $r = Get-Content "$dir\$($c.label).result.json" -Raw | ConvertFrom-Json } catch { $r = $null }
    if (-not $r) { Say "$($c.label): no result"; continue }
    Say ("{0}: tps={1} mean={2} rounds={3} ms/round={4} accept={5} pp={6} greedy={7} greedy_tps={8}" -f $c.label, ($r.tps -join '/'), $r.tps_mean, ($r.rounds -join '/'), ($r.ms_per_round -join '/'), ($r.draft_accept -join '/'), (($r.pp | % { $_.prompt_tps }) -join '/'), ($r.greedy.hashes -join ','), ($r.greedy.tps -join '/'))
}
Say "done"
