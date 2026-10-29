# Building the Windows executables

Requirements: Windows 10/11 (64-bit), Python 3.12 or newer from python.org
("Add python.exe to PATH" ticked).

```powershell
cd gst_recon
.\packaging\build_windows.ps1
```

The script

1. creates an isolated virtual environment `.venv-build`,
2. installs `requirements.txt`,
3. runs the full test suite and **stops if any test fails**,
4. builds two one-folder applications with PyInstaller (one-folder builds start faster
   and are flagged by antivirus less often than `--onefile`):
   * `dist\FinTaxPro\FinTaxPro.exe` – the desktop application (windowed)
   * `dist\FinTaxPro-GST\FinTaxPro-GST.exe` – the command-line tool
5. runs `FinTaxPro.exe --smoke-test` and the CLI demo,
6. builds `dist\installer\FinTaxPro-Setup-1.0.0.exe` if Inno Setup 6 is installed
   (`packaging\fintaxpro.iss`; per-user install, no administrator rights needed;
   uninstalling never deletes the data folder).

Check the desktop build with `dist\FinTaxPro\FinTaxPro.exe --smoke-test`. It opens every
page once and exits with code 0.

To distribute, copy the `dist\FinTaxPro` folder (and the CLI folder, if needed). Zip it or
wrap it with an installer such as Inno Setup. The target PC does not need Python. The
desktop folder is about 300 MB, mostly Qt libraries.

**Verified so far:** only on Linux, where the GUI spec builds and passes `--smoke-test`.
The Windows build has not been run yet. Run the script on a Windows PC before shipping.

Manual equivalent:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\pip install -r requirements.txt
.\.venv-build\Scripts\python -m pytest
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_gui.spec
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_cli.spec
```

Data location on Windows: `%LOCALAPPDATA%\FinTaxPro\`. It holds `fintaxpro.db` (the
database), `fintaxpro.log`, `backups\` and `attachments\` (evidence files). Override it
with the `FINTAX_HOME` or `FINTAX_DB` environment variables, or with the `--db` option
(both executables accept it).

To run from source instead, use `python -m fintax_gst.ui` (desktop) or
`python -m fintax_gst` (CLI). After `pip install -e .` the commands are `fintax-gst-gui`
and `fintax-gst`.
