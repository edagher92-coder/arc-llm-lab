# End-to-end A/B of the scratch engine (production c85e6c598 + GDN state-out fusion + Intel MMVQ knobs).
$ErrorActionPreference = 'Continue'
$dir = 'C:\AI\bench\ab-20261018'
$exe = 'D:\build\vk-tune-20261018-build\bin\llama-server.exe'
$log = "$dir\kernel-ab.log"
function Say($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -FilePath $log -Append }
$configs = @(
    @{ label = 'K0-scratch-default'; env = @{} },
    @{ label = 'K1-kq2-wg3';         env = @{ GGML_VK_TUNE_RM_KQ_INT = '2'; GGML_VK_TUNE_MMVQ_WG = '3' } },
    @{ label = 'K2-kq2';             env = @{ GGML_VK_TUNE_RM_KQ_INT = '2' } }
)
foreach ($c in $configs) {
    foreach ($k in 'GGML_VK_TUNE_RM_KQ_INT', 'GGML_VK_TUNE_MMVQ_WG', 'GGML_VK_TUNE_RM_STDQ_INT', 'GGML_VK_TUNE_RM_KQ') { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
    foreach ($k in $c.env.Keys) { Set-Item "env:$k" $c.env[$k] }
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\run-ab.ps1" -Label $c.label -Kv f16 -Ctx 32768 -Runs 3 -Exe $exe -Greedy | Out-Null
    try { $r = Get-Content "$dir\$($c.label).result.json" -Raw | ConvertFrom-Json } catch { $r = $null }
    if (-not $r) { Say "$($c.label): no result"; continue }
    Say ("{0}: tps={1} mean={2} ms/round={3} accept={4} pp={5} greedy={6} greedy_tps={7} ded={8} shared={9}" -f $c.label, ($r.tps -join '/'), $r.tps_mean, ($r.ms_per_round -join '/'), ($r.draft_accept -join '/'), (($r.pp | % { $_.prompt_tps }) -join '/'), ($r.greedy.hashes -join ','), ($r.greedy.tps -join '/'), $r.dedicated_gib, $r.shared_gib)
}
Say "done"
