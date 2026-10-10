# Compare stock Vulkan b11524 vs the Intel-FA build at depth. Unloads the model while running, restores AUTO after.
$out = 'C:\AI\bench\compare.txt'
$new = 'C:\AI\llama.cpp\vulkan-intelfa\llama-bench.exe'
if (-not (Test-Path $new)) { Write-Host "Not found: $new - finish steps 2-3 first"; exit 1 }
Set-Content C:\AI\governor\mode.txt 'OFF'; Set-Content C:\AI\governor\power.txt 'PERFORMANCE'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
try { Invoke-RestMethod -Method Post 'http://127.0.0.1:8090/api/models/unload' -Headers @{ Authorization = "Bearer $key" } | Out-Null } catch {}
Start-Sleep 8
$m = (Get-Content C:\AI\governor\profiles.json -Raw | ConvertFrom-Json).variants.default.model
$env:GGML_VK_FORCE_MMVQ = '1'
"start $(Get-Date -Format s)" | Set-Content $out
foreach ($e in @(@{ n = 'STOCK b11524'; b = 'C:\AI\llama.cpp\vulkan\llama-bench.exe' }, @{ n = 'INTEL-FA'; b = $new })) {
  Write-Host "Running $($e.n) ..."
  $r = & $e.b -m $m -ngl 99 -lm dio -fa 1 -ctk q4_0 -ctv q4_0 -p 8,2048 -n 32 -d 0,16384,32768 -r 1 2>&1 | ? { "$_" -match '^\|.*qwen' }
  $rows = $r | % { $c = "$_" -split '\|'; "{0}={1}" -f $c[-3].Trim(), ($c[-2].Trim() -split ' ')[0] }
  ("{0,-14} | {1}" -f $e.n, ($rows -join ' | ')) | Add-Content $out
}
Set-Content C:\AI\governor\mode.txt 'AUTO'; Set-Content C:\AI\governor\power.txt 'AUTO'
"END $(Get-Date -Format s)" | Add-Content $out
Get-Content $out
