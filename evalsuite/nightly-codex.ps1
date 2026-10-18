# Nightly Codex (codex-qwen) regression run on the acceptance set (acceptance.txt), added 2026-10-19.
# Scheduled 01:43 by "Local Qwen Codex Nightly". Skips when an eval is running, the model is busy or mode is OFF.
# Writes C:\AI\governor\public\codex-nightly.json and appends to C:\AI\bench\nightly.log. Turn cap 25 (runner default).
param([string]$Ids = '', [string]$Run = '')
$ErrorActionPreference = 'Continue'
$log = 'C:\AI\bench\nightly.log'; $out = 'C:\AI\governor\public\codex-nightly.json'
function L($m) { "$(Get-Date -f s) codex-nightly $m" | Out-File $log -Append -Encoding utf8 }
$busy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -match 'runner\.py|sustained\.py' }
$st = try { Get-Content C:\AI\governor\public\status.json -Raw | ConvertFrom-Json } catch { $null }
$mode = (Get-Content C:\AI\governor\mode.txt -ErrorAction SilentlyContinue | Select -First 1)
if ($busy -or ($st -and $st.processing) -or ($mode -eq 'OFF')) { L "SKIP: eval running, model busy or mode OFF"; exit 0 }
Set-Location C:\AI\evalsuite; $env:PYTHONIOENCODING = 'utf-8'
if (-not $Ids) { $Ids = (Get-Content acceptance.txt | ? { $_ -and $_ -notmatch '^\s*#' } | % { $_.Trim() }) -join ',' }
if (-not $Run) { $Run = "codex-nightly-$(Get-Date -f yyyyMMdd)" }
$n = ($Ids -split ',').Count
L "START $Run ($n tasks)"; $t0 = Get-Date
python runner.py --agent codex --cap 32768 --max-turns 25 --run $Run --ids $Ids *> "results\$Run.console.txt"
python prune_codex_trust.py *>> "results\$Run.console.txt"
$r = @(Get-Content "results\$Run.jsonl" -ErrorAction SilentlyContinue | % { $_ | ConvertFrom-Json })
$pass = @($r | ? passed).Count; $mins = [math]::Round(($r | Measure wall_s -Sum).Sum / 60, 1)
# compare with the previous nightly run
$prev = Get-ChildItem results\codex-nightly-2*.jsonl | ? { $_.BaseName -ne $Run } | Sort Name | Select -Last 1
$prevPass = $null; $newFails = @()
if ($prev) {
  $pr = @(Get-Content $prev.FullName | % { $_ | ConvertFrom-Json }); $prevPass = @($pr | ? passed).Count
  $prevOk = @($pr | ? passed | % id); $newFails = @($r | ? { -not $_.passed -and ($prevOk -contains $_.id) } | % id)
}
$alerts = @()
if ($r.Count -lt $n) { $alerts += "only $($r.Count)/$n tasks recorded" }
if ($pass -lt ($n - 1)) { $alerts += "codex acceptance: $pass/$($r.Count) passed (expect >= $($n - 1))" }
if ($newFails.Count) { $alerts += "regressions vs $($prev.BaseName): $($newFails -join ', ')" }
$capped = @($r | ? turn_capped | % id)
[ordered]@{ time = (Get-Date -f s); run = $Run; ok = ($alerts.Count -eq 0); alerts = $alerts; passed = $pass; total = $r.Count; expected = $n
  minutes = $mins; previous = $(if ($prev) { $prev.BaseName } else { $null }); previous_passed = $prevPass; turn_capped = $capped
  failed_tasks = @($r | ? { -not $_.passed } | % { "$($_.id): $($_.failure)" }) } | ConvertTo-Json |
  % { [IO.File]::WriteAllText($out, $_, (New-Object Text.UTF8Encoding $false)) }
L ("END $pass/$($r.Count) in $mins min " + $(if ($alerts.Count) { 'ALERT ' + ($alerts -join '; ') } else { 'OK' }))
# keep the last 14 nightly workspaces (failed tasks only are left in them; passes are cleaned by the runner)
Get-ChildItem C:\AI\evalsuite\work -Directory -Filter 'codex-nightly-*' | Sort Name -Descending | Select -Skip 14 | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
