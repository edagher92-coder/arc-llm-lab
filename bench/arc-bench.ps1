<#
.SYNOPSIS
  Measure your Intel Arc GPU with llama-bench (Windows) and write a community result file.
.DESCRIPTION
  Runs: llama-bench -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d 0,16384,32768 -r 1 -o json
  (the flags of bench\compare-f16.ps1; GGML_VK_FORCE_MMVQ=1 is added with -Mmvq).
  Writes <OutDir>\<date>-<gpu>-<backend>-<build>.json following data\community\schema.json, prints a markdown row and
  tells you how to submit it: https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File bench\arc-bench.ps1 -Model C:\AI\models\Qwen3.8-27B-UD-Q4_K_M.gguf -VramGb 24 -Contributor "Your Name" -Mmvq
#>
param(
  [string]$Model = '',
  [string]$Bench = '',
  [string]$Depths = '0,16384,32768',
  [string]$OutDir = '.\arc-bench-results',
  [double]$VramGb = 0,
  [string]$Gpu = '',
  [string]$Contributor = 'anonymous',   # the name or handle credited in the results table; your Windows user name is never used unless you pass it
  [string]$Driver = '',
  [string]$OsName = '',
  [string[]]$Patches = @(),
  [string]$Notes = '',
  [string]$RawLogUrl = '',
  [switch]$Mmvq,
  [string]$FromJson = ''
)
$ErrorActionPreference = 'Stop'
# Under 'Stop', Write-Error throws before any 'exit' runs, so report fatal problems this way instead.
function Fail([string]$Message, [int]$Code = 1) { Write-Host $Message -ForegroundColor Red; exit $Code }
$Patches = @($Patches | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($VramGb -le 0) { Fail '-VramGb is required (for example -VramGb 24)' 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ($FromJson) { $raw = $FromJson; $flags = '(converted from an existing llama-bench -o json file)' }
else {
  if (-not $Model -or -not (Test-Path $Model)) { Fail "model file not found: '$Model' (use -Model PATH)" 2 }
  if (-not $Bench) {
    $c = Get-Command llama-bench -ErrorAction SilentlyContinue
    if ($c) { $Bench = $c.Source } elseif (Test-Path 'C:\AI\llama.cpp\vulkan-intelfa\llama-bench.exe') { $Bench = 'C:\AI\llama.cpp\vulkan-intelfa\llama-bench.exe' }
  }
  if (-not $Bench -or -not (Test-Path $Bench)) { Fail 'llama-bench not found (use -Bench PATH)' 2 }
  $flags = "llama-bench -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d $Depths -r 1"
  if ($Mmvq) { $env:GGML_VK_FORCE_MMVQ = '1'; $flags = "GGML_VK_FORCE_MMVQ=1 $flags" }
  $raw = Join-Path $OutDir "llama-bench-$stamp.json"; $err = "$raw.stderr"
  Write-Host "Running: $flags   (about 5-15 minutes for a 27B model)"
  # Start-Process, not '& $Bench ... 2> $err': under Windows PowerShell 5.1 with $ErrorActionPreference = 'Stop', redirected native stderr
  # (llama-bench logs to it) becomes a terminating NativeCommandError.
  $benchArgs = @('-m', "`"$Model`"", '-ngl', '99', '-fa', '1', '-ctk', 'f16', '-ctv', 'f16', '-p', '2048', '-n', '32', '-d', "`"$Depths`"", '-r', '1', '-o', 'json')
  $proc = Start-Process -FilePath $Bench -ArgumentList $benchArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput $raw -RedirectStandardError $err
  if ($proc.ExitCode -ne 0) { Fail "llama-bench failed (exit code $($proc.ExitCode)); see $err" 1 }
}

# Windows PowerShell 5.1 emits a JSON array as ONE pipeline object; unroll it so each row is a result.
$rows = @(Get-Content $raw -Raw | ConvertFrom-Json | ForEach-Object { $_ })
if ($rows.Count -eq 0) { Fail 'llama-bench output contained no results' 1 }
$first = $rows[0]
$backend = ("$($first.backends)").Trim(); if (-not $backend) { $backend = 'unknown' }
if ($backend -match '^(CPU|BLAS|CPU,BLAS)$') { Fail "llama-bench ran on the CPU only (backends: $backend). Check that your build has Vulkan or SYCL and that the GPU is visible." 1 }
$gpuBackends = @($backend -split ',' | Where-Object { $_ -notmatch '^(CPU|BLAS|RPC)$' }); if ($gpuBackends.Count -gt 0) { $backend = $gpuBackends -join ',' }

$depth = @{}
foreach ($r in $rows) {
  $d = [string][int]$r.n_depth; $np = [int]$r.n_prompt; $ng = [int]$r.n_gen
  if (-not $depth.ContainsKey($d)) { $depth[$d] = @{} }
  $cell = $depth[$d]
  $sd = 0.0; if ($null -ne $r.stddev_ts) { $sd = [double]$r.stddev_ts }
  if ($np -gt 0 -and $ng -eq 0 -and $np -ge [int]$cell['pp_tokens']) { $cell['pp_tok_s'] = [math]::Round([double]$r.avg_ts, 2); $cell['pp_tokens'] = $np; $cell['pp_stddev'] = [math]::Round($sd, 2) }
  elseif ($ng -gt 0 -and $np -eq 0 -and $ng -ge [int]$cell['tg_tokens']) { $cell['tg_tok_s'] = [math]::Round([double]$r.avg_ts, 2); $cell['tg_tokens'] = $ng; $cell['tg_stddev'] = [math]::Round($sd, 2) }
}
$ds = @($depth.Keys | Where-Object { $depth[$_].ContainsKey('pp_tok_s') -and $depth[$_].ContainsKey('tg_tok_s') } | Sort-Object { [int]$_ })
if ($ds.Count -eq 0) { Fail 'no complete pp/tg pairs found in the llama-bench output' 1 }
$dr = [ordered]@{}
foreach ($d in $ds) { $c = $depth[$d]; $dr[$d] = [ordered]@{ pp_tok_s = $c['pp_tok_s']; pp_tokens = $c['pp_tokens']; pp_stddev = $c['pp_stddev']; tg_tok_s = $c['tg_tok_s']; tg_tokens = $c['tg_tokens']; tg_stddev = $c['tg_stddev'] } }

$fname = [IO.Path]::GetFileName(("$($first.model_filename)" -replace '\\', '/')); if (-not $fname) { $fname = "$($first.model_type)" }
$quant = 'unknown'; $qm = [regex]::Match($fname, '(?<![A-Za-z])((?:UD-)?(?:IQ\d(?:_[A-Z0-9]+)*|Q\d(?:_[A-Z0-9]+)*|MXFP4|BF16|F16|F32))', 'IgnoreCase'); if ($qm.Success) { $quant = $qm.Groups[1].Value }
if (-not $Gpu) { $Gpu = ("$($first.gpu_info)").Trim(); if (-not $Gpu) { $Gpu = 'unknown GPU' } }
$build = "b$($first.build_number) ($($first.build_commit))"

if (-not $OsName) { try { $o = Get-CimInstance Win32_OperatingSystem; $OsName = "$($o.Caption.Trim()) (build $($o.Version))" } catch { $OsName = [Environment]::OSVersion.VersionString } }
if (-not $Driver) {
  try { $v = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'Intel' -and $_.Name -match 'Arc' } | Select-Object -First 1; if ($v) { $Driver = $v.DriverVersion } } catch {}
  if (-not $Driver) { $Driver = 'unknown (please edit this field)' }
}
$cpu = ''; $ram = 0
try { $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name.Trim(); $ram = [int][math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) } catch {}

$res = [ordered]@{
  schema_version = 1; contributor = $Contributor; date = (Get-Date -Format 'yyyy-MM-dd'); gpu = $Gpu; vram_gb = $VramGb
  driver = $Driver; os = $OsName; backend = $backend; llama_cpp_build = $build; patches = $Patches
  model = $fname; quant = $quant; kv_cache = [ordered]@{ k = "$($first.type_k)"; v = "$($first.type_v)" }
  flash_attn = ("$($first.flash_attn)" -notmatch '^(0|false|off|disabled|no)$'); flags = $flags; depth_results = $dr; repeats = 1
}
if ($cpu) { $res['cpu'] = $cpu }
if ($ram -gt 0) { $res['ram_gb'] = $ram }
if ($RawLogUrl) { $res['raw_log_url'] = $RawLogUrl }
if ($Notes) { $res['notes'] = $Notes }
if ("$($first.type_k)" -eq '') { $res['kv_cache'] = [ordered]@{ k = 'f16'; v = 'f16' } }

$slug = { param($s) (($s.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')); }
$trim = { param($s) $t = & $slug $s; if ($t.Length -gt 48) { $t.Substring(0, 48) } else { $t } }
$path = Join-Path $OutDir ("{0}-{1}-{2}-{3}.json" -f $res.date, (& $trim $Gpu), (& $trim $backend), (& $trim $build))
[IO.File]::WriteAllText($path, (($res | ConvertTo-Json -Depth 8) + "`n"), $utf8)

Write-Host ''; Write-Host "Wrote $path"; Write-Host ''
$f = { param($k) ($ds | ForEach-Object { '{0:N1}' -f $depth[$_][$k] }) -join ' / ' }
$ppn = $depth[$ds[0]]['pp_tokens']; $tgn = $depth[$ds[0]]['tg_tokens']
Write-Host ("| GPU | VRAM | Backend / build | Model | pp{0} at depth {1} (tok/s) | tg{2} at depth {1} (tok/s) | By |" -f $ppn, ($ds -join '/'), $tgn)
Write-Host '|---|---|---|---|---|---|---|'
$pp = ''; if ($res.patches.Count -gt 0) { $pp = " + $($res.patches.Count) patch(es)" }
Write-Host ("| {0} | {1} GB | {2} {3}{4} | {5} {6} | {7} | {8} | {9} |" -f $Gpu, $VramGb, $backend, $build, $pp, $fname, $quant, (& $f 'pp_tok_s'), (& $f 'tg_tok_s'), $Contributor)
Write-Host ''
Write-Host 'Share it: open https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml and paste the JSON file,'
Write-Host 'or add it to data\community\ in a pull request. Please also attach the raw llama-bench output.'
