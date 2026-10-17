# ctxlab v4.3 checks (run on the PC): the patched files only count OUR llama-server, and the profile edit is in place.
param([string]$Dir = (Split-Path -Parent $MyInvocation.MyCommand.Path))
$fail = 0
function Check($name, $ok) { if ($ok) { "PASS $name" } else { "FAIL $name"; $script:fail++ } }
$g = Get-Content "$Dir\governor.ps1" -Raw; $l = Get-Content "$Dir\launch.ps1" -Raw; $p = Get-Content "$Dir\profiles.json" -Raw | ConvertFrom-Json
Check 'governor ProcIds filters llama-server by C:\AI\llama.cpp path' ($g -match "notlike 'C:\\AI\\llama\.cpp\\\*'")
Check 'launch.ps1 waits only for OurServers' (($l -match 'function OurServers') -and ($l -notmatch 'while \(\$waited -lt 45 -and @\(Get-Process llama-server'))
Check 'BALANCED margin 2.5 (18 Oct shared-memory finding)' ($p.profiles.BALANCED.free_margin_gib -eq 2.5)
Check 'default variant keeps f16 KV' ($p.variants.default.ctk -eq 'f16' -and $p.variants.default.ctv -eq 'f16')
Check 'default keeps drafter + -ub 256' ((($p.variants.default.extra_args) -join ' ') -match 'draft-dflash.*-ub 256')
# behavioural: ProcIds must drop a llama-server.exe outside C:\AI\llama.cpp (simulate with a fake Get-Process)
$ast = [System.Management.Automation.Language.Parser]::ParseInput($g, [ref]$null, [ref]$null)
$fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'ProcIds' }, $true)
$sb = [scriptblock]::Create($fn.Extent.Text)   # whole function via the AST (a fixed line count broke when comments were added)
function Attempt([scriptblock]$b) { try { @{ ok = $true; value = (& $b) } } catch { @{ ok = $false } } }
function Get-Process { param($Name, $ErrorAction) @([pscustomobject]@{ Id = 1; Path = 'C:\Apps\Ollama\lib\ollama\llama-server.exe' }, [pscustomobject]@{ Id = 2; Path = 'C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe' }) }
. $sb
$ids = ProcIds 'llama-server'
Check 'ProcIds returns only the C:\AI\llama.cpp pid' (($ids.Count -eq 1) -and ($ids[0] -eq 2))
Check 'ProcIds still returns every pid for other names' ((ProcIds 'codex').Count -eq 2)
if ($fail) { "FAILED: $fail"; exit 1 } else { "ALL PASS"; exit 0 }
