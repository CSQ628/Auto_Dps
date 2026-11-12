"""Read public release metadata and report newer versions without installing them."""
import json
import re
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from .platform_paths import VERSION
from .storage import DATA, atomic_json, load_json

API = 'https://api.github.com/repos/weixiao030/Auto_Dps/releases/latest'
RELEASES = 'https://github.com/weixiao030/Auto_Dps/releases'


def version_tuple(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value or '') if isinstance(value, str) else None
    return tuple(map(int, match.groups())) if match else None


def release_state(payload, current=VERSION):
    current_tuple, latest_tuple = version_tuple(current), version_tuple(payload.get('tag_name'))
    if not current_tuple or not latest_tuple or payload.get('draft') is not False or payload.get('prerelease') is not False:
        raise ValueError('invalid_release_metadata')
    latest = '.'.join(map(str, latest_tuple))
    return {'status': 'available' if latest_tuple > current_tuple else 'current', 'current': current,
            'latest': latest, 'url': RELEASES + '/tag/v' + latest}


def existing_instance_notice(current, running):
    wanted, existing = version_tuple(current), version_tuple(running)
    if wanted and existing and wanted > existing:
        return (f'后台仍在运行 v{running}，本次打开的是 v{current}。\n\n'
                '请先通过旧助手的托盘或“停止助手.cmd”退出，再重新打开新版本。\n'
                '关闭网页不会退出旧助手，退出助手不会关闭游戏。')
    return None


class VersionChecker:
    def __init__(self, current=VERSION, cache=None, fetch=None):
        self.current = current
        self.cache = DATA/'updates.json' if cache is None else cache
        self.fetch = fetch or self._fetch
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.value = {'status': 'checking', 'current': current}
        cached = load_json(self.cache, {})
        try:
            self.value = {**release_state(cached, current), 'checked_at': cached['checked_at']}
        except (ValueError, KeyError, TypeError):
            pass
        self.thread = threading.Thread(target=self._loop, name='dps-version-check', daemon=True)

    @staticmethod
    def _fetch():
        request = Request(API, headers={'Accept':'application/vnd.github+json', 'User-Agent':'Auto_Dps-version-check'})
        error = None
        # Respect an available system proxy; retry directly when an accelerator was closed.
        for opener in (build_opener(), build_opener(ProxyHandler({}))):
            try:
                with opener.open(request, timeout=4) as response:
                    data = response.read(131073)
                if len(data) > 131072:
                    raise ValueError('release_metadata_too_large')
                return json.loads(data)
            except Exception as exc:
                error = exc
        raise error

    def refresh(self):
        try:
            payload = self.fetch()
            value = {**release_state(payload, self.current), 'checked_at': time.time()}
            atomic_json(self.cache, {'tag_name':'v'+value['latest'], 'draft':False, 'prerelease':False,
                                     'checked_at':value['checked_at']})
            with self.lock:
                self.value = value
        except Exception:
            with self.lock:
                if self.value.get('status') != 'available':
                    self.value = {'status':'unavailable', 'current':self.current}

    def _loop(self):
        while not self.stopping.is_set():
            self.refresh()
            self.stopping.wait(21600)

    def start(self):
        self.thread.start()

    def state(self):
        with self.lock:
            return dict(self.value)

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
