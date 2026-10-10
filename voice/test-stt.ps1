Add-Type -AssemblyName System.Speech
$f = 'C:\AI\whisper\test.wav'
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($f, $fmt)
$s.Speak('Hi Qwen, how many ice machines do we have available for hire this weekend in Riverside?')
$s.Dispose()
$sw = [Diagnostics.Stopwatch]::StartNew()
$r = & curl.exe -s -F "file=@$f" -F response_format=json -F temperature=0 http://127.0.0.1:8091/inference
$sw.Stop()
"local whisper: {0:N1} s -> {1}" -f $sw.Elapsed.TotalSeconds, $r
