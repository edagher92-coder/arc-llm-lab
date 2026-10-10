# Set (or change) the PIN for the tool-approval page. Run this yourself on the PC; the PIN is never shown or stored in clear text.
# Stored as a salted PBKDF2-SHA256 hash in C:\AI\gateway\approval-pin.json. Use at least 6 characters.
$ErrorActionPreference = 'Stop'
$a = Read-Host 'New approval PIN (6+ digits)' -AsSecureString
$b = Read-Host 'Repeat the PIN' -AsSecureString
$p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($a))
$p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($b))
if ($p1 -ne $p2) { Write-Host 'The two PINs differ. Nothing changed.'; exit 1 }
if ($p1.Length -lt 6) { Write-Host 'Use at least 6 characters. Nothing changed.'; exit 1 }
$p1 | & 'C:\AI\gateway\.venv\Scripts\python.exe' 'C:\AI\gateway\set_pin.py'
$p1 = $null; $p2 = $null
if (Test-Path 'C:\AI\gateway\approval-pin.json') { Write-Host 'Approval PIN set. Open https://<your-pc>.<tailnet>.ts.net:8445/tts/approvals on your phone.' }
