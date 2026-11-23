# kimi-code.ps1 -- launch Claude Code backed by a Kimi model via Ollama's
# Anthropic-compatible API (Ollama >= 0.14). Windows twin of kimi-code.sh.
#
#   .\kimi-code.ps1                    # best available Kimi (prefers kimi-k3*)
#   .\kimi-code.ps1 kimi-k2.5:cloud    # explicit tag
#   .\kimi-code.ps1 -List              # show Kimi tags the daemon can see
#
# Works identically on the laptop and the server PC: both daemons are signed
# in to ollama.com, so :cloud tags proxy to Ollama Cloud (flat rate, zero
# Claude quota). A laptop WITHOUT a local daemon can point at the server hub:
#   $env:CLAUDE_KIMI_OLLAMA_URL = 'http://elzydlab.tail76b098.ts.net:11434'
#
# NUMBERS RULE (non-negotiable): a Kimi-backed session is for heavy NON-stakes
# work only -- bulk coding, refactors, drafts, research. Customer prices,
# quotes, invoices, legal content stay in a real Claude session.
param(
    [string]$Model = "",
    [switch]$List
)
$ErrorActionPreference = "Stop"

$Base = if ($env:CLAUDE_KIMI_OLLAMA_URL) { $env:CLAUDE_KIMI_OLLAMA_URL.TrimEnd('/') } else { 'http://localhost:11434' }
$Fallback = 'kimi-k2.7-code:cloud'

try {
    Invoke-RestMethod -Uri "$Base/api/version" -TimeoutSec 5 | Out-Null
} catch {
    Write-Error "no Ollama daemon at $Base -- start Ollama (>= 0.14) first. Cloud tags need the daemon signed in to ollama.com (or OLLAMA_API_KEY set)."
    exit 1
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "'claude' CLI not on PATH."
    exit 1
}

function Get-KimiTags {
    try {
        (Invoke-RestMethod -Uri "$Base/api/tags" -TimeoutSec 10).models |
            Where-Object { $_.name -match 'kimi' } | ForEach-Object { $_.name }
    } catch { @() }
}

if ($List) { Get-KimiTags; exit 0 }

if (-not $Model) {
    # Prefer K3 the moment it exists (expected on Ollama Cloud ~2026-07-27);
    # otherwise the current bench code specialist.
    $k3 = Get-KimiTags | Where-Object { $_ -match 'kimi-k3' } | Select-Object -First 1
    $Model = if ($k3) { $k3 } else { $Fallback }
}

Write-Host "[kimi-code] Claude Code -> $Model via $Base (zero Claude quota)"
Write-Host "[kimi-code] NUMBERS RULE: non-stakes work only -- no customer prices/quotes/invoices/legal."

$env:ANTHROPIC_BASE_URL = $Base
$env:ANTHROPIC_AUTH_TOKEN = 'ollama'
& claude --model $Model
exit $LASTEXITCODE
