# qwen doctor - one-command health check of the whole local AI stack on this PC. Read-only: changes nothing.
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\AI\governor'; $swap = 'http://127.0.0.1:8090'
$script:fails = 0; $script:warns = 0
function Check($name, $ok, $detail, [switch]$Warn) {
  $tag = if ($ok) { 'OK  ' } elseif ($Warn) { $script:warns++; 'WARN' } else { $script:fails++; 'FAIL' }
  $line = "  {0}  {1,-28} {2}" -f $tag, $name, $detail
  $col = @{ 'OK  ' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }[$tag]
  if ([Console]::IsOutputRedirected) { Write-Output $line } else { Write-Host $line -ForegroundColor $col }
}
Write-Host "Qwen doctor - $(Get-Date -f 'yyyy-MM-dd HH:mm')" -ForegroundColor Cyan

Write-Host 'Model server'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
$m = try { Invoke-RestMethod "$swap/v1/models" -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 5 } catch { $null }
Check 'llama-swap API' ($null -ne $m) $(if ($m) { "$($m.data.Count) models listed" } else { 'not answering on :8090' })
$s = try { Get-Content "$dir\public\status.json" -Raw | ConvertFrom-Json } catch { $null }
$age = if ($s) { [math]::Round(((Get-Date) - [datetime]$s.time).TotalSeconds) } else { 9999 }
Check 'governor' ($age -lt 60) "status $age s old, mode $($s.mode), profile $($s.profile)"
if ($s.loaded) {
  Check 'model loaded' $true "ctx $($s.n_ctx), $($s.loaded_profile)"
  Check 'VRAM headroom' ($s.vram_free_gib -ge 1.15) "$($s.vram_free_gib) GiB free (target >= 1.5, floor 1.15)" -Warn:($s.vram_free_gib -ge 1.0)
} else { Check 'model loaded' $true "not loaded (loads on first request) - state $($s.state)" }
$p = try { Get-Content "$dir\profiles.json" -Raw | ConvertFrom-Json } catch { $null }
Check 'profiles.json' ($null -ne $p) $(if ($p) { 'valid JSON' } else { 'unreadable / invalid JSON' })
$exe = $p.exe; Check 'engine binary' (Test-Path $exe) "$exe"
$ca = ($p.common_args -join ' ') + ' ' + ($p | ConvertTo-Json -Depth 8)
Check 'no silent truncation' ($ca -match '--no-context-shift') 'context shift disabled (overflow = explicit error)'
$sn = Get-Content "$dir\session-need.txt" -ErrorAction SilentlyContinue
Check 'session protection' ($null -ne $sn) "session-need $sn tokens" -Warn

Write-Host 'Voice'
$w = try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8091/' -TimeoutSec 5 } catch { $null }
Check 'Whisper STT :8091' ($null -ne $w) $(if ($w) { 'up' } else { 'down - Start-ScheduledTask "Local Whisper (voice STT)"' })
$k = try { Invoke-RestMethod 'http://127.0.0.1:8092/voices' -TimeoutSec 5 } catch { $null }
Check 'Kokoro TTS :8092' ($null -ne $k) $(if ($k) { "$(@($k.PSObject.Properties).Count) voices" } else { 'down - Start-ScheduledTask "Local Kokoro (voice TTS)"' })

Write-Host 'Remote access'
$ts = try { & 'C:\Program Files\Tailscale\tailscale.exe' status --json | ConvertFrom-Json } catch { $null }
Check 'Tailscale' ($ts.BackendState -eq 'Running') "backend $($ts.BackendState)"
$serve = (& 'C:\Program Files\Tailscale\tailscale.exe' serve status 2>&1) -join "`n"
foreach ($route in '/stt', '/tts', '/governor/') { Check "tailnet route $route" ($serve -match [regex]::Escape($route)) ':8445' }
$funnel = ($serve -split "`n" | ? { $_ -match 'Funnel on' }) -join '; '
Check 'public exposure' $true $(if ($funnel) { "Funnel: $funnel (Qwen stack is tailnet-only)" } else { 'no Funnel' })

Write-Host 'Scheduled services'
foreach ($t in 'Local Qwen (llama-swap)', 'Local Qwen Governor', 'Local Whisper (voice STT)', 'Local Kokoro (voice TTS)') {
  $st = (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue).State
  Check $t ($st -eq 'Running') "$st" -Warn:($st -eq 'Ready')
}

Write-Host 'Agents'
Check 'claude-qwen wrapper' (Test-Path "$env:USERPROFILE\bin\claude-qwen.cmd") "$env:USERPROFILE\bin\claude-qwen.cmd"
Check 'codex-qwen wrapper' (Test-Path "$env:USERPROFILE\bin\codex-qwen.cmd") "$env:USERPROFILE\bin\codex-qwen.cmd"
$acl = (Get-Acl "$env:LOCALAPPDATA\Python").Access | ? { $_.IdentityReference -match 'CodexSandbox' }
Check 'Codex sandbox Python' ($null -ne $acl) $(if ($acl) { 'sandbox can run Python' } else { 'sandbox cannot see Python (tests will fail)' })

Write-Host 'PC'
$sb = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String 'Current AC Power Setting Index' | % { $_.Line.Split(':')[-1].Trim() })
Check 'never sleeps (AC)' ($sb -eq '0x00000000') "standby idle $sb"
foreach ($d in 'C', 'D') { $f = [math]::Round((Get-PSDrive $d).Free / 1GB); Check "disk $d free" ($f -ge 20) "$f GB" -Warn:($f -ge 10) }
$ram = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Check 'RAM free' ($ram -ge 4) "$ram GB" -Warn

Write-Host 'Regression benchmark'
$hist = Import-Csv 'C:\AI\bench\history.csv' -ErrorAction SilentlyContinue
if ($hist) {
  $last = $hist[-1]; $ageD = [math]::Round(((Get-Date) - [datetime]$last.time).TotalDays, 1)
  Check 'last qwen bench' ([double]$last.three_turn_s -le 63) "$($last.three_turn_s) s 3-turn (baseline 54.9, alert > 63), $($last.coding) coding, $($last.tools) tools, $ageD days ago" -Warn:([double]$last.three_turn_s -le 70)
} else { Check 'last qwen bench' $false 'no history - run: qwen bench' -Warn }

Write-Host ''
if ($script:fails -eq 0) { Write-Host ("All critical checks passed ({0} warnings)." -f $script:warns) -ForegroundColor Green } else { Write-Host ("{0} FAILED, {1} warnings." -f $script:fails, $script:warns) -ForegroundColor Red }
exit $script:fails


