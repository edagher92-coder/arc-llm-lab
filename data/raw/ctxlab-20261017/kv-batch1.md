# bench-kv batch 1  2026-10-17T16:08:48
baseline: ["16:08:48 GPU-exclusive begin: mode OFF + unload","16:08:56 baseline VRAM: {\"adapter_dedicated_gib\":2.42,\"free_gib\":21.46,\"dwm_dedicated_gib\":5.37}",{"adapter_dedicated_gib":2.42,"free_gib":21.46,"dwm_dedicated_gib":5.37}]

## ctk=f16 ctv=f16 d=0 r=3
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Arc(TM) Pro B60 Graphics (Intel Corporation) | uma: 0 | fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_ubatch |  fa |         lm |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | -------: | --: | ---------: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |           pp512 |       484.53 ± 19.30 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |            tg32 |         13.01 ± 0.19 |

build: c85e6c598 (11526)
elapsed 28 s

## ctk=f16 ctv=f16 d=16384,32768 r=1
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Arc(TM) Pro B60 Graphics (Intel Corporation) | uma: 0 | fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_ubatch |  fa |         lm |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | -------: | --: | ---------: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |  pp512 @ d16384 |        378.60 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |   tg32 @ d16384 |         14.39 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |  pp512 @ d32768 |        354.27 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   1 |        dio |   tg32 @ d32768 |         12.69 ± 0.00 |

build: c85e6c598 (11526)
elapsed 134 s

## ctk=q8_0 ctv=q8_0 d=0 r=3
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Arc(TM) Pro B60 Graphics (Intel Corporation) | uma: 0 | fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_ubatch | type_k | type_v |  fa |         lm |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | -------: | -----: | -----: | --: | ---------: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |           pp512 |        587.56 ± 5.70 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |            tg32 |         15.68 ± 0.17 |

build: c85e6c598 (11526)
elapsed 24 s

## ctk=q8_0 ctv=q8_0 d=16384 r=1
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Arc(TM) Pro B60 Graphics (Intel Corporation) | uma: 0 | fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_ubatch | type_k | type_v |  fa |         lm |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | -------: | -----: | -----: | --: | ---------: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |  pp512 @ d16384 |        197.66 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  16.23 GiB |    27.32 B | Vulkan     |  99 |      256 |   q8_0 |   q8_0 |   1 |        dio |   tg32 @ d16384 |         11.53 ± 0.00 |

build: c85e6c598 (11526)
elapsed 75 s

DONE 2026-10-17T16:13:47
