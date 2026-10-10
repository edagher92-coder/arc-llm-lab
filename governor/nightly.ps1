# Nightly regression check (scheduled 03:07). Doctor + 3-turn benchmark + 14-task agent smoke (2 per category).
# Writes C:\AI\governor\public\nightly.json (visible on the tailnet at /governor/nightly.json) and appends to C:\AI\bench\nightly.log.
$ErrorActionPreference = 'Continue'
$log = 'C:\AI\bench\nightly.log'; $out = 'C:\AI\governor\public\nightly.json'
function L($m) { "$(Get-Date -f s) $m" | Out-File $log -Append -Encoding utf8 }
# never collide with an evaluation run or active use
$busy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -match 'runner\.py|sustained\.py' }
$st = try { Get-Content C:\AI\governor\public\status.json -Raw | ConvertFrom-Json } catch { $null }
if ($busy -or ($st -and $st.processing)) { L 'SKIP: evaluation running or model busy'; exit 0 }
L 'START'; $t0 = Get-Date
$doc = powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\doctor.ps1 2>&1 | Out-String
$docFails = ([regex]::Matches($doc, '(?m)^\s+FAIL')).Count
L "doctor fails=$docFails"
powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\bench\regression.ps1 *> C:\AI\bench\nightly-bench.txt
$b = (Import-Csv C:\AI\bench\history.csv)[-1]
L "bench three_turn=$($b.three_turn_s)s coding=$($b.coding) tools=$($b.tools)"
$ids = 'code-merge_intervals,code-gst,debug-pager,debug-csvout,tool-sha256,tool-git-branch,files-version-bump,files-refactor-rename,long-config-path,long-find-caller,biz-gst-invoice,biz-bank-rec,recover-missing-dir,recover-encoding'
$run = "nightly-$(Get-Date -f yyyyMMdd)"
Set-Location C:\AI\evalsuite; $env:PYTHONIOENCODING = 'utf-8'
python runner.py --agent claude --run $run --ids $ids *> "C:\AI\evalsuite\results\$run.console.txt"
$r = Get-Content "C:\AI\evalsuite\results\$run.jsonl" | % { $_ | ConvertFrom-Json }
$pass = ($r | ? passed).Count; $mins = [math]::Round(($r | Measure wall_s -Sum).Sum / 60, 1)
L "smoke $pass/$($r.Count) in $mins min"
$alerts = @()
if ([datetime]$b.time -lt $t0) { $alerts += 'benchmark wrote no new history row (regression.ps1 failed?)' }
if ($docFails -gt 0) { $alerts += "doctor: $docFails failed checks" }
if ([double]$b.three_turn_s -gt 63) { $alerts += "benchmark slow: $($b.three_turn_s)s (baseline 54.9)" }
if ($b.coding -ne '7/7' -or $b.tools -ne '3/3') { $alerts += "benchmark accuracy: coding $($b.coding), tools $($b.tools)" }
if ($pass -lt 12) { $alerts += "agent smoke: $pass/$($r.Count) passed (expect >= 12)" }
[ordered]@{ time = (Get-Date -f s); ok = ($alerts.Count -eq 0); alerts = $alerts; doctor_fails = $docFails; three_turn_s = [double]$b.three_turn_s;
  bench_coding = $b.coding; bench_tools = $b.tools; smoke_passed = $pass; smoke_total = $r.Count; smoke_minutes = $mins;
  failed_tasks = @($r | ? { -not $_.passed } | % { "$($_.id): $($_.failure)" }) } | ConvertTo-Json | % { [IO.File]::WriteAllText($out, $_, (New-Object Text.UTF8Encoding $false)) }
L ("END " + $(if ($alerts.Count) { 'ALERT ' + ($alerts -join '; ') } else { 'OK' }))
# keep only the last 14 nightly runs' workspaces
Get-ChildItem C:\AI\evalsuite\work -Directory -Filter 'nightly-*' | Sort Name -Descending | Select -Skip 14 | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
