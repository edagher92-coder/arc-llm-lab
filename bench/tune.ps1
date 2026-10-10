# Tuning sweep on a private test server (port 18080). Pauses the live model, restores AUTO afterwards.
$log = 'C:\AI\bench\tune.txt'
function L($m) { $m | Out-File $log -Append -Encoding utf8 }
while (Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | ? { $_.CommandLine -match 'regression\.ps1' }) { Start-Sleep 5 }
Set-Content C:\AI\governor\mode.txt 'OFF'; Set-Content C:\AI\governor\power.txt 'PERFORMANCE'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
try { Invoke-RestMethod -Method Post 'http://127.0.0.1:8090/api/models/unload' -Headers @{ Authorization = "Bearer $key" } | Out-Null } catch {}
Start-Sleep 8
$cfg = Get-Content C:\AI\governor\profiles.json -Raw | ConvertFrom-Json
$m = $cfg.variants.default.model; $mm = $cfg.mmproj; $df = 'C:/AI/models/qwen3.8-27b/Qwen3.8-27B-DFlash2-Q4_K_M.gguf'
$exe = $cfg.exe
$common = "-m $m --mmproj $mm --host 127.0.0.1 --port 18080 -ngl 99 -fa on -lm dio --jinja -np 1 -t 8 -cram 4096 --cache-reuse 256 --metrics --no-mmproj-offload -fit off --chat-template-file C:/AI/governor/qwen38-template.jinja -c 65536 -ctk f16 -ctv f16 -ngld 99 -md $df --spec-type draft-dflash"
$tests = [ordered]@{
  'n7 ub512 (current)'   = '--spec-draft-n-max 7'
  'n5'                   = '--spec-draft-n-max 5'
  'n10'                  = '--spec-draft-n-max 10'
  'n15'                  = '--spec-draft-n-max 15'
  'n7 ub256 dkv-q8'      = '--spec-draft-n-max 7 -ub 256 -ctkd q8_0 -ctvd q8_0'
}
"start $(Get-Date -f s)" | Set-Content $log
foreach ($k in $tests.Keys) {
  $p = (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force; Start-Sleep 3 }
  $v0 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "cmd.exe /c set GGML_VK_FORCE_MMVQ=1&& $exe $common $($tests[$k]) > C:\AI\bench\tune-srv.log 2>&1" } | Out-Null
  $ok = $false; for ($i = 0; $i -lt 90; $i++) { Start-Sleep 2; try { if ((Invoke-RestMethod http://127.0.0.1:18080/health -TimeoutSec 2).status -eq 'ok') { $ok = $true; break } } catch {} }
  if (-not $ok) { L "$k : FAILED TO START"; continue }
  Start-Sleep 3
  # warm-up request so compute buffers are allocated before measuring VRAM
  & python C:\AI\bench\req.py 18080 warm 2>&1 | Out-Null
  $v1 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  $sh = (& python C:\AI\bench\req.py 18080 "$k" 2>&1 | Out-String) | ConvertFrom-Json
  $ev = (& python C:\AI\bench\eval.py 18080 "$k" 2>&1 | Select -Last 1) | ConvertFrom-Json
  $tps = ($ev.coding | % { $_.tps }) -join '/'
  L ("{0,-20} | model {1:N2} GiB, free {2:N2} GiB (others {3:N2}) | chat t0.6 {4} tok/s acc {5}/{6} | code t0.2 avg {7} [{8}] | coding {9}/{10} tools {11}/{12}" -f $k, (($v1-$v0)/1GB), (23.88 - $v1/1GB), ($v0/1GB), $sh.tg_tps, $sh.draft_accepted, $sh.draft_n, $ev.avg_gen_tps_wall, $tps, $ev.coding_pass, $ev.coding_total, $ev.tools_pass, $ev.tools_total)
}
$p = (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force }
Set-Content C:\AI\governor\mode.txt 'AUTO'; Set-Content C:\AI\governor\power.txt 'AUTO'
L "END $(Get-Date -f s)"
