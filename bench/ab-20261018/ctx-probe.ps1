# Production-slowness probe (18 Oct 2026): governor MAX loads ctx 49152 / -t 14 and runs ~30 tok/s vs 51 in the bench.
# Separates the two differences: context size (VRAM spill to shared memory) vs thread count.
$ErrorActionPreference = 'Continue'
$d = 'C:\AI\bench\ab-20261018'
$exe = 'C:\AI\llama.cpp\vulkan-intelfa-kq2-20261018\llama-server.exe'
$log = "$d\ctx-probe.log"
& "$d\bench-session.ps1" start | Add-Content $log
function Row($label) {
    $j = Get-Content "$d\$label.result.json" -Raw | ConvertFrom-Json
    "{0} {1}: tps={2} ms/round={8} ded={3} shared={4}/{5} adapter={6} greedy={7}" -f (Get-Date -Format HH:mm:ss), $label, (($j.tps) -join '/'), $j.dedicated_gib, $j.shared_gib, $j.shared_gib_after, $j.adapter_used_gib, (($j.greedy.hashes) -join ','), (($j.ms_per_round) -join '/') | Add-Content $log
}
& "$d\run-ab.ps1" -Label P1-ctx49k-t8 -Ctx 49152 -Exe $exe -Runs 1 -SkipPP -Greedy | Out-Null; Row P1-ctx49k-t8
& "$d\run-ab.ps1" -Label P2-ctx32k-t14 -Ctx 32768 -Exe $exe -Runs 1 -SkipPP -Greedy -Extra @('-t', '14', '-tb', '14') | Out-Null; Row P2-ctx32k-t14
& "$d\run-ab.ps1" -Label P3-ctx40k-t8 -Ctx 40960 -Exe $exe -Runs 1 -SkipPP -Greedy | Out-Null; Row P3-ctx40k-t8
'probe done' | Add-Content $log
