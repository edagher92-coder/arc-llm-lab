# MCP hub for Open WebUI: mcpo turns stdio MCP servers into OpenAPI tool servers on 127.0.0.1:8100 (loopback only).
# Tools run here on the CPU; only their short descriptions reach the model. Keep the set small (each schema costs context).
$root = 'C:\AI\mcpo'
New-Item -ItemType Directory -Force 'C:\AI\shared' | Out-Null
$keyFile = Join-Path $root 'api-key.txt'
if (-not (Test-Path $keyFile)) {
  $b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  [IO.File]::WriteAllText($keyFile, (($b | ForEach-Object { $_.ToString('x2') }) -join ''))
}
$key = (Get-Content $keyFile -Raw).Trim()
Remove-Item env:DATABASE_URL -ErrorAction SilentlyContinue
# Newest installed Claude Code binary for the "pc" tool server (claude mcp serve); survives app updates.
# The Claude desktop app is an MSIX package: its AppData\Roaming is virtualised, so outside the app the real files live under
# %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming. Search both.
$cached = Join-Path $root 'claude-bin.txt'
$known = if (Test-Path $cached) { (Get-Content $cached -Raw).Trim() } else { '' }
# Fast path: reuse the cached claude.exe unless it vanished (app update); the full recursive search costs seconds.
if (-not ($known -and (Test-Path $known))) {
$roots = @("$env:APPDATA\Claude\claude-code") + @(Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'LocalCache\Roaming\Claude\claude-code' })
$cb = $roots | Where-Object { Test-Path $_ } | ForEach-Object { Get-ChildItem $_ -Recurse -Force -Filter claude.exe -ErrorAction SilentlyContinue } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($cb) { [IO.File]::WriteAllText($cached, $cb.FullName) }
}
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $root
# mcpo 0.0.20 imports streamablehttp_client, which the mcp 2.x SDK renamed - pin the 1.x SDK.
# A persistent venv (C:\AI\mcpo\.venv) skips uvx's ~30 s package resolution on every start; uvx stays as the fallback.
$mcpo = Join-Path $root '.venv\Scripts\mcpo.exe'
if (Test-Path $mcpo) { $exe = $mcpo; $pre = @() } else { $exe = 'C:\Users\you\.local\bin\uvx.exe'; $pre = @('--python', '3.11', '--with', 'mcp<2', 'mcpo==0.0.20') }
& $exe @pre --host 127.0.0.1 --port 8100 --api-key $key --config (Join-Path $root 'config.json') 2>&1 |
  ForEach-Object { "$_" } | Out-File -FilePath (Join-Path $root 'mcpo.log') -Append -Encoding utf8
