"""App-local IPv4 loopback transport; never changes the system Winsock catalog."""
import ctypes
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import os
import socket
import select
import threading
import urllib.request


class _Guid(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]


class _Chain(ctypes.Structure):
    _fields_ = [('length', ctypes.c_int32), ('entries', ctypes.c_uint32 * 7)]


class _Protocol(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ('service1', 'service2', 'service3', 'service4', 'flags')] + [
        ('provider', _Guid), ('catalog', ctypes.c_uint32), ('chain', _Chain)] + [
        (n, ctypes.c_int32) for n in ('version', 'family', 'max_address', 'min_address', 'type',
                                     'protocol', 'protocol_offset', 'byte_order', 'security')] + [
        ('message_size', ctypes.c_uint32), ('reserved', ctypes.c_uint32), ('name', ctypes.c_wchar * 256)]


def _windows_socket():
    # An explicit base TCP provider avoids third-party LSP state on this socket only.
    winsock = ctypes.WinDLL('ws2_32')
    winsock.WSAEnumProtocolsW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    winsock.WSAEnumProtocolsW.restype = ctypes.c_int
    size = ctypes.c_uint32()
    winsock.WSAEnumProtocolsW(None, None, ctypes.byref(size))
    if not size.value:
        raise OSError('winsock_protocol_inventory_unavailable')
    buffer = ctypes.create_string_buffer(size.value)
    count = winsock.WSAEnumProtocolsW(None, buffer, ctypes.byref(size))
    if count < 0:
        raise OSError(winsock.WSAGetLastError(), 'winsock_protocol_inventory_failed')
    entries = ctypes.cast(buffer, ctypes.POINTER(_Protocol))
    chosen = next((p for p in entries[:count] if p.chain.length == 1 and p.family == socket.AF_INET
                   and p.type == socket.SOCK_STREAM and p.protocol == socket.IPPROTO_TCP
                   and p.name == 'MSAFD Tcpip [TCP/IP]'), None)
    if chosen is None:
        raise OSError('windows_base_tcp_provider_unavailable')
    winsock.WSASocketW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.POINTER(_Protocol), ctypes.c_uint32, ctypes.c_uint32]
    winsock.WSASocketW.restype = ctypes.c_size_t
    handle = winsock.WSASocketW(-1, -1, -1, ctypes.byref(chosen), 0, 0x81)
    if handle == ctypes.c_size_t(-1).value:
        raise OSError(winsock.WSAGetLastError(), 'windows_base_tcp_socket_failed')
    try:
        return socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, fileno=handle)
    except BaseException:
        winsock.closesocket.argtypes = [ctypes.c_size_t]
        winsock.closesocket(handle)
        raise


def _make_socket(prefer_native=True):
    if os.name == 'nt' and prefer_native:
        try:
            return _windows_socket(), 'native'
        except OSError:
            pass
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM), 'system'


def loopback_socket():
    return _make_socket()[0]


class LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self._serving_stop = threading.Event()
        self._serving_done = threading.Event()
        super().__init__(*args, **kwargs)

    def serve_forever(self, poll_interval=0.5):
        self._serving_done.clear()
        try:
            while not self._serving_stop.is_set():
                # Resolve the current socket each poll; a provider switch changes its handle.
                readable, _, _ = select.select([self.socket], [], [], poll_interval)
                if self._serving_stop.is_set():
                    break
                if readable:
                    self._handle_request_noblock()
                self.service_actions()
        finally:
            self._serving_done.set()

    def shutdown(self):
        self._serving_stop.set()
        self._serving_done.wait()

    def _new_listener(self, prefer_native):
        listener, mode = _make_socket(prefer_native)
        try:
            if os.name == 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(self.server_address)
            listener.listen(self.request_queue_size)
            return listener, mode
        except BaseException:
            listener.close()
            raise

    def server_bind(self):
        if self.server_address[0] != '127.0.0.1':
            raise ValueError('loopback_address_required')
        self.socket.close()
        self.socket, self.transport_mode = self._new_listener(True)
        self.server_address = self.socket.getsockname()
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]
        self._accept_errors = 0
        self._recoveries = 0
        self._last_error = None

    def transport_state(self):
        return {'mode': self.transport_mode, 'automatic': True, 'recoveries': self._recoveries,
                'last_error': self._last_error}

    def get_request(self):
        try:
            request = super().get_request()
            self._accept_errors = 0
            return request
        except OSError as error:
            self._accept_errors += 1
            self._last_error = getattr(error, 'winerror', None) or error.errno
            if self._accept_errors >= 3:
                previous = self.transport_mode
                self.socket.close()
                try:
                    self.socket, self.transport_mode = self._new_listener(previous != 'native')
                except OSError:
                    self.socket, self.transport_mode = self._new_listener(previous == 'native')
                self._recoveries += 1
                self._accept_errors = 0
            raise


class _Connection(HTTPConnection):
    def connect(self):
        if self.host != '127.0.0.1' or self._tunnel_host:
            raise ValueError('loopback_address_required')
        for preference in (True, False):
            self.sock, mode = _make_socket(preference)
            try:
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    self.sock.settimeout(self.timeout)
                if self.source_address:
                    self.sock.bind(self.source_address)
                self.sock.connect((self.host, self.port))
                return
            except OSError:
                self.sock.close()
                self.sock = None
                if not preference or mode == 'system':
                    raise


class _Handler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_Connection, req)


def loopback_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Handler())
