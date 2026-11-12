"""Windows notification area control; uses the OS directly, with no extra runtime."""
import ctypes
from ctypes import wintypes as w
import os
import threading
import webbrowser
from .platform_paths import VERSION


class SystemTray:
    def __init__(self, engine, server, icon):
        self.engine, self.server, self.icon = engine, server, str(icon)
        self.ready = threading.Event()
        self.active = False
        self.error = None
        self.hwnd = None
        self._post = None
        self.thread = threading.Thread(target=self._run, name='dps-tray', daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(3)

    def command(self, command):
        if command == 1:
            webbrowser.open(self.server.origin)
        elif command == 2:
            self.engine.update({'running': not self.engine.config['running']})
            if self.hwnd and self._post:
                self._post(self.hwnd, 0x8022, 0, 0)
        elif command == 3:
            # Shutdown the helper's server; game processes remain owned by the game.
            self.server.shutdown()

    def stop(self):
        if self.hwnd and self._post:
            self._post(self.hwnd, 0x0010, 0, 0)
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=3)

    def _run(self):
        try:
            self._windows_loop()
        except Exception as error:
            self.error = type(error).__name__
            self.engine.record('system', 'waiting', '系统托盘暂不可用，可从网页继续控制助手')
        finally:
            self.active = False
            self.ready.set()

    def _windows_loop(self):
        if os.name != 'nt':
            raise OSError('windows_required')
        user = ctypes.WinDLL('user32', use_last_error=True)
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        result_type = ctypes.c_ssize_t
        callback_type = ctypes.WINFUNCTYPE(result_type, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [('style', w.UINT), ('proc', callback_type), ('class_extra', ctypes.c_int),
                        ('window_extra', ctypes.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                        ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]

        class IconData(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('window', w.HWND), ('id', w.UINT), ('flags', w.UINT),
                        ('callback', w.UINT), ('icon', w.HICON), ('tip', w.WCHAR * 128),
                        ('state', w.DWORD), ('state_mask', w.DWORD), ('info', w.WCHAR * 256),
                        ('version', w.UINT), ('title', w.WCHAR * 64), ('info_flags', w.DWORD),
                        ('guid', ctypes.c_byte * 16), ('balloon_icon', w.HICON)]

        def bind(lib, name, returns, args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = returns, args
            return fn

        module = bind(kernel, 'GetModuleHandleW', w.HMODULE, [w.LPCWSTR])(None)
        register = bind(user, 'RegisterClassW', w.WORD, [ctypes.POINTER(WindowClass)])
        unregister = bind(user, 'UnregisterClassW', w.BOOL, [w.LPCWSTR, w.HINSTANCE])
        create = bind(user, 'CreateWindowExW', w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID])
        destroy = bind(user, 'DestroyWindow', w.BOOL, [w.HWND])
        default = bind(user, 'DefWindowProcW', result_type, [w.HWND, w.UINT, w.WPARAM, w.LPARAM])
        self._post = bind(user, 'PostMessageW', w.BOOL, [w.HWND, w.UINT, w.WPARAM, w.LPARAM])
        quit_loop = bind(user, 'PostQuitMessage', None, [ctypes.c_int])
        notify = bind(shell, 'Shell_NotifyIconW', w.BOOL, [w.DWORD, ctypes.POINTER(IconData)])
        load_icon = bind(user, 'LoadImageW', w.HANDLE, [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT])
        destroy_icon = bind(user, 'DestroyIcon', w.BOOL, [w.HICON])
        create_menu = bind(user, 'CreatePopupMenu', w.HMENU, [])
        append = bind(user, 'AppendMenuW', w.BOOL, [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR])
        popup = bind(user, 'TrackPopupMenu', w.UINT, [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, ctypes.c_void_p])
        delete_menu = bind(user, 'DestroyMenu', w.BOOL, [w.HMENU])
        cursor = bind(user, 'GetCursorPos', w.BOOL, [ctypes.POINTER(w.POINT)])
        foreground = bind(user, 'SetForegroundWindow', w.BOOL, [w.HWND])
        get_message = bind(user, 'GetMessageW', ctypes.c_int, [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT])
        translate = bind(user, 'TranslateMessage', w.BOOL, [ctypes.POINTER(w.MSG)])
        dispatch = bind(user, 'DispatchMessageW', result_type, [ctypes.POINTER(w.MSG)])
        set_timer = bind(user, 'SetTimer', ctypes.c_size_t, [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p])
        kill_timer = bind(user, 'KillTimer', w.BOOL, [w.HWND, ctypes.c_size_t])
        taskbar = bind(user, 'RegisterWindowMessageW', w.UINT, [w.LPCWSTR])('TaskbarCreated')
        icon = load_icon(None, self.icon, 1, 0, 0, 0x10)
        if not icon:
            raise ctypes.WinError(ctypes.get_last_error())
        data = IconData()
        data.size, data.id, data.flags, data.callback, data.icon = ctypes.sizeof(data), 1, 7, 0x8021, icon

        def update(add=False):
            data.tip = f'DPS 远征助手 v{VERSION} · ' + ('自动远征中' if self.engine.config['running'] else '已暂停')
            self.active = bool(notify(0 if add else 1, ctypes.byref(data)))

        def menu(hwnd):
            handle = create_menu()
            try:
                append(handle, 0, 1, '打开助手')
                append(handle, 0, 2, '暂停全部远征' if self.engine.config['running'] else '继续自动远征')
                append(handle, 0x800, 0, None)
                append(handle, 0, 3, '退出助手')
                point = w.POINT()
                cursor(ctypes.byref(point))
                foreground(hwnd)
                command = popup(handle, 0x180, point.x, point.y, 0, hwnd, None)
                self._post(hwnd, 0, 0, 0)
                if command:
                    threading.Thread(target=self.command, args=(command,), daemon=True).start()
            finally:
                delete_menu(handle)

        @callback_type
        def window_proc(hwnd, message, wp, lp):
            if message == 0x8021:
                if lp in (0x0205, 0x007B):
                    menu(hwnd)
                elif lp == 0x0203:
                    threading.Thread(target=self.command, args=(1,), daemon=True).start()
                return 0
            if message == taskbar:
                update(add=True)
                return 0
            if message == 0x0113:
                update(add=not self.active)
                return 0
            if message == 0x8022:
                update()
                return 0
            if message == 0x0010:
                destroy(hwnd)
                return 0
            if message == 0x0002:
                notify(2, ctypes.byref(data))
                self.active = False
                quit_loop(0)
                return 0
            return default(hwnd, message, wp, lp)

        name = f'DPSAssistantTray-{os.getpid()}'
        cls = WindowClass(0, window_proc, 0, 0, module, icon, None, None, None, name)
        registered = False
        try:
            if not register(ctypes.byref(cls)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            self.hwnd = create(0, name, 'DPS 远征助手', 0, 0, 0, 0, 0, None, None, module, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            data.window = self.hwnd
            update(add=True)
            set_timer(self.hwnd, 1, 3000, None)
            self.ready.set()
            message = w.MSG()
            while True:
                status = get_message(ctypes.byref(message), None, 0, 0)
                if status <= 0:
                    if status < 0:
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
                translate(ctypes.byref(message))
                dispatch(ctypes.byref(message))
        finally:
            notify(2, ctypes.byref(data))
            if self.hwnd:
                kill_timer(self.hwnd, 1)
                destroy(self.hwnd)
                self.hwnd = None
            if registered:
                unregister(name, module)
            destroy_icon(icon)
