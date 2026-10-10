param([string]$Agent = 'claude', [int]$Cap = 32768, [string]$Run = '')
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
if (-not $Run) { $Run = "$Agent-$([int]($Cap/1024))k" }
$log = "$PSScriptRoot\results\$Run.console.txt"
New-Item -ItemType Directory -Force results | Out-Null
"== $Run start $(Get-Date -f s)" | Out-File $log -Append -Encoding utf8
$env:PYTHONIOENCODING = 'utf-8'
python runner.py --agent $Agent --cap $Cap --run $Run 2>&1 | Out-File $log -Append -Encoding utf8
"== $Run end $(Get-Date -f s)" | Out-File $log -Append -Encoding utf8
