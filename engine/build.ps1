# Portable (no-admin) build of llama.cpp b11524 + Intel FA prefill patches (from PR #29357). Output: C:\AI\llama.cpp\vulkan-intelfa
# The two patches are vendored in engine\patches (checksummed); the build applies them with git am. Fetching the author's branch is only a fallback.
param([string]$Root = "$env:SystemDrive\build\intelfa")
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'   # Windows PowerShell 5.1 downloads are very slow with the progress bar on
$log = Join-Path $PSScriptRoot 'build.log'
function L($m) { "$(Get-Date -Format T) $m" | Add-Content $log }
"start $(Get-Date -Format s)" | Set-Content $log
$root = $Root; $tools = "$root\tools"; New-Item -ItemType Directory -Force $tools | Out-Null
Set-Location $root
# 1. portable toolchain
if (-not (Test-Path "$tools\w64devkit\bin\gcc.exe")) { L 'download w64devkit'; Invoke-WebRequest 'https://github.com/skeeto/w64devkit/releases/download/v2.10.0/w64devkit-x64-2.10.0.7z.exe' -OutFile "$tools\w64devkit.7z.exe"; & "$tools\w64devkit.7z.exe" "-o$tools" -y | Out-Null }
if (-not (Test-Path "$tools\cmake\bin\cmake.exe")) { L 'download cmake'; Invoke-WebRequest 'https://github.com/Kitware/CMake/releases/download/v4.4.4/cmake-4.4.4-windows-x86_64.zip' -OutFile "$tools\cmake.zip"; Expand-Archive "$tools\cmake.zip" $tools -Force; Rename-Item "$tools\cmake-4.4.4-windows-x86_64" 'cmake' }
if (-not (Test-Path "$tools\ninja.exe")) { L 'download ninja'; Invoke-WebRequest 'https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip' -OutFile "$tools\ninja.zip"; Expand-Archive "$tools\ninja.zip" $tools -Force }
$env:PATH = "$tools\w64devkit\bin;$tools\cmake\bin;$tools;$env:PATH"
L ("gcc: " + (& gcc --version | Select -First 1)); L ("cmake: " + (& cmake --version | Select -First 1))
# 2. sources
if (-not (Test-Path "$root\Vulkan-Headers")) { L 'clone Vulkan-Headers'; git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers.git 2>&1 | Out-Null }
if (-not (Test-Path "$root\shaderc")) { L 'clone shaderc'; git clone --depth 1 https://github.com/google/shaderc.git 2>&1 | Out-Null; Push-Location shaderc; python utils\git-sync-deps 2>&1 | Out-Null; Pop-Location }
if (-not (Test-Path "$root\llama.cpp")) {
  L 'clone llama.cpp'; git clone --filter=blob:none https://github.com/ggml-org/llama.cpp.git 2>&1 | Out-Null
  Push-Location llama.cpp; git -c advice.detachedHead=false checkout -q b11524
  git -c user.email=x@x -c user.name=x checkout -q -b intelfa
  # 1. Preferred: the vendored patches, after verifying their SHA-256 checksums.
  $pd = Join-Path $PSScriptRoot 'patches'; $applied = $false
  if (Test-Path "$pd\SHA256SUMS") {
    $bad = 0
    foreach ($line in Get-Content "$pd\SHA256SUMS") {
      if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
        $want = $Matches[1].ToLower(); $f = Join-Path $pd $Matches[2]
        if (-not (Test-Path $f) -or (Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $want) { $bad++; L "patch checksum problem: $($Matches[2])" }
      }
    }
    if ($bad -eq 0) {
      $patches = @(Get-ChildItem "$pd\*.patch" | Sort-Object Name | ForEach-Object { $_.FullName })
      $out = git -c user.email=x@x -c user.name=x am --3way @patches 2>&1; $rc = $LASTEXITCODE
      $out | ForEach-Object { L "git am: $_" }
      if ($rc -eq 0 -and $patches.Count -gt 0) { $applied = $true; L "applied $($patches.Count) vendored patches" } else { git am --abort 2>&1 | Out-Null }
    }
  }
  # 2. Fallback: fetch the author's branch (it may have been force-pushed, so this can fail).
  if (-not $applied) {
    L 'vendored patches missing or failed: falling back to sliu39/llama.cpp intel/fa-prefill'
    git fetch -q https://github.com/sliu39/llama.cpp.git intel/fa-prefill
    git -c user.email=x@x -c user.name=x cherry-pick 61cc4c25a6878bfcff2d2d76870ba1948ee0f3e2 1a5137a44fe7b2c921fe6b5f7d62704226bac599 2>&1 | ForEach-Object { L "cherry-pick: $_" }
  }
  Pop-Location }
L ("llama.cpp HEAD: " + (git -C llama.cpp log --oneline -3 | Out-String).Replace("`n", ' | '))
# Verify the Intel FA patch is really in the tree (a stale or partial clone from an earlier run would otherwise build a stock engine).
$subjects = (git -C llama.cpp log -2 --format=%s 2>&1 | Out-String)
if ($subjects -notmatch 'Intel customized FA shader') {
  L 'FAILED: the Intel FA prefill patch is not applied in llama.cpp (stale or partial clone?). Delete the llama.cpp folder under the build root and run this script again.'
  Write-Host "The Intel FA prefill patch is not applied in $root\llama.cpp (found: $($subjects.Trim() -replace '\s+', ' | ')). Delete that folder and run this script again." -ForegroundColor Red
  exit 1
}
$jobs = [int]$env:NUMBER_OF_PROCESSORS; if ($jobs -lt 1) { $jobs = 4 }
# 3. glslc (needs coopmat + integer dot support)
$glslc = "$root\shaderc\b\glslc\glslc.exe"
if (-not (Test-Path $glslc)) { L 'build glslc'
  cmake -S shaderc -B shaderc\b -G Ninja -DCMAKE_BUILD_TYPE=Release -DSHADERC_SKIP_TESTS=ON -DSHADERC_SKIP_EXAMPLES=ON -DSPIRV_SKIP_TESTS=ON -DSHADERC_SKIP_COPYRIGHT_CHECK=ON -DENABLE_GLSLANG_BINARIES=OFF -DCMAKE_EXE_LINKER_FLAGS="-static" *> "$root\glslc-cfg.log"
  cmake --build shaderc\b --target glslc_exe -j $jobs *> "$root\glslc-build.log" }
if (-not (Test-Path $glslc)) { L 'FAILED: glslc not built (see glslc-build.log)'; exit 1 }
L 'glslc ok'
# 4. llama.cpp
$vkinc = "$root\Vulkan-Headers\include"; $spv = "$root\shaderc\third_party\spirv-headers\include"
if (-not (Test-Path "$root\spv-install\share")) { L 'install SPIRV-Headers package'
  cmake -S shaderc\third_party\spirv-headers -B spv-b -G Ninja -DCMAKE_INSTALL_PREFIX="$root\spv-install" -DSPIRV_HEADERS_ENABLE_TESTS=OFF *> "$root\spv.log"; cmake --install spv-b *>> "$root\spv.log" }
Remove-Item -Recurse -Force llama.cpp\bw -EA SilentlyContinue
cmake -S llama.cpp -B llama.cpp\bw -G Ninja -DCMAKE_PREFIX_PATH="$root\spv-install" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DVulkan_INCLUDE_DIR="$vkinc" -DVulkan_LIBRARY="C:/Windows/System32/vulkan-1.dll" -DVulkan_GLSLC_EXECUTABLE="$glslc" -DCMAKE_CXX_FLAGS="-I$spv" -DGGML_NATIVE=ON -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF -DGGML_OPENMP=OFF -DCMAKE_EXE_LINKER_FLAGS="-static" *> "$root\llama-cfg.log"
Select-String "$root\llama-cfg.log" -Pattern 'supported by glslc|not supported' | % { L $_.Line }
cmake --build llama.cpp\bw --target llama-server llama-bench -j $jobs *> "$root\llama-build.log"
$bin = "$root\llama.cpp\bw\bin"
if (-not (Test-Path "$bin\llama-server.exe")) { L 'FAILED: llama-server not built (see llama-build.log)'; exit 1 }
New-Item -ItemType Directory -Force C:\AI\llama.cpp\vulkan-intelfa | Out-Null
Copy-Item "$bin\*.exe","$bin\*.dll" C:\AI\llama.cpp\vulkan-intelfa\ -Force -EA SilentlyContinue
L 'BUILD OK -> C:\AI\llama.cpp\vulkan-intelfa'
"END $(Get-Date -Format s)" | Add-Content $log
