# Private voice assistant (phone → your PC)

Open [voice/voice.html](../voice/voice.html) from your phone over Tailscale. Everything runs on the PC; nothing goes to a cloud service.

| Piece | What | Where | Speed (Ryzen 7 3700X) |
|---|---|---|---|
| Speech to text | whisper.cpp `small.en-q5_1`, CPU | `:8091`, Tailscale path `/stt` | ~1.8 s per sentence |
| Model | Qwen3.8-27B `:code` preset, streaming | llama-swap `:8090` | first words ~1 s |
| Text to speech | Kokoro-82M ONNX, CPU, 6 voices | `:8092`, Tailscale path `/tts` | ~0.35× real time warm; ~2 s per sentence over the tailnet |

## How it feels fast

- **Sentence-by-sentence speech.** The page speaks each sentence while the model is still writing the next one, with up to two speech requests in flight and back-to-back playback.
- **Interrupt.** Tap the orb while it's talking and it stops immediately.
- **Hands-free mode.** It listens again after each reply and sends after about 1.1 s of silence. Voice-activity detection adapts to the room's noise floor.
- **Fallback.** If `/tts` is unreachable, the page uses the phone's built-in voice, so it still works.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File voice\setup-whisper.ps1
powershell -ExecutionPolicy Bypass -File voice\setup-tts.ps1     # uv venv (Python 3.12), kokoro-onnx, model files
```

Register both as logon tasks through `conhost.exe --headless`. Speech to text: `whisper-server.exe --host 127.0.0.1 --port 8091 -m ggml-small.en-q5_1.bin -t 6 -l en`. Text to speech: the venv's `python.exe voice\tts_server.py`. Then add the tailnet routes, which needs admin once:

```powershell
tailscale serve --bg --https=8445 --set-path=/stt http://127.0.0.1:8091
tailscale serve --bg --https=8445 --set-path=/tts http://127.0.0.1:8092
```

## OpenAI-compatible routes (for Open WebUI and other apps)

[voice/tts_server.py](../voice/tts_server.py) also speaks the OpenAI audio API on `127.0.0.1:8092`, so apps that expect OpenAI-style speech endpoints can use it without changes:

| Route | Does |
|---|---|
| `POST /v1/audio/speech` (also `POST /tts`) | `{"input" or "text", "voice", "speed"}` to a WAV from Kokoro. OpenAI voice names map to the nearest curated voice (alloy to heart, echo to michael, fable to george, onyx to lewis, nova to emma, shimmer to isabella). |
| `POST /v1/audio/transcriptions` | Forwards the request to whisper.cpp (`WHISPER_URL`, default `http://127.0.0.1:8091/inference`) and returns its JSON. Returns 502 if whisper.cpp is not running. |
| `GET /voices` | The six curated voices |

Set the Base URL to `http://127.0.0.1:8092/v1`. The file is a single copy-ready script: it needs only the Kokoro model files from `setup-tts.ps1` and the Python packages that script installs. Step-by-step Open WebUI settings are in [PLATFORM.md](PLATFORM.md#4-voice).

## Personalise

Edit `SYS` (who you are, your units, your business context) and `STT_VOCAB` (names and jargon Whisper should spell correctly) at the top of the script in `voice.html`.
