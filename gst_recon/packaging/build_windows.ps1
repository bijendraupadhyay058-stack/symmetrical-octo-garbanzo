# Build the FIN TAX PRO GST command-line executable on Windows.
# Run from the gst_recon folder in PowerShell:  .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"

py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python -m pip install --upgrade pip
.\.venv-build\Scripts\python -m pip install -r requirements.txt

# Run the test suite first – never ship a build that fails its tests.
.\.venv-build\Scripts\python -m pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed – build aborted" }

.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_cli.spec

Write-Host "Built dist\FinTaxPro-GST\FinTaxPro-GST.exe"
Write-Host "Smoke test:"
.\dist\FinTaxPro-GST\FinTaxPro-GST.exe demo --out "$env:TEMP\fintaxpro-demo"
