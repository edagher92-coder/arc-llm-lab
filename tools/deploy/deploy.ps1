<#
.SYNOPSIS
  One-command deploy with automatic rollback for the local gateway (PowerShell 5.1, Windows 11).

.DESCRIPTION
  deploy.ps1 -Zip <bundle.zip> -Sha256 <hex> [-DryRun] [-ApplyDeletes]

  Bundle comes from tools/deploy/make_bundle.sh (zip entries are repo paths gateway/<x> plus MANIFEST.json).
  Flow: verify hash -> read manifest -> busy guard -> backup + restore.ps1 -> install ->
  restart hub (detached) -> poll ports 8100/8093 and Studio 200 for up to 120 s ->
  on failure restore + restart and exit 1. One JSON line per run goes to C:\AI\gateway\deploy.log.

  Exit codes: 0 ok (or dry run), 1 deploy failed (rolled back), 2 aborted (busy), 3 bad input/bundle.

  Never touched: gateway.json, anything under state/, secrets, .env files, backups, deploy.log.
  -ApplyDeletes also removes files listed under "deleted" in the manifest (backed up first).
  -RestartHubOnly / -ResultFile are internal (used for the detached restart helper).
#>
param(
  [string]$Zip,
  [string]$Sha256,
  [switch]$DryRun,
  [switch]$ApplyDeletes,
  [switch]$RestartHubOnly,
  [string]$ResultFile
)

$ErrorActionPreference = 'Stop'

# ---- configuration -------------------------------------------------------------------------------
$GatewayRoot = 'C:\AI\gateway'
$ComfyNodes  = 'C:\AI\comfy\ComfyUI_windows_portable\ComfyUI\custom_nodes\elz_nodes'
$NodePrefix  = 'comfy_nodes/elz_nodes/'
$JobsFile    = 'C:\AI\gateway\state\video\jobs.json'
$BackupRoot  = 'C:\AI\gateway\backups'
$LogFile     = 'C:\AI\gateway\deploy.log'
$StageRoot   = 'C:\AI\deploy\stage'
$TaskName    = 'Local MCP hub (mcpo)'
$StudioUrl   = 'http://127.0.0.1:8093/approvals/studio'
$HubPorts    = @(8100, 8093)
$ComfyPort   = 8188
$ActiveStates = @('queued', 'waiting', 'starting', 'running')
$SelfPath    = $MyInvocation.MyCommand.Path
$HealthSeconds = 120

# ---- helpers -------------------------------------------------------------------------------------
function Get-Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }

function Get-ListenPorts([int[]]$Ports) {
  @(Get-NetTCPConnection -State Listen -LocalPort $Ports -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty LocalPort -Unique)
}

function Get-StudioCode {
  try { return [int](Invoke-WebRequest -Uri $StudioUrl -UseBasicParsing -TimeoutSec 8).StatusCode }
  catch {
    try { return [int]$_.Exception.Response.StatusCode } catch { return 0 }
  }
}

function Get-BusyReason {
  $reasons = @()
  if (Test-Path -LiteralPath $JobsFile) {
    $raw = Get-Content -LiteralPath $JobsFile -Raw
    if ($raw -and $raw.Trim()) {
      $all = @($raw | ConvertFrom-Json)
      $active = @($all | Where-Object { $ActiveStates -contains $_.state })
      if ($active.Count -gt 0) { $reasons += ('video jobs active: ' + (($active | ForEach-Object { $_.id + '=' + $_.state }) -join ', ')) }
    }
  }
  if ((Get-ListenPorts @($ComfyPort)).Count -gt 0) { $reasons += "something is listening on 127.0.0.1:$ComfyPort (ComfyUI)" }
  return $reasons
}

function Write-DeployLog($Entry) {
  $line = ($Entry | ConvertTo-Json -Compress -Depth 5)
  [System.IO.File]::AppendAllText($LogFile, $line + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
}

function Write-TextNoBom([string]$Path, [string]$Text) {
  [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# Restart the hub task and poll until both ports + Studio 200, or timeout. Returns a result object.
function Invoke-HubRestart {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $owners = @(Get-NetTCPConnection -State Listen -LocalPort $HubPorts -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  foreach ($o in $owners) { if ($o -gt 4) { & taskkill /PID $o /T /F 2>&1 | Out-Null } }
  Start-Sleep -Seconds 3
  Start-ScheduledTask -TaskName $TaskName
  $deadline = (Get-Date).AddSeconds($HealthSeconds)
  $ports = @(); $code = 0
  while ((Get-Date) -lt $deadline) {
    $ports = Get-ListenPorts $HubPorts
    if ($ports.Count -ge 2) {
      $code = Get-StudioCode
      if ($code -eq 200) { break }
    }
    Start-Sleep -Seconds 3
  }
  $ok = ($ports.Count -ge 2 -and $code -eq 200)
  return [ordered]@{ ok = $ok; ports = ($ports -join ','); studio = $code; seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

# ---- internal mode: detached restart helper ------------------------------------------------------
if ($RestartHubOnly) {
  $res = Invoke-HubRestart
  $json = $res | ConvertTo-Json -Compress
  if ($ResultFile) { Write-TextNoBom $ResultFile $json } else { $json }
  if ($res.ok) { exit 0 } else { exit 1 }
}

# Start the restart helper fully detached from this process tree (WMI Create), so killing the hub's
# process tree cannot take the helper (or this script) with it. Waits for the helper's result file.
function Restart-HubDetached {
  $rf = Join-Path $StageRoot ('restart-' + [guid]::NewGuid().ToString('N') + '.json')
  $cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $SelfPath + '" -RestartHubOnly -ResultFile "' + $rf + '"'
  $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
  if ($r.ReturnValue -ne 0) { return [ordered]@{ ok = $false; ports = ''; studio = 0; seconds = 0; error = ('detached start failed, code ' + $r.ReturnValue) } }
  $limit = (Get-Date).AddSeconds($HealthSeconds + 45)
  while ((Get-Date) -lt $limit -and -not (Test-Path -LiteralPath $rf)) { Start-Sleep -Seconds 2 }
  if (-not (Test-Path -LiteralPath $rf)) { return [ordered]@{ ok = $false; ports = ''; studio = 0; seconds = 0; error = 'restart helper produced no result' } }
  Start-Sleep -Milliseconds 300
  $out = Get-Content -LiteralPath $rf -Raw | ConvertFrom-Json
  Remove-Item -LiteralPath $rf -Force -ErrorAction SilentlyContinue
  return [ordered]@{ ok = [bool]$out.ok; ports = [string]$out.ports; studio = [int]$out.studio; seconds = [double]$out.seconds }
}

# restore.ps1 written into every backup folder. Reads restore.json beside it.
$RestoreScript = @'
# Restores the files saved by deploy.ps1 in this folder. Usage: restore.ps1 [-Restart]
param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$plan = Get-Content -LiteralPath (Join-Path $here 'restore.json') -Raw | ConvertFrom-Json
foreach ($e in @($plan.entries)) {
  if ($e.backup) {
    $src = Join-Path $here $e.backup
    $dir = Split-Path -Parent $e.live
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    Copy-Item -LiteralPath $src -Destination $e.live -Force
    'restored ' + $e.live
  } else {
    if (Test-Path -LiteralPath $e.live) { Remove-Item -LiteralPath $e.live -Force; 'removed (was new) ' + $e.live } else { 'already absent ' + $e.live }
  }
}
if ($Restart) {
  $rf = Join-Path $env:TEMP ('hub-restart-' + [guid]::NewGuid().ToString('N') + '.json')
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\AI\deploy\deploy.ps1' -RestartHubOnly -ResultFile $rf
  if (Test-Path -LiteralPath $rf) { 'hub restart result: ' + (Get-Content -LiteralPath $rf -Raw) }
}
'restore complete'
'@

# ---- main ----------------------------------------------------------------------------------------
$total = [Diagnostics.Stopwatch]::StartNew()
$startedAt = (Get-Date).ToString('s')
$toShort = ''
$zipSha = ''
$fileCount = 0
$stage = $null

function Finish([bool]$Ok, [int]$Code, [hashtable]$Extra) {
  $entry = [ordered]@{
    time = $startedAt; to = $toShort; zip_sha256 = $zipSha; files = $fileCount
    ok = $Ok; seconds = [math]::Round($total.Elapsed.TotalSeconds, 1)
  }
  foreach ($k in $Extra.Keys) { $entry[$k] = $Extra[$k] }
  if (-not $DryRun) { Write-DeployLog $entry }
  if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
  exit $Code
}

try {
  if (-not $Zip -or -not $Sha256) { 'usage: deploy.ps1 -Zip <bundle.zip> -Sha256 <hex> [-DryRun] [-ApplyDeletes]'; exit 3 }
  if (-not (Test-Path -LiteralPath $Zip)) { "ABORT: zip not found: $Zip"; exit 3 }
  New-Item -ItemType Directory -Force $StageRoot | Out-Null
  New-Item -ItemType Directory -Force $BackupRoot | Out-Null

  # 1. verify hash
  $zipSha = Get-Sha $Zip
  if ($zipSha -ne $Sha256.Trim().ToLower()) { "ABORT: SHA256 mismatch. expected $($Sha256.Trim().ToLower()) got $zipSha"; Finish $false 3 @{ aborted = 'hash mismatch' } }
  'sha256 ok: ' + $zipSha

  # 2. extract (zip-slip safe) and read manifest
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $stage = Join-Path $StageRoot ('s-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force $stage | Out-Null
  $stageFull = [IO.Path]::GetFullPath($stage).TrimEnd('\') + '\'
  $za = [IO.Compression.ZipFile]::OpenRead($Zip)
  try {
    foreach ($en in $za.Entries) {
      if ($en.FullName.EndsWith('/')) { continue }
      $dest = [IO.Path]::GetFullPath((Join-Path $stage ($en.FullName -replace '/', '\')))
      if (-not $dest.StartsWith($stageFull, [StringComparison]::OrdinalIgnoreCase)) { throw "unsafe zip entry: $($en.FullName)" }
      New-Item -ItemType Directory -Force (Split-Path -Parent $dest) | Out-Null
      [IO.Compression.ZipFileExtensions]::ExtractToFile($en, $dest, $true)
    }
  } finally { $za.Dispose() }

  $mPath = Join-Path $stage 'MANIFEST.json'
  if (-not (Test-Path -LiteralPath $mPath)) { 'ABORT: MANIFEST.json missing from zip'; Finish $false 3 @{ aborted = 'no manifest' } }
  $m = Get-Content -LiteralPath $mPath -Raw | ConvertFrom-Json
  $toShort = ([string]$m.to).Substring(0, [Math]::Min(7, ([string]$m.to).Length))
  $mFiles = @($m.files)
  $mDeleted = @($m.deleted | Where-Object { $_ })
  $fileCount = $mFiles.Count

  # 3. build and validate plan
  $blocked = '(^|/)gateway\.json$|(^|/)\.env($|\.)|^gateway/state/|^gateway/backups/|^gateway/secrets/|(^|/)secrets?/|^gateway/deploy\.log$'
  $plan = @()
  foreach ($f in $mFiles) {
    $p = [string]$f.path
    if (-not $p.StartsWith('gateway/') -or $p.Contains('..') -or $p.Contains('\') -or $p -match $blocked) { throw "refusing protected or invalid path in manifest: $p" }
    $rel = $p.Substring(8)
    $src = Join-Path $stage ($p -replace '/', '\')
    if (-not (Test-Path -LiteralPath $src)) { throw "manifest file missing from zip: $p" }
    if ((Get-Sha $src) -ne ([string]$f.sha256).ToLower()) { throw "content hash differs from manifest: $p" }
    $targets = @([ordered]@{ kind = 'gateway'; rel = $rel; live = (Join-Path $GatewayRoot ($rel -replace '/', '\')) })
    if ($rel.StartsWith($NodePrefix)) {
      $nrel = $rel.Substring($NodePrefix.Length)
      $targets += [ordered]@{ kind = 'comfy'; rel = $nrel; live = (Join-Path $ComfyNodes ($nrel -replace '/', '\')) }
    }
    foreach ($t in $targets) {
      $exists = Test-Path -LiteralPath $t.live
      $status = 'NEW'
      if ($exists) { if ((Get-Sha $t.live) -eq (Get-Sha $src)) { $status = 'SAME' } else { $status = 'CHANGE' } }
      $plan += [ordered]@{ src = $src; kind = $t.kind; rel = $t.rel; live = $t.live; status = $status; exists = $exists }
    }
  }
  $delPlan = @()
  foreach ($d in $mDeleted) {
    $d = [string]$d
    if (-not $d.StartsWith('gateway/') -or $d.Contains('..') -or $d -match $blocked) { throw "refusing protected or invalid deleted path: $d" }
    $rel = $d.Substring(8)
    $delPlan += [ordered]@{ kind = 'gateway'; rel = $rel; live = (Join-Path $GatewayRoot ($rel -replace '/', '\')) }
    if ($rel.StartsWith($NodePrefix)) {
      $nrel = $rel.Substring($NodePrefix.Length)
      $delPlan += [ordered]@{ kind = 'comfy'; rel = $nrel; live = (Join-Path $ComfyNodes ($nrel -replace '/', '\')) }
    }
  }

  # 4. busy guard
  $busy = @(Get-BusyReason)

  $ts = (Get-Date).ToString('yyyyMMdd-HHmmss')
  $backupDir = Join-Path $BackupRoot ($ts + '-' + $toShort)

  '=== deploy plan ==='
  'bundle    : ' + $Zip
  'range     : ' + ([string]$m.from).Substring(0, 7) + ' -> ' + $toShort
  'files     : ' + $mFiles.Count + ' in manifest, ' + $plan.Count + ' install targets, ' + $mDeleted.Count + ' deleted in manifest'
  foreach ($p in $plan) { '  {0,-6} {1,-7} {2}' -f $p.status, $p.kind, $p.live }
  foreach ($d in $delPlan) { '  {0,-6} {1,-7} {2}' -f 'DELETE', $d.kind, ($d.live + $(if ($ApplyDeletes) { '' } else { '  (skipped: no -ApplyDeletes)' })) }
  'backup to : ' + $backupDir + '  (+ restore.ps1)'
  'restart   : scheduled task "' + $TaskName + '" (stop, taskkill /T owners of 8100+8093, start); health poll up to ' + $HealthSeconds + ' s'
  'smoke     : ports 8100+8093 listening and GET ' + $StudioUrl + ' == 200'
  'never     : gateway.json, secrets, state/, .env, backups/'
  if ($busy.Count -gt 0) { 'BUSY     : ' + ($busy -join '; ') } else { 'busy guard: clear (no active video jobs, nothing on :8188)' }

  if ($DryRun) { '=== DRY RUN: nothing changed, hub not restarted ==='; Finish $true 0 @{ dry_run = $true } }

  if ($busy.Count -gt 0) { 'ABORT: video busy. Nothing changed.'; Finish $false 2 @{ aborted = 'busy'; detail = ($busy -join '; ') } }

  # 5. backup + restore.ps1
  New-Item -ItemType Directory -Force $backupDir | Out-Null
  $entries = @()
  $all = @($plan | ForEach-Object { $_ }) + @($(if ($ApplyDeletes) { $delPlan | ForEach-Object { [ordered]@{ kind = $_.kind; rel = $_.rel; live = $_.live; exists = (Test-Path -LiteralPath $_.live); src = $null; status = 'DELETE' } } }))
  foreach ($a in $all) {
    $b = $null
    if ($a.exists) {
      $b = $a.kind + '\' + ($a.rel -replace '/', '\')
      $bp = Join-Path $backupDir $b
      New-Item -ItemType Directory -Force (Split-Path -Parent $bp) | Out-Null
      Copy-Item -LiteralPath $a.live -Destination $bp -Force
    }
    $entries += [ordered]@{ live = $a.live; backup = $b }
  }
  Write-TextNoBom (Join-Path $backupDir 'restore.json') (([ordered]@{ to = [string]$m.to; entries = @($entries) }) | ConvertTo-Json -Depth 5)
  Write-TextNoBom (Join-Path $backupDir 'restore.ps1') $RestoreScript
  'backup written: ' + $backupDir

  $rolledBack = $false
  $restoreFiles = {
    param($why)
    '!! ' + $why + ' -> restoring from ' + $backupDir
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $backupDir 'restore.ps1')
  }

  # 6. install
  try {
    foreach ($p in $plan) {
      New-Item -ItemType Directory -Force (Split-Path -Parent $p.live) | Out-Null
      Copy-Item -LiteralPath $p.src -Destination $p.live -Force
      if ((Get-Sha $p.live) -ne (Get-Sha $p.src)) { throw "post-copy hash mismatch: $($p.live)" }
    }
    if ($ApplyDeletes) { foreach ($d in $delPlan) { if (Test-Path -LiteralPath $d.live) { Remove-Item -LiteralPath $d.live -Force } } }
    'installed ' + $plan.Count + ' file(s)'
  } catch {
    $err = $_.Exception.Message
    & $restoreFiles ('install failed: ' + $err)
    Finish $false 1 @{ rolled_back = $true; error = $err; backup = $backupDir; restarted = $false }
  }

  # 7. restart + health
  'restarting hub (detached), polling up to ' + $HealthSeconds + ' s ...'
  $res = Restart-HubDetached
  'result: ok=' + $res.ok + ' ports=' + $res.ports + ' studio=' + $res.studio + ' (' + $res.seconds + ' s)'
  if ($res.ok) {
    'DEPLOY OK (' + [math]::Round($total.Elapsed.TotalSeconds, 1) + ' s). Backup: ' + $backupDir
    Finish $true 0 @{ backup = $backupDir; ports = $res.ports; studio = $res.studio }
  }

  # 8. automatic rollback
  & $restoreFiles 'health check failed'
  'restarting hub on restored files ...'
  $res2 = Restart-HubDetached
  'rollback restart: ok=' + $res2.ok + ' ports=' + $res2.ports + ' studio=' + $res2.studio
  'DEPLOY FAILED, ROLLED BACK. Backup: ' + $backupDir
  Finish $false 1 @{ rolled_back = $true; rollback_healthy = $res2.ok; backup = $backupDir; error = ('health: ports=' + $res.ports + ' studio=' + $res.studio) }
} catch {
  'ERROR: ' + $_.Exception.Message
  Finish $false 3 @{ error = $_.Exception.Message }
}
