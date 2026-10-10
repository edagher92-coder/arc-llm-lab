# qwen snapshot [message] | qwen rollback <commit> | qwen history
# Versions every config file of the local AI stack in a local git repo (C:\AI\config-history). Never pushes anywhere.
param([string]$Action = 'snapshot', [string]$Arg = '')
$repo = 'C:\AI\config-history'
$files = @(
  'C:\AI\governor\profiles.json', 'C:\AI\governor\launch.ps1', 'C:\AI\governor\governor.ps1', 'C:\AI\governor\qwen.ps1',
  'C:\AI\governor\doctor.ps1', 'C:\AI\governor\snapshot.ps1', 'C:\AI\governor\nightly.ps1', 'C:\AI\governor\public\voice.html',
  'C:\AI\llama-swap\config.yaml',
  "$env:USERPROFILE\bin\claude-qwen.cmd", "$env:USERPROFILE\bin\codex-qwen.cmd",
  "$env:USERPROFILE\.codex\config.toml",
  'C:\AI\claude-local\LOCAL-SYSTEM.md', 'C:\AI\claude-local\CLAUDE.md', 'C:\AI\claude-local\mcp.json', 'C:\AI\claude-local\mcp-browser.json',
  'C:\AI\tts\tts_server.py', 'C:\AI\bench\regression.ps1'
)
function Rel($p) { ($p -replace '^C:\\', '' -replace '\\', '/') }
function G { & git -C $repo -c user.name='ARC-PC' -c user.email='local@arc-pc' @args }
if (-not (Test-Path "$repo\.git")) { New-Item -ItemType Directory -Force $repo | Out-Null; G init -q -b main; G config core.autocrlf false; Set-Content "$repo\README.md" "Local config history for the ARC-PC Qwen stack. Managed by qwen snapshot / qwen rollback." }
switch ($Action) {
  'snapshot' {
    foreach ($f in $files) { if (Test-Path $f) { $d = Join-Path $repo (Rel $f); New-Item -ItemType Directory -Force (Split-Path $d) | Out-Null; Copy-Item $f $d -Force } }
    G add -A
    $msg = if ($Arg) { $Arg } else { "snapshot $(Get-Date -f 'yyyy-MM-dd HH:mm')" }
    $changed = G status --porcelain
    if ($changed) { G commit -q -m $msg; Write-Host "Snapshot saved: $(G log -1 --format='%h %s')"; G show --stat --format='' HEAD | Select -Last 1 }
    else { Write-Host "No changes since $(G log -1 --format='%h %s')" }
  }
  'history' { G log --format='%h  %ad  %s' --date=format:'%Y-%m-%d %H:%M' -n 20 }
  'diff' { if ($Arg) { G diff $Arg -- . } else { Write-Host 'usage: qwen diff <commit>' } }
  'rollback' {
    if (-not $Arg) { Write-Host 'usage: qwen rollback <commit>   (see: qwen history)'; break }
    if (-not (G rev-parse --verify -q "$Arg^{commit}")) { Write-Host "Unknown commit $Arg"; break }
    & $PSCommandPath snapshot "safety snapshot before rollback to $Arg"
    G checkout -q $Arg -- .   # byte-exact old versions into the repo working tree
    foreach ($f in $files) { $src = Join-Path $repo (Rel $f); if (Test-Path $src) { Copy-Item $src $f -Force; Write-Host "restored $f" } }
    G checkout -q HEAD -- .   # repo back to latest; next snapshot records the rollback as a new commit
    & $PSCommandPath snapshot "rolled back to $Arg"
    Write-Host "Rolled back to $Arg. Restart to apply: qwen restart"
  }
}
