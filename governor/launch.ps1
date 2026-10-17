# Called by llama-swap to start llama-server with the governor's current profile.
# Context is sized at load time from the VRAM actually free right now, keeping the profile's
# "free VRAM" margin for Windows/apps, and never spilling into shared memory (measured limits).
# llama-swap stops it with "taskkill /f /t", which also kills the llama-server child.
# v4 (2026-10-15): 'others' is measured only after the previous llama-server is really gone (up to 45 s), as the
# minimum of three samples, and cross-checked against the governor's last good value (status.json). The old code
# measured once after a 15 s wait and once booked a dying server's 21.24 GiB as "others" (ctx 32768 at 08:04 on 10-11).
# The others/ctx formulas mirror govpolicy.launch_others / fit_ctx (test_govpolicy.py).
param([string]$Variant = 'default', [switch]$DryRun)   # -DryRun: print the decision and the command line, start nothing
$ErrorActionPreference = 'Stop'
$dir = 'C:\AI\governor'
$cfg = Get-Content "$dir\profiles.json" -Raw | ConvertFrom-Json
$v = $cfg.variants.$Variant; if (-not $v) { $Variant = 'default'; $v = $cfg.variants.default }
$name = 'BALANCED'
try { $d = (Get-Content "$dir\desired.txt" -ErrorAction Stop).Trim().ToUpper(); if ($cfg.profiles.PSObject.Properties.Name -contains $d) { $name = $d } } catch {}
$p = $cfg.profiles.$name
$OTHERS_PLAUSIBLE_MAX_GIB = 8.0
function LaunchLog($m) { try { "$(Get-Date -f s) $m" | Add-Content "$dir\governor.log" } catch {} }

# ---- 1) wait (max 45 s) for any previous llama-server to exit; its VRAM must not be booked as 'others' ----
$waited = 0
# v4.3 (2026-10-17): only OUR llama-server counts. Ollama's runner is also named llama-server.exe (C:\Apps\Ollama\lib\ollama\),
# and on 17 Oct it kept llama3.2:3b (3.07 GiB) resident for 24 h: the old code waited 45 s for it, then booked others=default.
function OurServers { @(Get-Process llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like 'C:\AI\llama.cpp\*' }) }
while ($waited -lt 45 -and (OurServers).Count -gt 0) { Start-Sleep 1; $waited++ }
$stillAlive = ((OurServers).Count -gt 0)
if ($waited -gt 0) { Start-Sleep 2 }   # let the driver release the heap before measuring

# ---- 2) measure adapter 'Dedicated Usage' three times (max over adapters per sample), keep the smallest ----
$samples = @()
for ($i = 0; $i -lt 3; $i++) {
  try {
    $cs = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples
    $mx = $null
    foreach ($x in @($cs)) { if ($null -ne $x -and $x.Status -eq 0) { $g = [double]$x.CookedValue / 1GB; if (($null -eq $mx) -or ($g -gt $mx)) { $mx = $g } } }
    if ($null -ne $mx) { $samples += $mx }
  } catch {}
  if ($i -lt 2) { Start-Sleep 1 }
}
# the governor's last good 'others' (status.json), if fresh
$stOthers = $null; $stAge = $null
try {
  $st = Get-Content "$dir\public\status.json" -Raw -ErrorAction Stop | ConvertFrom-Json
  $stAge = ((Get-Date) - [datetime]$st.time).TotalSeconds
  if ($st.vram_ok -eq $true -and $null -ne $st.vram_others_gib) { $stOthers = [double]$st.vram_others_gib }
} catch {}
$fresh = ($null -ne $stOthers) -and ($null -ne $stAge) -and ($stAge -le 120) -and ($stOthers -ge 0) -and ($stOthers -le $OTHERS_PLAUSIBLE_MAX_GIB)
$others = 2.2; $othersNote = 'default'
if ($samples.Count -eq 0) {
  if ($fresh) { $others = $stOthers; $othersNote = "adapter counter failed; using governor's others" } else { $othersNote = 'adapter counter failed; default' }
} else {
  $meas = ($samples | Measure-Object -Minimum).Minimum
  if ($stillAlive) {
    if ($fresh) { $others = $stOthers; $othersNote = ('old llama-server still alive (measured {0:F2}); using governor''s others' -f $meas) }
    else { $othersNote = ('old llama-server still alive (measured {0:F2}); default' -f $meas) }
  } elseif ($meas -gt $OTHERS_PLAUSIBLE_MAX_GIB) {
    if ($fresh) { $others = $stOthers; $othersNote = ('measured {0:F2} GiB implausible; using governor''s others' -f $meas) }
    else { $others = $meas; $othersNote = ('measured {0:F2} GiB implausible but no better source' -f $meas) }
  } else { $others = $meas; $othersNote = 'measured' }
}
$others = [math]::Round([double]$others, 2)

# ---- 3) context sizing ----
$ctk = $v.ctk; $ctv = $v.ctv
$extra = @($v.extra_args)
$draftNote = ''; $overhead = 0.0
if ($v.fixed_ctx) {
  $ctx = [int]$v.fixed_ctx
  # Optional drafter (e.g. MTP for the 262k LONG model) only if enough VRAM stays free after it loads
  if ($v.optional_draft) {
    $freeAfter = $cfg.vram.total_gib - $others - $v.base_gib - $v.optional_draft.cost_gib
    if ($freeAfter -ge $v.optional_draft.min_free_gib) { $extra += @($v.optional_draft.args) ; $draftNote = "with drafter (free after ~$([math]::Round($freeAfter,2)) GiB)" } else { $draftNote = "no drafter (would leave only $([math]::Round($freeAfter,2)) GiB free)" }
  }
}
else {
  $kvKiB = $v.kv_kib_per_token
  # learned footprint the base_gib/kv model misses (governor writes calib.json at each post-launch baseline); never negative
  $overhead = 0.0; $calEnabled = $true; try { if ($cfg.calibration.enabled -is [bool]) { $calEnabled = $cfg.calibration.enabled } } catch {}
  $maxOver = 1.5; try { if ($cfg.calibration.max_overhead_gib) { $maxOver = [double]$cfg.calibration.max_overhead_gib } } catch {}
  # an entry only counts for the model file + engine it was learned with (same fingerprint rule as governor.ps1 CalibEntry)
  $fpSize = ''; try { $fpSize = [string](Get-Item -LiteralPath ([string]$v.model) -ErrorAction Stop).Length } catch {}
  $fp = '{0}|{1}|{2}' -f [string]$v.model, $fpSize, [string]$cfg.exe
  if ($calEnabled) { try { $cal = Get-Content "$dir\calib.json" -Raw -ErrorAction Stop | ConvertFrom-Json; $ce = $cal.PSObject.Properties[$v.id]
                           if ($ce -and ($null -ne $ce.Value.overhead_gib) -and ([string]$ce.Value.fingerprint -eq $fp)) { $overhead = [math]::Round([math]::Max(0.0, [math]::Min($maxOver, [double]$ce.Value.overhead_gib)), 2) } } catch {} }
  $targetGiB = $cfg.vram.total_gib - $p.free_margin_gib - $others
  $kib = ($targetGiB - $v.base_gib - $overhead) * 1MB   # GiB->KiB = *1MB
  $ctx = 0; if ($kib -gt 0) { $ctx = [int]([math]::Floor($kib / $kvKiB / 4096) * 4096) }
  $ctx = [math]::Max([int]$p.ctx_min, [math]::Min([int]$v.ctx_max, $ctx))
  # Session protection: never come back smaller than the largest live agent session (written by the governor).
  try { $need = [int](Get-Content "$dir\session-need.txt" -ErrorAction Stop) } catch { $need = 0 }
  if ($need -gt 0 -and $ctx -lt ($need + 8192)) {
    $want = [int]([math]::Ceiling(($need + 8192) / 4096) * 4096)
    $emerg = [int]([math]::Floor(((($cfg.vram.total_gib - 1.15 - $others) - $v.base_gib - $overhead) * 1MB) / $kvKiB / 4096) * 4096)   # 1.15 GiB = just above the measured slowdown cliff
    $new = [math]::Min([math]::Min($want, $emerg), [int]$v.ctx_max)
    if ($new -gt $ctx) { $draftNote = "session-protect: raised ctx $ctx -> $new for live session of $need tokens"; $ctx = $new }
    if ($ctx -lt ($need + 4096)) { $draftNote += " WARNING: cannot fit live session ($need tokens) - client will get an explicit context error, never silent truncation" }
  }
  # why the fit is below the preferred window (f16 KV: 61440 needs others <= ~1.6 GiB in MAX) - informational
  $tgt = 0; try { $tgt = [int]$cfg.auto.ctx_target_min } catch {}
  if ($tgt -gt 0 -and $ctx -lt $tgt -and $ctx -lt [int]$v.ctx_max) {
    $maxOthers = [math]::Round($cfg.vram.total_gib - $p.free_margin_gib - $v.base_gib - $overhead - ($tgt * $kvKiB / 1MB), 2)
    $draftNote += " (ctx below target $tgt`: others=$others GiB, margin=$($p.free_margin_gib); target needs others <= $maxOthers GiB)"
  }
}

$prio = @{ Normal = '0'; BelowNormal = '-1' }[$p.priority]; if (-not $prio) { $prio = '-1' }
try { if ($cfg.slots -and $cfg.slots.dir) { New-Item -ItemType Directory -Force -Path $cfg.slots.dir | Out-Null } } catch {}   # llama-server does not create --slot-save-path itself
$args2 = @('-m', $v.model, '--mmproj', $(if ($v.mmproj) { $v.mmproj } else { $cfg.mmproj }), '-a', $v.id, '--host', '127.0.0.1', '--port', "$($v.port)",
           '-c', "$ctx", '-ctk', $ctk, '-ctv', $ctv,
           '-t', "$($p.threads)", '-tb', "$($p.threads)", '-cram', "$($p.cache_ram_mib)", '--prio', $prio) + @($cfg.common_args) + $extra
foreach ($e in $cfg.env.PSObject.Properties) { Set-Item -Path "env:$($e.Name)" -Value $e.Value }

try { @{ emergency = [bool]($draftNote -like 'session-protect*'); profile = $name; variant = $Variant; id = $v.id; port = $v.port; ctx = $ctx; ctk = $ctk; ctv = $ctv; others_gib = $others; others_note = $othersNote; overhead_gib = $overhead; started = (Get-Date).ToString('s'); launcher_pid = [System.Diagnostics.Process]::GetCurrentProcess().Id } | ConvertTo-Json | Set-Content "$dir\running.json" } catch {}   # governor may hold the file for a moment; never abort the launch for bookkeeping
$line = "launch: $($v.id) profile=$name ctx=$ctx kv=$ctk/$ctv others=${others}GiB ($othersNote; waited ${waited}s) overhead=${overhead}GiB port=$($v.port) $draftNote"
if ($DryRun) { Write-Output "DRYRUN $line"; Write-Output ("DRYRUN cmd: " + $cfg.exe + ' ' + ($args2 -join ' ')); exit 0 }
LaunchLog $line
& $cfg.exe @args2
exit $LASTEXITCODE
