# PyInstaller spec for the Phase 1 command-line application (one-folder build).
# Build:  pyinstaller --noconfirm --clean packaging/fintax_gst_cli.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller

a = Analysis(  # noqa: F821
    [str(root / "packaging" / "entry_cli.py")],
    pathex=[str(root)],
    datas=collect_data_files("docx"),  # Word letter template
    hiddenimports=["sqlalchemy.dialects.sqlite", "rapidfuzz.fuzz", "openpyxl.cell._writer", "cryptography.fernet"]
    + collect_submodules("uvicorn"),
    excludes=["PySide6", "tkinter", "matplotlib", "IPython"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="FinTaxPro-GST", console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FinTaxPro-GST")  # noqa: F821
