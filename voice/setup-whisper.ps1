$log = 'C:\AI\whisper\setup.log'; "start $(Get-Date -f s)" | Set-Content $log
function L($m) { "$(Get-Date -f T) $m" | Add-Content $log }
$d = 'C:\AI\whisper'; New-Item -ItemType Directory -Force "$d\models" | Out-Null
if (-not (Test-Path "$d\bin\whisper-server.exe")) {
  L 'download whisper.cpp b5454 (OpenBLAS CPU build)'
  Invoke-WebRequest 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-blas-bin-x64.zip' -OutFile "$d\whisper.zip"
  Expand-Archive "$d\whisper.zip" "$d\x" -Force
  $srv = Get-ChildItem "$d\x" -Recurse -Filter whisper-server.exe | Select -First 1
  New-Item -ItemType Directory -Force "$d\bin" | Out-Null; Copy-Item "$($srv.DirectoryName)\*" "$d\bin\" -Recurse -Force
}
L ("server: " + (Test-Path "$d\bin\whisper-server.exe"))
$model = "$d\models\ggml-small.en-q5_1.bin"
if (-not (Test-Path $model)) { L 'download model small.en q5_1'; Invoke-WebRequest 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_1.bin' -OutFile $model }
L ("model MB: " + [math]::Round((Get-Item $model).Length/1MB,1))
$act = New-ScheduledTaskAction -Execute 'C:\Windows\System32\conhost.exe' -Argument "--headless `"$d\bin\whisper-server.exe`" --host 127.0.0.1 --port 8091 -m `"$model`" -t 6 -l en"
$trg = @((New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME), (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)))
$set = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
try { Register-ScheduledTask -TaskName 'Local Whisper (voice STT)' -Action $act -Trigger $trg -Settings $set -Force | Out-Null; L 'task registered' } catch { L "task error: $_" }
Start-ScheduledTask 'Local Whisper (voice STT)' -EA SilentlyContinue; Start-Sleep 8
L ("listening 8091: " + [bool](Get-NetTCPConnection -LocalPort 8091 -State Listen -EA SilentlyContinue))
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
& $ts serve --bg --https=8445 --set-path=/stt http://127.0.0.1:8091 2>&1 | % { L "ts: $_" }
L 'END'
