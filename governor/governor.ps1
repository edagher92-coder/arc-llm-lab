# Qwen governor v4 (2026-10-15): adapts the local model to how the PC is being used. Runs hidden in the user session
# as the scheduled task "Local Qwen Governor". Windows PowerShell 5.1.
#
# Rules of this file
#  - Never interrupts a request: every unload re-checks /slots and /metrics for a request in flight first.
#  - One failed read (PDH counter, JSON file, HTTP to llama-swap/llama-server, process query) never kills the loop
#    and never becomes a number we act on: readings are validated, invalid ones keep the last good value and are
#    marked degraded. status.json is written on EVERY sample, degraded or not.
#  - Pressure must persist (pressure_persist_sec, 60 s) before any unload/re-fit; re-fits and upgrades happen at
#    most once per refit_min_interval_min (15 min). The KV slot is saved before a governor-initiated unload and
#    restored after the relaunch (slotlib.ps1), so agent clients keep their cached prefix.
#  - The power plan (GovPowerDecide, v4.2) has hysteresis: upgrades at once, downgrades one step per power.dwell_min
#    (10) and only after the lower demand persisted for the whole dwell; BALANCED floor while an agent client is active;
#    SAVER only when the PC is idle >= 15 min AND the model quiet >= 15 min. Every transition is logged with its reason.
#  - The pure decision functions (Gov*) mirror govpolicy.py, which has the pytest suite (test_govpolicy.py).
#    Change a rule in both places (GovPowerDecide is PowerShell-only so far). `. governor.ps1 -FunctionsOnly` loads
#    them for test_governor.ps1.
param([switch]$FunctionsOnly)
$ErrorActionPreference = 'Continue'
$dir = 'C:\AI\governor'
$swap = 'http://127.0.0.1:8090'
$model = 'qwen3.8-27b'                         # default variant (prewarm target)
$ids = @('qwen3.8-27b', 'qwen3.8-27b-turbo', 'qwen3.8-27b-long', 'qwen3.8-27b-big')    # governed 27B variants
$ports = @{ 'qwen3.8-27b' = 10001; 'qwen3.8-27b-turbo' = 10003; 'qwen3.8-27b-long' = 10004; 'qwen3.8-27b-big' = 10005 }
$script:curId = $model; $script:curPort = 10001
$task = 'Local Qwen (llama-swap)'
$script:vramTotalGib = 23.88                   # Arc Pro B60 heap 0 (vulkaninfo); overridden by profiles.json vram.total_gib

# constants mirrored in govpolicy.py
$GOV_LOADED_MIN_ADAPTER_GIB = 8.0
$GOV_LOADED_MIN_LLAMA_GIB = 4.0
$GOV_OTHERS_JUMP_GIB = 4.0
$GOV_OTHERS_CONFIRM_SAMPLES = 4
$GOV_OTHERS_PLAUSIBLE_MAX_GIB = 8.0

try {
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class IdleTime {
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  public static double Seconds() { var l = new LASTINPUTINFO(); l.cbSize = (uint)Marshal.SizeOf(l);
    if (!GetLastInputInfo(ref l)) return 0; return ((uint)Environment.TickCount - l.dwTime) / 1000.0; }
}
'@ -ErrorAction Stop
} catch {}

# ============================================================ logging ============================================================
function Log($m) {
  $f = "$dir\governor.log"
  try { if ((Test-Path $f) -and (Get-Item $f).Length -gt 5MB) { Move-Item $f "$f.1" -Force } } catch {}
  try { "$(Get-Date -f s) $m" | Add-Content $f -ErrorAction Stop } catch { try { Start-Sleep -Milliseconds 200; "$(Get-Date -f s) $m" | Add-Content $f -ErrorAction Stop } catch {} }
}
$script:onceKeys = @{}
function LogOnce($key, $m) { if (-not $script:onceKeys.ContainsKey($key)) { $script:onceKeys[$key] = (Get-Date); Log $m } }
# log a repeating condition once, then at most every $everyMin minutes
function LogEvery($key, $everyMin, $m) {
  $t = $script:onceKeys[$key]
  if (($null -eq $t) -or (((Get-Date) - $t).TotalMinutes -ge $everyMin)) { $script:onceKeys[$key] = (Get-Date); Log $m }
}
function ClearOnce($key) { if ($script:onceKeys.ContainsKey($key)) { $script:onceKeys.Remove($key) } }

# ============================================================ null-safe helpers ============================================================
# Run a read; never throw. Returns @{ ok; value; err }.
function Attempt([scriptblock]$sb) {
  try { $v = & $sb; return @{ ok = $true; value = $v; err = $null } }
  catch { return @{ ok = $false; value = $null; err = $_.Exception.Message } }
}
# Run a read and return its value or $fallback. Never throws.
function Try1([scriptblock]$sb, $fallback = $null) { $r = Attempt $sb; if ($r.ok -and ($null -ne $r.value)) { return $r.value }; return $fallback }
function GovIsNum($v) { ($v -is [int]) -or ($v -is [long]) -or ($v -is [double]) -or ($v -is [decimal]) -or ($v -is [single]) -or ($v -is [int16]) -or ($v -is [uint32]) -or ($v -is [uint64]) }
function GovClamp($v, $lo, $hi) { if ($v -lt $lo) { return $lo }; if ($v -gt $hi) { return $hi }; return $v }
function ReadJsonFile($path, $fallback = $null) {
  try { if (Test-Path -LiteralPath $path) { return (Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json) } } catch {}
  return $fallback
}
function ReadTextFile($path, $fallback = $null) {
  try { if (Test-Path -LiteralPath $path) { return ([string](Get-Content -LiteralPath $path -Raw -ErrorAction Stop)).Trim() } } catch {}
  return $fallback
}
function WriteText($path, $text) { [IO.File]::WriteAllText($path, [string]$text, (New-Object System.Text.UTF8Encoding($false))) }
function Key { $k = ReadTextFile 'C:\AI\llama-swap\api-key.txt' ''; return $k }
# HTTP JSON GET/POST to llama-swap (authenticated). Throws on failure: wrap with Attempt/Try1.
function Api($method, $path, $body = $null, $timeout = 10) {
  $h = @{ Authorization = "Bearer $(Key)" }
  if ($body) { return Invoke-RestMethod -Method $method -Uri "$swap$path" -Headers $h -Body ($body | ConvertTo-Json -Depth 5) -ContentType 'application/json' -TimeoutSec $timeout }
  return Invoke-RestMethod -Method $method -Uri "$swap$path" -Headers $h -TimeoutSec $timeout
}
function HttpJson($uri, $timeout = 5) { return Try1 { Invoke-RestMethod -Uri $uri -TimeoutSec $timeout } $null }
function HttpText($uri, $timeout = 5) { return Try1 { (Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec $timeout).Content } $null }
# PDH: each path is queried on its own (one flaky counter must not spoil the others) and only samples whose
# Status is 0 are returned. A failed query ("Internal performance counter API call failed", 800007d8) or an
# invalid sample set gives @(), never zeros.
function Counters([string[]]$paths) {
  $out = @()
  foreach ($p in $paths) {
    $r = Attempt { Get-Counter -Counter $p -ErrorAction SilentlyContinue }
    if (-not $r.ok -or $null -eq $r.value) { continue }
    foreach ($smp in @($r.value.CounterSamples)) { if ($null -ne $smp -and $smp.Status -eq 0) { $out += $smp } }
  }
  return $out
}
# process ids by name; always a real array (possibly empty), never $null and never @($null)
function ProcIds($name) {
  # v4.3 (2026-10-17): 'llama-server' means OUR engine only (C:\AI\llama.cpp\*). Ollama ships its own llama-server.exe
  # (C:\Apps\Ollama\lib\ollama\); on 17 Oct its llama3.2:3b runner (3.07 GiB, 24 h keep-alive) was booked as the model,
  # so 'others' read 3 GiB low, the fit over-committed and free VRAM sat at 0.56 GiB (calib.json 15:44).
  $out = @()
  $r = Attempt { Get-Process -Name $name -ErrorAction Stop }
  if ($r.ok) { foreach ($x in @($r.value)) { if ($null -eq $x) { continue }
    if ($name -eq 'llama-server') { $p = $null; try { $p = $x.Path } catch {}; if ($p -and ($p -notlike 'C:\AI\llama.cpp\*')) { continue } }
    $out += [int]$x.Id } }
  return ,$out
}
function Mode { $m = ReadTextFile "$dir\mode.txt" 'AUTO'; $m = $m.ToUpper(); if ($m -in 'AUTO','MAX','BALANCED','LEAN','OFF') { return $m }; 'AUTO' }
function PowerMode { $p = ReadTextFile "$dir\power.txt" 'AUTO'; $p = $p.ToUpper(); if ($p -in 'AUTO','PERFORMANCE','BALANCED','SAVER') { return $p }; 'AUTO' }
function CfgNum($obj, $name, $default) { try { $v = $obj.$name; if (GovIsNum $v) { return [double]$v } } catch {}; return [double]$default }
function CfgBool($obj, $name, $default) { try { $v = $obj.$name; if ($v -is [bool]) { return $v }; if (GovIsNum $v) { return ($v -ne 0) } } catch {}; return [bool]$default }

# ============================================================ pure decisions (mirror govpolicy.py) ============================================================
# Turn the two PDH readings into trusted numbers. Returns @{ m = <ordered: used free llama others ok warn>; suspect = <int> }.
function GovValidateVram($adapterGib, $llamaGib, $totalGib, $loaded, $llamaAlive, $lastGood, $suspectCount, $starting = $false) {
  $warn = @()
  $lg = $lastGood
  $adapterOk = (GovIsNum $adapterGib) -and ($adapterGib -ge 0.0) -and ($adapterGib -le $totalGib * 1.05)
  if (-not $adapterOk) { $warn += "adapter counter invalid ($adapterGib)" }
  elseif ($loaded -and $adapterGib -lt $GOV_LOADED_MIN_ADAPTER_GIB) { $adapterOk = $false; $warn += ('adapter counter reads {0:F2} GiB while the model is loaded (impossible)' -f $adapterGib) }
  if (-not $adapterOk) {
    if ($lg) { $m = [ordered]@{ used = $lg.used; free = $lg.free; llama = $lg.llama; others = $lg.others; ok = $false; warn = $warn }; return @{ m = $m; suspect = $suspectCount } }
    return @{ m = [ordered]@{ used = $null; free = $null; llama = $null; others = $null; ok = $false; warn = $warn }; suspect = $suspectCount }
  }
  $used = [double]$adapterGib
  $free = GovClamp ($totalGib - $used) 0.0 $totalGib
  $llamaOk = (GovIsNum $llamaGib) -and ($llamaGib -ge 0.0) -and ($llamaGib -le $used + 0.5)
  if ($llamaOk -and $loaded -and $llamaGib -lt $GOV_LOADED_MIN_LLAMA_GIB) { $llamaOk = $false; $warn += ('process counter reads {0:F2} GiB for a loaded model (lagging)' -f $llamaGib) }
  if (-not $llamaOk -and (GovIsNum $llamaGib) -and -not $loaded) { $llamaOk = $true }
  $lgOthersNum = ($null -ne $lg) -and (GovIsNum $lg.others)
  if ($llamaOk) { $llama = GovClamp ([double]$llamaGib) 0.0 $used }
  elseif ($loaded -and $lgOthersNum) { $llama = GovClamp ($used - [double]$lg.others) 0.0 $used }
  elseif ($loaded) { $llama = $used }
  else { $llama = 0.0 }
  if (-not $llamaAlive -and -not $loaded) { $llama = 0.0 }
  $others = GovClamp ($used - $llama) 0.0 $totalGib
  $ok = $true
  if ($starting) {
    $warn += 'model starting: keeping last good others'
    if ($lgOthersNum) { $others = [double]$lg.others; $llama = GovClamp ($used - $others) 0.0 $used } else { $others = $null }
    $m = [ordered]@{ used = [math]::Round($used, 2); free = [math]::Round($free, 2); llama = [math]::Round($llama, 2); others = $(if ($null -eq $others) { $null } else { [math]::Round($others, 2) }); ok = $false; warn = $warn }
    return @{ m = $m; suspect = $suspectCount }
  }
  if ($lgOthersNum -and ([math]::Abs($others - [double]$lg.others) -gt $GOV_OTHERS_JUMP_GIB)) {
    $suspectCount++
    if ($suspectCount -lt $GOV_OTHERS_CONFIRM_SAMPLES) {
      $warn += ('others jumped {0:F2} -> {1:F2} GiB; keeping last good until confirmed ({2}/{3})' -f [double]$lg.others, $others, $suspectCount, $GOV_OTHERS_CONFIRM_SAMPLES)
      $others = [double]$lg.others; $llama = GovClamp ($used - $others) 0.0 $used; $ok = $false
    } else { $warn += "others change confirmed after $suspectCount samples"; $suspectCount = 0 }
  } else { $suspectCount = 0 }
  if (($null -ne $others) -and ($others -gt $GOV_OTHERS_PLAUSIBLE_MAX_GIB) -and -not $loaded -and $llamaAlive) {
    $warn += ('others {0:F2} GiB with a llama-server alive but not ready: ignoring' -f $others)
    if ($lgOthersNum) { $others = [double]$lg.others } else { $others = $null }
    $ok = $false
  }
  $m = [ordered]@{ used = [math]::Round($used, 2); free = [math]::Round($free, 2); llama = [math]::Round($llama, 2); others = $(if ($null -eq $others) { $null } else { [math]::Round($others, 2) }); ok = $ok; warn = $warn; llama_measured = ($llamaOk -and $ok -and $loaded -and (GovIsNum $llamaGib) -and ($llamaGib -ge $GOV_LOADED_MIN_LLAMA_GIB)) }
  return @{ m = $m; suspect = $suspectCount }
}
# Available RAM in GB: 0 or an absurd value is a failed PDH sample, not an empty machine. Returns @{ gb; ok }.
function GovValidateRam($ramGb, $lastGoodGb) {
  if ((GovIsNum $ramGb) -and ($ramGb -ge 0.05) -and ($ramGb -le 2048.0)) { return @{ gb = [double]$ramGb; ok = $true } }
  return @{ gb = $lastGoodGb; ok = $false }
}
# Consecutive samples of REAL pressure; invalid samples reset it (a reading we cannot trust is no evidence).
# A re-fit must mean OTHER apps grew: low free VRAM alone is the model's own steady state after a tight fit (2026-10-16:
# ctx 40960 left 0.65 GiB free and v4.0 re-fitted onto the same footprint every 15 min). free < threshold counts only when
# others has grown >= $growthMin since the post-launch baseline; no baseline -> it does not count. free < $hardFloor always counts.
function GovPressureStep($count, $freeGib, $ramGb, $vramOk, $ramOk, $freeThreshold, $ramCritical, $othersGib = $null, $baselineOthers = $null, $growthMin = 0.5, $hardFloor = 0.25) {
  $now = $false
  if ($vramOk -and (GovIsNum $freeGib)) {
    if ($freeGib -lt $hardFloor) { $now = $true }
    elseif (($freeGib -lt $freeThreshold) -and (GovIsNum $othersGib) -and (GovIsNum $baselineOthers) -and (($othersGib - $baselineOthers) -ge $growthMin)) { $now = $true }
  }
  if ($ramOk -and (GovIsNum $ramGb) -and ($ramGb -lt $ramCritical)) { $now = $true }
  if ($now) { return ($count + 1) }; return 0
}
function GovPressureReason($freeGib, $ramGb, $freeThreshold, $ramCritical, $othersGib = $null, $baselineOthers = $null, $hardFloor = 0.25) {
  $parts = @()
  if ((GovIsNum $freeGib) -and ($freeGib -lt $hardFloor)) { $parts += ('free VRAM {0:F2} GiB < hard floor {1:F2}' -f [double]$freeGib, [double]$hardFloor) }
  elseif ((GovIsNum $freeGib) -and ($freeGib -lt $freeThreshold)) {
    if ((GovIsNum $othersGib) -and (GovIsNum $baselineOthers)) { $parts += ('free VRAM {0:F2} GiB < {1:F2} with others {2:+0.00;-0.00} GiB since baseline {3:F2}' -f [double]$freeGib, [double]$freeThreshold, ([double]$othersGib - [double]$baselineOthers), [double]$baselineOthers) }
    else { $parts += ('free VRAM {0:F2} GiB < {1:F2}' -f [double]$freeGib, [double]$freeThreshold) }
  }
  if ((GovIsNum $ramGb) -and ($ramGb -lt $ramCritical)) { $parts += ('RAM {0:F2} GB < {1:F2}' -f [double]$ramGb, [double]$ramCritical) }
  if ($parts.Count -eq 0) { return 'no pressure' }; return ($parts -join ', ')
}
# After a launch the counters settle: take the baseline on the $need-th consecutive loaded sample with valid VRAM, a directly
# measured llama share and a known n_ctx. Returns @{ count; take }.
function GovBaselineReady($loaded, $vramOk, $llamaMeasured, $nCtx, $stableCount, $need = 2) {
  if ($loaded -and $vramOk -and $llamaMeasured -and (GovIsNum $nCtx) -and ($nCtx -gt 0)) { $stableCount++; return @{ count = $stableCount; take = ($stableCount -ge $need) } }
  return @{ count = 0; take = $false }
}
function GovPredictedLlamaGib($baseGib, $ctx, $kvKibPerToken, $overheadGib = 0.0) { return ([double]$baseGib + [double]$overheadGib + [double]$ctx * [double]$kvKibPerToken / 1048576.0) }
# Learn the footprint launch.ps1's model misses (drafter KV, mmproj, compute buffers): EMA of (measured - predicted), clamped.
# Returns @{ overhead; predicted; delta }.
function GovCalibrate($prevOverhead, $llamaActualGib, $baseGib, $ctx, $kvKibPerToken, $alpha = 0.5, $maxOverhead = 1.5, $minOverhead = -0.5) {
  $predicted = [double]$baseGib + [double]$ctx * [double]$kvKibPerToken / 1048576.0
  $raw = [double]$llamaActualGib - $predicted
  $delta = GovClamp $raw $minOverhead $maxOverhead
  if (GovIsNum $prevOverhead) { $new = [double]$prevOverhead + $alpha * ($delta - [double]$prevOverhead) } else { $new = $delta }
  return @{ overhead = [math]::Round($new, 2); predicted = [math]::Round($predicted, 2); delta = [math]::Round($raw, 2) }
}
# What launch.ps1 adds to base_gib: the learned overhead, never negative.
function GovLaunchOverhead($calibEntry, $enabled = $true, $maxOverhead = 1.5) {
  if (-not $enabled -or ($null -eq $calibEntry)) { return 0.0 }
  $v = $null; try { $v = $calibEntry.overhead_gib } catch {}
  if (-not (GovIsNum $v)) { return 0.0 }
  return [math]::Round((GovClamp ([double]$v) 0.0 $maxOverhead), 2)
}
# After a re-fit that landed on the same ctx (+- one step) as before, block further re-fits until others changed >= $growthMin.
function GovRefitRepeatBlocked($prevCtx, $newCtx, $othersNow, $othersAtRefit, $growthMin = 0.5, $step = 4096) {
  if (-not ((GovIsNum $prevCtx) -and (GovIsNum $newCtx))) { return $false }
  if ([math]::Abs([double]$newCtx - [double]$prevCtx) -gt $step) { return $false }
  if ((GovIsNum $othersNow) -and (GovIsNum $othersAtRefit) -and ([math]::Abs([double]$othersNow - [double]$othersAtRefit) -ge $growthMin)) { return $false }
  return $true
}
# Which profile AUTO wants this sample ($a = profiles.json 'auto'). Invalid readings never push LEAN.
function GovProfileChoice($mode, $idleSec, $ramGb, $ramOk, $othersGib, $othersOk, $cpuHighCount, $a) {
  if ($mode -ne 'AUTO' -and $mode -ne 'OFF') { return $mode }
  $pressure = ($ramOk -and (GovIsNum $ramGb) -and ($ramGb -lt (CfgNum $a 'ram_floor_gb' 3.5))) -or
              ($othersOk -and (GovIsNum $othersGib) -and ($othersGib -gt (CfgNum $a 'others_vram_lean_gib' 3.5))) -or
              ($cpuHighCount -ge 8)
  if ($pressure) { return 'LEAN' }
  if (($idleSec -ge (CfgNum $a 'idle_for_max_sec' 600)) -and $ramOk -and (GovIsNum $ramGb) -and ($ramGb -ge (CfgNum $a 'ram_for_max_gb' 8.0)) -and
      $othersOk -and (GovIsNum $othersGib) -and ($othersGib -lt (CfgNum $a 'others_vram_max_gib' 3.0))) { return 'MAX' }
  return 'BALANCED'
}
# One sample's action from a hashtable of inputs (see govpolicy.decide). Returns @{ action; reason }.
# action: none | unload | refit | upgrade | idle-unload | prewarm
function GovDecide($s) {
  if ($s.mode -eq 'OFF') {
    if ($s.loaded -and ($s.in_flight -eq $false) -and ($s.quiet_sec -ge 30)) { return @{ action = 'unload'; reason = 'mode OFF' } }
    return @{ action = 'none'; reason = 'mode OFF' }
  }
  if ($s.loaded) {
    if ($null -eq $s.in_flight) { return @{ action = 'none'; reason = 'slot state unknown' } }
    if ($s.in_flight -eq $true) { return @{ action = 'none'; reason = 'request in flight' } }
    $persistent = ($s.pressure_count -gt 0) -and (($s.pressure_count * $s.sample_sec) -ge $s.persist_sec)
    if ($persistent -and ($s.quiet_sec -ge 30)) {
      $hf = 0.25; if (GovIsNum $s.hard_floor) { $hf = $s.hard_floor }
      $why = GovPressureReason $s.free_gib $s.ram_gb $s.free_threshold $s.ram_critical $s.others_gib $s.baseline_others $hf
      if ($s.committed -eq 'LEAN') { return @{ action = 'unload'; reason = "pressure, LEAN ($why)" } }
      if (($s.cur_id -eq 'qwen3.8-27b-long') -or $s.emergency) { return @{ action = 'none'; reason = "pressure but protected ($why)" } }
      if ($s.refit_blocked) { return @{ action = 'none'; reason = "pressure but a re-fit would repeat the same ctx; waiting for others to change ($why)" } }
      if ($s.since_refit_min -ge $s.refit_interval_min) { return @{ action = 'refit'; reason = ('{0} for {1}s -> re-fit context ({2})' -f $why, ($s.pressure_count * $s.sample_sec), $s.committed) } }
      return @{ action = 'none'; reason = ('pressure persists but re-fit rate-limited ({0:F0}/{1} min)' -f [double]$s.since_refit_min, $s.refit_interval_min) }
    }
    if (($s.idle_unload_min -gt 0) -and ($s.quiet_sec -ge $s.idle_unload_min * 60)) {
      if ($s.agent_active) { return @{ action = 'none'; reason = 'idle but an agent client is active: stay warm' } }
      return @{ action = 'idle-unload'; reason = ('idle {0} min in {1}' -f [math]::Round($s.quiet_sec / 60), $s.committed) }
    }
    if (($s.loaded_profile -eq 'LEAN') -and ($s.committed -ne 'LEAN') -and ($s.quiet_sec -ge $s.quiet_before_reload_sec) -and ($s.since_refit_min -ge $s.refit_interval_min)) {
      return @{ action = 'upgrade'; reason = "upgrade LEAN -> $($s.committed)" } }
    if (($s.loaded_profile -eq 'BALANCED') -and ($s.committed -eq 'MAX') -and ($s.quiet_sec -ge $s.max_upgrade_quiet_min * 60) -and ($s.since_refit_min -ge $s.refit_interval_min)) {
      return @{ action = 'upgrade'; reason = 'upgrade BALANCED -> MAX' } }
    return @{ action = 'none'; reason = 'steady' }
  }
  if (($s.state -eq 'stopped') -and -not $s.other_running -and ($s.since_prewarm_min -ge $s.prewarm_cooldown_min)) {
    if ($s.committed -eq 'MAX') { return @{ action = 'prewarm'; reason = 'PC idle - keep model warm in MAX' } }
    if ($s.agent_active -and ($s.committed -ne 'LEAN')) { return @{ action = 'prewarm'; reason = 'agent client active - keep model warm' } }
  }
  return @{ action = 'none'; reason = "not loaded ($($s.state))" }
}
# Windows power plan with hysteresis (v4.2, 2026-10-16: v4.1 flipped the plan 104 times in 400 log lines, driven by CPU
# bursts from agent clients). Upgrades are immediate; downgrades go ONE step at a time and only after the lower demand
# has persisted for the whole dwell AND the current plan has been held for the dwell. While an agent client is active
# (codex/claude process, or a model request within agent_recent_min) the floor is BALANCED. SAVER needs the PC idle
# (no input) for saver_idle_min AND the model quiet for saver_model_quiet_min AND calm CPU.
#   $st: @{ now = <plan|$null>; entered = <datetime>; down_since = <datetime|$null>; cpu_busy = <int> }   (mutated and returned)
#   $in: @{ t = <datetime>; mode = AUTO|PERFORMANCE|BALANCED|SAVER; cpu = <pct|$null>; idle_sec; quiet_sec; model_busy; agent_active; cfg = profiles.json 'power' }
# Returns @{ st; want; apply = <plan to set now, or $null>; reason; why }.
$GOV_POWER_RANK = @{ SAVER = 0; BALANCED = 1; PERFORMANCE = 2 }
function GovPowerDecide($st, $in) {
  $p = $in.cfg
  $dwellSec = (CfgNum $p 'dwell_min' 10) * 60.0
  $saverIdleSec = (CfgNum $p 'saver_idle_min' 15) * 60.0
  $saverQuietSec = (CfgNum $p 'saver_model_quiet_min' 15) * 60.0
  $recentSec = CfgNum $p 'perf_model_recent_sec' 120
  $busyPct = CfgNum $p 'cpu_busy_pct' 40
  $busySamples = [int](CfgNum $p 'cpu_busy_samples' 2)
  $calmPct = CfgNum $p 'cpu_calm_pct' 25
  if ($null -eq $st) { $st = @{ now = $null; entered = $in.t; down_since = $null; cpu_busy = 0 } }
  $cpu = $in.cpu; if (-not (GovIsNum $cpu)) { $cpu = 30.0 }   # unknown CPU: neutral
  $busy = 0; if (GovIsNum $st.cpu_busy) { $busy = [int]$st.cpu_busy }
  if ($cpu -ge $busyPct) { $busy++ } elseif ($cpu -lt $calmPct) { $busy = 0 }
  $st.cpu_busy = $busy
  $idle = 0.0; if (GovIsNum $in.idle_sec) { $idle = [double]$in.idle_sec }
  $quiet = 0.0; if (GovIsNum $in.quiet_sec) { $quiet = [double]$in.quiet_sec }
  if ($in.mode -ne 'AUTO') { $want = [string]$in.mode; $why = "power mode $($in.mode)" }
  elseif ($in.model_busy) { $want = 'PERFORMANCE'; $why = 'model busy' }
  elseif ($quiet -lt $recentSec) { $want = 'PERFORMANCE'; $why = ('model request {0}s ago' -f [math]::Round($quiet)) }
  elseif ($busy -ge $busySamples) { $want = 'PERFORMANCE'; $why = ('cpu {0}% for {1} samples' -f $cpu, $busy) }
  elseif ($in.agent_active) { $want = 'BALANCED'; $why = 'agent client active (floor)' }
  elseif (($idle -ge $saverIdleSec) -and ($quiet -ge $saverQuietSec) -and ($cpu -lt $calmPct)) { $want = 'SAVER'; $why = ('PC idle {0} min, model quiet {1} min' -f [math]::Round($idle / 60), [math]::Round($quiet / 60)) }
  else { $want = 'BALANCED'; $why = 'PC in use' }
  $apply = $null; $reason = ''
  $now = $st.now
  if ($null -eq $now) { $apply = $want; $reason = "startup: $why" }
  elseif ($in.mode -ne 'AUTO') { if ($want -ne $now) { $apply = $want; $reason = $why } }
  elseif ($GOV_POWER_RANK[$want] -gt $GOV_POWER_RANK[$now]) { $apply = $want; $reason = "up: $why" }
  elseif ($GOV_POWER_RANK[$want] -lt $GOV_POWER_RANK[$now]) {
    if ($null -eq $st.down_since) { $st.down_since = $in.t }
    $held = ($in.t - $st.entered).TotalSeconds
    $lowFor = ($in.t - $st.down_since).TotalSeconds
    if (($held -ge $dwellSec) -and ($lowFor -ge $dwellSec)) {
      $step = $null; foreach ($k in $GOV_POWER_RANK.Keys) { if ($GOV_POWER_RANK[$k] -eq ($GOV_POWER_RANK[$now] - 1)) { $step = $k } }   # one level down
      $apply = $step; $reason = ('down after {0} min: {1}' -f [math]::Round($lowFor / 60), $why)
    }
  } else { $st.down_since = $null }
  if ($apply) { $st.now = $apply; $st.entered = $in.t; $st.down_since = $null }
  return @{ st = $st; want = $want; apply = $apply; reason = $reason; why = $why }
}
# Context that fits (same formula as launch.ps1): (total - margin - others - base) GiB of KV, rounded down to 4096, clamped.
function GovFitCtx($totalGib, $marginGib, $othersGib, $baseGib, $kvKibPerToken, $ctxMin, $ctxMax, $overheadGib = 0.0) {
  $kib = ([double]$totalGib - [double]$marginGib - [double]$othersGib - [double]$baseGib - [double]$overheadGib) * 1048576.0
  $ctx = 0; if ($kib -gt 0) { $ctx = [int]([math]::Floor($kib / [double]$kvKibPerToken / 4096) * 4096) }
  return [math]::Max([int]$ctxMin, [math]::Min([int]$ctxMax, $ctx))
}

# ============================================================ loop error accounting / self-heal ============================================================
$script:errStreak = 0; $script:errTotal = 0; $script:lastError = $null; $script:lastErrorAt = $null; $script:heals = 0
function ReInit {
  $script:lastGoodVram = $null; $script:lastGoodRam = $null; $script:suspect = 0; $script:needLog = @(); $script:ctxCache = $null
  $script:pressureCount = 0; $script:senseWarn = @(); $script:statusDraft = $null
  Set-Variable -Name candidate -Value $null -Scope Script; Set-Variable -Name count -Value 0 -Scope Script; Set-Variable -Name cpuHigh -Value 0 -Scope Script
}
function NoteLoopError($er) {
  $msg = $er.Exception.Message; $line = $null; try { $line = $er.InvocationInfo.ScriptLineNumber } catch {}
  $script:errStreak++; $script:errTotal++; $script:lastError = "$msg (line $line)"; $script:lastErrorAt = Get-Date
  if ($script:errStreak -eq 1) { Log "loop error at line ${line}: $msg" }
  elseif ($script:errStreak % 20 -eq 0) { Log "loop error x$($script:errStreak) (last at line ${line}: $msg)" }
  if (($script:errStreak -eq 4) -or (($script:errStreak -gt 4) -and ($script:errStreak % 40 -eq 0))) { ReInit; $script:heals++; Log "self-heal: state re-initialised after $($script:errStreak) consecutive loop errors" }
}

if ($FunctionsOnly) { return }

# ============================================================ sensing ============================================================
# slotlib (slot save/restore) is optional: without it the governor behaves as before, minus the restore.
$script:slotLib = $false; $script:slots = $null; $script:warmJob = $null
try { . "$dir\slotlib.ps1"; $script:slotLib = $true; $script:SlotLogPath = "$dir\governor.log" } catch {}

$script:lastGoodVram = $null; $script:lastGoodRam = $null; $script:suspect = 0; $script:senseWarn = @()
# post-launch baseline (others/free/ctx when the counters settled) and the learned footprint per variant (calib.json)
$script:baseline = $null; $script:baseStable = 0; $script:baseStarted = $null
$script:refitPrevCtx = $null; $script:refitOthers = $null; $script:refitBlocked = $false
function VariantOf($id) { return (Try1 { $cfg.variants.PSObject.Properties | ForEach-Object { $_.Value } | Where-Object { $_.id -eq $id } | Select-Object -First 1 } $null) }
function CalibRead { $c = ReadJsonFile "$dir\calib.json"; if ($null -eq $c) { return [pscustomobject]@{} }; return $c }
function CalibEntry($id) { $c = CalibRead; $pr = $c.PSObject.Properties[$id]; if ($pr) { return $pr.Value }; return $null }
function CalibWrite($id, $entry) {
  try {
    $c = CalibRead
    if ($c.PSObject.Properties[$id]) { $c.PSObject.Properties.Remove($id) }
    $c | Add-Member -NotePropertyName $id -NotePropertyValue $entry
    WriteText "$dir\calib.json.tmp" ($c | ConvertTo-Json -Depth 5)
    Move-Item -LiteralPath "$dir\calib.json.tmp" -Destination "$dir\calib.json" -Force
  } catch { Log "calib write error: $($_.Exception.Message)" }
}
function Sense($loaded, $starting) {
  $s = [ordered]@{ idle_sec = [int](Try1 { [math]::Round([IdleTime]::Seconds()) } 0) }
  $warn = @()
  # each counter path is its own PDH query (see Counters): a flaky GPU counter can no longer zero the RAM/CPU samples
  $smp = Counters @('\Memory\Available MBytes', '\Processor(_Total)\% Processor Time')
  $ramRaw = $null; $cpuRaw = $null
  foreach ($x in $smp) { if ($x.Path -like '*available mbytes') { $ramRaw = [double]$x.CookedValue / 1024.0 } elseif ($x.Path -like '*processor(_total)*') { $cpuRaw = [double]$x.CookedValue } }
  $ram = GovValidateRam $ramRaw $script:lastGoodRam
  if ($ram.ok) { $script:lastGoodRam = $ram.gb } else { $warn += "RAM counter invalid ($ramRaw)" }
  $s.ram_avail_gb = $(if ($null -eq $ram.gb) { $null } else { [math]::Round([double]$ram.gb, 2) }); $s.ram_ok = $ram.ok
  if ((GovIsNum $cpuRaw) -and $cpuRaw -ge 0 -and $cpuRaw -le 100) { $s.cpu_total = [math]::Round($cpuRaw, 1) } else { $s.cpu_total = $null; $warn += 'CPU counter invalid' }
  # GPU adapter: max over adapters (the B60 is the only one with dedicated memory; virtual adapters read 0)
  $ad = Counters @('\GPU Adapter Memory(*)\Dedicated Usage')
  $adapterGib = $null
  foreach ($x in $ad) { $v = [double]$x.CookedValue / 1GB; if (($null -eq $adapterGib) -or ($v -gt $adapterGib)) { $adapterGib = $v } }
  # GPU per-process: the llama-server share
  $llamaIds = ProcIds 'llama-server'
  $llamaGib = $null; $llamaCpu = 0.0
  if ($llamaIds.Count) {
    $g = Counters @('\GPU Process Memory(*)\Dedicated Usage')
    if ($g.Count) { $llamaGib = 0.0; foreach ($x in $g) { foreach ($lid in $llamaIds) { if ($x.InstanceName -like "pid_$($lid)_*") { $llamaGib += [double]$x.CookedValue / 1GB } } } }
    $pc = Counters @('\Process(llama-server*)\% Processor Time')
    if ($pc.Count) { $sum = 0.0; foreach ($x in $pc) { $sum += [double]$x.CookedValue }; $llamaCpu = $sum / [Environment]::ProcessorCount }
  }
  $vr = GovValidateVram $adapterGib $llamaGib $script:vramTotalGib $loaded ($llamaIds.Count -gt 0) $script:lastGoodVram $script:suspect $starting
  $script:suspect = $vr.suspect
  $m = $vr.m
  if ($m.ok) { $script:lastGoodVram = $m }
  $warn += @($m.warn)
  $s.vram_total_gib = $script:vramTotalGib
  $s.vram_used_gib = $m.used; $s.vram_free_gib = $m.free; $s.vram_llama_gib = $m.llama; $s.vram_others_gib = $m.others; $s.vram_ok = $m.ok
  $s.llama_measured = [bool]$m.llama_measured
  $s.vram_adapter_raw_gib = $(if ($null -eq $adapterGib) { $null } else { [math]::Round($adapterGib, 2) })
  $s.vram_llama_raw_gib = $(if ($null -eq $llamaGib) { $null } else { [math]::Round($llamaGib, 2) })
  $s.cpu_others = $(if ($null -eq $s.cpu_total) { $null } else { [math]::Round([math]::Max(0, $s.cpu_total - $llamaCpu), 1) })
  $s.llama_pids = $llamaIds.Count
  $script:senseWarn = $warn
  return $s
}
# Is a request in flight on the loaded server? $true / $false / $null (= could not tell).
function InFlight($port) {
  $known = $false; $busy = $false
  $sl = HttpJson "http://127.0.0.1:$port/slots" 5
  if ($null -ne $sl) { $known = $true; foreach ($x in @($sl)) { if ($x.is_processing -eq $true) { $busy = $true } } }
  $met = HttpText "http://127.0.0.1:$port/metrics" 5
  if ($met) {
    $known = $true
    foreach ($name in 'requests_processing', 'requests_deferred') {
      $mm = [regex]::Match($met, "(?m)^llamacpp:$name\s+([0-9.eE+-]+)")
      if ($mm.Success) { $v = 0.0; if ([double]::TryParse($mm.Groups[1].Value, [ref]$v) -and $v -gt 0) { $busy = $true } }
    }
  }
  if (-not $known) { return $null }
  return $busy
}
function ModelState {
  $st = [ordered]@{ loaded = $false; state = 'stopped'; other_running = $null; processing = $null; tokens = $null; n_ctx = $null; prompt_tokens = 0; id = $script:curId }
  $r = Attempt { (Api GET '/running' $null 10).running }
  if (-not $r.ok) {
    $st.state = 'api-error'
    if ($r.err -match 'Unable to connect|actively refused|connection could not be made|The remote name|timed out|No connection') { $st.state = 'swap-down' }
    return $st
  }
  foreach ($x in @($r.value)) {
    if ($null -eq $x) { continue }
    if ($ids -contains $x.model) { $st.state = [string]$x.state; $st.loaded = ($x.state -eq 'ready'); $script:curId = $x.model; $script:curPort = $ports[$x.model] }
    elseif ($x.model) { $st.other_running = [string]$x.model }
  }
  $st.id = $script:curId
  if ($st.loaded) {
    $st.processing = InFlight $script:curPort
    $sl = HttpJson "http://127.0.0.1:$($script:curPort)/slots" 5
    if ($null -ne $sl) {
      $mx = 0
      foreach ($x in @($sl)) { $n = 0; try { $n = [int]$x.n_prompt_tokens + [int]$x.params.n_predict } catch {}; if ($n -gt $mx) { $mx = $n } }
      $st.prompt_tokens = $mx
    }
    if (-not $script:ctxCache) { $p = HttpJson "http://127.0.0.1:$($script:curPort)/props" 5; if ($null -ne $p) { $script:ctxCache = Try1 { [int]$p.default_generation_settings.n_ctx } $null } }
    $st.n_ctx = $script:ctxCache
    $met = HttpText "http://127.0.0.1:$($script:curPort)/metrics" 5
    if ($met) {
      $sum = 0.0; $any = $false
      foreach ($mm in [regex]::Matches($met, '(?m)^llamacpp:(prompt_tokens_total|tokens_predicted_total)\s+([\d.e+]+)')) { $v = 0.0; if ([double]::TryParse($mm.Groups[2].Value, [ref]$v)) { $sum += $v; $any = $true } }
      if ($any) { $st.tokens = $sum }
    }
  } else { $script:ctxCache = $null }
  return $st
}
function LoadedEmergency { $j = ReadJsonFile "$dir\running.json"; if ($j) { return [bool](Try1 { $j.emergency } $false) }; return $false }
function LoadedProfile { $j = ReadJsonFile "$dir\running.json"; if ($j) { return (Try1 { [string]$j.profile } $null) }; return $null }
function AgentActive($a, $quietSec) {
  $names = @('codex', 'claude')
  try { if ($a.agent_processes) { $names = @($a.agent_processes | ForEach-Object { [string]$_ }) } } catch {}
  $found = @()
  foreach ($n in $names) { if ((ProcIds $n).Count -gt 0) { $found += $n } }
  $recentMin = CfgNum $a 'agent_recent_min' 10
  $recent = $script:sawActivity -and ($quietSec -le $recentMin * 60)
  return @{ active = (($found.Count -gt 0) -or $recent); procs = $found; recent = $recent }
}

# ============================================================ actions ============================================================
$script:unloadResult = 'failed'; $script:prewarmOk = $false
function StopWarmJob {
  $j = $script:warmJob; if (-not $j) { return }
  $was = $j.State
  try { Stop-Job $j -ErrorAction SilentlyContinue; Remove-Job $j -Force -ErrorAction SilentlyContinue } catch {}
  $script:warmJob = $null
  if ($script:slotLib) { try { SlotClearPhase "$dir\phase.json" } catch {} }
  if ($was -eq 'Running') { Log 'restore warm-up job stopped before unload' }
}
function ReapWarmJob {
  $j = $script:warmJob; if (-not $j) { return }
  if ($j.State -eq 'Running') {
    if (((Get-Date) - $j.PSBeginTime).TotalSeconds -le 600) { return }
    Stop-Job $j -ErrorAction SilentlyContinue; Log 'warm-up job exceeded 10 min and was stopped'
  }
  try { Receive-Job $j -ErrorAction SilentlyContinue -ErrorVariable je | Out-Null; if ($je) { Log "warm-up job error: $($je[0])" } } catch {}
  Remove-Job $j -Force -ErrorAction SilentlyContinue; $script:warmJob = $null
  if ($script:slotLib) { try { SlotClearPhase "$dir\phase.json" } catch {} }
}
# Every governor-initiated unload goes through here. Result in $script:unloadResult: ok | busy | failed.
function Unload($why) {
  $script:unloadResult = 'failed'
  StopWarmJob
  # a request may have started since the sample was taken: re-check right now
  $busy = InFlight $script:curPort
  if ($busy -eq $true) { Log "UNLOAD postponed ($why): a request is in flight"; $script:unloadResult = 'busy'; return }
  if ($null -eq $busy) { Log "UNLOAD postponed ($why): slot state unknown"; $script:unloadResult = 'busy'; return }
  if ($script:slotLib -and $script:slots) {
    $go = $true
    try {
      $kv = Try1 { $cfg.variants.PSObject.Properties | ForEach-Object { $_.Value } | Where-Object { $_.id -eq $script:curId } | Select-Object -First 1 } $null
      $sv = @(SlotSave $script:slots $script:curId $script:curPort (SlotModelPath $cfg $script:curId) $script:ctxCache $kv); $go = [bool]$sv[-1]
      SlotPrune $script:slots $ids
    } catch { Log "slot save error: $($_.Exception.Message)" }
    if (-not $go) { Log "UNLOAD postponed ($why): a request started during the slot save"; $script:unloadResult = 'busy'; return }
  }
  # llama-swap waits for the process to exit before answering: 90 s, not 10 (the old 10 s timeout produced 'unload failed'
  # followed by a relaunch on top of the dying server, which is how others=21 GiB got measured at launch)
  $r = Attempt { Api POST "/api/models/unload/$($script:curId)" $null 90 }
  if ($r.ok) { Log "UNLOAD ($why)"; $script:lastReload = Get-Date; $script:ctxCache = $null; $script:unloadResult = 'ok' }
  else { Log "unload failed: $($r.err)" }
}
# wait (max $sec) for every llama-server process to be gone so the next launch measures clean VRAM
function WaitServerGone($sec) {
  $t = Get-Date
  while (((Get-Date) - $t).TotalSeconds -lt $sec) { if ((ProcIds 'llama-server').Count -eq 0) { return $true }; Start-Sleep -Seconds 1 }
  return ((ProcIds 'llama-server').Count -eq 0)
}
function Prewarm($why) {
  $script:prewarmOk = $false
  $script:lastPrewarm = Get-Date; $script:lastBusy = $script:lastPrewarm   # a fresh load is not 'idle'
  try {
    if ($script:warmJob -and $script:warmJob.State -eq 'Running') { Log "PREWARM skipped ($why): previous warm-up job still running"; return }
    $sc = $null
    if ($script:slotLib -and $script:slots) { $sc = Try1 { SlotRestorePlan $script:slots $script:curId (SlotModelPath $cfg $script:curId) } $null }
    if ($sc) {
      $jp = @{ swap = $swap; key = (Key); id = $script:curId; port = $script:curPort; model_path = (SlotModelPath $cfg $script:curId); dir = $script:slots.dir; headroom = $script:slots.headroom; log = "$dir\governor.log"; phase_file = "$dir\phase.json" }
      $script:warmJob = Start-Job -ScriptBlock { param($lib, $jp) . $lib; SlotWarmFlow $jp } -ArgumentList "$dir\slotlib.ps1", $jp
      Log "PREWARM ($why) restore-first"
    } else {
      $hdr = "$dir\.auth-header"; "Authorization: Bearer $(Key)" | Set-Content $hdr -NoNewline
      $body = "$dir\.prewarm.json"; '{"model":"' + $script:curId + '","max_tokens":1,"messages":[{"role":"user","content":"hi"}],"chat_template_kwargs":{"enable_thinking":false}}' | Set-Content $body -NoNewline
      Start-Process curl.exe -WindowStyle Hidden -ArgumentList '-s','-m','300','-o','NUL','-H',('@' + $hdr),'-H','"Content-Type: application/json"','--data-binary',('@' + $body),"$swap/v1/chat/completions" | Out-Null
      Log "PREWARM ($why)"
    }
    $script:prewarmOk = $true
  } catch { Log "prewarm failed: $($_.Exception.Message)" }
}
# unload, then prewarm only if the unload really happened and the old server is gone
function UnloadThenPrewarm($why, $pwWhy) {
  Unload $why
  if ($script:unloadResult -ne 'ok') { return }
  $script:lastRefit = Get-Date
  if (-not (WaitServerGone 45)) { Log 'old llama-server still alive 45 s after unload; prewarm deferred to the next sample' ; $script:pendingPrewarm = @{ why = $pwWhy; tries = 0 }; return }
  Start-Sleep -Seconds 2   # let the driver release the VRAM before launch.ps1 measures
  Prewarm $pwWhy
  if (-not $script:prewarmOk) { $script:pendingPrewarm = @{ why = $pwWhy; tries = 0 } }
}

# ---- smart Windows power plan: SAVER when nobody is using the PC or the model, PERFORMANCE under load; hysteresis in GovPowerDecide ----
$planGuid = @{ PERFORMANCE = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'; BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'; SAVER = 'a1841308-3541-4fab-bc81-f71556f20b4a' }
$script:pow = @{ now = $null; entered = (Get-Date); down_since = $null; cpu_busy = 0 }
$script:powWhy = ''
function ApplyPower($s, $quietSec, $modelBusy, $agentActive) {
  $pm = PowerMode
  $pcfg = $null; try { $pcfg = $cfg.power } catch {}
  $in = @{ t = (Get-Date); mode = $pm; cpu = $s.cpu_total; idle_sec = $s.idle_sec; quiet_sec = $quietSec; model_busy = [bool]$modelBusy; agent_active = [bool]$agentActive; cfg = $pcfg }
  $prev = $script:pow.now
  $r = GovPowerDecide $script:pow $in
  $script:pow = $r.st
  $script:powWhy = $r.why
  if ($r.apply) {
    $act = [string](Try1 { (powercfg /getactivescheme) -replace '.*GUID:\s*([0-9a-f-]+).*', '$1' } '')
    if ($act.Trim() -ne $planGuid[$r.apply]) {
      powercfg /setactive $planGuid[$r.apply] | Out-Null
      Log "power $prev -> $($r.apply) ($($r.reason); idle=$($s.idle_sec)s modelQuiet=$([math]::Round($quietSec))s cpu=$($s.cpu_total)% agent=$([bool]$agentActive))"
    }
  }
  $script:pow.now
}
function SetPriority($prof) {
  $want = 'BelowNormal'; if ($prof -eq 'MAX') { $want = 'Normal' }
  Get-Process llama-server -ErrorAction SilentlyContinue | ForEach-Object { try { if ("$($_.PriorityClass)" -ne $want) { $_.PriorityClass = $want } } catch {} }
}

# ============================================================ loop state, self-heal ============================================================
$cfg = ReadJsonFile "$dir\profiles.json"
if (-not $cfg) { Log 'FATAL: profiles.json unreadable at start'; exit 1 }
$A = $cfg.auto
$script:vramTotalGib = CfgNum $cfg.vram 'total_gib' 23.88
$committed = 'BALANCED'; $candidate = $null; $count = 0
$script:lastBusy = Get-Date; $lastTokens = $null; $script:lastReload = (Get-Date).AddHours(-1); $script:lastPrewarm = (Get-Date).AddHours(-1); $script:lastRefit = (Get-Date).AddHours(-1)
$swapFails = 0; $lastRestart = (Get-Date).AddHours(-1); $cpuHigh = 0; $script:lastTsStart = (Get-Date).AddHours(-1)
$script:needLog = @(); $script:pressureCount = 0; $script:sawActivity = $false; $script:pendingPrewarm = $null
$script:statusDraft = $null; $script:lastDecision = @{ action = 'none'; reason = 'startup' }
if (-not (Test-Path "$dir\mode.txt")) { 'AUTO' | Set-Content "$dir\mode.txt" }
Try1 { Set-Content "$dir\desired.txt" $committed } | Out-Null
Try1 { New-Item -ItemType Directory -Force -Path "$dir\public" | Out-Null } | Out-Null
Log "governor start pid=$([System.Diagnostics.Process]::GetCurrentProcess().Id) v4"
if (-not $script:slotLib) { Log 'slotlib.ps1 not loaded: slot save/restore is off' }
else { try { $script:slots = SlotCfg $cfg; if ($script:slots) { SlotDirReady $script:slots.dir; SlotPrune $script:slots $ids; Log "slots on: dir=$($script:slots.dir) max_files=$($script:slots.max_files) max_gib=$($script:slots.max_gib) min_tokens=$($script:slots.min_tokens)" } else { Log 'slots off (slots.enabled false, or slots.dir / --slot-save-path not wired)' } } catch { Log "slot init error: $($_.Exception.Message)" } }

# ============================================================ main loop ============================================================
while ($true) {
  $sampleOk = $true
  $now = Get-Date
  try {
    $c2 = ReadJsonFile "$dir\profiles.json"; if ($c2 -and $c2.auto) { $cfg = $c2; $A = $cfg.auto; $script:vramTotalGib = CfgNum $cfg.vram 'total_gib' $script:vramTotalGib } else { LogEvery 'cfg' 30 'profiles.json unreadable: using the last good configuration' }
    $sampleSec = [int](CfgNum $A 'sample_sec' 15); if ($sampleSec -lt 5) { $sampleSec = 5 }
    if ($script:slotLib) { ReapWarmJob; $script:slots = Try1 { SlotCfg $cfg } $script:slots }
    $mode = Mode
    $m = ModelState
    $s = Sense $m.loaded ($m.state -eq 'starting')
    if ($script:senseWarn.Count) { LogEvery 'sense' 10 ("sense degraded: " + ($script:senseWarn -join '; ')) } else { ClearOnce 'sense' }
    # --- watchdog for llama-swap ---
    if ($m.state -eq 'swap-down') {
      $swapFails++
      if ($swapFails -ge 3 -and ($now - $lastRestart).TotalMinutes -ge 5) { Log 'WATCHDOG: llama-swap not responding, restarting task'; Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue; Get-Process llama-swap -ErrorAction SilentlyContinue | Stop-Process -Force; Get-Process llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like 'C:\AI\*' } | Stop-Process -Force; Start-Sleep 3; Start-ScheduledTask -TaskName $task; $lastRestart = $now; $swapFails = 0 }
    } else { $swapFails = 0 }
    # --- keep Tailscale's user backend alive (without tailscale-ipn the daemon sits in NoState and remote access dies) ---
    if (((ProcIds 'tailscale-ipn').Count -eq 0) -and (Test-Path 'C:\Program Files\Tailscale\tailscale-ipn.exe') -and ($now - $script:lastTsStart).TotalMinutes -ge 5) {
      $script:lastTsStart = $now; Try1 { Start-Process 'C:\Program Files\Tailscale\tailscale-ipn.exe' } | Out-Null; Log 'WATCHDOG: tailscale-ipn was not running - started it' }
    # --- activity of the model ---
    $tokMoved = ($null -ne $m.tokens) -and ($null -ne $lastTokens) -and ($m.tokens -ne $lastTokens)
    if (($m.processing -eq $true) -or $tokMoved -or $m.state -eq 'starting') { $script:lastBusy = $now; if ($m.processing -eq $true -or $tokMoved) { $script:sawActivity = $true } }
    $lastTokens = $m.tokens
    $quietSec = ($now - $script:lastBusy).TotalSeconds
    # --- live-session tracking (largest prompt seen in the last 60 min) for session-protected resizing in launch.ps1 ---
    if ($m.prompt_tokens -gt 0) { $script:needLog += ,([pscustomobject]@{ t = $now; n = [int]$m.prompt_tokens }) }
    $keep = @(); foreach ($e in @($script:needLog)) { if (($null -ne $e) -and (($now - $e.t).TotalMinutes -le 60)) { $keep += $e } }
    $script:needLog = $keep
    $sessNeed = 0; foreach ($e in $script:needLog) { if ($e.n -gt $sessNeed) { $sessNeed = [int]$e.n } }
    Try1 { Set-Content "$dir\session-need.txt" $sessNeed } | Out-Null
    $agent = AgentActive $A $quietSec   # needed by the power plan (BALANCED floor) and by the decision below
    $power = $null; try { $power = ApplyPower $s $quietSec (($m.processing -eq $true) -or $m.state -eq 'starting') $agent.active } catch { Log "power error: $($_.Exception.Message)" }
    # --- choose profile (confirm_samples in a row; invalid readings never push LEAN) ---
    if (($null -ne $s.cpu_others) -and ($s.cpu_others -ge (CfgNum $A 'others_cpu_lean_pct' 85))) { $cpuHigh++ } else { $cpuHigh = 0 }
    $want = GovProfileChoice $mode $s.idle_sec $s.ram_avail_gb $s.ram_ok $s.vram_others_gib $s.vram_ok $cpuHigh $A
    if ($want -eq $candidate) { $count++ } else { $candidate = $want; $count = 1 }
    if ($want -ne $committed -and ($count -ge (CfgNum $A 'confirm_samples' 4) -or $mode -ne 'AUTO')) {
      Log "profile $committed -> $want (idle=$($s.idle_sec)s ram=$($s.ram_avail_gb)GB othersVRAM=$($s.vram_others_gib)GiB cpuOthers=$($s.cpu_others)%)"; $committed = $want; Try1 { Set-Content "$dir\desired.txt" $committed } | Out-Null }
    $loadedProf = $null; if ($m.loaded) { $loadedProf = LoadedProfile; SetPriority $committed }
    # --- post-launch baseline and footprint calibration ---
    $started = $null; try { $rj = ReadJsonFile "$dir\running.json"; if ($rj -and $rj.started) { $started = [string]$rj.started } } catch {}
    if (-not $m.loaded) { $script:baseline = $null; $script:baseStable = 0 }
    elseif ($script:baseline -and ($script:baseStarted -ne $started)) { $script:baseline = $null; $script:baseStable = 0 }   # a new server: new baseline
    if ($m.loaded -and -not $script:baseline) {
      $br = GovBaselineReady $m.loaded $s.vram_ok $s.llama_measured $m.n_ctx $script:baseStable
      $script:baseStable = $br.count
      if ($br.take) {
        $script:baseline = [ordered]@{ others = $s.vram_others_gib; free = $s.vram_free_gib; used = $s.vram_used_gib; llama = $s.vram_llama_gib; ctx = [int]$m.n_ctx; id = $script:curId; t = $now.ToString('s') }
        $script:baseStarted = $started
        $vv = VariantOf $script:curId; $cal = $null
        if ($vv -and (GovIsNum $vv.base_gib) -and (GovIsNum $vv.kv_kib_per_token)) {
          $cc = $cfg.calibration; $alpha = CfgNum $cc 'alpha' 0.5; $maxO = CfgNum $cc 'max_overhead_gib' 1.5
          $prev = $null; $pe = CalibEntry $script:curId; if ($pe) { $prev = Try1 { [double]$pe.overhead_gib } $null }
          $cal = GovCalibrate $prev $s.vram_llama_gib $vv.base_gib $m.n_ctx $vv.kv_kib_per_token $alpha $maxO
          $n = 1; if ($pe) { $n = (Try1 { [int]$pe.samples } 0) + 1 }
          CalibWrite $script:curId ([ordered]@{ overhead_gib = $cal.overhead; last_delta_gib = $cal.delta; predicted_gib = $cal.predicted; measured_gib = $s.vram_llama_gib; ctx = [int]$m.n_ctx; others_gib = $s.vram_others_gib; free_gib = $s.vram_free_gib; samples = $n; updated = $now.ToString('s') })
        }
        $calTxt = ''; if ($cal) { $calTxt = (' predicted={0} measured={1} delta={2:+0.00;-0.00} overhead->{3}' -f $cal.predicted, $s.vram_llama_gib, $cal.delta, $cal.overhead) }
        Log ("BASELINE ctx={0} others={1} free={2} llama={3}{4}" -f $m.n_ctx, $s.vram_others_gib, $s.vram_free_gib, $s.vram_llama_gib, $calTxt)
        # a re-fit that landed on the same ctx as before: block re-fits until others changes
        if ($script:refitPrevCtx) { $script:refitBlocked = GovRefitRepeatBlocked $script:refitPrevCtx $m.n_ctx $s.vram_others_gib $script:refitOthers (CfgNum $A 'others_growth_gib' 0.5); if ($script:refitBlocked) { Log "re-fit landed on ctx $($m.n_ctx) again (was $($script:refitPrevCtx)); further re-fits wait for others to change" }; $script:refitPrevCtx = $null }
      }
    }
    if ($script:refitBlocked -and (GovIsNum $s.vram_others_gib) -and (GovIsNum $script:refitOthers) -and ([math]::Abs($s.vram_others_gib - $script:refitOthers) -ge (CfgNum $A 'others_growth_gib' 0.5))) { $script:refitBlocked = $false; Log 'others changed since the repeated re-fit: re-fits allowed again' }
    # --- pressure with hysteresis (relative to the baseline) ---
    $freeThr = CfgNum $A 'vram_free_pressure_gib' 1.1; $ramCrit = CfgNum $A 'ram_critical_gb' 1.5; $growth = CfgNum $A 'others_growth_gib' 0.5; $hardFloor = CfgNum $A 'vram_free_hard_floor_gib' 0.25
    $bOthers = $null; if ($script:baseline) { $bOthers = $script:baseline.others }
    if ($m.loaded) { $script:pressureCount = GovPressureStep $script:pressureCount $s.vram_free_gib $s.ram_avail_gb $s.vram_ok $s.ram_ok $freeThr $ramCrit $s.vram_others_gib $bOthers $growth $hardFloor } else { $script:pressureCount = 0 }
    # --- a prewarm that could not start is retried (max 5 samples) unless the model is back already ---
    if ($script:pendingPrewarm) {
      if ($m.loaded -or $m.state -eq 'starting' -or $script:pendingPrewarm.tries -ge 5) { $script:pendingPrewarm = $null }
      elseif ((ProcIds 'llama-server').Count -eq 0) { $script:pendingPrewarm.tries++; Prewarm $script:pendingPrewarm.why; if ($script:prewarmOk) { $script:pendingPrewarm = $null } }
    }
    # --- decide and act (never while busy) ---
    $din = @{ mode = $mode; loaded = $m.loaded; state = $m.state; in_flight = $m.processing; quiet_sec = $quietSec
      pressure_count = $script:pressureCount; sample_sec = $sampleSec; persist_sec = (CfgNum $A 'pressure_persist_sec' 60)
      committed = $committed; loaded_profile = $loadedProf; idle_unload_min = (CfgNum $cfg.profiles.$committed 'idle_unload_min' 0)
      since_refit_min = ($now - $script:lastRefit).TotalMinutes; refit_interval_min = (CfgNum $A 'refit_min_interval_min' 15)
      since_prewarm_min = ($now - $script:lastPrewarm).TotalMinutes; prewarm_cooldown_min = (CfgNum $A 'prewarm_cooldown_min' 10)
      cur_id = $script:curId; emergency = $(if ($m.loaded) { LoadedEmergency } else { $false }); agent_active = $agent.active; other_running = $m.other_running
      free_gib = $s.vram_free_gib; ram_gb = $s.ram_avail_gb; free_threshold = $freeThr; ram_critical = $ramCrit
      others_gib = $s.vram_others_gib; baseline_others = $bOthers; hard_floor = $hardFloor; refit_blocked = $script:refitBlocked
      quiet_before_reload_sec = (CfgNum $A 'model_quiet_sec_before_reload' 120); max_upgrade_quiet_min = (CfgNum $A 'max_upgrade_quiet_min' 20) }
    $d = GovDecide $din
    $script:lastDecision = $d
    switch ($d.action) {
      'unload'      { Unload $d.reason }
      'idle-unload' { Unload $d.reason }
      'refit'       { $script:refitPrevCtx = $m.n_ctx; $script:refitOthers = $s.vram_others_gib; UnloadThenPrewarm $d.reason "re-fit as $committed" }
      'upgrade'     { UnloadThenPrewarm $d.reason "upgrade to $committed" }
      'prewarm'     { $script:curId = $model; $script:curPort = $ports[$model]; Prewarm $d.reason }
      default       { if ($d.reason -like 'pressure persists*') { LogEvery 'ratelimit' 5 $d.reason } elseif ($d.reason -like 'pressure but protected*') { LogEvery 'protected' 15 $d.reason } }
    }
    # --- status draft (completed and written below, even when something above failed) ---
    $status = [ordered]@{ time = $now.ToString('s'); mode = $mode; profile = $committed; loaded = $m.loaded; loaded_profile = $loadedProf; state = $m.state
      processing = $m.processing; n_ctx = $m.n_ctx; model_quiet_min = [math]::Round($quietSec / 60, 1); other_model = $m.other_running }
    foreach ($k in $s.Keys) { $status[$k] = $s[$k] }
    # expected context if the default model were (re)loaded now with the current profile
    try { $vd = $cfg.variants.default; $pp = $cfg.profiles.$committed; $oth = $s.vram_others_gib; if (-not $m.loaded -and ($null -ne $s.vram_used_gib) -and ($s.llama_pids -eq 0)) { $oth = $s.vram_used_gib }
          $oh = GovLaunchOverhead (CalibEntry $vd.id) (CfgBool $cfg.calibration 'enabled' $true) (CfgNum $cfg.calibration 'max_overhead_gib' 1.5)
          if ($null -ne $oth) { $status['expected_ctx'] = GovFitCtx $script:vramTotalGib (CfgNum $pp 'free_margin_gib' 1.5) $oth (CfgNum $vd 'base_gib' 17.15) (CfgNum $vd 'kv_kib_per_token' 64.5) (CfgNum $pp 'ctx_min' 32768) (CfgNum $vd 'ctx_max' 65536) $oh; $status['calib_overhead_gib'] = $oh } } catch {}
    $status['model_id'] = $script:curId
    $status['power_plan'] = $power; $status['power_mode'] = PowerMode; $status['power_reason'] = $script:powWhy; $status['session_need_tokens'] = $sessNeed
    $status['pressure_count'] = $script:pressureCount; $status['pressure_sec'] = $script:pressureCount * $sampleSec
    $status['agent_active'] = $agent.active; $status['agent_procs'] = @($agent.procs); $status['decision'] = $d.action; $status['decision_reason'] = $d.reason
    $status['since_refit_min'] = [math]::Round(($now - $script:lastRefit).TotalMinutes, 1); $status['slots_on'] = [bool]$script:slots
    $status['baseline'] = $script:baseline; $status['refit_blocked'] = $script:refitBlocked
    $status['sense_warnings'] = @($script:senseWarn)
    $script:statusDraft = $status
  } catch { $sampleOk = $false; NoteLoopError $_ }
  # --- status.json is written on every sample, degraded or not ---
  try {
    $st = $script:statusDraft
    if ($null -eq $st) { $st = [ordered]@{ time = $now.ToString('s'); mode = (Mode); profile = $committed; loaded = $null; state = 'unknown' } }
    else { $st['time'] = $now.ToString('s') }
    $degraded = (-not $sampleOk) -or ($script:errStreak -gt 0) -or ($script:senseWarn.Count -gt 0)
    $st['degraded'] = $degraded
    $st['last_error'] = $script:lastError
    $st['last_error_time'] = $(if ($script:lastErrorAt) { $script:lastErrorAt.ToString('s') } else { $null })
    $st['loop_errors'] = $script:errTotal; $st['loop_error_streak'] = $script:errStreak; $st['self_heals'] = $script:heals
    $st['sample_ok'] = $sampleOk
    $tmp = "$dir\public\status.json.tmp"
    WriteText $tmp ($st | ConvertTo-Json -Depth 5)
    Move-Item -LiteralPath $tmp -Destination "$dir\public\status.json" -Force
  } catch { Log "status write error: $($_.Exception.Message)" }
  if ($sampleOk -and $script:errStreak -gt 0) { Log "loop recovered after $($script:errStreak) error sample(s)"; $script:errStreak = 0 }
  $sl = 15; try { $sl = [int](CfgNum $A 'sample_sec' 15); if ($sl -lt 5) { $sl = 5 } } catch {}
  if ($env:GOV_MAX_LOOPS) { $script:loops++; if ($script:loops -ge [int]$env:GOV_MAX_LOOPS) { break } }   # test harness only
  Start-Sleep -Seconds $sl
}
