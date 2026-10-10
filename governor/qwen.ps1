# qwen - control the local Qwen server on this PC
#   qwen status | qwen mode auto|max|balanced|lean|off | qwen load [fast] | qwen unload | qwen restart | qwen log
param([string]$Cmd = 'status', [string]$Arg = '')
$dir = 'C:\AI\governor'; $swap = 'http://127.0.0.1:8090'
$key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim(); $h = @{ Authorization = "Bearer $key" }
switch ($Cmd.ToLower()) {
  'status' {
    try { $s = Get-Content "$dir\public\status.json" -Raw | ConvertFrom-Json } catch { Write-Host 'governor status not available'; break }
    $age = [math]::Round(((Get-Date) - [datetime]$s.time).TotalSeconds)
    Write-Host ("Mode {0} | profile {1} | model {2}{3} | ctx {4} | quiet {5} min" -f $s.mode, $s.profile, $(if ($s.loaded) { "LOADED ($($s.loaded_profile))" } else { $s.state }), $(if ($s.processing) { ' BUSY' } else { '' }), $s.n_ctx, $s.model_quiet_min)
    Write-Host ("PC: idle {0}s | RAM free {1} GB | VRAM used {2}/23.9 GiB (model {3}, others {4}) | CPU others {5}%" -f $s.idle_sec, $s.ram_avail_gb, $s.vram_used_gib, $s.vram_llama_gib, $s.vram_others_gib, $s.cpu_others)
    if ($age -gt 60) { Write-Host "WARNING: governor status is $age s old - governor may not be running" -ForegroundColor Yellow }
  }
  'mode' {
    $m = $Arg.ToUpper(); if ($m -notin 'AUTO','MAX','BALANCED','LEAN','OFF') { Write-Host 'usage: qwen mode auto|max|balanced|lean|off'; break }
    Set-Content "$dir\mode.txt" $m; Write-Host "mode set to $m (applies within ~15 s; context changes apply on next load)"
  }
  'load' {
    $id = switch ($Arg) { 'fast' { 'qwen3.6-35b-a3b' } 'turbo' { 'qwen3.8-27b-turbo' } default { 'qwen3.8-27b' } }
    $b = @{ model = $id; max_tokens = 1; messages = @(@{ role = 'user'; content = 'hi' }) } | ConvertTo-Json -Depth 4
    $t = Get-Date; Invoke-RestMethod -Method Post "$swap/v1/chat/completions" -Headers $h -Body $b -ContentType 'application/json' -TimeoutSec 300 | Out-Null
    Write-Host "$id loaded in $([math]::Round(((Get-Date)-$t).TotalSeconds,1)) s"
  }
  'unload' { Invoke-RestMethod -Method Post "$swap/api/models/unload" -Headers $h | Out-Null; Write-Host 'all models unloaded (VRAM freed)' }
  'restart' { Stop-ScheduledTask 'Local Qwen (llama-swap)' -ErrorAction SilentlyContinue; Get-Process llama-swap -ErrorAction SilentlyContinue | Stop-Process -Force
              Get-Process llama-server -ErrorAction SilentlyContinue | ? { $_.Path -like 'C:\AI\*' } | Stop-Process -Force; Start-Sleep 2; Start-ScheduledTask 'Local Qwen (llama-swap)'
              Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | ? { $_.CommandLine -match 'governor\\governor\.ps1' } | % { Stop-Process -Id $_.ProcessId -Force }
              Stop-ScheduledTask 'Local Qwen Governor' -ErrorAction SilentlyContinue; Start-Sleep 4; Start-ScheduledTask 'Local Qwen Governor'; Write-Host 'llama-swap and governor restarted' }
  'power' {
    $p = $Arg.ToUpper(); if ($p -eq '') { try { $s = Get-Content "$dir\public\status.json" -Raw | ConvertFrom-Json; Write-Host "Power mode $($s.power_mode) | plan now $($s.power_plan)" } catch {}; break }
    if ($p -notin 'AUTO','PERFORMANCE','BALANCED','SAVER') { Write-Host 'usage: qwen power auto|performance|balanced|saver'; break }
    Set-Content "$dir\power.txt" $p; Write-Host "power mode set to $p (applies within ~15 s)"
  }
  'engine' {
    $map = @{ 'stock' = 'C:/AI/llama.cpp/vulkan/llama-server.exe'; 'intelfa' = 'C:/AI/llama.cpp/vulkan-intelfa/llama-server.exe' }
    $cfgPath = "$dir\profiles.json"; $c = Get-Content $cfgPath -Raw
    $cur = ($c | ConvertFrom-Json).exe
    if (-not $map.ContainsKey($Arg.ToLower())) { Write-Host "Engine now: $cur"; Write-Host 'usage: qwen engine stock|intelfa'; break }
    $want = $map[$Arg.ToLower()]
    if (-not (Test-Path $want)) { Write-Host "Not found: $want (build it first: engine\BUILD-INTEL-FA.md in the arc-llm-lab repo)"; break }
    Copy-Item $cfgPath "$cfgPath.bak-engine" -Force
    $c = $c.Replace('"' + $cur + '"', '"' + $want + '"'); Set-Content $cfgPath $c
    Write-Host "Engine set to $($Arg.ToLower()) ($want). Reloading model..."
    try { Invoke-RestMethod -Method Post "$swap/api/models/unload" -Headers $h | Out-Null } catch {}
    Write-Host 'Done - the next request (or the governor prewarm) loads the new engine.'
  }
  'bench' { powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\bench\regression.ps1 }
  'log' { Get-Content "$dir\governor.log" -Tail 25 }
  'doctor' { powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\doctor.ps1" }
  { $_ -in 'snapshot', 'history', 'rollback', 'diff' } { powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\snapshot.ps1" $Cmd $Arg }
  'window' {
    # Safe client context window = loaded ctx (or expected ctx if not loaded) minus 8k headroom
    $w = 100000
    try { $s = Get-Content "$dir\public\status.json" -Raw | ConvertFrom-Json
          $c = if ($s.loaded -and $s.n_ctx) { [int]$s.n_ctx } elseif ($s.expected_ctx) { [int]$s.expected_ctx } else { 0 }
          if ($Arg -eq 'long') { $c = 262144 }
          # never exceed the server's real ctx (minus 8k headroom), otherwise the agent overflows before it compacts
          if ($c -gt 0) { $w = [math]::Max(16384, $c - 8192) } } catch {}
    Write-Output $w
  }
  default { Write-Host 'qwen status | mode auto|max|balanced|lean|off | load [fast] | unload | restart | log' }
}


