# Microbench sweep of the env tuning knobs on the scratch build: MUL_MAT q4_K/q6_K, m=4096 k=14336, n=1 and n=8 (MMVQ).
param([string]$Out = 'D:\build\vk-tune-20261018-work\mmv-sweep.txt')
$exe = 'D:\build\vk-tune-20261018-build\bin\test-backend-ops.exe'
$env:PATH = 'D:\build\intelfa\tools\w64devkit\bin;' + $env:PATH
$env:GGML_VK_FORCE_MMVQ = '1'
$configs = @(
    @{ name = 'default';        RM_KQ_INT = $null; RM_STDQ_INT = $null; MMVQ_WG = $null },
    @{ name = 'kq_int2';        RM_KQ_INT = '2';   RM_STDQ_INT = $null; MMVQ_WG = $null },
    @{ name = 'kq_int4';        RM_KQ_INT = '4';   RM_STDQ_INT = $null; MMVQ_WG = $null },
    @{ name = 'wg_large';       RM_KQ_INT = $null; RM_STDQ_INT = $null; MMVQ_WG = '1' },
    @{ name = 'wg_large_kq2';   RM_KQ_INT = '2';   RM_STDQ_INT = $null; MMVQ_WG = '1' },
    @{ name = 'wg_large_kq4';   RM_KQ_INT = '4';   RM_STDQ_INT = $null; MMVQ_WG = '1' },
    @{ name = 'kq_int8';        RM_KQ_INT = '8';   RM_STDQ_INT = $null; MMVQ_WG = $null }
)
"mmv sweep $(Get-Date -Format s)" | Out-File $Out -Encoding utf8
foreach ($c in $configs) {
    foreach ($k in 'RM_KQ_INT', 'RM_STDQ_INT', 'MMVQ_WG') {
        $v = $c[$k]; $name = "GGML_VK_TUNE_$k"
        if ($v) { Set-Item "env:$name" $v } else { Remove-Item "env:$name" -ErrorAction SilentlyContinue }
    }
    $lines = & $exe perf -b Vulkan0 -o MUL_MAT -p 'type_a=q[46]_K,type_b=f32,m=4096,n=(1|8),k=14336,' 2>&1 | Select-String -Pattern 'MUL_MAT\(' | % { $_.Line.Trim() }
    foreach ($l in $lines) {
        $ta = [regex]::Match($l, 'type_a=(\w+)').Groups[1].Value; $n = [regex]::Match($l, ',n=(\d+)').Groups[1].Value
        $us = [regex]::Match($l, '([0-9.]+) us/run').Groups[1].Value
        $bpw = if ($ta -eq 'q4_K') { 4.5 } else { 6.5625 }
        $gbs = if ($us) { [math]::Round((4096.0 * 14336 * $bpw / 8) / ([double]$us * 1e-6) / 1e9, 1) } else { '' }
        ("{0,-14} {1,-5} n={2} {3,9} us/run {4,9} GB/s" -f $c.name, $ta, $n, $us, $gbs) | Tee-Object -FilePath $Out -Append
    }
}
