# Vendored Intel FA prefill patches

These two commits add Intel's flash-attention **prefill** shader to the llama.cpp Vulkan backend. They are the reason prompt reading at 32K context goes from 118 to 420 tok/s on an Arc Pro B60 (see [docs/INTEL-FA.md](../../docs/INTEL-FA.md)).

| File | Upstream commit | Subject |
|---|---|---|
| `0001-vulkan-Intel-customized-FA-shader-for-prefill-usage.patch` | `61cc4c25a6878bfcff2d2d76870ba1948ee0f3e2` | vulkan : Intel customized FA shader for prefill usage |
| `0002-vulkan-adding-check-of-max_bias-logit_softcap-for-In.patch` | `1a5137a44fe7b2c921fe6b5f7d62704226bac599` | vulkan : adding check of max_bias/logit_softcap for Intel FA kernel path |

## Why they are vendored

The commits come from llama.cpp [PR #29357](https://github.com/ggml-org/llama.cpp/pull/29357) (branch `intel/fa-prefill` in `sliu39/llama.cpp`). The author closed that PR without merging on 2026-09-25 and the branch has since been force-pushed, so a build that fetches the branch can break. Keeping the two patches here makes the build reproducible whatever happens to the branch.

## Provenance and licence

- **Author:** Russell Liu (Intel), GitHub [@sliu39](https://github.com/sliu39). The author lines in each patch are unchanged, so `git am` preserves attribution.
- **Licence:** llama.cpp is MIT licensed (Copyright (c) 2023-2026 The ggml authors), and these patches are contributions to it. The MIT licence text is in the [llama.cpp repository](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE). Credit for the kernel belongs to its author; this repository only redistributes the patch files so the build stays reproducible.
- **How these files were produced:** the two commit objects were fetched from `sliu39/llama.cpp` by SHA and written out with `git format-patch -2 --no-signature --no-stat`. The `From <sha>` line at the top of each file is the original commit id, so you can compare against the upstream commits yourself.
- **Applies cleanly to:** llama.cpp tag `b11524` (commit `86a283532072722c5f3363d37d59a874d09fa99b`), with both `git am` and `git apply`. This was checked on 2026-10-10.
- **Checksums:** [SHA256SUMS](SHA256SUMS). Verify with `sha256sum -c SHA256SUMS` (Linux, macOS) or `Get-FileHash -Algorithm SHA256` (PowerShell). [../build.ps1](../build.ps1) verifies them before applying.

## Apply by hand

```bash
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
git checkout b11524
git am /path/to/arc-llm-lab/engine/patches/0001-*.patch /path/to/arc-llm-lab/engine/patches/0002-*.patch
```

If `git am` complains about identity, add `-c user.name=x -c user.email=x@x` after `git`.

## If the upstream status changes

Intel's separate decode-focused Xe flash-attention kernels (PR #24406) are already merged upstream. This prefill shader is not. When it, or an equivalent, is merged into mainline llama.cpp, use an official release and drop this directory.
