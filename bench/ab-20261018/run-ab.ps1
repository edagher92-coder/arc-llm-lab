# A/B harness for engine variants (18 Oct 2026). Launches a scratch llama-server on :10011 with the production
# command line (from launch.ps1 -DryRun) changing only the given knobs, waits for health, reads PDH dedicated/shared,
# runs the 3-seed sustained contract (sustained.py) and a prompt-processing probe, then stops the server.
# Caller must hold the engine lock and have the governor in mode OFF.
param(
    [string]$Label,
    [string]$Kv = 'f16',
    [int]$Ctx = 32768,
    [int]$Runs = 3,
    [string]$Exe = 'C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe',
    [string[]]$Extra = @(),
    [hashtable]$Env = @{ GGML_VK_FORCE_MMVQ = '1' },
    [double]$AbortBelowTps = 0,
    [switch]$SkipPP,
    [switch]$Greedy
)
$ErrorActionPreference = 'Stop'
$out = 'C:\AI\bench\ab-20261018'
$port = 10011
$base = "http://127.0.0.1:$port"
foreach ($k in $Env.Keys) { Set-Item "env:$k" $Env[$k] }
$args2 = @('-m', 'C:/AI/models/thinkingcap/ThinkingCap-Qwen3.8-27B-Q4_K_M.gguf',
    '--mmproj', 'C:/AI/models/thinkingcap/mmproj-ThinkingCap-Qwen3.8-27B-f16.gguf', '--no-mmproj-offload',
    '-a', 'qwen3.8-27b', '--host', '127.0.0.1', '--port', "$port", '-c', "$Ctx", '-ctk', $Kv, '-ctv', $Kv,
    '-t', '8', '-tb', '8', '-cram', '6144', '--prio', '-1', '-ngl', '99', '-fa', 'on', '-lm', 'dio', '--jinja', '-np', '1',
    '--cache-reuse', '256', '--metrics', '--reasoning-budget', '16384', '-fit', 'off',
    '--chat-template-file', 'C:/AI/governor/qwen38-template.jinja', '--no-context-shift',
    '-ngld', '99', '-md', 'C:/AI/models/qwen3.8-27b/Qwen3.8-27B-DFlash2-Q4_K_M.gguf', '--spec-type', 'draft-dflash',
    '--spec-draft-n-max', '7', '-ub', '256', '-ctkd', 'q8_0', '-ctvd', 'q8_0', '--spec-draft-p-min', '0.4') + $Extra
$log = "$out\$Label.server.log"
$p = Start-Process -FilePath $Exe -ArgumentList $args2 -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden -PassThru
$t0 = Get-Date; $ok = $false
while (((Get-Date) - $t0).TotalSeconds -lt 240) {
    Start-Sleep 2
    if ($p.HasExited) { break }
    try { $h = Invoke-RestMethod "$base/health" -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
}
$loadS = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
$result = [ordered]@{ label = $Label; kv = $Kv; ctx = $Ctx; exe = $Exe; extra = ($Extra -join ' '); env = ($Env.Keys | % { "$_=$($Env[$_])" }) -join ' '; load_s = $loadS; healthy = $ok }
if (-not $ok) { $result.error = "server not healthy; exited=$($p.HasExited)"; $result | ConvertTo-Json | Set-Content "$out\$Label.result.json"; if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }; $result | ConvertTo-Json; exit 1 }
Start-Sleep 3
$set = (Get-Counter '\GPU Process Memory(*)\Dedicated Usage', '\GPU Process Memory(*)\Shared Usage').CounterSamples | ? { $_.InstanceName -like "pid_$($p.Id)_*" }
$result.dedicated_gib = [math]::Round((($set | ? { $_.Path -like '*dedicated usage' } | measure CookedValue -Sum).Sum) / 1GB, 2)
$result.shared_gib = [math]::Round((($set | ? { $_.Path -like '*shared usage' } | measure CookedValue -Sum).Sum) / 1GB, 2)
$adapter = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | measure CookedValue -Maximum
$result.adapter_used_gib = [math]::Round($adapter.Maximum / 1GB, 2)
$result.free_gib = [math]::Round(23.9 - $result.adapter_used_gib, 2)

# warm-up: pipelines with new specialisation constants compile lazily on first use; exercise prefill and every
# DFlash column count once so the measured runs below are warm (identical treatment for every config)
foreach ($w in 1..2) { try { $wb = @{ model = 'qwen3.8-27b'; messages = @(@{ role = 'user'; content = ('Summarise this service log in five bullet points. ' + ('The technician replaced the auger seal, cleaned the condenser and recorded compressor temperatures. ' * 60)) }); max_tokens = 400; temperature = 0.2; seed = 7; chat_template_kwargs = @{ enable_thinking = $false } } | ConvertTo-Json -Depth 5; Invoke-RestMethod "$base/v1/chat/completions" -Method Post -Body $wb -ContentType 'application/json' -TimeoutSec 600 | Out-Null } catch {} }
# prompt-processing probe: fresh prompts of ~2048 and ~8192 tokens, no cache, 1 token out
$para = 'The service technician inspected the slushie machine, recorded the compressor temperature, cleaned the auger, replaced the worn seal and logged the parts used for the invoice. '
$pp = @()
foreach ($target in $(if ($SkipPP) { @() } else { @(2048, 8192) })) {
    $text = ''; $n = 0
    while ($n -lt $target) { $text += "[$n] " + $para; $n = (Invoke-RestMethod "$base/tokenize" -Method Post -Body (@{ content = $text } | ConvertTo-Json) -ContentType 'application/json').tokens.Count }
    $body = @{ prompt = $text; n_predict = 1; cache_prompt = $false; temperature = 0 } | ConvertTo-Json
    $r = Invoke-RestMethod "$base/completion" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 600
    $pp += [ordered]@{ prompt_n = $r.timings.prompt_n; prompt_tps = [math]::Round($r.timings.prompt_per_second, 1) }
}
$result.pp = $pp

# sustained contract (seeds 4242..), unless the caller wants an early abort check after seed 1
$env:QWEN_BASE = $base
$sus = "$out\$Label.sustained.jsonl"
if (Test-Path $sus) { Remove-Item $sus }
$py = Get-Command python | % Source
& $py "$out\sustained.py" --label $Label --output $sus --runs $Runs --stream --expected-context $Ctx 2>&1 | Out-Null
$rows = Get-Content $sus -ErrorAction SilentlyContinue | % { $_ | ConvertFrom-Json }
$result.tps = @($rows | % { [math]::Round($_.timings.predicted_per_second, 2) })
$result.ttft_s = @($rows | % { [math]::Round($_.latency.first_content_s, 3) })
$result.draft_accept = @($rows | % { $d = $_.native_counter_deltas; if ($d.spec_decode_num_draft_tokens_total) { [math]::Round($d.spec_decode_num_accepted_tokens_total / $d.spec_decode_num_draft_tokens_total, 3) } })
$result.rounds = @($rows | % { $_.native_counter_deltas.spec_decode_num_drafts_total })
$result.ms_per_round = @($rows | % { $d = $_.native_counter_deltas; if ($d.spec_decode_num_drafts_total) { [math]::Round($_.timings.predicted_ms / $d.spec_decode_num_drafts_total, 1) } })
if ($result.tps.Count) { $result.tps_mean = [math]::Round(($result.tps | measure -Average).Average, 2) }
if ($Greedy) { $g = & $py "$out\greedy_check.py" $Label 2>&1 | Select-Object -Last 1; try { $result.greedy = ($g | ConvertFrom-Json) } catch { $result.greedy = "$g" } }
$result.oc = (& 'D:\build\igcl\probe\oc_set.exe' get | Select-Object -Last 1)
$set2 = (Get-Counter '\GPU Process Memory(*)\Shared Usage').CounterSamples | ? { $_.InstanceName -like "pid_$($p.Id)_*" }
$result.shared_gib_after = [math]::Round((($set2 | measure CookedValue -Sum).Sum) / 1GB, 2)
Stop-Process -Id $p.Id -Force
Start-Sleep 3
$result | ConvertTo-Json -Depth 4 | Set-Content "$out\$Label.result.json"
$result | ConvertTo-Json -Depth 4 -Compress



