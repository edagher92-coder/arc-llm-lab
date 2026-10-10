$log = 'C:\AI\tts\setup.log'; "start $(Get-Date -f s)" | Set-Content $log
function L($m) { "$(Get-Date -f T) $m" | Add-Content $log }
$d = 'C:\AI\tts'; $uv = "$env:USERPROFILE\.local\bin\uv.exe"
Set-Location $d
if (-not (Test-Path "$d\venv\Scripts\python.exe")) { L 'create venv (Python 3.12)'; & $uv venv --python 3.12 "$d\venv" *>> $log }
L 'install kokoro-onnx'; & $uv pip install --python "$d\venv\Scripts\python.exe" kokoro-onnx soundfile numpy *>> $log
foreach ($f in 'kokoro-v1.0.onnx','voices-v1.0.bin') {
  if (-not (Test-Path "$d\$f")) { L "download $f"; Invoke-WebRequest "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f" -OutFile "$d\$f" }
}
L ("files: " + ((Get-ChildItem $d -File | % { "$($_.Name)=$([math]::Round($_.Length/1MB))MB" }) -join ' '))
L 'END'
