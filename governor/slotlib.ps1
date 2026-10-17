# Slot persistence for the Qwen governor: save the KV slot before an unload, restore it after a governor-initiated load.
# v4 (2026-10-15): sidecar records the KV type (ctk/ctv) and a restore into a different KV type is refused; the save checks free disk first.
# Dot-sourced by governor.ps1, qwen.ps1 and the restore background job. PowerShell 5.1 compatible. No top-level side effects.
# The pure decision functions (Slot*Decision, SlotPruneSelection, SlotEmptyReplyStep ...) mirror governor/slotpolicy.py,
# which has the unit tests (python3 governor/test_slotpolicy.py). Change a rule in both places.
$script:SlotLogPath = 'C:\AI\governor\governor.log'
$script:SlotLogged = @{}

function SlotLog($m) {
  $line = "$(Get-Date -f s) $m"
  try { $line | Add-Content $script:SlotLogPath -ErrorAction Stop } catch { try { Start-Sleep -Milliseconds 250; $line | Add-Content $script:SlotLogPath -ErrorAction Stop } catch {} }
}
function SlotLogOnce($key, $m) { if (-not $script:SlotLogged.ContainsKey($key)) { $script:SlotLogged[$key] = $true; SlotLog $m } }

# ---------------- pure decision logic (mirrors slotpolicy.py) ----------------
function SlotIsNum($v) { ($v -is [int]) -or ($v -is [long]) -or ($v -is [double]) -or ($v -is [decimal]) -or ($v -is [single]) }
function SlotResult($ok, $reason) { [pscustomobject]@{ ok = [bool]$ok; reason = [string]$reason } }
function SlotNormPath($p) { ([string]$p).Replace('\', '/').Trim().ToLowerInvariant() }

function SlotFilename($id) {
  if (($id -isnot [string]) -or ($id -notmatch '^[A-Za-z0-9._-]{1,64}$') -or $id.StartsWith('.')) { return $null }
  return ($id + '.bin')
}
function SlotTokenCount($slot) {
  if ($null -eq $slot) { return $null }
  foreach ($k in 'n_tokens', 'n_past', 'n_cache_tokens') {
    $pr = $slot.PSObject.Properties[$k]
    if ($pr -and (SlotIsNum $pr.Value) -and ($pr.Value -ge 0)) { return [int]$pr.Value }
  }
  return $null
}
function SlotSaveDecision($slot, $minTokens) {
  if ($null -eq $slot) { return (SlotResult $false 'no slot info') }
  if ($slot.is_processing -eq $true) { return (SlotResult $false 'slot busy') }
  $n = SlotTokenCount $slot
  if ($null -eq $n) { return (SlotResult $true 'n_tokens not reported') }      # save anyway; SlotPostSaveOk re-checks n_saved
  if ($n -lt $minTokens) { return (SlotResult $false "n_tokens $n < min_tokens $minTokens") }
  return (SlotResult $true "n_tokens $n")
}
function SlotPostSaveOk($nSaved, $minTokens) {
  if (-not (SlotIsNum $nSaved)) { return (SlotResult $false 'save reply has no n_saved') }
  $n = [int]$nSaved
  if ($n -lt $minTokens) { return (SlotResult $false "n_saved $n < min_tokens $minTokens") }
  return (SlotResult $true "n_saved $n")
}
function SlotRestoreDecision($sidecar, $binExists, $modelPath, $ctx, $modelStat, $headroom = 4096, $kvNow = $null) {
  if (-not $binExists) { return (SlotResult $false 'no slot file') }
  if (($null -eq $sidecar) -or ($sidecar -is [string]) -or ($sidecar -is [ValueType]) -or ($sidecar -is [array])) { return (SlotResult $false 'no sidecar') }
  $n = $sidecar.n_tokens
  if (-not (SlotIsNum $n) -or $n -le 0) { return (SlotResult $false 'sidecar has no n_tokens') }
  $n = [int]$n
  $sm = $sidecar.model_path
  if (-not $sm -or -not $modelPath -or ((SlotNormPath $sm) -ne (SlotNormPath $modelPath))) { return (SlotResult $false 'model_path mismatch') }
  if (-not $modelStat) { return (SlotResult $false 'model file stat unavailable') }
  if (-not (SlotIsNum $sidecar.model_size) -or -not (SlotIsNum $sidecar.model_mtime)) { return (SlotResult $false 'sidecar has no model size/mtime') }
  if (([long]$sidecar.model_size -ne [long]$modelStat.size) -or ([long]$sidecar.model_mtime -ne [long]$modelStat.mtime)) { return (SlotResult $false 'model file changed (size/mtime differ)') }
  # a slot saved with one KV type (f16) cannot be restored into another (q8_0): refuse when both sides are known and differ
  $skv = $null; $kp = $sidecar.PSObject.Properties['kv']; if ($kp -and ($kp.Value -is [string])) { $skv = $kp.Value }
  if ($skv -and $kvNow -and ($skv.ToLowerInvariant() -ne ([string]$kvNow).ToLowerInvariant())) { return (SlotResult $false "kv type changed ($skv -> $kvNow)") }
  if (-not (SlotIsNum $ctx) -or $ctx -le 0) { return (SlotResult $false 'new ctx unknown') }
  $ctx = [int]$ctx
  if ($ctx -lt ($n + $headroom)) { return (SlotResult $false "ctx $ctx < n_tokens $n + $headroom") }
  return (SlotResult $true "n_tokens $n")
}
# May the governor unload now? Only a definitely-processing slot says no (checked before AND after the save).
function SlotUnloadGate($slot) {
  if (($null -ne $slot) -and ($slot.is_processing -eq $true)) { return (SlotResult $false 'slot busy') }
  if ($null -eq $slot) { return (SlotResult $true 'slot state unknown') }
  return (SlotResult $true 'slot idle')
}
function SlotRestoreTargetOk($slot) {
  if ($null -eq $slot) { return (SlotResult $true 'slot state unknown') }
  if ($slot.is_processing -eq $true) { return (SlotResult $false 'slot busy (a request is already running)') }
  $n = SlotTokenCount $slot
  if (($null -ne $n) -and ($n -gt 0)) { return (SlotResult $false "slot not empty ($n tokens)") }
  return (SlotResult $true 'slot empty')
}
# entries: objects with .name .size (bytes) .mtime (epoch seconds). Returns leaf names to delete. Never returns anything but *.bin / *.json leaf names.
function SlotPruneSelection($entries, $maxFiles, $maxGib, $managedIds = $null) {
  $maxBytes = [double]$maxGib * 1GB
  $del = New-Object System.Collections.ArrayList
  $units = @{}
  foreach ($e in @($entries)) {
    $name = [string]$e.name
    if (-not $name -or $name.Contains('/') -or $name.Contains('\')) { continue }
    if ($name.EndsWith('.tmp.bin')) { $stem = $name.Substring(0, $name.Length - 8); $kind = 'tmp' }
    elseif ($name.EndsWith('.bin')) { $stem = $name.Substring(0, $name.Length - 4); $kind = 'bin' }
    elseif ($name.EndsWith('.json')) { $stem = $name.Substring(0, $name.Length - 5); $kind = 'json' }
    else { continue }
    if (($null -ne $managedIds) -and (@($managedIds) -notcontains $stem)) { continue }
    if ($kind -eq 'tmp') { [void]$del.Add($name); continue }
    if (-not $units.ContainsKey($stem)) { $units[$stem] = @{} }
    $units[$stem][$kind] = $e
  }
  $complete = @()
  foreach ($stem in @($units.Keys)) {
    $u = $units[$stem]
    if ($u.ContainsKey('bin') -and $u.ContainsKey('json')) {
      $complete += [pscustomobject]@{ stem = $stem; size = ([double]$u['bin'].size + [double]$u['json'].size); mtime = [math]::Max([double]$u['bin'].mtime, [double]$u['json'].mtime) }
    } else { foreach ($k in @($u.Keys)) { [void]$del.Add([string]$u[$k].name) } }
  }
  $complete = @($complete | Sort-Object mtime, stem)      # oldest first
  $count = $complete.Count; $total = 0.0; foreach ($c in $complete) { $total += $c.size }
  $i = 0
  while (($i -lt $complete.Count) -and (($count -gt $maxFiles) -or ($total -gt $maxBytes))) {
    $c = $complete[$i]; [void]$del.Add($c.stem + '.bin'); [void]$del.Add($c.stem + '.json')
    $count--; $total -= $c.size; $i++
  }
  return @($del)
}
function SlotHygieneDecision($loadedMin, $quietMin, $processing, $intervalHours, $sinceLastMin, $minQuietMin = 10, $cooldownMin = 30) {
  if (-not $intervalHours -or $intervalHours -le 0) { return (SlotResult $false 'disabled') }
  if ($processing) { return (SlotResult $false 'busy') }
  if ($null -eq $loadedMin) { return (SlotResult $false 'load time unknown') }
  if ($loadedMin -lt ($intervalHours * 60)) { return (SlotResult $false ('loaded {0:F0} min < {1:F0} min' -f $loadedMin, ($intervalHours * 60))) }
  if ($quietMin -le $minQuietMin) { return (SlotResult $false ('quiet {0:F1} min <= {1} min' -f $quietMin, $minQuietMin)) }
  if (($null -ne $sinceLastMin) -and ($sinceLastMin -lt $cooldownMin)) { return (SlotResult $false 'cooldown') }
  return (SlotResult $true ('loaded {0:F1} h, quiet {1:F1} min' -f ($loadedMin / 60.0), $quietMin))
}
# Heuristic over /metrics counters (there is no per-request counter). Caller advances prev* only when nothing is processing.
function SlotEmptyReplyStep($prevP, $prevT, $p, $t, $processing, $count) {
  if (($null -eq $prevP) -or ($null -eq $prevT) -or ($null -eq $p) -or ($null -eq $t)) { return 0 }
  if (($p -lt $prevP) -or ($t -lt $prevT)) { return 0 }       # counters went backwards: server restarted
  if ($processing) { return $count }
  if (($t - $prevT) -gt 0) { return 0 }
  if (($p - $prevP) -gt 0) { return ($count + 1) }
  return $count
}

# ---------------- Control Centre levers: request.json, phases, VRAM bands (mirror slotpolicy.py) ----------------
function SlotReqResult($ok, $action, $arg, $reason) { [pscustomobject]@{ ok = [bool]$ok; action = $action; arg = $arg; reason = [string]$reason } }
function SlotPlan($plan, $reason) { [pscustomobject]@{ plan = [string]$plan; reason = [string]$reason } }
# Epoch seconds of a request's t (number = seconds, >= 1e11 = milliseconds; ISO 8601 string, naive = UTC), else $null.
function SlotRequestTime($t) {
  if (($null -eq $t) -or ($t -is [bool])) { return $null }
  if (SlotIsNum $t) {
    $n = [double]$t
    if ([double]::IsNaN($n) -or ($n -le 0)) { return $null }
    if ($n -ge 1e11) { return ($n / 1000.0) }
    return $n
  }
  if ($t -is [datetime]) {
    $u = $t; if ($u.Kind -eq [DateTimeKind]::Local) { $u = $u.ToUniversalTime() } else { $u = [datetime]::SpecifyKind($u, [DateTimeKind]::Utc) }
    return ($u - [datetime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)).TotalSeconds
  }
  if ($t -is [string]) {
    $str = $t.Trim()
    if ($str -notmatch '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}') { return $null }
    $dto = [DateTimeOffset]::MinValue
    if ([DateTimeOffset]::TryParse($str, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$dto)) { return ([double]$dto.ToUnixTimeMilliseconds() / 1000.0) }
  }
  return $null
}
# Validate a request.json that ConvertFrom-Json produced. $now = epoch seconds. Result: ok, action (load|unload|restore|mode), arg (mode name), reason.
# Nothing in the file is ever executed; anything outside the four actions, or older than 60 s, is refused.
function SlotRequestDecision($req, $now, $maxAge = 60) {
  if (($null -eq $req) -or ($req -isnot [pscustomobject])) { return (SlotReqResult $false $null $null 'not a JSON object') }
  $ap = $req.PSObject.Properties['action']
  if ((-not $ap) -or ($ap.Value -isnot [string])) { return (SlotReqResult $false $null $null 'no action') }
  $act = $ap.Value.Trim().ToLowerInvariant()
  if ($act -eq 'reload') { $act = 'restore' }                       # the GUI says reload, the governor says restore
  if (@('load', 'unload', 'restore', 'mode') -notcontains $act) { return (SlotReqResult $false $null $null 'action not allowed') }
  $tp = $req.PSObject.Properties['t']; $raw = $null; if ($tp) { $raw = $tp.Value }
  $tt = SlotRequestTime $raw
  if ($null -eq $tt) { return (SlotReqResult $false $null $null 'no usable timestamp') }
  $age = [double]$now - $tt
  if ($age -gt $maxAge) { return (SlotReqResult $false $null $null ('stale request ({0:F0} s old, limit {1} s)' -f $age, $maxAge)) }
  if ($age -lt -5) { return (SlotReqResult $false $null $null 'request dated in the future') }
  $arg = $null
  if ($act -eq 'mode') {
    $mp = $req.PSObject.Properties['mode']; $mv = $null
    if ($mp -and ($mp.Value -is [string])) { $mv = $mp.Value.Trim().ToUpperInvariant() }
    if (@('AUTO', 'MAX', 'BALANCED', 'LEAN', 'OFF') -notcontains $mv) { return (SlotReqResult $false $null $null 'mode not allowed') }
    $arg = $mv
  }
  return (SlotReqResult $true $act $arg 'ok')
}
# What to do with a valid request: plan = set-mode | prewarm | unload | unload-then-prewarm | postpone | noop. 'postpone' = a request is running ("never while busy").
function SlotRequestPlan($action, $loaded, $state, $processing, $curMode, $otherRunning = $false) {
  if ($action -eq 'mode') { return (SlotPlan 'set-mode' 'ok') }
  if (($state -eq 'swap-down') -or ($state -eq 'api-error')) { return (SlotPlan 'noop' 'llama-swap not answering') }
  if ($state -eq 'starting') { return (SlotPlan 'noop' 'model is already loading') }
  if ($action -eq 'load') {
    if ($loaded) { return (SlotPlan 'noop' 'already loaded') }
    if ($curMode -eq 'OFF') { return (SlotPlan 'noop' 'mode OFF') }
    if ($otherRunning) { return (SlotPlan 'noop' 'another model is running') }
    return (SlotPlan 'prewarm' 'load')
  }
  if ($action -eq 'restore') {
    if ($curMode -eq 'OFF') { return (SlotPlan 'noop' 'mode OFF') }
    if (-not $loaded) { if ($otherRunning) { return (SlotPlan 'noop' 'another model is running') }; return (SlotPlan 'prewarm' 'load with restore') }
    if ($processing) { return (SlotPlan 'postpone' 'a request is running') }
    return (SlotPlan 'unload-then-prewarm' 'save, unload, reload with restore')
  }
  if ($action -eq 'unload') {
    if (-not $loaded) { return (SlotPlan 'noop' 'not loaded') }
    if ($processing) { return (SlotPlan 'postpone' 'a request is running') }
    return (SlotPlan 'unload' 'unload')
  }
  return (SlotPlan 'noop' 'action not allowed')
}
# The `phase` string for status.json. Ages are seconds since the event or $null. NOTE: in PowerShell $null -lt 30 is TRUE, so every age is null-checked.
function SlotPhaseDecide($state, $loaded, $processing, $jobPhase = $null, $jobAge = $null, $unloadAge = $null, $postponedAge = $null, $prewarmAge = $null) {
  if ($loaded -and ($null -ne $postponedAge) -and ($postponedAge -lt 30)) { return 'postponed-busy' }
  if ((@('loading', 'restoring', 'warming') -contains $jobPhase) -and ($null -ne $jobAge) -and ($jobAge -lt 180)) { return $jobPhase }
  if ($state -eq 'starting') { return 'loading' }
  if ($state -eq 'stopping') { return 'unloading' }
  if (($null -ne $prewarmAge) -and ($prewarmAge -lt 30) -and (($null -eq $unloadAge) -or ($prewarmAge -le $unloadAge))) {
    if (($null -ne $unloadAge) -and ($unloadAge -lt 10)) { return 'loading' }          # unload then reload in one sample: $loaded is still the pre-unload value
    if ((-not $loaded) -and ($state -eq 'stopped')) { return 'loading' }
    if ($loaded -and $processing) { return 'warming' }
  }
  if ($loaded -and ($null -ne $unloadAge) -and ($unloadAge -lt 10)) { return 'unloading' }
  if ($loaded) { return 'ready' }
  return 'stopped'
}
# VRAM bands in GiB that sum to the heap total: model + kv (estimated) + desktop (dwm) + other + free.
function SlotVramBands($total, $used, $llama, $desktop, $nCtx = $null, $kvKib = $null) {
  $tot = [math]::Max(0.0, [double]$total); $usd = [math]::Max(0.0, [double]$used)
  $lla = [math]::Min([math]::Max(0.0, [double]$llama), $usd)
  $dsk = [math]::Min([math]::Max(0.0, [double]$desktop), ($usd - $lla))
  $oth = [math]::Max(0.0, ($usd - $lla - $dsk))
  $kv = 0.0
  if (($lla -gt 0) -and $nCtx -and $kvKib) { $kv = [math]::Min($lla, ([double]$nCtx * [double]$kvKib / 1048576.0)) }
  $mdl = $lla - $kv
  $free = [math]::Max(0.0, ($tot - $usd))
  $sum = $mdl + $kv + $dsk + $oth
  if (($tot -gt 0) -and ($sum -gt $tot)) { $f = $tot / $sum; $mdl *= $f; $kv *= $f; $dsk *= $f; $oth *= $f; $free = 0.0 }
  return [ordered]@{ total_gib = [math]::Round($tot, 2); model_gib = [math]::Round($mdl, 2); kv_gib = [math]::Round($kv, 2); desktop_gib = [math]::Round($dsk, 2); other_gib = [math]::Round($oth, 2); free_gib = [math]::Round($free, 2); kv_estimated = $true }
}
# Itemised cost of the next load: base (weights + drafter + compute buffers, from profiles.json base_gib) + KV at ctx. others = VRAM not ours (desktop included).
function SlotPreload($total, $others, $base, $kvKib, $ctx, $margin) {
  $kv = [double]$ctx * [double]$kvKib / 1048576.0
  $need = [double]$base + $kv
  $after = [double]$total - [double]$others - $need
  return [ordered]@{ base_gib = [math]::Round([double]$base, 2); kv_gib = [math]::Round($kv, 2); ctx = [int]$ctx; need_gib = [math]::Round($need, 2); others_gib = [math]::Round([double]$others, 2); free_after_gib = [math]::Round($after, 2); margin_gib = [math]::Round([double]$margin, 2); fits = ($after -ge ([double]$margin - 0.05)) }
}
# phase.json: the restore warm-up job (a separate process) reports its step here; the governor merges it into status.json.
function SlotSetPhase($p, $phase) {
  try {
    $f = [string]$p.phase_file; if (-not $f) { return }
    $o = [ordered]@{ phase = $phase; t = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); id = [string]$p.id }
    $tmp = $f + '.tmp'
    [IO.File]::WriteAllText($tmp, ($o | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $f -Force
  } catch {}
}
function SlotClearPhase($file) { try { if ($file -and (Test-Path -LiteralPath $file)) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue } } catch {} }
function SlotReadPhase($file) {
  try {
    if ($file -and (Test-Path -LiteralPath $file)) {
      $o = [IO.File]::ReadAllText($file) | ConvertFrom-Json
      if (($o.phase -is [string]) -and (SlotIsNum $o.t)) { return [pscustomobject]@{ phase = $o.phase; age = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$o.t) } }
    }
  } catch {}
  return [pscustomobject]@{ phase = $null; age = $null }
}

# ---------------- paths and config ----------------
function SlotDirSafe($d) {
  try {
    if (-not $d) { return $false }
    $full = [IO.Path]::GetFullPath([string]$d).TrimEnd([char[]]'\/')
    if ($full.Length -le 3) { return $false }                                        # a drive root
    if (@($full.Split([char[]]'\/') | ? { $_ }).Count -lt 3) { return $false }       # C:\AI is too shallow, C:\AI\cache\slots is fine
    return $true
  } catch { return $false }
}
# Full path of a leaf name inside $dir, or $null if it could land anywhere else.
function SlotSafePath($dir, $name) {
  try {
    if (-not $name -or ($name -ne [IO.Path]::GetFileName($name)) -or $name.StartsWith('.')) { return $null }
    $root = [IO.Path]::GetFullPath([string]$dir).TrimEnd([char[]]'\/')
    $full = [IO.Path]::GetFullPath((Join-Path $dir $name))
    if ($full -ne ($root + '\' + $name)) { return $null }
    return $full
  } catch { return $null }
}
function SlotDirReady($d) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } }
function SlotModelPath($cfg, $id) {
  foreach ($p in $cfg.variants.PSObject.Properties) { if ($p.Value.id -eq $id) { return [string]$p.Value.model } }
  return $null
}
# Returns a hashtable (dir, max_files, max_gib, min_tokens, headroom) or $null when slots are off / unsafe / not wired into the server args.
function SlotCfg($cfg) {
  try {
    $s = $cfg.slots
    if (-not $s -or ($s.enabled -ne $true)) { return $null }
    $d = [string]$s.dir
    if (-not (SlotDirSafe $d)) { SlotLogOnce 'dir' "slots disabled: unsafe slots.dir '$d'"; return $null }
    $ca = @($cfg.common_args); $i = [array]::IndexOf($ca, '--slot-save-path')
    if (($i -lt 0) -or (($i + 1) -ge $ca.Count) -or ((SlotNormPath $ca[$i + 1]).TrimEnd('/') -ne (SlotNormPath $d).TrimEnd('/'))) {
      SlotLogOnce 'args' 'slots disabled: common_args has no --slot-save-path equal to slots.dir (server could not save/restore)'; return $null }
    $mf = [int]$s.max_files; if ($mf -lt 1) { $mf = 3 }
    $mg = [double]$s.max_gib; if ($mg -le 0) { $mg = 12 }
    $mt = [int]$s.min_tokens; if ($mt -lt 1) { $mt = 4096 }
    $md = 10.0; try { if (SlotIsNum $s.min_free_disk_gib) { $md = [double]$s.min_free_disk_gib } } catch {}
    return @{ dir = $d; max_files = $mf; max_gib = $mg; min_tokens = $mt; headroom = 4096; min_free_disk_gib = $md }
  } catch { return $null }
}
# (size, mtime) of the model file as the sidecar records it: mtime is whole UTC epoch seconds. $null when unreadable.
function SlotModelStat($path) {
  try { $fi = Get-Item -LiteralPath $path -ErrorAction Stop
        return [pscustomobject]@{ size = [long]$fi.Length; mtime = [long][math]::Floor(($fi.LastWriteTimeUtc - [datetime]'1970-01-01').TotalSeconds) } } catch { return $null }
}
# First slot from GET /slots, or $null. PS 5.1 hands a JSON array back as ONE object, so take [0] from the variable, never from @(Invoke-RestMethod ...).
function SlotGetSlot($base) {
  try { $r = Invoke-RestMethod -Uri "${base}/slots" -TimeoutSec 5; return @($r)[0] } catch { return $null }
}
function SlotReadSidecar($dir, $id) {
  try { $f = SlotSafePath $dir ($id + '.json'); if ($f -and (Test-Path -LiteralPath $f)) { return (Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json) } } catch {}
  return $null
}

# ---------------- save (before a governor-initiated unload). Never throws; a failure only logs. ----------------
# Returns $true when the unload may go ahead, $false only when a request was running before or after the save (unloading would kill it).
# Free GiB on the drive that holds $dir, or $null.
function SlotDiskFreeGib($dir) { try { $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath([string]$dir)); return ((New-Object System.IO.DriveInfo $root).AvailableFreeSpace / 1GB) } catch { return $null } }
# $variant (optional): the profiles.json variant object of $id (ctk, ctv, kv_kib_per_token) - recorded in the sidecar and used for the disk-space estimate.
function SlotSave($s, $id, $port, $modelPath, $ctx, $variant = $null) {
  $tmp = $null
  try {
    $fn = SlotFilename $id
    if (-not $fn) { SlotLog 'SAVE skipped (bad variant id)'; return $true }
    SlotDirReady $s.dir
    $base = "http://127.0.0.1:${port}"
    $slot = SlotGetSlot $base
    $g = SlotUnloadGate $slot
    if (-not $g.ok) { SlotLog "SAVE skipped, unload postponed ($($g.reason))"; return $false }
    $d = SlotSaveDecision $slot $s.min_tokens
    if (-not $d.ok) { SlotLog "SAVE skipped ($($d.reason))"; return $true }
    $slotId = 0; if ($slot -and ($null -ne $slot.id)) { $slotId = [int]$slot.id }
    # never fill the disk: estimated file size = tokens * KV bytes/token (+ headroom), checked against the free space
    $kvKib = 64.5; $kvType = $null
    if ($variant) { try { if (SlotIsNum $variant.kv_kib_per_token) { $kvKib = [double]$variant.kv_kib_per_token }; if ($variant.ctk) { $kvType = "$($variant.ctk)/$($variant.ctv)" } } catch {} }
    $nEst = SlotTokenCount $slot; if ($null -eq $nEst) { $nEst = 65536 }
    $estGib = ($nEst * $kvKib / 1048576.0) * 1.1
    $freeDisk = SlotDiskFreeGib $s.dir
    $minFree = 10.0; try { if ($null -ne $s.min_free_disk_gib) { $minFree = [double]$s.min_free_disk_gib } } catch {}
    if (($null -ne $freeDisk) -and (($freeDisk - $estGib) -lt $minFree)) { SlotLog ('SAVE skipped (disk: {0:F1} GiB free, slot needs ~{1:F1} GiB, keep {2:F0} GiB free)' -f $freeDisk, $estGib, $minFree); return $true }
    if (-not $ctx) { try { $ctx = [int](Invoke-RestMethod -Uri "${base}/props" -TimeoutSec 5).default_generation_settings.n_ctx } catch {} }
    $tmpName = $id + '.tmp.bin'
    $tmp = SlotSafePath $s.dir $tmpName; $final = SlotSafePath $s.dir $fn; $side = SlotSafePath $s.dir ($id + '.json')
    if (-not $tmp -or -not $final -or -not $side) { SlotLog 'SAVE skipped (path outside slots dir)'; return $true }
    # Save under a temp name and rename on success: a timeout or crash mid-write can never leave a half file under the real name.
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-RestMethod -Method Post -Uri "${base}/slots/${slotId}?action=save" -Body (@{ filename = $tmpName } | ConvertTo-Json -Compress) -ContentType 'application/json' -TimeoutSec 30
    $ms = $sw.ElapsedMilliseconds
    $ok = SlotPostSaveOk $r.n_saved $s.min_tokens
    if (-not $ok.ok) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue; SlotLog "SAVE discarded ($($ok.reason))" }
    else {
      Remove-Item -LiteralPath $side -Force -ErrorAction SilentlyContinue          # sidecar present == file valid; drop the old one first
      Move-Item -LiteralPath $tmp -Destination $final -Force
      $st = SlotModelStat $modelPath
      $meta = [ordered]@{ n_tokens = [int]$r.n_saved; ctx = $ctx; saved_at = (Get-Date).ToString('s'); model_path = $modelPath; model_size = $(if ($st) { $st.size } else { $null }); model_mtime = $(if ($st) { $st.mtime } else { $null }); variant = $id; kv = $kvType }
      [IO.File]::WriteAllText($side, ($meta | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
      $gib = [math]::Round((Get-Item -LiteralPath $final).Length / 1GB, 2)
      SlotLog "SAVE $($meta.n_tokens) tokens, $gib GiB in $ms ms ($id)"
    }
    # a request may have arrived during the (multi-second) save: re-read the slot before letting the caller unload
    $g2 = SlotUnloadGate (SlotGetSlot $base)
    if (-not $g2.ok) { SlotLog "unload postponed: a request started during the slot save ($($g2.reason))"; return $false }
    return $true
  } catch {
    SlotLog "SAVE failed ($($_.Exception.Message)); unloading anyway"
    if ($tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    return $true
  }
}

# ---------------- pruning: only *.bin / *.json leaf names inside the slots dir, only governed variant ids ----------------
function SlotPrune($s, $managedIds) {
  try {
    if (-not (Test-Path -LiteralPath $s.dir)) { return }
    $epoch = [datetime]'1970-01-01'
    $ents = @(Get-ChildItem -LiteralPath $s.dir -File -ErrorAction Stop | ? { $_.Extension -in '.bin', '.json' } |
              % { [pscustomobject]@{ name = $_.Name; size = [double]$_.Length; mtime = ($_.LastWriteTimeUtc - $epoch).TotalSeconds } })
    $del = @(SlotPruneSelection $ents $s.max_files $s.max_gib $managedIds)
    $gone = @()
    foreach ($n in $del) { $f = SlotSafePath $s.dir $n; if ($f -and (Test-Path -LiteralPath $f)) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue; $gone += $n } }
    if ($gone.Count) { SlotLog "PRUNE removed $($gone -join ', ')" }
  } catch { SlotLog "prune failed: $($_.Exception.Message)" }
}
function SlotDropVariant($s, $id) {
  try { foreach ($n in @(($id + '.bin'), ($id + '.json'), ($id + '.tmp.bin'))) { $f = SlotSafePath $s.dir $n; if ($f -and (Test-Path -LiteralPath $f)) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue } }
        SlotLog "slot files for $id dropped" } catch { SlotLog "slot drop failed: $($_.Exception.Message)" }
}

# ---------------- restore (after a governor-initiated load) ----------------
# Cheap check on the governor thread: is a restore even possible? Returns the sidecar or $null (and logs why not).
function SlotRestorePlan($s, $id, $modelPath, $kvNow = $null) {
  if (-not $s) { return $null }
  $fn = SlotFilename $id; if (-not $fn) { return $null }
  $bin = SlotSafePath $s.dir $fn
  $exists = [bool]($bin -and (Test-Path -LiteralPath $bin))
  $sc = SlotReadSidecar $s.dir $id
  $d = SlotRestoreDecision $sc $exists $modelPath ([int]::MaxValue) (SlotModelStat $modelPath) $s.headroom $kvNow       # ctx is unknown until the new server is up
  if (-not $d.ok) { SlotLog "RESTORE skipped ($($d.reason))"; return $null }
  return $sc
}
# Runs in a background job (Start-Job) so the governor loop never blocks. Guaranteed order: load -> /health ok -> restore -> (1-token 'hi' only if no restore).
# $p: swap, key, id, port, model_path, dir, headroom, log
function SlotWarmFlow($p) {
  $script:SlotLogPath = $p.log
  $hdr = @{ Authorization = "Bearer $($p.key)" }
  $base = "http://127.0.0.1:$($p.port)"
  $deadline = (Get-Date).AddSeconds(120)
  $healthy = $false; $restored = $false; $skipHi = $false; $trigOk = $false
  SlotSetPhase $p 'loading'                       # phase.json -> status.json `phase` for the Control Centre (only when $p.phase_file is set)
  # 1) load the model WITHOUT running inference: llama-swap starts the upstream and proxies /health once it answers
  try { Invoke-WebRequest -Uri "$($p.swap)/upstream/$($p.id)/health" -Headers $hdr -UseBasicParsing -TimeoutSec 120 | Out-Null; $trigOk = $true }
  catch { SlotLog "RESTORE: load trigger failed ($($_.Exception.Message))" }
  # 2) wait for the server's own /health ok (up to 120 s from the start); if the trigger failed, one look only
  do {
    try { $h = Invoke-RestMethod -Uri "${base}/health" -TimeoutSec 3; if ($h.status -eq 'ok') { $healthy = $true; break } } catch {}
    if (-not $trigOk) { break }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  if (-not $healthy) { SlotLog 'RESTORE skipped (server not healthy within 120 s); sending the normal warm-up' }
  else {
    # 3) restore, unless a user request already got into the slot while the model was loading
    $ctx = $null; try { $ctx = [int](Invoke-RestMethod -Uri "${base}/props" -TimeoutSec 5).default_generation_settings.n_ctx } catch {}
    $slot = SlotGetSlot $base
    $gate = SlotRestoreTargetOk $slot
    if (-not $gate.ok) { SlotLog "RESTORE skipped ($($gate.reason))"; $skipHi = $true }       # slot is in use: no restore and no 'hi' either
    else {
      $fn = SlotFilename $p.id; $bin = SlotSafePath $p.dir $fn
      $sc = SlotReadSidecar $p.dir $p.id
      $kvNow = $null; try { $rj = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $p.log) 'running.json') -Raw | ConvertFrom-Json; if ($rj.ctk) { $kvNow = "$($rj.ctk)/$($rj.ctv)" } } catch {}
      $d = SlotRestoreDecision $sc ([bool]($bin -and (Test-Path -LiteralPath $bin))) $p.model_path $ctx (SlotModelStat $p.model_path) $p.headroom $kvNow
      if (-not $d.ok) { SlotLog "RESTORE skipped ($($d.reason))" }
      else {
        SlotSetPhase $p 'restoring'
        try {
          $sw = [Diagnostics.Stopwatch]::StartNew()
          $r = Invoke-RestMethod -Method Post -Uri "${base}/slots/0?action=restore" -Body (@{ filename = $fn } | ConvertTo-Json -Compress) -ContentType 'application/json' -TimeoutSec 60
          $n = [int]$sc.n_tokens; if ($r -and (SlotIsNum $r.n_restored)) { $n = [int]$r.n_restored }
          SlotLog "RESTORE $n tokens in $($sw.ElapsedMilliseconds) ms ($($p.id))"
          $restored = $true
        } catch { SlotLog "RESTORE failed ($($_.Exception.Message)); sending the normal warm-up" }
      }
    }
  }
  # 4) the 1-token prompt would overwrite the slot, so it is only for the no-restore case
  if (-not $restored -and -not $skipHi) {
    SlotSetPhase $p 'warming'
    try {
      $body = @{ model = $p.id; max_tokens = 1; messages = @(@{ role = 'user'; content = 'hi' }); chat_template_kwargs = @{ enable_thinking = $false } } | ConvertTo-Json -Depth 5 -Compress
      Invoke-RestMethod -Method Post -Uri "$($p.swap)/v1/chat/completions" -Headers $hdr -Body $body -ContentType 'application/json' -TimeoutSec 300 | Out-Null
    } catch { SlotLog "warm-up request failed ($($_.Exception.Message))" }
  }
  SlotSetPhase $p 'ready'
}

# ---------------- for qwen.ps1 ----------------
function SlotAgeText($min) {
  if ($min -lt 90) { return ('{0:F0} min' -f $min) }
  if ($min -lt 2880) { return ('{0:F1} h' -f ($min / 60)) }
  return ('{0:F1} d' -f ($min / 1440))
}
function SlotList($d) {
  $rows = @()
  if (-not (Test-Path -LiteralPath $d)) { return $rows }
  foreach ($f in @(Get-ChildItem -LiteralPath $d -File -Filter '*.bin' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
    $id = $f.Name.Substring(0, $f.Name.Length - 4)
    $sc = SlotReadSidecar $d $id
    $tok = $null; $ctx = $null; $at = $f.LastWriteTime
    if ($sc) {
      if (SlotIsNum $sc.n_tokens) { $tok = [int]$sc.n_tokens }
      if (SlotIsNum $sc.ctx) { $ctx = [int]$sc.ctx }
      try { $at = [datetime]$sc.saved_at } catch {}
    }
    $rows += [pscustomobject]@{ file = $f.Name; gib = [math]::Round($f.Length / 1GB, 2); tokens = $tok; ctx = $ctx; age_min = [math]::Max(0, ((Get-Date) - $at).TotalMinutes); sidecar = [bool]$sc }
  }
  return $rows
}
# Deletes every *.bin / *.json leaf in $d (nothing else, nothing outside). Returns the number of files removed.
function SlotClear($d) {
  $n = 0
  foreach ($f in @(Get-ChildItem -LiteralPath $d -File -ErrorAction SilentlyContinue | ? { $_.Extension -in '.bin', '.json' })) {
    $p = SlotSafePath $d $f.Name
    if ($p) { try { Remove-Item -LiteralPath $p -Force -ErrorAction Stop; $n++ } catch {} }
  }
  return $n
}
