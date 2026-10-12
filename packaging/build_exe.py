"""Build dist/CsvFtps.exe with PyInstaller.

Usage (from the repository root, after ``pip install -e .[build]``):

    python packaging/build_exe.py
"""

import os
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "csvftps" / "assets"

PyInstaller.__main__.run(
    [
        str(ROOT / "packaging" / "app.py"),
        "--name=CsvFtps",
        "--onefile",
        "--windowed",
        "--noconfirm",
        f"--icon={ASSETS / 'icon.ico'}",
        # os.pathsep is ';' on Windows and ':' elsewhere, as PyInstaller expects.
        f"--add-data={ASSETS}{os.pathsep}csvftps/assets",
        "--collect-data=customtkinter",
        # keyring finds its backends through entry points, which a frozen app must bundle.
        "--copy-metadata=keyring",
        "--collect-submodules=keyring.backends",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT / 'build'}",
    ]
)
