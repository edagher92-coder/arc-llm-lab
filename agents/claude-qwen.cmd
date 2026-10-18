@echo off
rem claude-qwen: Claude Code running on the local Qwen3.8-27B (ELZYDLAB Arc B60) through llama-swap's
rem Anthropic-compatible /v1/messages endpoint. --bare keeps the prompt small (no plugins, hooks, connectors,
rem CLAUDE.md auto-discovery). Your normal "claude" command and settings are not changed.
rem Usage: claude-qwen [claude args]     e.g.  claude-qwen      or   claude-qwen -p "explain this repo"
rem Add context explicitly if you want it: --add-dir . (CLAUDE.md), --mcp-config <file>
setlocal
if "%LOCAL_QWEN_KEY%"=="" for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY','User')"`) do set "LOCAL_QWEN_KEY=%%k"
rem One Qwen job at a time: preflight takes C:\AI\locks\qwen-engine.lock (kind claude) and prints "<window> <lockHolderPid>".
set "WIN=" & set "LOCKPID=0"
for /f "usebackq tokens=1,2" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\codex-local\preflight.ps1 -Kind claude`) do (
  set "WIN=%%a"
  set "LOCKPID=%%b"
)
if not defined WIN set "WIN=28672"
set "ANTHROPIC_BASE_URL=http://127.0.0.1:8090"
set "ANTHROPIC_API_KEY=%LOCAL_QWEN_KEY%"
set "ANTHROPIC_AUTH_TOKEN="
set "ANTHROPIC_MODEL=qwen3.8-27b:code"
set "ANTHROPIC_DEFAULT_OPUS_MODEL=qwen3.8-27b:code"
set "ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3.8-27b:code"
set "ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3.8-27b:code"
set "ANTHROPIC_SMALL_FAST_MODEL=qwen3.8-27b:code"
set "CLAUDE_CODE_SUBAGENT_MODEL=qwen3.8-27b:code"
set "CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"
set "API_TIMEOUT_MS=900000"
set "SET_FILE=%LOCALAPPDATA%\Temp\claude-qwen-settings.json"
> "%SET_FILE%" echo {"autoCompactWindow": %WIN%, "autoCompactEnabled": true}
claude --bare --model qwen3.8-27b:code --settings "%SET_FILE%" %*
set "RC=%ERRORLEVEL%"
if not "%LOCKPID%"=="0" powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\locks\qwen-lock.ps1 release -HolderPid %LOCKPID% >nul 2>&1
endlocal & exit /b %RC%
