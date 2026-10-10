# Build llama.cpp with Intel's long-context FA prefill patches (PR #29357) - Visual Studio route

Prefer no admin / no Visual Studio? Run `engine\build.ps1` instead (portable toolchain). This page is the classic route.

The two Intel commits are **vendored** in [patches/](patches/) (with SHA-256 checksums and attribution), because the upstream PR was closed unmerged on 2026-09-25 and its branch has since been force-pushed. The steps below apply the vendored files; fetching the branch is only a fallback. On Linux, see [build-linux.sh](build-linux.sh).

Unreleased code: your current engine (C:\AI\llama.cpp\vulkan) is NOT touched. The new build goes to
C:\AI\llama.cpp\vulkan-intelfa and only becomes live if you run `qwen engine intelfa`.

## 1. Install the build tools (once, ~7 GB, approve the UAC prompts)
Open PowerShell and run:
```
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
winget install --id Kitware.CMake -e
winget install --id KhronosGroup.VulkanSDK -e
```
Then sign out and back in (so PATH and VULKAN_SDK are set).

## 2. Build (~30-40 min)
Open **"x64 Native Tools Command Prompt for VS 2022"** (Start menu) and run:
```
mkdir C:\build & cd /d C:\build
git clone https://github.com/ggml-org/llama.cpp.git llama-intelfa
cd llama-intelfa
git checkout b11524
git -c user.name=x -c user.email=x@x am <path-to-this-repo>\engine\patches\0001-vulkan-Intel-customized-FA-shader-for-prefill-usage.patch <path-to-this-repo>\engine\patches\0002-vulkan-adding-check-of-max_bias-logit_softcap-for-In.patch
cmake -B build -DGGML_VULKAN=ON -DLLAMA_CURL=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF
cmake --build build --config Release -j 16 --target llama-server llama-bench
```
Optional check first: `Get-FileHash -Algorithm SHA256 <path-to-this-repo>\engine\patches\*.patch` should match `SHA256SUMS`.

Fallback if the patch files are unavailable (the branch may have been rewritten, so this can fail):
```
git fetch https://github.com/sliu39/llama.cpp.git intel/fa-prefill
git cherry-pick 61cc4c25a6878bfcff2d2d76870ba1948ee0f3e2 1a5137a44fe7b2c921fe6b5f7d62704226bac599
```
Check the configure output says `GL_KHR_cooperative_matrix supported by glslc` and `GL_EXT_integer_dot_product supported by glslc`.

## 3. Install side-by-side
```
mkdir C:\AI\llama.cpp\vulkan-intelfa
xcopy /y build\bin\Release\* C:\AI\llama.cpp\vulkan-intelfa\
```

## 4. Compare (unloads the model for ~15 min, then restores AUTO)
```
powershell -ExecutionPolicy Bypass -File bench\compare-f16.ps1
```
Results: bench\compare-f16.txt (prompt reading and generation at 0 / 16k / 32k tokens deep, both engines).

## 5. Switch (only if faster) and back
```
qwen engine intelfa     use the new build
qwen engine stock       back to the official b11524
```
Then ask Claude to run the coding/tool-calling quality check before relying on it.
