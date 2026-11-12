"""Portable resource and installed-game discovery for source and Windows releases."""
import json
import os
from pathlib import Path
import re
import sys
import winreg

RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
VERSION = json.loads((RESOURCE_ROOT/'version.json').read_text(encoding='utf-8'))['version']


def registry_value(hive, key, name):
    try:
        with winreg.OpenKey(hive, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except OSError:
        return None


def valid_game(path):
    path = Path(path)
    return path.name.lower() == 'dps.exe' and path.is_file() and (path.parent/'GameAssembly.dll').is_file() and (path.parent/'DPS_Data/il2cpp_data/Metadata/global-metadata.dat').is_file()


def steam_libraries(steam_root):
    root = Path(steam_root)
    libraries = [root]
    try:
        text = (root/'steamapps/libraryfolders.vdf').read_text(encoding='utf-8-sig')
        libraries += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s*"([^"\r\n]+)"', text)]
    except OSError:
        pass
    return list(dict.fromkeys(libraries))


def find_game():
    explicit = os.environ.get('DPS_GAME_PATH')
    candidates = [Path(explicit)] if explicit else []
    executable_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else RESOURCE_ROOT
    candidates += [executable_dir/'DPS.exe', executable_dir.parent/'DPS.exe']
    steam_roots = [registry_value(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                   registry_value(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                   str(Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))/'Steam')]
    for steam in filter(None, steam_roots):
        for library in steam_libraries(steam):
            candidates.append(library/'steamapps/common/DPS Desktop Pension Squad/DPS.exe')
    return next((p.resolve() for p in candidates if valid_game(p)), None)


def find_sandboxie():
    candidates = [Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Sandboxie-Plus',
                  Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Sandboxie']
    service = registry_value(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\SbieSvc', 'ImagePath')
    if service:
        match = re.match(r'\s*"([^"]+)"|\s*(.+?\.exe)(?:\s|$)', os.path.expandvars(service), re.I)
        if match:
            candidates.insert(0, Path(match.group(1) or match.group(2)).parent)
    return next((p for p in candidates if (p/'SbieDll.dll').is_file()), candidates[0])


def bridge_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--bridge-host']
    return [sys.executable, str(RESOURCE_ROOT/'tools/bridge_host.py')]
