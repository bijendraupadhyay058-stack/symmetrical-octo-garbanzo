# Build FIN TAX PRO for Windows: the desktop app (FinTaxPro.exe) and the command-line tool
# (FinTaxPro-GST.exe). Run from the gst_recon folder in PowerShell:  .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"

# FINTAX_BUILD_PYTHON may name the interpreter (e.g. "python" on a CI runner); default: the py launcher.
if ($env:FINTAX_BUILD_PYTHON) { & $env:FINTAX_BUILD_PYTHON -m venv .venv-build } else { py -3.12 -m venv .venv-build }
if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment" }
.\.venv-build\Scripts\python -m pip install --upgrade pip
# Library versions bundled into the installer are pinned (packaging\build-constraints.txt) for the widest PC support.
.\.venv-build\Scripts\python -m pip install -r requirements.txt -c packaging\build-constraints.txt
if ($LASTEXITCODE -ne 0) { throw "Installing the build requirements failed" }

# Run the test suite first – never ship a build that fails its tests.
.\.venv-build\Scripts\python -m pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed – build aborted" }

.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_gui.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (desktop) failed" }
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_cli.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (CLI) failed" }

Write-Host "Built dist\FinTaxPro\FinTaxPro.exe (desktop) and dist\FinTaxPro-GST\FinTaxPro-GST.exe (CLI)"
# FinTaxPro.exe is a windowed program: PowerShell does not wait for it unless asked to.
$smoke = Start-Process -FilePath ".\dist\FinTaxPro\FinTaxPro.exe" -ArgumentList "--smoke-test" -Wait -PassThru -NoNewWindow
if ($smoke.ExitCode -ne 0) { throw "Desktop smoke test failed (exit code $($smoke.ExitCode))" }

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
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    $setup = (Get-ChildItem .\dist\installer\FinTaxPro-Setup-*.exe | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
    Sign-Files @($setup)
    Write-Host "Installer: $setup"
} else {
    Write-Host "Inno Setup 6 not found – skipping the installer (https://jrsoftware.org/isinfo.php)"
}
Write-Host "Smoke test (CLI demo):"
.\dist\FinTaxPro-GST\FinTaxPro-GST.exe demo --out "$env:TEMP\fintaxpro-demo"
if ($LASTEXITCODE -ne 0) { throw "CLI demo failed" }
