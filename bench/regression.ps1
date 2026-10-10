# Permanent regression benchmark for the local Qwen on ARC-PC.
# Core metric: the 3-turn agentic coding test at 30-37k tokens deep (baseline 54.9 s on 10 Oct 2026, Intel-FA engine).
# Usage: qwen bench   (or: powershell -File C:\AI\bench\regression.ps1 [-Port 18080] [-Label name])
param([int]$Port = 0, [string]$Label = 'live')
$dir = 'C:\AI\bench'; $hist = "$dir\history.csv"
$BASE_3TURN = 54.9; $BASE_SHALLOW = 42.8; $BASE_EVAL_TPS = 43.0
if ($Port -eq 0) {
  try { $Port = [int](Get-Content C:\AI\governor\running.json -Raw | ConvertFrom-Json).port } catch { $Port = 10001 }
  $key = (Get-Content 'C:\AI\llama-swap\api-key.txt' -Raw).Trim()
  try { Invoke-RestMethod http://127.0.0.1:$Port/health -TimeoutSec 3 | Out-Null } catch {
    Write-Host 'Model not loaded - loading...'; $b = @{ model = 'qwen3.8-27b'; max_tokens = 1; messages = @(@{ role = 'user'; content = 'hi' }) } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method Post http://127.0.0.1:8090/v1/chat/completions -Headers @{ Authorization = "Bearer $key" } -Body $b -ContentType 'application/json' -TimeoutSec 300 | Out-Null
    $Port = [int](Get-Content C:\AI\governor\running.json -Raw | ConvertFrom-Json).port }
}
$eng = try { (Get-Content C:\AI\governor\profiles.json -Raw | ConvertFrom-Json).exe } catch { '?' }
$ctx = try { (Invoke-RestMethod http://127.0.0.1:$Port/props -TimeoutSec 5).default_generation_settings.n_ctx } catch { 0 }
Write-Host "Benchmarking port $Port (ctx $ctx, engine $eng) - takes ~4 min..."
$env:NF = '590'
$sh = (& python "$dir\req.py" $Port "$Label-shallow" 2>&1 | Out-String) | ConvertFrom-Json
$at = (& python "$dir\agentturn.py" $Port $Label 2>&1) | % { try { $_ | ConvertFrom-Json } catch {} }
$turns = $at | ? { $_.run -like 'turn*' }; $three = ($at | ? { $_.three_turns_wall_s }).three_turns_wall_s
$ev = (& python "$dir\eval.py" $Port $Label 2>&1 | Select -Last 1) | ConvertFrom-Json
$row = [ordered]@{ time = (Get-Date -f s); label = $Label; ctx = $ctx; engine = (Split-Path (Split-Path $eng) -Leaf)
  three_turn_s = $three; deep_tg = [math]::Round(($turns.tg_tps | measure -Average).Average, 1); deep_pp = [math]::Round(($turns.pp_tps | measure -Average).Average, 0)
  shallow_tg = $sh.tg_tps; eval_tps = $ev.avg_gen_tps_wall; coding = "$($ev.coding_pass)/$($ev.coding_total)"; tools = "$($ev.tools_pass)/$($ev.tools_total)" }
if (-not (Test-Path $hist)) { ($row.Keys -join ',') | Set-Content $hist }
($row.Values -join ',') | Add-Content $hist
$ok = ($three -le $BASE_3TURN * 1.10) -and ($ev.coding_pass -eq $ev.coding_total) -and ($ev.tools_pass -eq $ev.tools_total)
Write-Host ''
Write-Host ("3-turn coding test : {0} s   (baseline {1} s)" -f $three, $BASE_3TURN)
Write-Host ("Deep generation    : {0} tok/s, deep reading {1} tok/s" -f $row.deep_tg, $row.deep_pp)
Write-Host ("Shallow generation : {0} tok/s (baseline {1})   eval avg {2} tok/s (baseline {3})" -f $sh.tg_tps, $BASE_SHALLOW, $ev.avg_gen_tps_wall, $BASE_EVAL_TPS)
Write-Host ("Quality            : coding {0}, tools {1}" -f $row.coding, $row.tools)
if ($ok) { Write-Host 'RESULT: PASS' -ForegroundColor Green } else { Write-Host 'RESULT: REGRESSION - check history.csv' -ForegroundColor Red }
