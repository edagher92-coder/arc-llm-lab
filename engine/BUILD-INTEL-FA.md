# Build llama.cpp with Intel's long-context FA fix (PR #29357) - Visual Studio route

Prefer no admin / no Visual Studio? Run `engine\build.ps1` instead (portable toolchain). This page is the classic route.

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
git fetch https://github.com/sliu39/llama.cpp.git intel/fa-prefill
git cherry-pick 61cc4c2 1a5137a
cmake -B build -DGGML_VULKAN=ON -DLLAMA_CURL=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF
cmake --build build --config Release -j 16 --target llama-server llama-bench
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
