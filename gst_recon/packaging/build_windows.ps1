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

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc packaging\fintaxpro.iss
    Write-Host "Installer: dist\installer\FinTaxPro-Setup-1.0.0.exe"
} else {
    Write-Host "Inno Setup 6 not found – skipping the installer (https://jrsoftware.org/isinfo.php)"
}
Write-Host "Smoke test (CLI demo):"
.\dist\FinTaxPro-GST\FinTaxPro-GST.exe demo --out "$env:TEMP\fintaxpro-demo"
