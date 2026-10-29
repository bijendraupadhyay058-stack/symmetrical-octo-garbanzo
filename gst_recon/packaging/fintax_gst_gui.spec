# PyInstaller spec for the PySide6 desktop application (windowed, one-folder build).
# Build:  pyinstaller --noconfirm --clean packaging/fintax_gst_gui.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller

a = Analysis(  # noqa: F821
    [str(root / "packaging" / "entry_gui.py")],
    pathex=[str(root)],
    datas=collect_data_files("docx"),  # Word letter template
    hiddenimports=["sqlalchemy.dialects.sqlite", "rapidfuzz.fuzz", "openpyxl.cell._writer",
                   "PySide6.QtCharts", "cryptography.fernet"]
    + collect_submodules("uvicorn"),  # the desktop can start the web view
    excludes=["tkinter", "matplotlib", "IPython", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="FinTaxPro", console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FinTaxPro")  # noqa: F821
