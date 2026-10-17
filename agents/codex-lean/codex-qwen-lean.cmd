@echo off
rem codex-qwen-lean: Codex on the local Qwen with the lean CODEX_HOME (3K-token base prompt instead of 12K).
rem Window = live server ctx - 8K (qwen window), auto-compact at 75% of it. Nothing in %USERPROFILE%\.codex is touched.
setlocal
rem Codex Windows sandbox cannot grant itself access to C:\Temp (admin-owned) - use the per-user temp folder
set "TEMP=%LOCALAPPDATA%\Temp"
set "TMP=%LOCALAPPDATA%\Temp"
set "CODEX_HOME=C:\AI\codex-local\home"
for /f %%w in ('powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\governor\qwen.ps1 window') do set "WIN=%%w"
if not defined WIN set "WIN=24576"
set /a "COMPACT=WIN*3/4"
codex -c model_context_window=%WIN% -c model_auto_compact_token_limit=%COMPACT% %*
endlocal
