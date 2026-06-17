# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['steampy_overlay.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('font/gnuunifontfull-pm9p.ttf', 'font'),
        ('libopenvr_api_64.dll', '.'),
    ],
    hiddenimports=['openvr'],
    hookspath=[],
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
    [],
    exclude_binaries=True,
    name='steampy_overlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='steampy_overlay',
)
