"""Build and package a self-contained Windows x64 release. Run from the project root."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root/'version.json').read_text(encoding='utf-8'))['version']
    if not args.skip_build:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', 'DPSAssistant.spec'], cwd=root, check=True)
    folder = root/'dist'/('DPSAssistant-'+version)
    assert (folder/'DPSAssistant.exe').is_file()
    for source in ['packaging/使用说明.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(root/source, folder/Path(source).name)
    (folder/'停止助手.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nDPSAssistant.exe --stop\r\n', encoding='utf-8')
    legal = folder/'ThirdPartyLicenses'
    legal.mkdir(exist_ok=True)
    shutil.copy2(root/'licenses/IdleLegions-AutoAbyss-Apache-2.0.txt', legal/'IdleLegions-AutoAbyss-Apache-2.0.txt')
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, legal/'Python.txt')
    for name in ['frida', 'psutil', 'pyinstaller']:
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            if 'license' in str(entry).lower() or Path(str(entry)).name.upper() == 'COPYING':
                path = Path(distribution.locate_file(entry))
                if path.is_file():
                    shutil.copy2(path, legal/(name+'-'+path.name))
    modules = root/'web/node_modules'
    for package in modules.rglob('package.json'):
        if '.vite' in package.parts:
            continue
        for name in ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENCE', 'COPYING']:
            source = package.parent/name
            if source.is_file():
                target = legal/'web'/package.parent.relative_to(modules)/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    output = root/'dist'/f'Auto_Dps-{version}-Windows-x64.zip'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n', encoding='utf-8')
    print(json.dumps({'zip': str(output), 'bytes': output.stat().st_size, 'sha256': digest}))


if __name__ == '__main__':
    main()
