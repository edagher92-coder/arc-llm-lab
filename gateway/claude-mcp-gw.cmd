@echo off
rem Claude Code's own tools (Bash, Read, Edit, Write, Glob, Grep...) as an MCP server for the local hub.
rem Picks the newest installed claude.exe (fast, no PowerShell) so app updates don't break it. Runs in C:\AI\workspace.
setlocal EnableDelayedExpansion
rem The MCP SDK starts servers with a minimal environment; restore the user profile so Claude Code finds its config and skills.
if not defined COMSPEC set "COMSPEC=C:\Windows\System32\cmd.exe"
if not defined SystemRoot set "SystemRoot=C:\Windows"
if not defined USERPROFILE set "USERPROFILE=C:\Users\you"
if not defined APPDATA set "APPDATA=C:\Users\you\AppData\Roaming"
if not defined LOCALAPPDATA set "LOCALAPPDATA=C:\Users\you\AppData\Local"
if not defined HOMEDRIVE set "HOMEDRIVE=C:"
if not defined HOMEPATH set "HOMEPATH=\Users\you"
set "HOME=%USERPROFILE%"
set "BASE=%APPDATA%\Claude\claude-code"
rem start-mcpo.ps1 resolves the newest claude.exe at hub start and writes its path here.
set "CLAUDE_BIN="
if exist "C:\AI\mcpo\claude-bin.txt" set /p CLAUDE_BIN=<"C:\AI\mcpo\claude-bin.txt"
if defined CLAUDE_BIN if not exist "%CLAUDE_BIN%" set "CLAUDE_BIN="
if not defined CLAUDE_BIN ( echo %DATE% %TIME% claude.exe not found under %BASE% >> "C:\AI\gateway\state\pc-stderr.log" & exit /b 2 )
if not exist "C:\AI\workspace" mkdir "C:\AI\workspace"
cd /d "C:\AI\workspace"
echo %DATE% %TIME% start bin=%CLAUDE_BIN% >> "C:\AI\gateway\state\pc-stderr.log"
"%CLAUDE_BIN%" mcp serve 2>> "C:\AI\gateway\state\pc-stderr.log"
echo %DATE% %TIME% exit=%ERRORLEVEL% >> "C:\AI\gateway\state\pc-stderr.log"
