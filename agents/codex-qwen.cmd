@echo off
rem Codex CLI on the local Qwen3.8-27B (Arc B60). Live context window from the governor; compacts early to stay fast.
rem Usage: codex-qwen [codex args]      Override compaction point: set QWEN_COMPACT=120000
setlocal
rem Codex Windows sandbox cannot grant itself access to C:\Temp (admin-owned) - use the per-user temp folder
set "TEMP=%LOCALAPPDATA%\Temp"
set "TMP=%LOCALAPPDATA%\Temp"
if "%LOCAL_QWEN_KEY%"=="" for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY','User')"`) do set "LOCAL_QWEN_KEY=%%k"
set "QWEN_WIN=100000"
for /f "usebackq delims=" %%w in (`powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\qwen.ps1 window`) do set "QWEN_WIN=%%w"
if "%QWEN_CLIENT_CAP%"=="" set "QWEN_CLIENT_CAP=32768"
if %QWEN_WIN% GTR %QWEN_CLIENT_CAP% set "QWEN_WIN=%QWEN_CLIENT_CAP%"
if "%QWEN_COMPACT%"=="" set "QWEN_COMPACT=200000"
set /a QWEN_CAP=QWEN_WIN*85/100
if %QWEN_COMPACT% GTR %QWEN_CAP% set "QWEN_COMPACT=%QWEN_CAP%"
rem Lean MCP set for the local model: disable any heavy/cloud MCP servers from your main Codex config here, e.g.
rem   -c mcp_servers.<name>.enabled=false
rem Each MCP server configured in your ~/.codex/config.toml adds its tool schemas to EVERY request. Switch off the ones a local
rem model does not need, by name, e.g.:  set "MCPOFF=-c mcp_servers.playwright.enabled=false -c mcp_servers.render.enabled=false"
if not defined MCPOFF set "MCPOFF="
codex --profile qwen -c model_context_window=%QWEN_WIN% -c model_auto_compact_token_limit=%QWEN_COMPACT% %MCPOFF% %*
endlocal
