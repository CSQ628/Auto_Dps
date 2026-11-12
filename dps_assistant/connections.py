"""Local game selection and explicit binding, always tied to a live process lifetime."""
from pathlib import Path
import math
import psutil
from .platform_paths import find_game, valid_game


def game_executable(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 32767:
        raise ValueError('请填写 DPS 游戏目录，或 DPS.exe 的完整路径')
    path = Path(value.strip().strip('"')).expanduser()
    if not path.is_absolute():
        raise ValueError('游戏路径需要是完整的绝对路径')
    if path.is_dir():
        path = path/'DPS.exe'
    if not valid_game(path):
        raise ValueError('此目录缺少 DPS.exe、GameAssembly.dll 或游戏元数据，请选择游戏安装目录')
    return str(path.resolve())


def live_process(pid, expected_created=None):
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError('请输入正在运行的 DPS 游戏进程 PID')
    if expected_created is not None and (isinstance(expected_created, bool) or
            not isinstance(expected_created, (int, float)) or not math.isfinite(expected_created)):
        raise ValueError('进程信息已失效，请重新扫描')
    try:
        process = psutil.Process(pid)
        created = process.create_time()
        if expected_created is not None and abs(created-expected_created) > .001:
            raise ValueError('这个 PID 已被其他进程复用，请重新扫描后绑定')
        if process.name().lower() != 'dps.exe':
            raise ValueError('所选进程不是 DPS.exe，请选择游戏进程')
        executable = game_executable(process.exe())
        if not process.is_running() or abs(psutil.Process(pid).create_time()-created) > .001:
            raise ValueError('游戏进程已退出，请重新扫描')
        return {'pid': pid, 'created': created, 'exe': executable}
    except psutil.AccessDenied as error:
        raise ValueError('无法读取此游戏进程，请让助手与游戏使用相同权限后重试') from error
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as error:
        raise ValueError('游戏进程已退出，请重新扫描') from error


def candidates(processes, selected_path=''):
    paths = []
    detected = find_game()
    sources = [(selected_path, '手动指定'), (str(detected) if detected else '', 'Steam 或自动识别')]
    sources.extend((row.get('exe',''), '运行中的游戏 · '+(row.get('box') or '主实例')) for row in processes)
    for value, source in sources:
        if value and valid_game(value) and not any(p['path'].casefold() == str(value).casefold() for p in paths):
            paths.append({'path': str(value), 'source': source})
    return {'games': paths, 'processes': [{k: row[k] for k in ('pid', 'created', 'exe', 'box')}
            for row in processes], 'selected_path': selected_path,
            'automatic': True}
