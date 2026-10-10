#!/usr/bin/env bash
# Build llama.cpp b11524 (Vulkan) with Intel's FA prefill patches on Linux (Mesa ANV or Intel's Vulkan driver).
# STATUS: the patches were verified to apply cleanly to b11524 with `git am` and `git apply`. This script itself has NOT been
# run on Linux with an Arc GPU by the author. If you try it, please share the result (see docs/GOOD-FIRST-ISSUES.md).
# Needs: git, cmake (3.14+), a C++ compiler, ninja or make, Vulkan headers and loader, and glslc (the "shaderc" or "glslc" package).
# The Intel FA shader needs glslc that reports GL_KHR_cooperative_matrix and GL_EXT_integer_dot_product support (check the configure output).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:-$HOME/arc-llm-lab-build}"
mkdir -p "$WORK" && cd "$WORK"
[ -d llama.cpp ] || git clone --filter=blob:none https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
git checkout -q b11524
git checkout -q -B intelfa
( cd "$HERE/patches" && sha256sum -c SHA256SUMS )
git -c user.name=arc-llm-lab -c user.email=arc-llm-lab@localhost am --3way "$HERE"/patches/0*.patch
cmake -B build -DGGML_VULKAN=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DCMAKE_BUILD_TYPE=Release 2>&1 | tee "$WORK/configure.log" | grep -E "glslc|Vulkan" || true
cmake --build build --config Release -j "$(nproc)" --target llama-server llama-bench
echo "Built: $WORK/llama.cpp/build/bin/llama-server and llama-bench"
echo "Next: bench/arc-bench.sh -m <model.gguf> --vram-gb <N> --bench $WORK/llama.cpp/build/bin/llama-bench --patches 61cc4c25a,1a5137a44 to measure and write a community JSON result."
