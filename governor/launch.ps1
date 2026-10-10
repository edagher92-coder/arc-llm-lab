# Called by llama-swap to start llama-server with the governor's current profile.
# Context is sized at load time from the VRAM actually free right now, keeping the profile's
# "free VRAM" margin for Windows/apps, and never spilling into shared memory (measured limits).
# llama-swap stops it with "taskkill /f /t", which also kills the llama-server child.
param([string]$Variant = 'default')
$ErrorActionPreference = 'Stop'
$dir = 'C:\AI\governor'
$cfg = Get-Content "$dir\profiles.json" -Raw | ConvertFrom-Json
$v = $cfg.variants.$Variant; if (-not $v) { $Variant = 'default'; $v = $cfg.variants.default }
$name = 'BALANCED'
try { $d = (Get-Content "$dir\desired.txt" -ErrorAction Stop).Trim().ToUpper(); if ($cfg.profiles.PSObject.Properties.Name -contains $d) { $name = $d } } catch {}
$p = $cfg.profiles.$name

# Wait (max 15 s) for any previous llama-server to release VRAM, then measure what everything else uses.
for ($i = 0; $i -lt 15 -and (Get-Process llama-server -ErrorAction SilentlyContinue | ? { $_.Path -like 'C:\AI\*' }); $i++) { Start-Sleep 1 }
$others = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | measure CookedValue -Sum).Sum / 1GB
if (-not $others -or $others -le 0) { $others = 2.2 }

# Context sizing
$ctk = $v.ctk; $ctv = $v.ctv
$extra = @($v.extra_args)
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
  $targetGiB = $cfg.vram.total_gib - $p.free_margin_gib - $others
  $ctx = [int]([math]::Floor((($targetGiB - $v.base_gib) * 1MB) / $kvKiB / 4096) * 4096)   # GiB->KiB = *1MB
  $ctx = [math]::Max([int]$p.ctx_min, [math]::Min([int]$v.ctx_max, $ctx))
  # Session protection: never come back smaller than the largest live agent session (written by the governor).
  try { $need = [int](Get-Content "$dir\session-need.txt" -ErrorAction Stop) } catch { $need = 0 }
  if ($need -gt 0 -and $ctx -lt ($need + 8192)) {
    $want = [int]([math]::Ceiling(($need + 8192) / 4096) * 4096)
    $emerg = [int]([math]::Floor(((($cfg.vram.total_gib - 1.15 - $others) - $v.base_gib) * 1MB) / $kvKiB / 4096) * 4096)   # 1.15 GiB = emergency floor, just above the 0.96 GiB free that slowed one run (threshold not isolated, see docs/TUNING-LOG.md)
    $new = [math]::Min([math]::Min($want, $emerg), [int]$v.ctx_max)
    if ($new -gt $ctx) { $draftNote = "session-protect: raised ctx $ctx -> $new for live session of $need tokens"; $ctx = $new }
    if ($ctx -lt ($need + 4096)) { $draftNote += " WARNING: cannot fit live session ($need tokens) - client will get an explicit context error, never silent truncation" }
  }
}

$prio = @{ Normal = '0'; BelowNormal = '-1' }[$p.priority]; if (-not $prio) { $prio = '-1' }
$args2 = @('-m', $v.model, '--mmproj', $cfg.mmproj, '-a', $v.id, '--host', '127.0.0.1', '--port', "$($v.port)",
           '-c', "$ctx", '-ctk', $ctk, '-ctv', $ctv,
           '-t', "$($p.threads)", '-tb', "$($p.threads)", '-cram', "$($p.cache_ram_mib)", '--prio', $prio) + @($cfg.common_args) + $extra
foreach ($e in $cfg.env.PSObject.Properties) { Set-Item -Path "env:$($e.Name)" -Value $e.Value }

@{ profile = $name; variant = $Variant; id = $v.id; port = $v.port; ctx = $ctx; ctk = $ctk; ctv = $ctv; others_gib = [math]::Round($others, 2); started = (Get-Date).ToString('s'); launcher_pid = $PID } | ConvertTo-Json | Set-Content "$dir\running.json"
"$(Get-Date -f s) launch: $($v.id) profile=$name ctx=$ctx kv=$ctk/$ctv others=$([math]::Round($others,2))GiB port=$($v.port) $draftNote" | Add-Content "$dir\governor.log"
& $cfg.exe @args2
exit $LASTEXITCODE
