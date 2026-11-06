# PyInstaller recipe for StockSense.exe (used by the GitHub build).
a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/stocksense.ico", "assets"), ("assets/stocksense.png", "assets"),
           ("assets/fonts", "assets/fonts"), ("LICENSE", ".")],
    hiddenimports=[],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
              "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
              "PySide6.QtUiTools", "PySide6.QtHelp", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="StockSense",
    icon="assets/stocksense.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="StockSense", upx=False)
