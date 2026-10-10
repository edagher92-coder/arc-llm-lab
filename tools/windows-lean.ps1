# windows-lean.ps1 - make a Windows 11 PC lighter as a local-LLM server without breaking daily work.
# DRY RUN by default: it only prints what it would change. Review, then run it yourself from an elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File windows-lean.ps1                 # dry run (prints the plan)
#   powershell -ExecutionPolicy Bypass -File windows-lean.ps1 -Apply          # apply the default-safe set
#   ... -Apply -Intel          also set the Intel Graphics Software + PROSet monitoring services to on-demand
#   ... -Apply -BrowserAccel   also switch Chrome/Edge hardware acceleration off by user policy (see note below)
#   ... -Apply -Apps           also remove the listed Store apps (current user)
#   powershell -ExecutionPolicy Bypass -File windows-lean.ps1 -Undo           # restore everything it changed
# Every change is recorded in C:\AI\cache\windows-lean-undo.json before it is made (re-running keeps the FIRST recorded value).
# Nothing is deleted except Store apps with -Apps (reinstall them from the Microsoft Store). It never touches Defender, firewall,
# updates, drivers, Tailscale, SSH or printing.
# Measured on the test PC (2026-10-11): the Intel services use 3-15 MB each and no VRAM; the big VRAM user is dwm.exe (2.5 GB with two
# 3440x1440 monitors), which only a lower resolution fixes (see docs/DISPLAY-POLICY.md). Chrome/Edge held <50 MB of VRAM, so
# -BrowserAccel is a small win and slower page rendering; it is off by default.
param([switch]$Apply, [switch]$Apps, [switch]$Undo, [switch]$Intel, [switch]$BrowserAccel)   # data lives in $undoData; $undo would clash with -Undo (PowerShell names are case-insensitive)
$ErrorActionPreference = 'Continue'
$undoFile = 'C:\AI\cache\windows-lean-undo.json'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (($Apply -or $Undo) -and -not $isAdmin) { Write-Host 'Run this from an elevated PowerShell (Run as administrator).'; exit 1 }

# Services: background work an LLM server does not need. Set to Manual (starts on demand) or Disabled (telemetry only).
$services = [ordered]@{
  'SysMain'           = 'Manual'    # SuperFetch: preloads apps into RAM; fights the model file and page cache for memory
  'DiagTrack'         = 'Disabled'  # Connected User Experiences and Telemetry
  'DoSvc'             = 'Manual'    # Delivery Optimization (peer update sharing); updates still work
  'WSAIFabricSvc'     = 'Manual'    # Windows AI Components Host (Copilot+/Recall features)
  'PCManager Service Store' = 'Manual'  # Microsoft PC Manager background service
  'StiSvc'            = 'Manual'    # Windows Image Acquisition (scanners/cameras); starts when needed
  'MapsBroker'        = 'Manual'    # Downloaded maps manager
  'RetailDemo'        = 'Disabled'
  'XblAuthManager'    = 'Manual'; 'XblGameSave' = 'Manual'; 'XboxNetApiSvc' = 'Manual'; 'XboxGipSvc' = 'Manual'
}
if ($Intel) {   # tiny savings (3-15 MB RAM each, no VRAM); the driver keeps working, the Intel Graphics Software app starts them when opened
  $services['IntelGraphicsSoftwareService'] = 'Manual'
  $services['Intel(R) PROSet Monitoring Service'] = 'Manual'
  $services['IntelGFXFWupdateTool'] = 'Manual'
}
# Kept on purpose: IGSDSserviceDiscrete (Intel shader distributor: helps shader cache), WSearch, BITS, Tailscale, SSH.
# Per-user registry switches (HKCU): Game DVR background recording off.
$regSets = @(
  @{ path = 'HKCU:\System\GameConfigStore'; name = 'GameDVR_Enabled'; value = 0 },
  @{ path = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR'; name = 'AppCaptureEnabled'; value = 0 },
  @{ path = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'; name = 'EnableTransparency'; value = 0 }
)
if ($BrowserAccel) {
  foreach ($p in 'HKCU:\SOFTWARE\Policies\Google\Chrome', 'HKCU:\SOFTWARE\Policies\Microsoft\Edge') { $regSets += @{ path = $p; name = 'HardwareAccelerationModeEnabled'; value = 0 } }
}
# Startup entries to switch off (the program stays installed; start it by hand when you want it).
$startupOff = @('Send to OneNote', 'Microsoft.Lists')
# Optional startup entries: uncomment the ones you don't use on this PC.
# $startupOff += 'OneDrive'      # only if you don't use OneDrive here
# $startupOff += 'OllamaHub'     # Ollama can load models into the same GPU as llama-swap
# Store apps to remove for the current user with -Apps (each reinstallable from the Store).
$appx = @('Microsoft.BingWeather', 'Microsoft.BingSearch', 'Clipchamp.Clipchamp', 'Microsoft.ZuneMusic', 'Microsoft.GetHelp',
          'Microsoft.WindowsFeedbackHub', 'Microsoft.Todos', 'Microsoft.Windows.DevHome', 'Microsoft.XboxGamingOverlay',
          'Microsoft.XboxSpeechToTextOverlay', 'MicrosoftWindows.Client.WebExperience')   # last one = Widgets board
# Keep (not touched): Microsoft.YourPhone (Phone Link with the S25), MSTeams, Outlook - remove by hand if unused.

function Load-Undo {
  $d = @{ services = @(); registry = @(); startup = @() }
  if (Test-Path $undoFile) {
    $j = Get-Content $undoFile -Raw | ConvertFrom-Json
    foreach ($s in @($j.services)) { if ($s) { $d.services += @{ name = $s.name; was = $s.was; delayed = [bool]$s.delayed } } }
    foreach ($r in @($j.registry)) { if ($r) { $d.registry += @{ path = $r.path; name = $r.name; existed = [bool]$r.existed; was = $r.was; kind = $r.kind } } }
    foreach ($s in @($j.startup)) { if ($s) { $d.startup += @{ name = $s.name; hive = $s.hive } } }
  }
  return $d
}
function Save-Undo($d) { New-Item -ItemType Directory -Force (Split-Path $undoFile) | Out-Null; $d | ConvertTo-Json -Depth 5 | Set-Content $undoFile -Encoding ascii }
function Approved-Key($hive) { "${hive}:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" }

if ($Undo) {
  if (-not (Test-Path $undoFile)) { Write-Host 'No undo file; nothing to restore.'; exit 0 }
  $u = Load-Undo
  foreach ($s in $u.services) {
    try {
      Set-Service -Name $s.name -StartupType $s.was -ErrorAction Stop
      if ($s.delayed) { Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$($s.name)" -Name DelayedAutostart -Value 1 -Type DWord }
      Write-Host "restored $($s.name) -> $($s.was)$(if ($s.delayed) {' (delayed start)'})"
    } catch { Write-Host "could not restore $($s.name): $($_.Exception.Message)" } }
  foreach ($r in $u.registry) {
    try {
      if ($r.existed) { Set-ItemProperty -Path $r.path -Name $r.name -Value $r.was -Type $r.kind -ErrorAction Stop; Write-Host "restored $($r.path)\$($r.name) = $($r.was)" }
      else { Remove-ItemProperty -Path $r.path -Name $r.name -ErrorAction Stop; Write-Host "removed $($r.path)\$($r.name) (did not exist before)" }
    } catch { Write-Host "could not restore $($r.path)\$($r.name): $($_.Exception.Message)" } }
  $sf = [Environment]::GetFolderPath('Startup')
  foreach ($e in $u.startup) {
    $name = $e.name
    if (Test-Path (Join-Path $sf "$name.lnk.disabled")) { Rename-Item (Join-Path $sf "$name.lnk.disabled") "$name.lnk"; Write-Host "re-enabled startup shortcut $name" }
    if ($e.hive) { $ap = Approved-Key $e.hive
      if ((Get-ItemProperty $ap -ErrorAction SilentlyContinue).$name) { Set-ItemProperty -Path $ap -Name $name -Value ([byte[]](2,0,0,0,0,0,0,0,0,0,0,0)) -Type Binary; Write-Host "re-enabled startup $name ($($e.hive))" } } }
  Write-Host 'Undo done. Store apps (if removed) reinstall from the Microsoft Store.'; exit 0
}

$plan = @(); $new = @{ services = @(); registry = @(); startup = @() }
foreach ($n in $services.Keys) {
  $svc = Get-Service -Name $n -ErrorAction SilentlyContinue; if (-not $svc) { continue }
  $want = $services[$n]; $was = (Get-CimInstance Win32_Service -Filter "Name='$($n -replace "'","''")'").StartMode
  if ($was -eq 'Auto') { $was = 'Automatic' }
  $delayed = [bool]((Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$n" -ErrorAction SilentlyContinue).DelayedAutostart -eq 1)
  if ($was -ne $want) { $plan += "service  $n : $was$(if ($delayed) {' (delayed)'}) -> $want"; $new.services += @{ name = $n; was = $was; delayed = $delayed } }
}
foreach ($r in $regSets) {
  $cur = (Get-ItemProperty $r.path -ErrorAction SilentlyContinue).$($r.name)
  if ($null -ne $cur -and $cur -eq $r.value) { continue }
  $plan += "registry $($r.path)\$($r.name) : $(if ($null -eq $cur) {'(not set)'} else {$cur}) -> $($r.value)"
  $new.registry += @{ path = $r.path; name = $r.name; existed = ($null -ne $cur); was = $cur; kind = 'DWord'; value = $r.value }
}
$runKeys = @(@{ hive = 'HKCU'; key = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' }, @{ hive = 'HKLM'; key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' })
foreach ($rk in $runKeys) { foreach ($name in $startupOff) { if ((Get-ItemProperty $rk.key -ErrorAction SilentlyContinue).$name) { $plan += "startup  $name (in $($rk.key)) -> off"; $new.startup += @{ name = $name; hive = $rk.hive } } } }
$startupFolder = [Environment]::GetFolderPath('Startup')
foreach ($name in $startupOff) { $lnk = Join-Path $startupFolder "$name.lnk"; if (Test-Path $lnk) { $plan += "startup  $lnk -> renamed .disabled"; $new.startup += @{ name = $name; hive = $null } } }
if ($Apps) { foreach ($a in $appx) { if (Get-AppxPackage -Name $a -ErrorAction SilentlyContinue) { $plan += "app      remove $a (current user)" } } }
if (-not $plan) { $plan += 'nothing to change: this PC is already in the lean state' }

Write-Host "`nPlan ($(if ($Apply) {'APPLYING'} else {'dry run - nothing changed'})):"; $plan | ForEach-Object { Write-Host "  $_" }
if (-not $Apply) { Write-Host "`nRe-run with -Apply (and optionally -Intel -BrowserAccel -Apps) from an elevated PowerShell to make these changes."; exit 0 }

# Merge into the undo file first; an item already recorded keeps its FIRST value, so re-running never loses the original state.
$u = Load-Undo
foreach ($s in $new.services) { if (-not ($u.services | Where-Object { $_.name -eq $s.name })) { $u.services += $s } }
foreach ($r in $new.registry) { if (-not ($u.registry | Where-Object { $_.path -eq $r.path -and $_.name -eq $r.name })) { $u.registry += @{ path = $r.path; name = $r.name; existed = $r.existed; was = $r.was; kind = $r.kind } } }
foreach ($e in $new.startup) { if (-not ($u.startup | Where-Object { $_.name -eq $e.name -and $_.hive -eq $e.hive })) { $u.startup += $e } }
Save-Undo $u
foreach ($s in $new.services) {
  try { Set-Service -Name $s.name -StartupType $services[$s.name] -ErrorAction Stop
    if ($s.delayed) { Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$($s.name)" -Name DelayedAutostart -Value 0 -Type DWord }
    if ($services[$s.name] -eq 'Disabled') { Stop-Service $s.name -Force -ErrorAction SilentlyContinue }
    Write-Host "set $($s.name) -> $($services[$s.name])" } catch { Write-Host "skip $($s.name): $($_.Exception.Message)" } }
foreach ($r in $new.registry) {
  try { if (-not (Test-Path $r.path)) { New-Item -Path $r.path -Force | Out-Null }
    Set-ItemProperty -Path $r.path -Name $r.name -Value $r.value -Type DWord -ErrorAction Stop; Write-Host "set $($r.path)\$($r.name) = $($r.value)" } catch { Write-Host "skip $($r.path)\$($r.name): $($_.Exception.Message)" } }
foreach ($e in $new.startup) {
  $name = $e.name
  if (-not $e.hive) { $lnk = Join-Path $startupFolder "$name.lnk"; try { Rename-Item $lnk "$lnk.disabled" -ErrorAction Stop; Write-Host "disabled startup shortcut $name" } catch { Write-Host "skip shortcut ${name}: $($_.Exception.Message)" } }
  else { $ap = Approved-Key $e.hive
    try { New-Item -Path $ap -Force | Out-Null; Set-ItemProperty -Path $ap -Name $name -Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Type Binary -ErrorAction Stop; Write-Host "disabled startup $name ($($e.hive); Task Manager > Startup shows it as Disabled)" }
    catch { Write-Host "skip startup ${name}: $($_.Exception.Message)" } }
}
if ($Apps) { foreach ($a in $appx) {
  if (-not (Get-AppxPackage -Name $a -ErrorAction SilentlyContinue)) { continue }
  Get-AppxPackage -Name $a -ErrorAction SilentlyContinue | Remove-AppxPackage -ErrorAction SilentlyContinue
  if (Get-AppxPackage -Name $a -ErrorAction SilentlyContinue) { Write-Host "could not remove $a" } else { Write-Host "removed $a" } } }
Write-Host "`nDone. Undo file: $undoFile. A sign-out or reboot completes the startup and visual changes."
