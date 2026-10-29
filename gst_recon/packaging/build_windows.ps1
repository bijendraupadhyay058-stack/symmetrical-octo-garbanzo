# Build FIN TAX PRO for Windows: the desktop app (FinTaxPro.exe) and the command-line tool
# (FinTaxPro-GST.exe). Run from the gst_recon folder in PowerShell:  .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"

py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python -m pip install --upgrade pip
.\.venv-build\Scripts\python -m pip install -r requirements.txt

# Run the test suite first – never ship a build that fails its tests.
.\.venv-build\Scripts\python -m pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed – build aborted" }

.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_gui.spec
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_cli.spec

Write-Host "Built dist\FinTaxPro\FinTaxPro.exe (desktop) and dist\FinTaxPro-GST\FinTaxPro-GST.exe (CLI)"
.\dist\FinTaxPro\FinTaxPro.exe --smoke-test
if ($LASTEXITCODE -ne 0) { throw "Desktop smoke test failed" }

# Optional Authenticode signing. Set FINTAX_SIGN_CERT to a code-signing certificate (.pfx)
# and FINTAX_SIGN_PASSWORD to its password; signtool.exe comes with the Windows SDK.
# FINTAX_SIGN_TIMESTAMP may name another RFC 3161 timestamp server.
function Sign-Files([string[]]$files) {
    if (-not $env:FINTAX_SIGN_CERT) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "FINTAX_SIGN_CERT is set but signtool.exe was not found (install the Windows SDK)" }
    $ts = if ($env:FINTAX_SIGN_TIMESTAMP) { $env:FINTAX_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
    foreach ($f in $files) {
        & $signtool.FullName sign /f $env:FINTAX_SIGN_CERT /p $env:FINTAX_SIGN_PASSWORD /fd SHA256 /tr $ts /td SHA256 /d "FIN TAX PRO" $f
        if ($LASTEXITCODE -ne 0) { throw "Signing failed: $f" }
        & $signtool.FullName verify /pa $f
        if ($LASTEXITCODE -ne 0) { throw "Signature verification failed: $f" }
    }
}
Sign-Files @(".\dist\FinTaxPro\FinTaxPro.exe", ".\dist\FinTaxPro-GST\FinTaxPro-GST.exe")

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc packaging\fintaxpro.iss
    Sign-Files @(".\dist\installer\FinTaxPro-Setup-1.0.0.exe")
    Write-Host "Installer: dist\installer\FinTaxPro-Setup-1.0.0.exe"
} else {
    Write-Host "Inno Setup 6 not found – skipping the installer (https://jrsoftware.org/isinfo.php)"
}
Write-Host "Smoke test (CLI demo):"
.\dist\FinTaxPro-GST\FinTaxPro-GST.exe demo --out "$env:TEMP\fintaxpro-demo"
