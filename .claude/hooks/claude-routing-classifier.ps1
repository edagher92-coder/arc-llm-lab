#requires -Version 5.1
<#
  claude-routing-classifier.ps1 -- UserPromptSubmit hook
  Model Routing Policy v5.1 (Sonnet 5 quality-intent guard).

  Deterministic gates run before the optional local classifier:
    STAKES  -> Opus review/delegation
    QUALITY -> pinned Claude Sonnet 5 + frontier-work (or a stronger model
               already selected by Elie)

  Remaining prompts are classified as EXTRACTION / HEAVY / TRIVIAL / NORMAL.
  HEAVY open-model output is draft material only; Claude must inspect and
  verify it before use. The hook fails open and never blocks a prompt.
#>

$ErrorActionPreference = 'Stop'

# Resource discipline: the deterministic gates below are microseconds; only
# the optional classifier model costs anything (llama3.2:3b ~2 GB resident).
# Preferred topology: the MAIN SERVER hosts the classifier once and clients
# point CLAUDE_ROUTER_OLLAMA_URL at it over Tailscale (bootstrap -OllamaHub),
# so the 2 GB lives on one box instead of every PC.
#   CLAUDE_ROUTER_DISABLE_LLM_CLASSIFIER=1  -> gates only, zero model cost
#   CLAUDE_ROUTER_CLASSIFIER_KEEPALIVE      -> residency after a call. Only
#     sent to a LOCAL hub (default 2m). Against a shared/remote hub nothing
#     is sent unless explicitly set, so clients can't shorten the server's
#     own OLLAMA_KEEP_ALIVE residency policy for everyone else.
# CLAUDE_ROUTER_OLLAMA_URL may be a comma-separated failover chain (shared with
# ollama_route.py). The classifier is an advisory single call, so take the FIRST
# (highest-priority) entry -- interpolating the whole list built an invalid URI
# like http://a,http://b/api/generate and silently failed open (Codex 2026-07-24).
$OllamaBase = if ($env:CLAUDE_ROUTER_OLLAMA_URL) { ($env:CLAUDE_ROUTER_OLLAMA_URL -split ',')[0].Trim().TrimEnd('/') } else { 'http://localhost:11434' }
$OllamaUrl  = "$OllamaBase/api/generate"
# CLAUDE_ROUTER_CLASSIFIER_MODEL: swap to llama3.2:1b (~1.3 GB vs ~3.1 GB) on
# VRAM-constrained hubs -- the money/STAKES gate is deterministic regex before
# the model, so a smaller classifier only affects advisory HEAVY/TRIVIAL hints.
$Model      = if ($env:CLAUDE_ROUTER_CLASSIFIER_MODEL) { $env:CLAUDE_ROUTER_CLASSIFIER_MODEL } else { 'llama3.2:3b' }
# num_ctx cap: the classify prompt is <1k tokens; loading at the model's full
# 8k context wastes ~0.7 GB of KV-cache VRAM on the hub for nothing.
$CtxLen     = if ($env:CLAUDE_ROUTER_CLASSIFIER_CTX) { [int]$env:CLAUDE_ROUTER_CLASSIFIER_CTX } else { 2048 }
$TimeoutSec = 3
$IsLocalHub = $OllamaBase -match '^https?://(localhost|127\.0\.0\.1)'
$KeepAlive  = if ($env:CLAUDE_ROUTER_CLASSIFIER_KEEPALIVE) { $env:CLAUDE_ROUTER_CLASSIFIER_KEEPALIVE }
              elseif ($IsLocalHub) { '2m' } else { $null }
$ModelFor   = @{ STAKES = 'opus'; QUALITY = 'claude-opus-5'; EXTRACTION = 'claude-sonnet-5'; TRIVIAL = 'haiku' }

function Write-EngineStatus([string]$model) {
    try {
        $engine = if ($OllamaBase -match 'ollama\.com') { 'cloud' } else { 'local' }
        $statusDir = Join-Path $env:USERPROFILE '.claude'
        if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Path $statusDir -Force | Out-Null }
        @{
            ts     = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            engine = $engine
            model  = $model
            role   = 'classify'
            source = 'hook'
        } | ConvertTo-Json | Set-Content -Path (Join-Path $statusDir '.routing-status.json') -Encoding utf8
    } catch { }
}

function Write-Hint([string]$verdict) {
    if ($verdict -eq 'NORMAL') { return }

    if ($verdict -eq 'QUALITY') {
        Write-Output ("ROUTING HINT (Model Routing Policy v5.1): explicit quality intent detected. " +
            "Keep this work on the pinned claude-opus-5 model at high effort, use xhigh for the " +
            "hardest bounded pass when supported, and invoke the frontier-work skill. If Elie " +
            "already selected Opus or Fable, do not demote it. Do not report completion until the " +
            "acceptance checks and important failure paths are verified.")
        return
    }

    if ($verdict -eq 'HEAVY') {
        Write-Output ("ROUTING HINT (Model Routing Policy v5.1): HEAVY non-stakes work may use " +
            "the Ollama bridge as draft-only assistance. Prefer --route mid-tier (GLM 5.2, the " +
            "tier between Sonnet and Opus) for bulk reasoning, drafting, and summarising; use " +
            "--route heavy-code or --route heavy-reason for the specialist open models. Run " +
            "python `"$env:USERPROFILE\.claude\tools\ollama_route.py`" with the chosen route, then " +
            "have Claude Sonnet 5 inspect, integrate, and verify the result. Never send money, " +
            "pricing, invoice, legal, private customer data, or final customer-facing text to " +
            "that tier.")
        return
    }

    $model = $ModelFor[$verdict]
    if (-not $model) { return }
    Write-Output ("ROUTING HINT (Model Routing Policy v5.1): this message classified $verdict -> " +
        "use model `"$model`" for the substantive work. Improve context and verification before " +
        "escalating solely for quality. If that tier fails verification or the stakes justify it, " +
        "escalate one tier. A manual model choice by Elie always overrides this hint.")
}

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }
    $prompt = [string]($raw | ConvertFrom-Json).prompt
    if ([string]::IsNullOrWhiteSpace($prompt)) { exit 0 }

    # Financial, legal, tax, irreversible, and customer-facing stakes always
    # outrank quality intent. Over-escalation is the safe direction here.
    $stakesRegex = '(?i)(\$\s?\d|\brefund|\binvoice|\bprice|\bpricing|\bquote\b|\bcharge\b|\bpayment|' +
                   '\bdeposit|\bdiscount|\bAUD\b|\bGST\b|\bBAS\b|\bowe\b|\boverdue|\bdebtor|\bbilling|' +
                   '\bcontract\b|\blegal\b|\btax\b)'
    if ($prompt -match $stakesRegex) { Write-Hint 'STAKES'; exit 0 }

    # Elie's explicit quality phrases bypass the quota-saving HEAVY route.
    $qualityRegex = '(?i)(\btake (your )?time\b|\bbe (more )?serious\b|\bdo (this|it) perfectly\b|' +
                    '\bbest possible\b|\bdeep (work|audit|review|analysis)\b|\bthorough(ly)?\b|' +
                    '\bdo not stop until\b|\bdon''t stop until\b|\buntil (it is |it''s )?verified\b|' +
                    '\bact,? think,? (and )?(reason|ressom) like fable\b)'
    if ($prompt -match $qualityRegex) { Write-Hint 'QUALITY'; exit 0 }

    # Cheap fast paths: no LLM call for prompts too short to need routing,
    # and none at all when the classifier is disabled by env.
    if ($prompt.Trim().Length -lt 24) { exit 0 }
    if ($env:CLAUDE_ROUTER_DISABLE_LLM_CLASSIFIER -eq '1') { exit 0 }

    $instructions = @'
You are a strict routing classifier. Read the USER MESSAGE and reply with EXACTLY ONE WORD from this set: STAKES EXTRACTION HEAVY TRIVIAL NORMAL. No explanation, punctuation, or other text.

STAKES = money, prices, quotes, invoices, refunds, charges, payments, discounts; legal/tax/compliance; irreversible or final customer-facing content; complex architecture.
EXTRACTION = pull structured data out of unstructured text; parsing, not deciding or acting.
HEAVY = large NON-stakes coding, refactors, long reasoning, or bulk summarising where an open model can prepare a draft and there is no money/customer/legal element.
TRIVIAL = mechanical low-stakes work: reformatting, renaming, a one-line lookup, or a quick fact with no consequential impact.
NORMAL = everything else. Use NORMAL when none of the above clearly applies.

Examples:
refund the customer $50 => STAKES
pull the invoice number and due date from this email => EXTRACTION
refactor this 600-line module for readability => HEAVY
rename these variables to camelCase => TRIVIAL
plan next week's content => NORMAL

USER MESSAGE:
'@
    $fullPrompt = $instructions + "`n" + $prompt + "`n=> "
    $bodyMap = @{
        model   = $Model
        prompt  = $fullPrompt
        stream  = $false
        options = @{ temperature = 0; seed = 42; top_k = 1; top_p = 1; num_predict = 5; num_ctx = $CtxLen }
    }
    if ($KeepAlive) { $bodyMap.keep_alive = $KeepAlive }
    $body = $bodyMap | ConvertTo-Json -Depth 5

    $resp = Invoke-RestMethod -Uri $OllamaUrl -Method Post -Body $body -ContentType 'application/json' -TimeoutSec $TimeoutSec
    Write-EngineStatus $Model
    $text = ([string]$resp.response).ToUpperInvariant()

    $verdict = 'NORMAL'
    if     ($text -match 'STAKES')     { $verdict = 'STAKES' }
    elseif ($text -match 'EXTRACTION') { $verdict = 'EXTRACTION' }
    elseif ($text -match 'HEAVY')      { $verdict = 'HEAVY' }
    elseif ($text -match 'TRIVIAL')    { $verdict = 'TRIVIAL' }
    elseif ($text -match 'NORMAL')     { $verdict = 'NORMAL' }

    Write-Hint $verdict
    exit 0
}
catch {
    exit 0
}
