# PyInstaller spec — 本機 (build_exe.bat) 與 CI (.github/workflows/build.yml) 共用的唯一打包設定。
# 產物：onedir，dist/VirtualSpot/VirtualSpot.exe，啟動時要求系統管理員權限（tunneld 需要）。
import os
import re

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = os.path.abspath(SPECPATH)

# ── 版本號：只從 version.py 讀（不 import，避免副作用）
with open(os.path.join(ROOT, "version.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
_nums = [int(re.sub(r"\D", "", p) or 0) for p in VERSION.split(".")][:4]
_nums += [0] * (4 - len(_nums))
FILEVER = tuple(_nums)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=FILEVER, prodvers=FILEVER, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "VirtualSpot"),
            StringStruct("FileDescription", "VirtualSpot"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "VirtualSpot"),
            StringStruct("OriginalFilename", "VirtualSpot.exe"),
            StringStruct("ProductName", "VirtualSpot"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# ── 收集第三方套件的資料檔 / 動態模組
datas, binaries, hiddenimports = [], [], []
for pkg in ("customtkinter", "tkintermapview", "pymobiledevice3"):
    d, b, h = collect_all(pkg)          # 失敗就讓建置直接失敗，不要默默打出壞掉的 exe
    datas += d
    binaries += b
    hiddenimports += h

# 確定用不到的大型模組，排除以縮小體積（若有 "No module named" 再從這裡拿掉）
EXCLUDES = ["pytest", "IPython", "matplotlib", "scipy", "pandas", "numpy.tests", "tkinter.test", "unittest"]

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas + [(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir
    name="VirtualSpot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX 容易被防毒誤報，且對管理員權限程式風險更大
    console=False,
    uac_admin=True,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VirtualSpot")
