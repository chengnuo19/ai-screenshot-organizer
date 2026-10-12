# -*- mode: python ; coding: utf-8 -*-
import os
import flet_cli

flet_cli_dir = list(flet_cli.__path__)[0]
flet_hooks_dir = os.path.join(flet_cli_dir, "__pyinstaller")

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('screenshot_organizer/default_config.yaml', 'screenshot_organizer')],
    hiddenimports=[],
    hookspath=[flet_hooks_dir],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AIScreenshotOrganizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
)
