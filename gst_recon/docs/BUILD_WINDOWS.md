# Building the Windows executable

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
4. builds `dist\FinTaxPro-GST\FinTaxPro-GST.exe` with PyInstaller (one-folder build –
   starts faster and is less often flagged by antivirus than `--onefile`),
5. runs the demo with the built executable as a smoke test.

Distribute the whole `dist\FinTaxPro-GST` folder (zip it, or wrap it with an installer
such as Inno Setup). No Python installation is needed on the target PC.

Manual equivalent:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\pip install -r requirements.txt
.\.venv-build\Scripts\python -m pytest
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging\fintax_gst_cli.spec
```

Data location on Windows: `%LOCALAPPDATA%\FinTaxPro\fintaxpro.db` (database),
`fintaxpro.log` (log) and `backups\` in the same folder. Override with the
`FINTAX_HOME` or `FINTAX_DB` environment variables or the `--db` option.

The Phase 2 desktop build will add a second spec (`fintax_gst_gui.spec`, windowed, with the
PySide6 plugins and icon) – the CLI executable remains available for batch work.
