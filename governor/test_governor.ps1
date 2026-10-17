# Plain-assert tests for the governor's pure decision functions (no Pester needed; Windows PowerShell 5.1 or pwsh 7).
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\test_governor.ps1
# 1) parse-checks every .ps1 next to this file, 2) loads governor.ps1 -FunctionsOnly, 3) replays the same
# scenarios as test_govpolicy.py (taken from real governor.log lines) and 4) proves the needLog fix.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fails = 0; $passes = 0
function Check($name, $cond) { if ($cond) { $script:passes++; "ok   $name" } else { $script:fails++; "FAIL $name" } }

# ---- 1) parse check ----
foreach ($f in Get-ChildItem -LiteralPath $here -Filter '*.ps1') {
  $tokens = $null; $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors) | Out-Null
  Check "parse $($f.Name)" ($errors.Count -eq 0)
  foreach ($e in $errors) { "     line $($e.Extent.StartLineNumber): $($e.Message)" }
  $src = Get-Content -LiteralPath $f.FullName -Raw
  Check "no PS7-only operators in $($f.Name)" (([regex]::Matches($src, '\?\?|\?\.')).Count -eq 0)
}

# ---- 2) load the pure functions ----
. (Join-Path $here 'governor.ps1') -FunctionsOnly
$ErrorActionPreference = 'Stop'
# Everything the functions under test log goes to a temp dir, never to C:\AI\governor\governor.log
$tmpRoot = $env:TEMP; if (-not $tmpRoot) { $tmpRoot = [IO.Path]::GetTempPath() }
$dir = Join-Path $tmpRoot ('qwen-governor-tests-' + [System.Diagnostics.Process]::GetCurrentProcess().Id)
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$testLog = Join-Path $dir 'governor.log'
Check "tests log to temp dir ($dir), not production" ($dir -notlike 'C:\AI\governor*')
$TOTAL = 23.88
$AUTO = [pscustomobject]@{ idle_for_max_sec = 600; ram_floor_gb = 3.5; ram_for_max_gb = 8.0; others_vram_lean_gib = 3.5; others_vram_max_gib = 3.0 }
function BaseState { param([hashtable]$o = @{})
  $s = @{ mode = 'AUTO'; loaded = $true; state = 'ready'; in_flight = $false; quiet_sec = 200; pressure_count = 0; sample_sec = 15; persist_sec = 60
    committed = 'MAX'; loaded_profile = 'MAX'; idle_unload_min = 0; since_refit_min = 60; refit_interval_min = 15; since_prewarm_min = 60; prewarm_cooldown_min = 10
    cur_id = 'qwen3.8-27b'; emergency = $false; agent_active = $false; other_running = $null; free_gib = 1.35; ram_gb = 12.0; free_threshold = 1.1; ram_critical = 1.5
    quiet_before_reload_sec = 120; max_upgrade_quiet_min = 20 }
  foreach ($k in $o.Keys) { $s[$k] = $o[$k] }; return $s }

# ---- 3a) the needLog bug (governor.ps1:147 in v3): piping $null runs the filter once with $_ = $null ----
$threw = $false
try { $null | ForEach-Object { $_[0] } | Out-Null } catch { $threw = $true }
Check 'v3 line 147 reproduces: $null[0] inside a pipeline throws "Cannot index into a null array"' $threw
$ok = $true
try { $needLog = @(); $now = Get-Date; $keep = @(); foreach ($e in @($needLog)) { if (($null -ne $e) -and (($now - $e.t).TotalMinutes -le 60)) { $keep += $e } }; $needLog = $keep } catch { $ok = $false }
Check 'v4 needLog filter is safe on an empty list' ($ok -and $needLog.Count -eq 0)

# ---- 3b) VRAM validation against real log lines ----
$last = [ordered]@{ used = 22.5; free = 1.38; llama = 21.0; others = 1.5; ok = $true }
$r = GovValidateVram 0.0 21.0 $TOTAL $true $true $last 0
Check '2026-10-10T22:38:26 adapter 0 while loaded -> rejected, last good kept' (($r.m.ok -eq $false) -and ($r.m.free -eq 1.38))
Check '   and it is no pressure' ((GovPressureStep 0 $r.m.free 12.0 $r.m.ok $true 1.1 1.5 1.5 1.5) -eq 0)
$ram = GovValidateRam 0.0 16.9
Check 'RAM 0 is an invalid sample, not an empty machine' (($ram.ok -eq $false) -and ($ram.gb -eq 16.9))
Check 'invalid RAM never counts as pressure' ((GovPressureStep 3 23.88 $ram.gb $false $ram.ok 1.1 1.5 1.5 1.5) -eq 0)
$last = [ordered]@{ used = 21.6; free = 2.28; llama = 21.2; others = 0.44; ok = $true }
$r = GovValidateVram 21.33 0.0 $TOTAL $false $true $last 0 $true
Check '2026-10-11T08:34:33 others 21.33 while starting -> last good 0.44' (($r.m.others -eq 0.44) -and ($r.m.ok -eq $false))
Check '   profile choice is not LEAN' ((GovProfileChoice 'AUTO' 37527 18.69 $true $r.m.others $r.m.ok 0 $AUTO) -ne 'LEAN')
$last = [ordered]@{ used = 21.5; free = 2.38; llama = 21.2; others = 0.3; ok = $true }
$r = GovValidateVram 21.5 6.5 $TOTAL $true $true $last 0
Check '2026-10-11T08:58:55 process counter lag -> others kept at 0.3, suspect=1' (($r.m.ok -eq $false) -and ($r.m.others -eq 0.3) -and ($r.suspect -eq 1))
$sc = $r.suspect
for ($i = 1; $i -lt 4; $i++) { $r = GovValidateVram 21.5 16.0 $TOTAL $true $true $last $sc; $sc = $r.suspect }
Check '   a real change is accepted after 4 samples' (($r.m.ok -eq $true) -and ($r.m.others -eq 5.5) -and ($sc -eq 0))
$r = GovValidateVram 20.0 21.16 $TOTAL $true $true $null 0
Check '2026-10-11T09:17:48 negative others clamped' (($r.m.others -ge 0) -and ($r.m.llama -le $r.m.used))
$r = GovValidateVram 2.87 $null $TOTAL $false $false $null 0
Check '2026-10-15T23:17:21 desktop alone = others 2.87' (($r.m.others -eq 2.87) -and ($r.m.llama -eq 0) -and $r.m.ok)
$r = GovValidateVram $null $null $TOTAL $false $false $null 0
Check 'adapter None without history -> degraded, free is $null (not 23.88)' (($r.m.ok -eq $false) -and ($null -eq $r.m.free))
Check '   $null free never counts as pressure (PS: $null -lt 1.1 is TRUE, so this matters)' ((GovPressureStep 2 $r.m.free $null $r.m.ok $false 1.1 1.5 $null $null) -eq 0)

# ---- 3c) hysteresis, baseline rule (2026-10-16) and rate limit ----
function P($c, $free, $others, $base) { GovPressureStep $c $free 9.0 $true $true 1.1 1.5 $others $base 0.5 0.25 }
# 2026-10-16 live v4.0: v3-launched ctx 40960 f16, others 2.62 -> adapter 23.23/23.88, free 0.65 -> re-fit onto its own footprint every 15 min
$c = 0; for ($i = 0; $i -lt 10; $i++) { $c = P $c 0.65 2.62 2.62 }
Check '2026-10-16 own footprint (free 0.65, others unchanged) is never pressure' ($c -eq 0)
Check '   no baseline yet -> low free alone never counts' ((P 3 0.65 2.62 $null) -eq 0)
Check '   growth 0.3 < 0.5 is not pressure' ((P 0 0.65 2.92 2.62) -eq 0)
$c = 0; for ($i = 0; $i -lt 4; $i++) { $c = P $c 0.65 3.22 2.62 }
$d = GovDecide (BaseState @{ free_gib = 0.65; pressure_count = $c; others_gib = 3.22; baseline_others = 2.62 })
Check '   others +0.60 since baseline for 60 s -> refit, reason says so' (($c -eq 4) -and ($d.action -eq 'refit') -and ($d.reason -like '*+0.60 GiB since baseline 2.62*'))
Check '   hard floor 0.25 always counts' ((P 0 0.20 2.62 2.62) -eq 1)
Check '   hard floor named in the reason' ((GovPressureReason 0.20 9.0 1.1 1.5 2.62 2.62) -like '*hard floor*')
$c = P 0 0.63 3.3 2.5
$d = GovDecide (BaseState @{ free_gib = 0.63; pressure_count = $c })
Check '2026-10-12T15:01:40 one low sample does not re-fit' (($c -eq 1) -and ($d.action -eq 'none'))
$c = 0; for ($i = 0; $i -lt 4; $i++) { $c = P $c 0.63 3.3 2.5 }
$d = GovDecide (BaseState @{ free_gib = 0.63; pressure_count = $c; since_refit_min = 60; others_gib = 3.3; baseline_others = 2.5 })
Check 'pressure for 60 s -> refit, reason names the real trigger' (($d.action -eq 'refit') -and ($d.reason -like 'free VRAM 0.63*60s*'))
$d = GovDecide (BaseState @{ free_gib = 0.63; pressure_count = $c; since_refit_min = 3 })
Check 'second re-fit within 15 min is rate-limited' (($d.action -eq 'none') -and ($d.reason -like '*rate-limited*'))
$d = GovDecide (BaseState @{ free_gib = 0.63; pressure_count = $c; since_refit_min = 15; refit_blocked = $true })
Check 'a re-fit that would repeat the same ctx is blocked' (($d.action -eq 'none') -and ($d.reason -like '*repeat the same ctx*'))
Check 'repeat guard: same ctx, others unchanged -> blocked' (GovRefitRepeatBlocked 40960 40960 2.62 2.62)
Check 'repeat guard: one step counts as the same' (GovRefitRepeatBlocked 40960 36864 2.62 2.62)
Check 'repeat guard: a real ctx change is not blocked' (-not (GovRefitRepeatBlocked 40960 24576 2.62 2.62))
Check 'repeat guard: others changed -> allowed again' (-not (GovRefitRepeatBlocked 40960 40960 3.3 2.62))
$b = GovBaselineReady $true $true $true 40960 0
$b2 = GovBaselineReady $true $true $true 40960 $b.count
Check 'baseline taken on the 2nd stable sample' ((-not $b.take) -and $b2.take -and ($b2.count -eq 2))
Check 'baseline resets on an invalid or inferred sample' (((GovBaselineReady $true $false $true 40960 5).count -eq 0) -and ((GovBaselineReady $true $true $false 40960 5).count -eq 0))
# calibration with today's numbers: predicted 17.15 + 40960*64.5/1MiB = 19.67, measured 23.23 - 2.62 = 20.61
$cal = GovCalibrate $null (23.23 - 2.62) 17.15 40960 64.5
Check 'calibration: delta +0.94 learned' (($cal.predicted -eq 19.67) -and ($cal.delta -eq 0.94) -and ($cal.overhead -eq 0.94))
Check 'calibration: EMA' ((GovCalibrate $cal.overhead 20.21 17.15 40960 64.5).overhead -eq 0.74)
Check 'calibration: clamps' (((GovCalibrate $null 30.0 17.15 40960 64.5).overhead -eq 1.5) -and ((GovCalibrate $null 10.0 17.15 40960 64.5).overhead -eq -0.5))
$oh = GovLaunchOverhead ([pscustomobject]@{ overhead_gib = $cal.overhead })
Check 'launch overhead: positive part only, off switch honoured' (($oh -eq 0.94) -and ((GovLaunchOverhead ([pscustomobject]@{ overhead_gib = -0.3 })) -eq 0.0) -and ((GovLaunchOverhead ([pscustomobject]@{ overhead_gib = 0.94 }) $false) -eq 0.0) -and ((GovLaunchOverhead $null) -eq 0.0))
$ctxCal = GovFitCtx $TOTAL 1.5 2.62 17.15 64.5 32768 65536 $oh
$freeAfter = [math]::Round($TOTAL - 2.62 - (GovPredictedLlamaGib 17.15 $ctxCal 64.5 $oh), 2)
Check "calibrated fit for today's launch: ctx $ctxCal (ctx_min), free lands at $freeAfter GiB" (($ctxCal -eq 32768) -and ($freeAfter -ge 1.1) -and ($freeAfter -le 1.3))
Check 'uncalibrated fit reproduces the 40960 that left 0.65 free' ((GovFitCtx $TOTAL 1.5 2.62 17.15 64.5 32768 65536) -eq 40960)
Check 'idle PC still gets 65536 with the overhead' ((GovFitCtx $TOTAL 1.35 0.14 17.15 64.5 32768 65536 $oh) -eq 65536)
Check 'a good sample resets the counter' ((GovPressureStep 3 1.4 9.0 $true $true 1.1 1.5 3.3 2.5) -eq 0)
Check 'reason: RAM trigger is named, not blamed on VRAM' ((GovPressureReason 23.88 1.2 1.1 1.5) -eq 'RAM 1.20 GB < 1.50')
$d = GovDecide (BaseState @{ free_gib = 0.3; pressure_count = 8; in_flight = $true })
Check 'never unload in flight' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ free_gib = 0.3; pressure_count = 8; in_flight = $null })
Check 'unknown slot state -> no optional reload' (($d.action -eq 'none') -and ($d.reason -eq 'slot state unknown'))
$d = GovDecide (BaseState @{ mode = 'OFF'; in_flight = $true })
Check 'mode OFF still waits for the request' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ free_gib = 0.5; pressure_count = 8; cur_id = 'qwen3.8-27b-long' })
Check 'LONG variant never re-fit' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ free_gib = 0.5; pressure_count = 8; committed = 'LEAN'; loaded_profile = 'LEAN' })
Check 'LEAN + persistent pressure -> unload' ($d.action -eq 'unload')

# ---- 3d) agent clients ----
$d = GovDecide (BaseState @{ committed = 'LEAN'; loaded_profile = 'LEAN'; idle_unload_min = 5; quiet_sec = 400; agent_active = $true })
Check 'agent active blocks idle unload' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ committed = 'LEAN'; loaded_profile = 'LEAN'; idle_unload_min = 5; quiet_sec = 400; agent_active = $false })
Check 'no agent -> idle unload as before' ($d.action -eq 'idle-unload')
$d = GovDecide (BaseState @{ loaded = $false; state = 'stopped'; committed = 'BALANCED'; agent_active = $true })
Check 'agent active + model stopped -> prewarm' ($d.action -eq 'prewarm')
$d = GovDecide (BaseState @{ loaded = $false; state = 'stopped'; committed = 'LEAN'; agent_active = $true })
Check 'but not under LEAN' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ loaded = $false; state = 'stopped'; committed = 'MAX'; since_prewarm_min = 2 })
Check 'prewarm cooldown respected' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ loaded_profile = 'BALANCED'; committed = 'MAX'; quiet_sec = 1300; since_refit_min = 10 })
Check 'upgrade is rate-limited' ($d.action -eq 'none')
$d = GovDecide (BaseState @{ loaded_profile = 'BALANCED'; committed = 'MAX'; quiet_sec = 1300; since_refit_min = 15 })
Check 'upgrade after 15 min' ($d.action -eq 'upgrade')

# ---- 3e) ctx formula against real launch lines ----
Check 'launch 2026-10-11T21:22:19 BALANCED others=1.53 -> 57344' ((GovFitCtx $TOTAL 1.5 1.53 17.15 64.5 32768 65536) -eq 57344)
Check 'launch 2026-10-15T23:17:21 BALANCED others=2.87 -> 36864' ((GovFitCtx $TOTAL 1.5 2.87 17.15 64.5 32768 65536) -eq 36864)
Check 'launch 2026-10-15T10:31:53 MAX others=3.32 -> 32768' ((GovFitCtx $TOTAL 1.35 3.32 17.15 64.5 32768 65536) -eq 32768)
Check 'launch 2026-10-11T12:56:33 MAX others=0.14 -> 65536' ((GovFitCtx $TOTAL 1.35 0.14 17.15 64.5 32768 65536) -eq 65536)
Check 'MAX 61440 needs others <= 1.6 GiB' ((GovFitCtx $TOTAL 1.35 1.6 17.15 64.5 32768 65536) -eq 61440)

# ---- 3f) profile choice with invalid readings ----
Check 'invalid ram+others never push LEAN' ((GovProfileChoice 'AUTO' 40000 0.0 $false 21.3 $false 0 $AUTO) -eq 'BALANCED')
Check 'idle PC, good readings -> MAX' ((GovProfileChoice 'AUTO' 40000 20.0 $true 0.4 $true 0 $AUTO) -eq 'MAX')
Check '2026-10-10T08:14:02 ram=2.43 -> LEAN' ((GovProfileChoice 'AUTO' 40000 2.43 $true 1.1 $true 0 $AUTO) -eq 'LEAN')

# ---- 3g) loop error accounting: first error logged, then counted; state re-initialised after 4 in a row ----
$script:errStreak = 0; $script:errTotal = 0; $script:heals = 0; $script:pressureCount = 7; $script:lastGoodVram = @{ used = 1 }
$fake = $null; try { throw 'Cannot index into a null array.' } catch { $fake = $_ }
for ($i = 0; $i -lt 4; $i++) { NoteLoopError $fake }
Check '4 consecutive loop errors -> one self-heal, state reset' (($script:heals -eq 1) -and ($script:errStreak -eq 4) -and ($script:pressureCount -eq 0) -and ($null -eq $script:lastGoodVram))
Check 'last_error carries the message and the line' ($script:lastError -like 'Cannot index into a null array.*line*')
for ($i = 0; $i -lt 36; $i++) { NoteLoopError $fake }
Check 'second self-heal only at 40' ($script:heals -eq 2)
$lg = ''; try { $lg = Get-Content -LiteralPath $testLog -Raw } catch {}
Check 'self-heal lines went to the temp log' (($lg -like '*loop error at line*') -and ($lg -like '*self-heal: state re-initialised after 40*'))

# ---- 3i) power plan hysteresis (v4.2) ----
# Replay of governor.log 2026-10-16 08:09-08:40 (v4.1: 104 power changes in 400 lines, e.g. 08:09:31 SAVER -> BALANCED cpu=32.9,
# 08:10:12 -> PERFORMANCE cpu=72.1, 08:11:33 -> SAVER cpu=3.2, 08:11:54 -> BALANCED, 08:12:14 -> PERFORMANCE ... 08:37:20 -> SAVER cpu=1,
# 08:38:22 -> BALANCED). Agent bursts: 2-3 samples >= 70 % CPU every ~2 min, ~3 % between; codex/claude processes alive; model quiet.
$PCFG = [pscustomobject]@{ dwell_min = 10; saver_idle_min = 15; saver_model_quiet_min = 15; perf_model_recent_sec = 120; cpu_busy_pct = 40; cpu_busy_samples = 2; cpu_calm_pct = 25 }
function PowStep($st, $t, $cpu, $idle, $quiet, $busy, $agent, $mode = 'AUTO') { GovPowerDecide $st @{ t = $t; mode = $mode; cpu = $cpu; idle_sec = $idle; quiet_sec = $quiet; model_busy = $busy; agent_active = $agent; cfg = $PCFG } }
$t0 = [datetime]'2026-10-16T08:09:16'
$st = @{ now = 'SAVER'; entered = $t0.AddMinutes(-9); down_since = $null; cpu_busy = 0 }   # as v4.1 left it before 08:09:31
$logged = @{ 15 = 32.9; 60 = 72.1; 135 = 3.2; 1680 = 1.0 }                                  # 08:09:31, 08:10:12, 08:11:33, 08:37:20 from the log, snapped to the 15 s grid
$trans = New-Object System.Collections.ArrayList
$plans = @{}
for ($sec = 15; $sec -le 1860; $sec += 15) {                                                # 08:09:31 .. 08:40:16, 15 s cadence
  $cpu = 3.0; if ((($sec % 120) -ge 45) -and (($sec % 120) -lt 90)) { $cpu = 72.0 }         # a burst of three samples every two minutes (first one 08:10:01-08:10:31)
  if ($logged.ContainsKey($sec)) { $cpu = $logged[$sec] }
  $t = $t0.AddSeconds($sec)
  $before = $st.now
  $r = PowStep $st $t $cpu 30 (1800 + $sec) $false $true
  $st = $r.st
  if ($r.apply -and $r.apply -ne $before) { [void]$trans.Add(('{0} {1} -> {2} ({3})' -f $t.ToString('HH:mm:ss'), $before, $r.apply, $r.reason)) }
  $plans[$sec] = $st.now
}
Check ("replay 08:09-08:40 with agent bursts: at most 2 power transitions (got {0}: {1})" -f $trans.Count, ($trans -join '; ')) ($trans.Count -le 2)
Check '   first step SAVER -> BALANCED at once (agent floor), then -> PERFORMANCE at 08:10:16 on the first sustained burst' (($trans.Count -eq 2) -and ($trans[0] -like '08:09:31 SAVER -> BALANCED (up: agent client active*') -and ($trans[1] -like '08:10:16 BALANCED -> PERFORMANCE (up: cpu 72*'))
Check '   final state after 31 min of bursts is PERFORMANCE (never dropped between bursts: 08:11:33 cpu=3.2 and 08:37:20 cpu=1 stay PERFORMANCE)' ($st.now -eq 'PERFORMANCE' -and $plans[135] -eq 'PERFORMANCE' -and $plans[1680] -eq 'PERFORMANCE')
Check '   transitions carry a reason' (@($trans | Where-Object { $_ -notmatch '\(.+\)$' }).Count -eq 0)
# bursts stop, agent still active: ONE step down to BALANCED after the 10 min dwell, never SAVER while the agent lives
$trans2 = New-Object System.Collections.ArrayList; $tb = $t0.AddSeconds(1860); $downAt = $null
for ($sec = 15; $sec -le 1800; $sec += 15) {
  $t = $tb.AddSeconds($sec); $before = $st.now
  $r = PowStep $st $t 2.0 (600 + $sec) (3600 + $sec) $false $true
  $st = $r.st
  if ($r.apply -and $r.apply -ne $before) { [void]$trans2.Add($r.apply); if ($null -eq $downAt) { $downAt = $sec } }
}
Check ("calm 30 min with an agent client: exactly one step down to BALANCED (got {0})" -f ($trans2 -join ',')) ($trans2.Count -eq 1 -and $trans2[0] -eq 'BALANCED' -and $st.now -eq 'BALANCED')
Check ("   the step down waited the full 10 min dwell from the first calm sample (at {0} s into the calm window, expected 615 = 15 + 600)" -f $downAt) ($downAt -eq 615)
Check '   the agent floor keeps it off SAVER even though the PC is idle 40 min and the model quiet 90 min' ($st.now -eq 'BALANCED')
# agent gone, PC idle, model quiet: one more step to SAVER after another dwell
$trans3 = New-Object System.Collections.ArrayList; $tc = $tb.AddSeconds(1800); $saverAt = $null
for ($sec = 15; $sec -le 1200; $sec += 15) {
  $t = $tc.AddSeconds($sec); $before = $st.now
  $r = PowStep $st $t 2.0 (2400 + $sec) (5400 + $sec) $false $false
  $st = $r.st
  if ($r.apply -and $r.apply -ne $before) { [void]$trans3.Add($r.apply); if ($null -eq $saverAt) { $saverAt = $sec } }
}
Check ("no agent, idle, quiet: one step BALANCED -> SAVER a full dwell after the agent left (got {0} at {1} s, expected 615 = first agent-free sample + 600)" -f ($trans3 -join ','), $saverAt) ($trans3.Count -eq 1 -and $st.now -eq 'SAVER' -and $saverAt -eq 615)
# upgrades are immediate: a request arrives
$r = PowStep $st $tc.AddSeconds(1215) 5.0 3000 0 $true $true
Check 'model busy -> SAVER -> PERFORMANCE on the very next sample' ($r.apply -eq 'PERFORMANCE' -and $r.reason -like 'up: model busy*')
$st = $r.st
# a one-sample CPU spike does not count; the second does
$st2 = @{ now = 'BALANCED'; entered = $t0; down_since = $null; cpu_busy = 0 }
$r = PowStep $st2 $t0.AddSeconds(15) 72.0 30 3000 $false $true
Check 'one 72 % sample: no change (cpu_busy_samples 2)' ($null -eq $r.apply -and $r.st.cpu_busy -eq 1)
$r = PowStep $r.st $t0.AddSeconds(30) 72.0 30 3000 $false $true
Check 'second 72 % sample: PERFORMANCE' ($r.apply -eq 'PERFORMANCE')
# SAVER needs BOTH idle and model-quiet thresholds (15 min), not the old 10/5
function LowFor30 { return @{ now = 'BALANCED'; entered = $t0.AddMinutes(-30); down_since = $t0.AddMinutes(-30); cpu_busy = 0 } }   # fresh state each time: GovPowerDecide mutates it
Check 'idle 20 min but model quiet only 10 min -> no SAVER' ((PowStep (LowFor30) $t0 2.0 1200 600 $false $false).want -eq 'BALANCED')
Check 'model quiet 20 min but idle only 10 min -> no SAVER' ((PowStep (LowFor30) $t0 2.0 600 1200 $false $false).want -eq 'BALANCED')
Check 'idle 16 min + quiet 16 min + calm -> SAVER wanted (and applied: dwell long satisfied)' ((PowStep (LowFor30) $t0 2.0 960 960 $false $false).apply -eq 'SAVER')
Check 'idle 16 min + quiet 16 min but CPU 30 % -> no SAVER' ((PowStep (LowFor30) $t0 30.0 960 960 $false $false).want -eq 'BALANCED')
Check 'same but agent active -> BALANCED floor' ((PowStep (@{ now = 'BALANCED'; entered = $t0.AddMinutes(-30); down_since = $null; cpu_busy = 0 }) $t0 2.0 960 960 $false $true).want -eq 'BALANCED')
# a plan held for less than the dwell is never left downward, even if the demand has been low for the dwell
$st4 = @{ now = 'PERFORMANCE'; entered = $t0.AddMinutes(-5); down_since = $t0.AddMinutes(-11); cpu_busy = 0 }
Check 'held 5 min < dwell: no step down yet' ($null -eq (PowStep $st4 $t0 2.0 30 3000 $false $true).apply)
# PERFORMANCE steps to BALANCED first, never straight to SAVER
$st5 = @{ now = 'PERFORMANCE'; entered = $t0.AddMinutes(-20); down_since = $t0.AddMinutes(-12); cpu_busy = 0 }
$r = PowStep $st5 $t0 2.0 2000 2000 $false $false
Check 'PERFORMANCE with SAVER wanted steps to BALANCED first' ($r.want -eq 'SAVER' -and $r.apply -eq 'BALANCED' -and $r.reason -like 'down after 12 min*')
# forced mode (power.txt) still applies immediately, both ways
Check 'power mode SAVER forced while the model is busy -> SAVER now' ((PowStep (@{ now = 'PERFORMANCE'; entered = $t0; down_since = $null; cpu_busy = 0 }) $t0.AddSeconds(15) 90.0 0 0 $true $true 'SAVER').apply -eq 'SAVER')
$ru = PowStep (@{ now = 'BALANCED'; entered = $t0; down_since = $null; cpu_busy = 1 }) $t0 $null 30 3000 $false $true
Check 'unknown CPU is neutral: busy streak neither grows nor resets, no spurious PERFORMANCE' (($null -eq $ru.apply) -and ($ru.st.cpu_busy -eq 1))
Check 'first sample ever applies the wanted plan (startup)' ((PowStep $null $t0 3.0 30 3000 $false $true).reason -like 'startup:*')
$pj = ReadJsonFile (Join-Path $here 'profiles.json')
Check 'profiles.json carries the power section with dwell 10 / saver 15+15' ($pj.power.dwell_min -eq 10 -and $pj.power.saver_idle_min -eq 15 -and $pj.power.saver_model_quiet_min -eq 15)

# ---- 3h) slotlib: KV type guard on restore ----
. (Join-Path $here 'slotlib.ps1')
$script:SlotLogPath = $testLog
$sc = [pscustomobject]@{ n_tokens = 43000; model_path = 'C:/m/x.gguf'; model_size = 1000; model_mtime = 2000; kv = 'f16/f16' }
$stat = [pscustomobject]@{ size = 1000; mtime = 2000 }
Check 'restore allowed: same KV' ((SlotRestoreDecision $sc $true 'C:/m/x.gguf' 65536 $stat 4096 'f16/f16').ok)
Check 'restore refused: KV type changed' (-not (SlotRestoreDecision $sc $true 'C:/m/x.gguf' 65536 $stat 4096 'q8_0/q8_0').ok)
Check 'restore allowed: KV unknown on one side (old sidecar)' ((SlotRestoreDecision $sc $true 'C:/m/x.gguf' 65536 $stat 4096 $null).ok)
Check 'restore refused: ctx too small for the slot' (-not (SlotRestoreDecision $sc $true 'C:/m/x.gguf' 45056 $stat 4096 'f16/f16').ok)
Check 'SlotCfg reads min_free_disk_gib' ((SlotCfg ([pscustomobject]@{ slots = [pscustomobject]@{ enabled = $true; dir = 'C:/AI/cache/slots'; max_files = 3; max_gib = 12; min_tokens = 4096; min_free_disk_gib = 25 }; common_args = @('--slot-save-path', 'C:/AI/cache/slots') })).min_free_disk_gib -eq 25)

try { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
""
"$passes passed, $fails failed"
if ($fails) { exit 1 }
