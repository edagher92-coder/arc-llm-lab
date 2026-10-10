# Raw logs

Unedited output from the machine this repo was developed on (Windows 11, Arc Pro B60 24GB), kept so you can check the numbers in the docs. They are stored byte for byte, so most files have Windows (CRLF) line endings, and `build.log` also contains bare CR characters. Paths such as `C:/AI/...` are from that machine. [.gitattributes](../../.gitattributes) stops Git converting them.

If a number in a document points here, the line it comes from is in one of these files. If it has no file, it is listed under "Not retained" below.

| File | What it is | Produced by | Used for |
|---|---|---|---|
| [compare-f16.txt](compare-f16.txt) | `llama-bench` on stock b11524 and the Intel FA build, f16 KV, depths 0, 16K and 32K (`pp8`, `pp2048`, `tg32`) | [bench/compare-f16.ps1](../../bench/compare-f16.ps1) | The 118 versus 420 tok/s prompt speed at 32K, and the 16.0 tok/s `tg32` figure (no drafter) |
| [compare-q4.txt](compare-q4.txt) | The same comparison with a q4_0 KV cache (identical on both engines) | [bench/compare-q4.ps1](../../bench/compare-q4.ps1) | Why the main KV cache stays f16 |
| [server-test.txt](server-test.txt) | JSON lines from the agent-style test: cold 29,679-token read (61.0 s), three turns (54.9 s total), 7/7 coding and 3/3 tool checks, a 21,493-token cold read and a warm follow-up | [bench/server-test.ps1](../../bench/server-test.ps1) | The 54.9 s first-build figure, the 61 s versus 18 s prefix-reuse example, draft acceptance (573 of 877 tokens) |
| [bench-history.csv](bench-history.csv) | One line per `qwen bench` run | [bench/regression.ps1](../../bench/regression.ps1) | The 52.2 s (61,440 context) and 56.7 s (57,344 context) rows |
| [bench-run-61k.txt](bench-run-61k.txt), [bench-run-64k.txt](bench-run-64k.txt) | Console output of those two `qwen bench` runs. The "64k" file is the tuned configuration, which loaded **57,344** tokens of context (the name is the tuning target, the header line shows the real value) | `qwen bench` | Same as above |
| [tune.txt](tune.txt), [tune-server.log](tune-server.log) | The first tuning sweep: draft length (n=5, 7, 10, 15), `-ub 256` and a q8_0 drafter KV | [bench/tune.ps1](../../bench/tune.ps1) | The 42.3 tok/s coding average (`n7 ub256 dkv-q8`), and the n=15 collapse |
| [tune2.txt](tune2.txt), [tune2-server.log](tune2-server.log) | A follow-up run (`ub512 dkv-q8`) | [bench/tune2.ps1](../../bench/tune2.ps1) | Free-VRAM comparison |
| [server-57344.log](server-57344.log) | llama-server start-up and request log at 57,344 context | llama-server | Flags in effect, the `cache_reuse is not supported by multimodal` line (line 27), memory use |
| [build.log](build.log) | The Intel FA engine build | [engine/build.ps1](../../engine/build.ps1) | Compiler and commit versions, glslc capability lines |
| [governor.log](governor.log) | The governor's launch and decision log for the day | [governor/](../../governor/) | Profile and context choices |
| [config-history/](config-history/) | Copies of `governor/profiles.json` taken before the Intel FA switch and before the 64K tuning | `qwen snapshot` | What changed between configurations |

## Read these before quoting a number

- **`tune.txt`, first row (`n7 ub512 (current)`).** This row is not a valid measurement of that setting. It reports a model size of 7.37 GiB and other programs holding 15.49 GiB of VRAM, so the model was not fully loaded on the GPU when it ran (our reading of the numbers; the 9.27 tok/s chat speed is far below every other row). The comparable `ub512` result is in `tune2.txt`.
- **The "keep 1.1 GiB free" rule of thumb rests on one row.** `n15` left 0.96 GiB free and ran at 27.0 tok/s, but it also changed the draft length. `n5` (1.04 GiB free, 41.4 tok/s) and the `tune2.txt` run (0.71 GiB free, 52.6 s for three turns) did not slow down. The governor keeps a larger margin as a precaution; the real threshold was not isolated.
- **Temperature.** The coding averages in `tune.txt` use temperature 0.2 and seven tasks.
- **`build.log` reports cmake 4.4.3**, while the current `engine/build.ps1` downloads 4.4.4 when no cmake is present. We did not test whether the difference matters.
- **Tuning servers had no API key.** `tune-server.log` and `tune2-server.log` warn that no key was set (they were loopback-only). Production use goes through llama-swap with a key ([SETUP.md](../../docs/SETUP.md)).

## Not retained

These figures appear in the docs without a raw log. Treat them as observations, and expect re-runs.

- **201 s** for the three-turn agent test on stock llama.cpp with the drafter. Observed before logging was in place; the raw log was not retained; a re-run is planned.
- **The SYCL versus Vulkan comparison** behind "Vulkan was faster for this model on our B60".
- **The "6.6K versus 19K token" system-prompt sizes** for Claude Code with and without the compact prompt ([AGENTS.md](../../docs/AGENTS.md)).
- **Where the DFlash2 drafter file was downloaded from.** Only its file name was recorded.

## Add your own

Send results in the community format instead: [data/community/](../community/) and [CONTRIBUTING.md](../../CONTRIBUTING.md).
