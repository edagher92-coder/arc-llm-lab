@echo off
rem Codex CLI on the local Qwen3.8-27B (ELZYDLAB Arc B60). Live context window from the governor; compacts early to stay fast.
rem Usage: codex-qwen [codex args]      Override compaction point: set QWEN_COMPACT=120000
setlocal
rem Codex Windows sandbox cannot grant itself access to C:\Temp (admin-owned) - use the per-user temp folder
set "TEMP=%LOCALAPPDATA%\Temp"
set "TMP=%LOCALAPPDATA%\Temp"
if "%LOCAL_QWEN_KEY%"=="" for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY','User')"`) do set "LOCAL_QWEN_KEY=%%k"
set "QWEN_WIN=100000"
for /f "usebackq delims=" %%w in (`powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\qwen.ps1 window`) do set "QWEN_WIN=%%w"
if "%QWEN_CLIENT_CAP%"=="" set "QWEN_CLIENT_CAP=65536"
if %QWEN_WIN% GTR %QWEN_CLIENT_CAP% set "QWEN_WIN=%QWEN_CLIENT_CAP%"
if "%QWEN_COMPACT%"=="" set "QWEN_COMPACT=200000"
set /a QWEN_CAP=QWEN_WIN*90/100
if %QWEN_COMPACT% GTR %QWEN_CAP% set "QWEN_COMPACT=%QWEN_CAP%"
rem Lean MCP set for the local model: keep context7; cloud/heavy servers off (playwright on with QWEN_BROWSER=1)
set "MCPOFF=-c mcp_servers.render.enabled=false -c mcp_servers.openaiDeveloperDocs.enabled=false -c mcp_servers.headroom.enabled=false -c mcp_servers.node_repl.enabled=false"
if not "%QWEN_BROWSER%"=="1" set "MCPOFF=%MCPOFF% -c mcp_servers.local-ai-playwright.enabled=false"
codex --profile qwen -c model_context_window=%QWEN_WIN% -c model_auto_compact_token_limit=%QWEN_COMPACT% %MCPOFF% %*
endlocal





rem (18 Oct 2026) Superseded by codex-qwen (lean). Kept for MCP-heavy sessions.
