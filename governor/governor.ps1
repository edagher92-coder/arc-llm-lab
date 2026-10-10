# Qwen governor: adapts the local model to how the PC is being used. Runs hidden in the user session.
# Never interrupts a request: reloads/unloads only happen when the model has been quiet.
$ErrorActionPreference = 'Continue'
$dir = 'C:\AI\governor'
$swap = 'http://127.0.0.1:8090'
$model = 'qwen3.8-27b'                         # default variant (prewarm target)
$ids = @('qwen3.8-27b', 'qwen3.8-27b-turbo', 'qwen3.8-27b-long', 'qwen3.8-27b-big')    # governed 27B variants
$ports = @{ 'qwen3.8-27b' = 10001; 'qwen3.8-27b-turbo' = 10003; 'qwen3.8-27b-long' = 10004; 'qwen3.8-27b-big' = 10005 }
$script:curId = $model; $script:curPort = 10001
$task = 'Local Qwen (llama-swap)'
$vramTotal = 25641877504.0   # Arc Pro B60 heap 0 (vulkaninfo)

Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class IdleTime {
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  public static double Seconds() { var l = new LASTINPUTINFO(); l.cbSize = (uint)Marshal.SizeOf(l);
    if (!GetLastInputInfo(ref l)) return 0; return ((uint)Environment.TickCount - l.dwTime) / 1000.0; }
}
'@

function Log($m) {
  $f = "$dir\governor.log"
  try { if ((Test-Path $f) -and (Get-Item $f).Length -gt 5MB) { Move-Item $f "$f.1" -Force } } catch {}
  "$(Get-Date -f s) $m" | Add-Content $f
}
function Key { (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim() }
function Api($method, $path, $body = $null, $timeout = 10) {
  $h = @{ Authorization = "Bearer $(Key)" }
  if ($body) { return Invoke-RestMethod -Method $method -Uri "$swap$path" -Headers $h -Body ($body | ConvertTo-Json -Depth 5) -ContentType 'application/json' -TimeoutSec $timeout }
  return Invoke-RestMethod -Method $method -Uri "$swap$path" -Headers $h -TimeoutSec $timeout
}
function Mode { try { $m = (Get-Content "$dir\mode.txt" -ErrorAction Stop).Trim().ToUpper(); if ($m -in 'AUTO','MAX','BALANCED','LEAN','OFF') { return $m } } catch {}; 'AUTO' }

function Sense {
  $s = [ordered]@{ idle_sec = [math]::Round([IdleTime]::Seconds()) }
  $c = Get-Counter -Counter '\Memory\Available MBytes','\Processor(_Total)\% Processor Time','\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue
  $smp = $c.CounterSamples
  $s.ram_avail_gb = [math]::Round((($smp | ? Path -like '*available mbytes').CookedValue | measure -Sum).Sum / 1024, 2)
  $s.cpu_total = [math]::Round((($smp | ? Path -like '*processor(_total)*').CookedValue | measure -Sum).Sum, 1)
  $vUsed = (($smp | ? Path -like '*gpu adapter memory*').CookedValue | measure -Sum).Sum
  $pids = @(Get-Process llama-server -ErrorAction SilentlyContinue | % Id)
  $llamaV = 0.0; $llamaCpu = 0.0
  if ($pids.Count) {
    $g = (Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples
    foreach ($id in $pids) { $llamaV += (($g | ? InstanceName -like "pid_$($id)_*").CookedValue | measure -Sum).Sum }
    $pc = (Get-Counter '\Process(llama-server*)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples
    $llamaCpu = (($pc.CookedValue | measure -Sum).Sum) / [Environment]::ProcessorCount
  }
  $s.vram_used_gib = [math]::Round($vUsed / 1GB, 2)
  $s.vram_free_gib = [math]::Round(($vramTotal - $vUsed) / 1GB, 2)
  $s.vram_llama_gib = [math]::Round($llamaV / 1GB, 2)
  $s.vram_others_gib = [math]::Round(($vUsed - $llamaV) / 1GB, 2)
  $s.cpu_others = [math]::Round([math]::Max(0, $s.cpu_total - $llamaCpu), 1)
  $s
}
function ModelState {
  $st = [ordered]@{ loaded = $false; state = 'stopped'; other_running = $null; processing = $false; tokens = $null; n_ctx = $null }
  try { $r = (Api GET '/running').running } catch { $st.state = 'swap-down'; return $st }
  foreach ($m in @($r)) {
    if ($ids -contains $m.model) { $st.state = $m.state; $st.loaded = ($m.state -eq 'ready'); $script:curId = $m.model
      $script:curPort = $ports[$m.model] }
    elseif ($m.model) { $st.other_running = $m.model }
  }
  $st.id = $script:curId
  if ($st.loaded) {
    try {
      $sl = Invoke-RestMethod "http://127.0.0.1:$($script:curPort)/slots" -TimeoutSec 5
      $st.processing = [bool](@($sl) | ? { $_.is_processing })
      $st.prompt_tokens = [int](@($sl) | % { [int]$_.n_prompt_tokens + [int]$_.params.n_predict } | measure -Maximum).Maximum
      if (-not $script:ctxCache) { $script:ctxCache = (Invoke-RestMethod "http://127.0.0.1:$($script:curPort)/props" -TimeoutSec 5).default_generation_settings.n_ctx }
      $st.n_ctx = $script:ctxCache
      $met = Invoke-WebRequest "http://127.0.0.1:$($script:curPort)/metrics" -UseBasicParsing -TimeoutSec 5
      $st.tokens = ([regex]::Matches($met.Content, '(?m)^llamacpp:(prompt_tokens_total|tokens_predicted_total)\s+([\d.e+]+)') | % { [double]$_.Groups[2].Value } | measure -Sum).Sum
    } catch {}
  } else { $script:ctxCache = $null }
  $st
}
function LoadedProfile { try { (Get-Content "$dir\running.json" -Raw | ConvertFrom-Json).profile } catch { $null } }
function Unload($why) { try { Api POST "/api/models/unload/$($script:curId)" | Out-Null; Log "UNLOAD ($why)"; $script:lastReload = Get-Date; $script:ctxCache = $null } catch { Log "unload failed: $($_.Exception.Message)" } }
function Prewarm($why) {
  $script:lastPrewarm = Get-Date
  try {
    $hdr = "$dir\.auth-header"; "Authorization: Bearer $(Key)" | Set-Content $hdr -NoNewline
    $body = "$dir\.prewarm.json"; '{"model":"' + $script:curId + '","max_tokens":1,"messages":[{"role":"user","content":"hi"}],"chat_template_kwargs":{"enable_thinking":false}}' | Set-Content $body -NoNewline
    Start-Process curl.exe -WindowStyle Hidden -ArgumentList '-s','-m','300','-o','NUL','-H',('@' + $hdr),'-H','"Content-Type: application/json"','--data-binary',('@' + $body),"$swap/v1/chat/completions" | Out-Null
    Log "PREWARM ($why)"
  } catch { Log "prewarm failed: $($_.Exception.Message)" }
}
# ---- smart Windows power plan: SAVER when nobody is using the PC or the model, PERFORMANCE under load ----
$planGuid = @{ PERFORMANCE = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'; BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'; SAVER = 'a1841308-3541-4fab-bc81-f71556f20b4a' }
$script:powNow = $null; $script:powCand = $null; $script:powCount = 0; $script:cpuBusy = 0
function PowerMode { try { $p = (Get-Content "$dir\power.txt" -ErrorAction Stop).Trim().ToUpper(); if ($p -in 'AUTO','PERFORMANCE','BALANCED','SAVER') { return $p } } catch {}; 'AUTO' }
function ApplyPower($s, $quietSec, $modelBusy) {
  $pm = PowerMode
  if ($s.cpu_total -ge 40) { $script:cpuBusy++ } elseif ($s.cpu_total -lt 25) { $script:cpuBusy = 0 }
  if ($pm -ne 'AUTO') { $want = $pm }
  elseif ($modelBusy -or $quietSec -lt 120 -or $script:cpuBusy -ge 2) { $want = 'PERFORMANCE' }
  elseif ($s.idle_sec -ge 600 -and $quietSec -ge 300 -and $s.cpu_total -lt 25) { $want = 'SAVER' }
  else { $want = 'BALANCED' }
  if ($want -eq $script:powCand) { $script:powCount++ } else { $script:powCand = $want; $script:powCount = 1 }
  $rank = @{ SAVER = 0; BALANCED = 1; PERFORMANCE = 2 }
  $up = ($script:powNow -eq $null) -or ($rank[$want] -gt $rank[$script:powNow])
  if ($want -ne $script:powNow -and ($up -or $script:powCount -ge 4 -or $pm -ne 'AUTO')) {
    $act = (powercfg /getactivescheme) -replace '.*GUID:\s*([0-9a-f-]+).*', '$1'
    if ($act.Trim() -ne $planGuid[$want]) { powercfg /setactive $planGuid[$want] | Out-Null; Log "power $($script:powNow) -> $want (idle=$($s.idle_sec)s modelQuiet=$([math]::Round($quietSec))s cpu=$($s.cpu_total)%)" }
    $script:powNow = $want
  }
  $script:powNow
}
function SetPriority($prof) {
  $want = if ($prof -eq 'MAX') { 'Normal' } else { 'BelowNormal' }
  Get-Process llama-server -ErrorAction SilentlyContinue | % { try { if ("$($_.PriorityClass)" -ne $want) { $_.PriorityClass = $want } } catch {} }
}

# ---- main loop ----
$cfg = Get-Content "$dir\profiles.json" -Raw | ConvertFrom-Json; $A = $cfg.auto
$committed = 'BALANCED'; $candidate = $null; $count = 0
$lastBusy = Get-Date; $lastTokens = $null; $script:lastReload = (Get-Date).AddHours(-1); $script:lastPrewarm = (Get-Date).AddHours(-1)
$swapFails = 0; $lastRestart = (Get-Date).AddHours(-1); $cpuHigh = 0; $script:lastTsStart = (Get-Date).AddHours(-1)
if (-not (Test-Path "$dir\mode.txt")) { 'AUTO' | Set-Content "$dir\mode.txt" }
Set-Content "$dir\desired.txt" $committed
Log "governor start pid=$PID"
while ($true) {
  try {
    $cfg = Get-Content "$dir\profiles.json" -Raw | ConvertFrom-Json; $A = $cfg.auto
    $mode = Mode; $s = Sense; $m = ModelState; $now = Get-Date
    # --- watchdog for llama-swap ---
    if ($m.state -eq 'swap-down') {
      $swapFails++
      if ($swapFails -ge 3 -and ($now - $lastRestart).TotalMinutes -ge 5) { Log "WATCHDOG: llama-swap not responding, restarting task"; Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue; Get-Process llama-swap -ErrorAction SilentlyContinue | Stop-Process -Force; Get-Process llama-server -ErrorAction SilentlyContinue | ? { $_.Path -like 'C:\AI\*' } | Stop-Process -Force; Start-Sleep 3; Start-ScheduledTask -TaskName $task; $lastRestart = $now; $swapFails = 0 }
    } else { $swapFails = 0 }
    # --- keep Tailscale's user backend alive (without tailscale-ipn the daemon sits in NoState and remote access dies) ---
    if (-not (Get-Process tailscale-ipn -ErrorAction SilentlyContinue) -and (Test-Path 'C:\Program Files\Tailscale\tailscale-ipn.exe') -and ($now - $script:lastTsStart).TotalMinutes -ge 5) {
      $script:lastTsStart = $now; Start-Process 'C:\Program Files\Tailscale\tailscale-ipn.exe'; Log 'WATCHDOG: tailscale-ipn was not running - started it' }
    # --- activity of the model ---
    if ($m.processing -or ($m.tokens -ne $null -and $lastTokens -ne $null -and $m.tokens -ne $lastTokens) -or $m.state -eq 'starting') { $lastBusy = $now }
    $lastTokens = $m.tokens
    $quietSec = ($now - $lastBusy).TotalSeconds
    # --- live-session tracking (largest prompt seen in the last 60 min) for session-protected resizing ---
    if ($m.prompt_tokens -gt 0) { $script:needLog += ,@($now, [int]$m.prompt_tokens) }
    $script:needLog = @($script:needLog | ? { ($now - $_[0]).TotalMinutes -le 60 })
    $sessNeed = [int](($script:needLog | % { $_[1] } | measure -Maximum).Maximum)
    Set-Content "$dir\session-need.txt" $sessNeed
    $power = $null; try { $power = ApplyPower $s $quietSec ($m.processing -or $m.state -eq 'starting') } catch { Log "power error: $($_.Exception.Message)" }
    # --- choose profile ---
    if ($s.cpu_others -ge $A.others_cpu_lean_pct) { $cpuHigh++ } else { $cpuHigh = 0 }
    $pressure = ($s.ram_avail_gb -lt $A.ram_floor_gb) -or ($s.vram_others_gib -gt $A.others_vram_lean_gib) -or ($cpuHigh -ge 8)
    if ($mode -ne 'AUTO' -and $mode -ne 'OFF') { $want = $mode }
    elseif ($pressure) { $want = 'LEAN' }
    elseif ($s.idle_sec -ge $A.idle_for_max_sec -and $s.ram_avail_gb -ge $A.ram_for_max_gb -and $s.vram_others_gib -lt $A.others_vram_max_gib) { $want = 'MAX' }
    else { $want = 'BALANCED' }
    if ($want -eq $candidate) { $count++ } else { $candidate = $want; $count = 1 }
    if ($want -ne $committed -and ($count -ge $A.confirm_samples -or $mode -ne 'AUTO')) { Log "profile $committed -> $want (idle=$($s.idle_sec)s ram=$($s.ram_avail_gb)GB othersVRAM=$($s.vram_others_gib)GiB cpuOthers=$($s.cpu_others)%)"; $committed = $want; Set-Content "$dir\desired.txt" $committed }
    $loadedProf = if ($m.loaded) { LoadedProfile } else { $null }
    if ($m.loaded) { SetPriority $committed }
    # --- actions (never while busy) ---
    $sinceReload = ($now - $script:lastReload).TotalMinutes
    if ($mode -eq 'OFF') {
      if ($m.loaded -and -not $m.processing -and $quietSec -ge 30) { Unload 'mode OFF' }
    } elseif ($m.loaded -and -not $m.processing) {
      $acute = ($s.vram_free_gib -lt $A.vram_free_pressure_gib) -or ($s.ram_avail_gb -lt $A.ram_floor_gb) -or ($s.vram_others_gib -gt $A.others_vram_lean_gib)
      $idleLimit = $cfg.profiles.$committed.idle_unload_min
      if ($acute -and $quietSec -ge 30) {
        if ($committed -eq 'LEAN') { Unload "pressure, LEAN" }
        elseif ($sinceReload -ge 3 -and $script:curId -ne 'qwen3.8-27b-long') { Unload "free VRAM $($s.vram_free_gib) GiB < $($A.vram_free_pressure_gib) -> re-fit context ($committed)"; Prewarm "re-fit as $committed" }
      }
      elseif ($idleLimit -gt 0 -and $quietSec -ge $idleLimit * 60) { Unload "idle $([math]::Round($quietSec/60)) min in $committed" }
      elseif ($loadedProf -eq 'LEAN' -and $committed -ne 'LEAN' -and $quietSec -ge $A.model_quiet_sec_before_reload -and $sinceReload -ge 10) { Unload "upgrade LEAN -> $committed"; Prewarm "upgrade to $committed" }
      elseif ($loadedProf -eq 'BALANCED' -and $committed -eq 'MAX' -and $quietSec -ge $A.max_upgrade_quiet_min * 60 -and $sinceReload -ge 10) { Unload "upgrade BALANCED -> MAX"; Prewarm "upgrade to MAX" }
    } elseif (-not $m.loaded -and $m.state -eq 'stopped' -and $committed -eq 'MAX' -and -not $m.other_running -and ($now - $script:lastPrewarm).TotalMinutes -ge $A.prewarm_cooldown_min) {
      Prewarm 'PC idle - keep model warm in MAX'
    }
    # --- status for humans / remote ---
    $status = [ordered]@{ time = $now.ToString('s'); mode = $mode; profile = $committed; loaded = $m.loaded; loaded_profile = $loadedProf; state = $m.state
      processing = $m.processing; n_ctx = $m.n_ctx; model_quiet_min = [math]::Round($quietSec / 60, 1); other_model = $m.other_running }
    foreach ($k in $s.Keys) { $status[$k] = $s[$k] }
    # expected context if the default model were (re)loaded now with the current profile
    try { $vd = $cfg.variants.default; $pp = $cfg.profiles.$committed; $oth = if ($m.loaded) { $s.vram_others_gib } else { $s.vram_used_gib }
          $ec = [int]([math]::Floor((($cfg.vram.total_gib - $pp.free_margin_gib - $oth - $vd.base_gib) * 1MB) / $vd.kv_kib_per_token / 4096) * 4096)
          $status['expected_ctx'] = [math]::Max([int]$pp.ctx_min, [math]::Min([int]$vd.ctx_max, $ec)) } catch {}
    $status['model_id'] = $script:curId
    $status['power_plan'] = $power; $status['power_mode'] = PowerMode; $status['session_need_tokens'] = $sessNeed
    $status | ConvertTo-Json | Set-Content "$dir\public\status.json"
  } catch { Log "loop error: $($_.Exception.Message)" }
  Start-Sleep -Seconds ([int]$A.sample_sec)
}


