# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

source = Path(SPECPATH)
a = Analysis([str(source / 'launcher.py')], pathex=[str(source)], binaries=[], datas=collect_data_files('pypinyin', includes=['*.json']),
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False, optimize=0)
# Qt uses the Windows-provided ICU API. Do not accidentally bundle an unrelated
# versioned ICU from developer tools on PATH (for example Poppler).
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != 'icuuc.dll']
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ACG Game Library',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          version=str(source / 'version_info.txt'), icon=[str(source / 'app.ico')])
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ACG Game Library')
