# Build with the isolated packaging environment, from the repository root.
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import json
package_version=json.loads(Path('version.json').read_text(encoding='utf-8'))['version']

frida_data, frida_binaries, frida_imports = collect_all('frida')
a = Analysis(['desktop_entry.py'], pathex=['.'],
    binaries=frida_binaries,
    datas=frida_data + [('bridge', 'bridge'), ('web/dist', 'web/dist'), ('version.json', '.')],
    hiddenimports=['tools.bridge_host', 'frida'] + frida_imports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DPSAssistant',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, version='packaging/windows-version.txt', disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DPSAssistant-'+package_version)
