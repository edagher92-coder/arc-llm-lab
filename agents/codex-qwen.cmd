@echo off
rem codex-qwen: THE Codex harness for the local Qwen3.8-27B on ELZYDLAB (locked in 18 Oct 2026).
rem Lean CODEX_HOME (C:\AI\codex-local\home): ~3K-token base prompt instead of ~16K, no plugins/MCP/global AGENTS.md.
rem Preflight takes the shared job lock (C:\AI\locks\qwen-engine.lock) so only one Qwen job runs at a time,
rem waits while the slot is busy, then sizes the window from the live server. The lock is released on exit.
rem Usage: codex-qwen [codex args]     Old heavy setup (your ~/.codex + MCP): codex-qwen-full
rem Knobs: QWEN_NOWAIT=1 (skip waits, no lock), QWEN_WAIT_S=600, QWEN_COMPACT=<tokens> (compaction point override)
setlocal
set "CODEX_HOME=C:\AI\codex-local\home"
rem Codex's Windows sandbox cannot grant itself access to C:\Temp (admin-owned) - use the per-user temp folder
set "TEMP=%LOCALAPPDATA%\Temp"
set "TMP=%LOCALAPPDATA%\Temp"
if "%LOCAL_QWEN_KEY%"=="" for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('LOCAL_QWEN_KEY','User')"`) do set "LOCAL_QWEN_KEY=%%k"
set "WIN="
set "LOCKPID=0"
for /f "usebackq tokens=1,2" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\codex-local\preflight.ps1`) do (
  set "WIN=%%a"
  set "LOCKPID=%%b"
)
if not defined WIN set "WIN=24576"
set /a "COMPACT=WIN*9/10"
set "CAP=%QWEN_COMPACT%"
if not defined CAP set "CAP=999999"
if %CAP% LSS %COMPACT% set "COMPACT=%CAP%"
rem Git: no global identity is set on this PC, so label commits made from Codex-on-Qwen instead of letting the model
rem invent one. Unattended "exec" runs cannot ask for approval, and Codex's sandbox keeps .git read-only, so for exec
rem only the current repo's .git is made writable (branches/commits work). Interactive sessions keep Codex's protection
rem and ask you before git writes. QWEN_GIT_WRITE=0 turns the exec exception off.
if not defined GIT_AUTHOR_NAME set "GIT_AUTHOR_NAME=Codex (local Qwen)"
if not defined GIT_AUTHOR_EMAIL set "GIT_AUTHOR_EMAIL=codex-qwen@elzydlab.local"
if not defined GIT_COMMITTER_NAME set "GIT_COMMITTER_NAME=%GIT_AUTHOR_NAME%"
if not defined GIT_COMMITTER_EMAIL set "GIT_COMMITTER_EMAIL=%GIT_AUTHOR_EMAIL%"
set "GITDIR="
set "GITW="
if /i "%~1"=="exec" if not "%QWEN_GIT_WRITE%"=="0" for /f "usebackq delims=" %%g in (`git rev-parse --absolute-git-dir 2^>nul`) do set "GITDIR=%%g"
rem git prints C:/x/.git; pass the native C:\x\.git form to the Windows sandbox
if defined GITDIR set "GITDIR=%GITDIR:/=\%"
if defined GITDIR set "GITW=-c sandbox_workspace_write.writable_roots=['%GITDIR%']"
rem For exec, overrides must come AFTER the subcommand: a root-level -c sandbox_workspace_write override is ignored
rem when exec gets -s (VERIFIED 18 Oct: root placement -> .git still denied; after "exec" -> branch created).
if /i not "%~1"=="exec" goto :interactive
set "REST=%*"
call set "REST=%%REST:*exec=%%"
codex exec -c model_context_window=%WIN% -c model_auto_compact_token_limit=%COMPACT% %GITW% %REST%
set "RC=%ERRORLEVEL%"
goto :release
:interactive
codex -c model_context_window=%WIN% -c model_auto_compact_token_limit=%COMPACT% %*
set "RC=%ERRORLEVEL%"
:release
if not "%LOCKPID%"=="0" powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\locks\qwen-lock.ps1 release -HolderPid %LOCKPID% >nul 2>&1
endlocal & exit /b %RC%
