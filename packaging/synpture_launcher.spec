# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


PROJECT_ROOT = Path.cwd()
APP_ICON = PROJECT_ROOT / "assets" / "branding" / "synpture-app.ico"
EDITION = os.environ.get("SYNPTURE_INSTALLER_EDITION", "Lite").strip().lower()
IS_FULL = EDITION == "full"


def add_tree(source: str, target: str):
    root = PROJECT_ROOT / source
    if not root.exists():
        return []
    return [(str(path), str(Path(target) / path.relative_to(root).parent)) for path in root.rglob("*") if path.is_file()]


datas = []
env_example = PROJECT_ROOT / ".env.example"
if env_example.exists():
    datas.append((str(env_example), "."))

runtime_manifest = PROJECT_ROOT / "packaging" / "runtime_resources.json"
if runtime_manifest.exists():
    datas.append((str(runtime_manifest), "packaging"))

for source_dir in ("workspace-ui", "assets", "templates", "tools"):
    datas.extend(add_tree(source_dir, source_dir))

if IS_FULL:
    datas.extend(add_tree("models", "models"))
    for whisper_bin_dir in (
        PROJECT_ROOT / "third_party" / "whisper.cpp" / "build-cuda" / "bin",
        PROJECT_ROOT / "third_party" / "whisper.cpp" / "build-core" / "bin",
    ):
        if whisper_bin_dir.exists():
            datas.extend(
                (str(path), str(Path("third_party") / path.parent.relative_to(PROJECT_ROOT / "third_party")))
                for path in whisper_bin_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in {".exe", ".dll"}
            )

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("multipart")
    + collect_submodules("pystray")
    + collect_submodules("PIL")
)


a = Analysis(
    [str(PROJECT_ROOT / "synpture_launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Synpture",
    icon=str(APP_ICON) if APP_ICON.exists() else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Synpture",
)
