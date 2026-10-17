# bench-kv batch 2  2026-10-17T16:38:41
baseline: ["16:38:41 GPU-exclusive begin: mode OFF + unload","16:38:49 baseline VRAM: {\"adapter_dedicated_gib\":1.8,\"free_gib\":22.08,\"dwm_dedicated_gib\":5.32}",{"adapter_dedicated_gib":1.8,"free_gib":22.08,"dwm_dedicated_gib":5.32}]

## ctk=q8_0 ctv=q8_0 d=32768 r=1
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Arc(TM) Pro B60 Graphics (Intel Corporation) | uma: 0 | fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_ubatch | type_k | type_v |  fa |         lm |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | -------: | -----: | -----: | --: | ---------: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |  pp512 @ d32768 |        122.83 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |   tg32 @ d32768 |          9.51 ± 0.00 |

build: c85e6c598 (11526)
elapsed 181 s

DONE 2026-10-17T16:42:21
