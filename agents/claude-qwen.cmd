@echo off
rem Claude Code (real CLI) on the local Qwen3.8-27B (Arc B60, llama-swap, loads on request).
rem Usage: claude-qwen [claude args]. Default preset qwen3.8-27b:code (fast agent turns, no thinking).
rem Deep planning: set QWEN_MODEL=qwen3.8-27b:plan   Balanced: qwen3.8-27b   Huge docs: qwen3.8-27b-long
setlocal
if "%QWEN_MODEL%"=="" set "QWEN_MODEL=qwen3.8-27b:code"
if "%QWEN_BASE%"=="" set "QWEN_BASE=http://127.0.0.1:8090"
set "CLAUDE_BIN="
if exist "%USERPROFILE%\.local\bin\claude.exe" set "CLAUDE_BIN=%USERPROFILE%\.local\bin\claude.exe"
if not defined CLAUDE_BIN for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-ChildItem \"$env:USERPROFILE\AppData\Roaming\Claude\claude-code\" -Recurse -Force -Filter claude.exe -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName"`) do set "CLAUDE_BIN=%%p"
if not defined CLAUDE_BIN ( echo Claude Code not found. Install it: powershell -c "irm https://claude.ai/install.ps1 ^| iex" & exit /b 2 )
if "%LOCAL_QWEN_KEY%"=="" for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY','User')"`) do set "LOCAL_QWEN_KEY=%%k"
set "ANTHROPIC_BASE_URL=%QWEN_BASE%"
set "ANTHROPIC_AUTH_TOKEN=%LOCAL_QWEN_KEY%"
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_MODEL=%QWEN_MODEL%"
set "ANTHROPIC_DEFAULT_OPUS_MODEL=%QWEN_MODEL%"
set "ANTHROPIC_DEFAULT_SONNET_MODEL=%QWEN_MODEL%"
set "ANTHROPIC_DEFAULT_HAIKU_MODEL=%QWEN_MODEL%"
set "CLAUDE_CODE_SUBAGENT_MODEL=%QWEN_MODEL%"
rem Live context window from the governor (loaded ctx or expected ctx, minus 8k headroom)
set "QWEN_WIN=50000"
set "WINARG="
if /i "%QWEN_MODEL%"=="qwen3.8-27b-long" set "WINARG=long"
for /f "usebackq delims=" %%w in (`powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\qwen.ps1 window %WINARG%`) do set "QWEN_WIN=%%w"
if "%QWEN_CLIENT_CAP%"=="" set "QWEN_CLIENT_CAP=32768"
if %QWEN_WIN% GTR %QWEN_CLIENT_CAP% set "QWEN_WIN=%QWEN_CLIENT_CAP%"
if /i "%QWEN_MODEL%"=="qwen3.8-27b-big" set "QWEN_WIN=120000"
set "CLAUDE_CODE_MAX_CONTEXT_TOKENS=%QWEN_WIN%"
rem Efficient sessions: 8k output reserve (more room before auto-compact), capped tool output
set "CLAUDE_CODE_MAX_OUTPUT_TOKENS=8000"
set "BASH_MAX_OUTPUT_LENGTH=15000"
set "MAX_MCP_OUTPUT_TOKENS=8000"
set "CLAUDE_CODE_ATTRIBUTION_HEADER=0"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"
set "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1"
set "API_TIMEOUT_MS=900000"
rem Auto-compact near the live window (override: set QWEN_COMPACT=40000)
if "%QWEN_COMPACT%"=="" set "QWEN_COMPACT=%QWEN_WIN%"
set "CLAUDE_CODE_AUTO_COMPACT_WINDOW=%QWEN_COMPACT%"
rem Browser tools (playwright) are opt-in: set QWEN_BROWSER=1
set "MCPFILE=C:\AI\claude-local\mcp.json"
if "%QWEN_BROWSER%"=="1" set "MCPFILE=C:\AI\claude-local\mcp-browser.json"
rem DEFAULT = FAST mode: full core toolset (Bash Read Edit Write Glob Grep WebFetch Agent TodoWrite + context7) with a compact local system prompt instead of Claude Code's ~19k-token one.
rem   set QWEN_FULL=1   standard Claude Code prompt (lean config dir, hooks/skills discovery)
if "%QWEN_FULL%"=="1" goto full
set "CLAUDE_CONFIG_DIR=C:\AI\claude-local"
"%CLAUDE_BIN%" --model %QWEN_MODEL% --system-prompt-file C:\AI\claude-local\LOCAL-SYSTEM.md --tools "Bash,Read,Edit,Write,Glob,Grep,WebFetch,Agent,TodoWrite" --mcp-config "%MCPFILE%" --strict-mcp-config %*
goto done
:full
set "CLAUDE_CONFIG_DIR=C:\AI\claude-local"
"%CLAUDE_BIN%" --model %QWEN_MODEL% --mcp-config "%MCPFILE%" --disallowedTools WebSearch %*
:done
endlocal
