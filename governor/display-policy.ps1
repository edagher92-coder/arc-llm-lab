# display-policy.ps1 - smart display policy for an AI PC: fewer pixels while nobody is at the screen, so the GPU compositor (dwm.exe)
# gives its VRAM back to the model. On the test PC (two 3440x1440 monitors) dwm held 2.5 GB of the B60's 24 GB.
#   PRESENT      you touched the keyboard/mouse recently          -> your normal mode (restored from Windows' own saved setting)
#   AWAY-REMOTE  idle, but you are connected remotely / using it   -> 2560x1440 ("2K"; these monitors offer no 2560x1080 mode)
#   AWAY-IDLE    idle and nobody connected                         -> 1920x1080
# 60 Hz cap. Changes are TEMPORARY (not written to the registry): a reboot or sign-out always returns to your normal mode, and any
# key press or mouse move restores it within ~2 s. Windows may rearrange windows when the mode changes; that is the cost of this feature.
# It must run in YOUR desktop session (a service or SYSTEM task cannot change the display). It never touches drivers or Intel settings.
#
#   .\display-policy.ps1 -Status                 # list displays, current and available modes, idle time, remote signals (read-only)
#   .\display-policy.ps1 -Discover               # list files that change when you use the PC remotely (to pick remote signals)
#   .\display-policy.ps1 -Set Remote|Idle|Native # apply one state once (for testing; add -Hold 20 to auto-revert after 20 s)
#   .\display-policy.ps1 -Watch                  # the loop. Does nothing unless "enabled": true in display-policy.json
#   .\display-policy.ps1 -Install / -Uninstall   # register / remove a logon task for the current user that runs -Watch
param([switch]$Status, [switch]$Discover, [ValidateSet('Native','Remote','Idle')][string]$Set, [int]$Hold = 0, [switch]$Watch, [switch]$Install, [switch]$Uninstall,
      [string]$Config = 'C:\AI\governor\display-policy.json')
$ErrorActionPreference = 'Stop'
$cfg = @{ enabled = $false; away_after_s = 300; settle_s = 60; poll_s = 15; poll_away_s = 2; hz_cap = 60
          remote = @{ width = 2560; height = 1440 }; idle = @{ width = 1920; height = 1080 }
          remote_window_s = 600; remote_activity_files = @('C:\AI\gateway\state\audit.jsonl'); remote_processes = @(); count_rdp_session = $true
          log = 'C:\AI\cache\display-policy.log'; state = 'C:\AI\cache\display-policy-state.json'; kill_file = 'C:\AI\governor\display-policy.off' }
if (Test-Path $Config) { $j = Get-Content $Config -Raw | ConvertFrom-Json; foreach ($p in $j.PSObject.Properties) { $cfg[$p.Name] = if ($p.Value -is [pscustomobject]) { @{ width = $p.Value.width; height = $p.Value.height } } else { $p.Value } } }

Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class Disp {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
    public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra; public int dmFields;
    public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency,
      dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DISPLAY_DEVICE {
    public int cb; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceString; public int StateFlags;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceID; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceKey; }
  [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll", CharSet=CharSet.Ansi)] static extern bool EnumDisplayDevices(string dev, uint i, ref DISPLAY_DEVICE d, uint f);
  [DllImport("user32.dll", CharSet=CharSet.Ansi)] static extern bool EnumDisplaySettings(string dev, int mode, ref DEVMODE m);
  [DllImport("user32.dll", CharSet=CharSet.Ansi)] static extern int ChangeDisplaySettingsEx(string dev, ref DEVMODE m, IntPtr hwnd, uint flags, IntPtr p);
  [DllImport("user32.dll", CharSet=CharSet.Ansi)] static extern int ChangeDisplaySettingsEx(string dev, IntPtr m, IntPtr hwnd, uint flags, IntPtr p);
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO i);
  [DllImport("kernel32.dll")] static extern uint GetTickCount();
  const int CURRENT = -1;
  public static uint IdleMs() { var i = new LASTINPUTINFO(); i.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO)); if (!GetLastInputInfo(ref i)) return 0; return unchecked(GetTickCount() - i.dwTime); }
  public static List<string> Devices() { var l = new List<string>(); for (uint n = 0; ; n++) { var d = new DISPLAY_DEVICE(); d.cb = Marshal.SizeOf(d); if (!EnumDisplayDevices(null, n, ref d, 0)) break; if ((d.StateFlags & 1) != 0) l.Add(d.DeviceName); } return l; }
  static DEVMODE New() { var m = new DEVMODE(); m.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE)); return m; }
  public static int[] Current(string dev) { var m = New(); if (!EnumDisplaySettings(dev, CURRENT, ref m)) return null; return new int[] { m.dmPelsWidth, m.dmPelsHeight, m.dmDisplayFrequency, m.dmPositionX, m.dmPositionY, m.dmBitsPerPel }; }
  public static List<int[]> Modes(string dev) { var l = new List<int[]>(); var m = New(); for (int i = 0; EnumDisplaySettings(dev, i, ref m); i++) l.Add(new int[] { m.dmPelsWidth, m.dmPelsHeight, m.dmDisplayFrequency, m.dmBitsPerPel }); return l; }
  // Stage a temporary mode (no registry write) for one display. Returns 0 on success.
  public static int Stage(string dev, int w, int h, int hz, int x, int y, int bpp, bool testOnly) {
    var m = New(); EnumDisplaySettings(dev, CURRENT, ref m);
    m.dmPelsWidth = w; m.dmPelsHeight = h; m.dmDisplayFrequency = hz; m.dmPositionX = x; m.dmPositionY = y; m.dmBitsPerPel = bpp;
    m.dmFields = 0x80000 | 0x100000 | 0x400000 | 0x20 | 0x40000;   // width, height, frequency, position, bits
    return ChangeDisplaySettingsEx(dev, ref m, IntPtr.Zero, testOnly ? 0x2u : 0x10000000u, IntPtr.Zero);   // CDS_TEST alone validates; CDS_NORESET stages (the two flags must not be combined)
  }
  public static int Commit() { return ChangeDisplaySettingsEx(null, IntPtr.Zero, IntPtr.Zero, 0, IntPtr.Zero); }
  // Back to Windows' saved setting for one display (NULL devmode = use the registry values), then commit.
  public static int StageSaved(string dev) { return ChangeDisplaySettingsEx(dev, IntPtr.Zero, IntPtr.Zero, 0x10000000u, IntPtr.Zero); }
}
'@

function Log($m) { $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Write-Host $l; try { New-Item -ItemType Directory -Force (Split-Path $cfg.log) | Out-Null; Add-Content $cfg.log $l } catch {} }
function Test-Remote {
  $why = @()
  if ($cfg.count_rdp_session) { $q = (& query.exe user 2>$null) -join "`n"; if ($q -match 'rdp-tcp#\d+\s+\d+\s+Active') { $why += 'rdp-session' } }
  foreach ($f in @($cfg.remote_activity_files)) { if ($f -and (Test-Path $f) -and ((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds -lt $cfg.remote_window_s) { $why += "activity:$f" } }
  foreach ($p in @($cfg.remote_processes)) { $ids = @(Get-Process -Name $p -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }); if ($ids -and (Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })) { $why += "proc:$p" } }
  return ,$why
}
function Pick-Mode($dev, $w, $h) {   # best available mode at or below the hz cap; exact size, else the largest same-aspect size not above it
  $cap = [int]$cfg.hz_cap; $ms = @([Disp]::Modes($dev) | ForEach-Object { [pscustomobject]@{ w = $_[0]; h = $_[1]; hz = $_[2]; bpp = $_[3] } } | Where-Object { $_.bpp -ge 24 -and $_.hz -le $cap -and $_.hz -ge 30 })
  $x = $ms | Where-Object { $_.w -eq $w -and $_.h -eq $h } | Sort-Object hz -Descending | Select-Object -First 1; if ($x) { return $x }
  $ar = $w / $h; return ($ms | Where-Object { [math]::Abs($_.w / $_.h - $ar) -lt 0.02 -and $_.w -le $w } | Sort-Object w, hz -Descending | Select-Object -First 1)
}
function Apply-State($state) {
  $devs = [Disp]::Devices()
  if ($state -eq 'Native') { foreach ($d in $devs) { [void][Disp]::StageSaved($d) }; $r = [Disp]::Commit(); Log "apply Native -> $r"; return ($r -eq 0) }
  $t = if ($state -eq 'Remote') { $cfg.remote } else { $cfg.idle }; $x = 0; $plan = @()
  foreach ($d in ($devs | Sort-Object { ([Disp]::Current($_))[3] })) {   # pack monitors left to right so there is no gap after shrinking
    $cur = [Disp]::Current($d); $m = Pick-Mode $d $t.width $t.height; if (-not $m) { Log "no mode near $($t.width)x$($t.height) on $d; skipping $state"; return $false }
    $plan += @{ d = $d; m = $m; x = $x; y = $cur[4]; bpp = $cur[5] }; $x += $m.w }
  foreach ($p in $plan) { $r = [Disp]::Stage($p.d, $p.m.w, $p.m.h, $p.m.hz, $p.x, $p.y, $p.bpp, $true); if ($r -ne 0) { Log "mode $($p.m.w)x$($p.m.h)@$($p.m.hz) rejected for $($p.d) (code $r); nothing changed"; return $false } }
  foreach ($p in $plan) { [void][Disp]::Stage($p.d, $p.m.w, $p.m.h, $p.m.hz, $p.x, $p.y, $p.bpp, $false) }
  $r = [Disp]::Commit(); Log ("apply $state -> " + (($plan | ForEach-Object { "$($_.d) $($_.m.w)x$($_.m.h)@$($_.m.hz)" }) -join ', ') + " result $r")
  if ($r -ne 0) { [void](Apply-State 'Native'); return $false }; return $true
}
function Write-State($s, $idle, $why) { try { New-Item -ItemType Directory -Force (Split-Path $cfg.state) | Out-Null; @{ state = $s; idle_s = $idle; remote = $why; time = (Get-Date).ToString('s') } | ConvertTo-Json | Set-Content $cfg.state -Encoding ascii } catch {} }

if ($Status) {
  Write-Host "idle: $([int]([Disp]::IdleMs()/1000)) s   remote signals: $((Test-Remote) -join ', ')   enabled in config: $($cfg.enabled)"
  foreach ($d in [Disp]::Devices()) { $c = [Disp]::Current($d); Write-Host "$d now $($c[0])x$($c[1])@$($c[2]) at ($($c[3]),$($c[4]))"
    foreach ($t in @($cfg.remote, $cfg.idle)) { $m = Pick-Mode $d $t.width $t.height; Write-Host "   target $($t.width)x$($t.height) -> $(if ($m) { "$($m.w)x$($m.h)@$($m.hz)" } else { 'NO MATCHING MODE' })" }
    Write-Host "   sizes: $((([Disp]::Modes($d) | ForEach-Object { "$($_[0])x$($_[1])" } | Sort-Object -Unique) -join ' '))" }
  exit 0 }
if ($Discover) {
  Write-Host 'Newest files under the gateway, llama-swap and Open WebUI folders (use one that changes when you use the PC from your phone as remote_activity_files):'
  foreach ($root in 'C:\AI\gateway\state', 'C:\AI\llama-swap', 'C:\AI\logs', 'C:\AI\cache') { if (Test-Path $root) { Get-ChildItem $root -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 4 | ForEach-Object { "{0}  {1}" -f $_.LastWriteTime.ToString('s'), $_.FullName } } }
  exit 0 }
if ($Install) {
  $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Watch"
  $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName 'AI-DisplayPolicy' -Action $a -Trigger $t -Settings $s -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive) -Force | Out-Null
  Write-Host 'Installed logon task AI-DisplayPolicy. It does nothing until "enabled": true is set in display-policy.json.'; exit 0 }
if ($Uninstall) { Unregister-ScheduledTask -TaskName 'AI-DisplayPolicy' -Confirm:$false -ErrorAction SilentlyContinue; [void](Apply-State 'Native'); Write-Host 'Removed the task and restored your normal mode.'; exit 0 }
if ($Set) {
  [void](Apply-State $Set)
  if ($Hold -gt 0 -and $Set -ne 'Native') { Start-Sleep -Seconds $Hold; [void](Apply-State 'Native') }
  exit 0 }
if ($Watch) {
  $state = 'PRESENT'; $since = Get-Date; Log "watch started (enabled=$($cfg.enabled))"
  try {
    while ($true) {
      if (Test-Path $Config) { try { $j = Get-Content $Config -Raw | ConvertFrom-Json; $cfg.enabled = [bool]$j.enabled } catch {} }
      if (-not $cfg.enabled -or (Test-Path $cfg.kill_file)) { if ($state -ne 'PRESENT') { [void](Apply-State 'Native'); $state = 'PRESENT' }; Write-State 'DISABLED' 0 @(); Start-Sleep -Seconds 30; continue }
      $idle = [int]([Disp]::IdleMs() / 1000); $why = Test-Remote
      if ($idle -lt 3 -and $state -ne 'PRESENT') { [void](Apply-State 'Native'); $state = 'PRESENT'; $since = Get-Date; Log "input detected: restored" }   # instant restore
      elseif ($idle -ge $cfg.away_after_s) {
        $want = if ($why.Count -gt 0) { 'AWAY-REMOTE' } else { 'AWAY-IDLE' }
        if ($want -ne $state -and ((Get-Date) - $since).TotalSeconds -ge $cfg.settle_s) {   # hysteresis: stay in a state for settle_s before switching
          if (Apply-State $(if ($want -eq 'AWAY-REMOTE') { 'Remote' } else { 'Idle' })) { $state = $want; $since = Get-Date } else { $since = Get-Date } } }
      Write-State $state $idle $why
      Start-Sleep -Seconds $(if ($state -eq 'PRESENT') { $cfg.poll_s } else { $cfg.poll_away_s })
    }
  } finally { try { [void](Apply-State 'Native') } catch {}; Log 'watch stopped; normal mode restored' }
  exit 0 }
Get-Help $PSCommandPath | Out-Null; Write-Host 'Use -Status, -Discover, -Set, -Watch, -Install or -Uninstall (see the header of this file).'
