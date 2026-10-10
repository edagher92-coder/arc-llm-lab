$log = 'C:\AI\bench\tune2.txt'
function L($m) { $m | Out-File $log -Append -Encoding utf8 }
Set-Content C:\AI\governor\mode.txt 'OFF'; Set-Content C:\AI\governor\power.txt 'PERFORMANCE'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
try { Invoke-RestMethod -Method Post 'http://127.0.0.1:8090/api/models/unload' -Headers @{ Authorization = "Bearer $key" } | Out-Null } catch {}
for ($i = 0; $i -lt 30; $i++) { if (-not (Get-Process llama-server -EA SilentlyContinue | ? { $_.Path -like 'C:\AI\*' })) { break }; Start-Sleep 1 }
Start-Sleep 4
$cfg = Get-Content C:\AI\governor\profiles.json -Raw | ConvertFrom-Json
$m = $cfg.variants.default.model; $mm = $cfg.mmproj; $df = 'C:/AI/models/qwen3.8-27b/Qwen3.8-27B-DFlash2-Q4_K_M.gguf'
$env:GGML_VK_FORCE_MMVQ = '1'
"start $(Get-Date -f s)" | Set-Content $log
$tests = [ordered]@{ 'ub512 dkv-q8' = @('--spec-draft-n-max','7','-ctkd','q8_0','-ctvd','q8_0'); 'ub384 dkv-q8' = @('--spec-draft-n-max','7','-ub','384','-ctkd','q8_0','-ctvd','q8_0') }
foreach ($k in $tests.Keys) {
  $p = (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force; Start-Sleep 3 }
  $v0 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  $a = @('-m',$m,'--mmproj',$mm,'--host','127.0.0.1','--port','18080','-ngl','99','-fa','on','-lm','dio','--jinja','-np','1','-t','8','-cram','4096','--cache-reuse','256','--metrics','--no-mmproj-offload','-fit','off','--chat-template-file','C:/AI/governor/qwen38-template.jinja','-c','65536','-ctk','f16','-ctv','f16','-ngld','99','-md',$df,'--spec-type','draft-dflash') + $tests[$k]
  Start-Process -FilePath $cfg.exe -ArgumentList $a -WindowStyle Hidden -RedirectStandardError C:\AI\bench\tune2-srv.log
  $ok = $false; for ($i = 0; $i -lt 90; $i++) { Start-Sleep 2; try { if ((Invoke-RestMethod http://127.0.0.1:18080/health -TimeoutSec 2).status -eq 'ok') { $ok = $true; break } } catch {} }
  if (-not $ok) { L "$k : FAILED"; continue }
  & python C:\AI\bench\req.py 18080 warm 2>&1 | Out-Null
  $v1 = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Sum).Sum
  $env:NF = '590'
  $at = (& python C:\AI\bench\agentturn.py 18080 $k 2>&1) | % { try { $_ | ConvertFrom-Json } catch {} }
  $three = ($at | ? { $_.three_turns_wall_s }).three_turns_wall_s; $tr = $at | ? { $_.run -like 'turn*' }
  L ("{0,-14} | model {1:N2} GiB, free {2:N2} GiB (others {3:N2}) | 3-turn {4} s | deep tg {5:N1} pp {6:N0}" -f $k, (($v1-$v0)/1GB), (23.88-$v1/1GB), ($v0/1GB), $three, ($tr.tg_tps | measure -Average).Average, ($tr.pp_tps | measure -Average).Average)
}
$p = (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force }
Set-Content C:\AI\governor\mode.txt 'AUTO'; Set-Content C:\AI\governor\power.txt 'AUTO'
L "END $(Get-Date -f s)"
