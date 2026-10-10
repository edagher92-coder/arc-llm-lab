$log = 'C:\AI\bench\server-test.txt'
function L($m) { $m | Out-File $log -Append -Encoding utf8 }
while (Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | ? { $_.CommandLine -match 'compare-f16\.ps1' }) { Start-Sleep 5 }
Set-Content C:\AI\governor\mode.txt 'OFF'; Set-Content C:\AI\governor\power.txt 'PERFORMANCE'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
try { Invoke-RestMethod -Method Post 'http://127.0.0.1:8090/api/models/unload' -Headers @{ Authorization = "Bearer $key" } | Out-Null } catch {}
Start-Sleep 8
$cfg = Get-Content C:\AI\governor\profiles.json -Raw | ConvertFrom-Json
$m = $cfg.variants.default.model; $mm = $cfg.mmproj; $df = 'C:/AI/models/qwen3.8-27b/Qwen3.8-27B-DFlash2-Q4_K_M.gguf'
$exe = 'C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe'
"start $(Get-Date -f s)" | Set-Content $log
foreach ($ctx in 57344) {
  $a = "set GGML_VK_FORCE_MMVQ=1&& $exe -m $m --mmproj $mm --host 127.0.0.1 --port 18080 -ngl 99 -fa on -lm dio --jinja -np 1 -t 8 -cram 4096 --cache-reuse 256 --metrics --no-mmproj-offload -fit off --chat-template-file C:/AI/governor/qwen38-template.jinja -c $ctx -ctk f16 -ctv f16 -ngld 99 -md $df --spec-type draft-dflash --spec-draft-n-max 7 -a qwen3.8-27b"
  $v0 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "cmd.exe /c $a > C:\AI\bench\srv-$ctx.log 2>&1" } | Out-Null
  $ok = $false; for ($i = 0; $i -lt 90; $i++) { Start-Sleep 2; try { if ((Invoke-RestMethod http://127.0.0.1:18080/health -TimeoutSec 2).status -eq 'ok') { $ok = $true; break } } catch {} }
  if (-not $ok) { L "ctx $ctx : FAILED TO START"; continue }
  Start-Sleep 3
  $v1 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  L ("ctx {0}: others before {1:N2} GiB | total now {2:N2} / 23.88 | model {3:N2} GiB | free {4:N2} GiB" -f $ctx, ($v0/1GB), ($v1/1GB), (($v1-$v0)/1GB), (23.88 - $v1/1GB))
  L ((& python C:\AI\backups\req.py 18080 "intelfa-f16-shallow" 2>&1 | Out-String) -replace '\s+', ' ')
  L ((& python C:\AI\backups\agentturn.py 18080 "intelfa-f16" 2>&1 | Out-String) -replace '\s+', ' ')
  L ((& python C:\AI\backups\eval.py 18080 "intelfa-f16" 2>&1 | Out-String) -replace '\s+', ' ')
  L ((& python C:\AI\backups\longreq.py 18080 2>&1 | Out-String) -replace '\s+', ' ')
  $p = (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force }
}
Set-Content C:\AI\governor\mode.txt 'AUTO'; Set-Content C:\AI\governor\power.txt 'AUTO'
L "END $(Get-Date -f s)"
