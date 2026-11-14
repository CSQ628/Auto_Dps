"""Bounded retries for diagnostic logs, independent of durable consumption records."""
from collections import deque
import copy
import math
import threading
import time


class RetryingEventLog:
    def __init__(self, writer, *, capacity=512, batch=16, clock=None):
        self._writer = writer
        self._capacity, self._batch = capacity, batch
        self._clock = clock or time.monotonic
        self._pending = deque()
        self._lock = threading.RLock()
        self._attempts = self._dropped = 0
        self._next_retry = 0
        self._error_type = None

    def append(self, value):
        with self._lock:
            if len(self._pending) >= self._capacity:
                self._pending.popleft()
                self._dropped += 1
            self._pending.append(copy.deepcopy(value))
            self.flush()

    def flush(self, *, force=False, limit=None):
        with self._lock:
            if not force and self._clock() < self._next_retry:
                return
            for _ in range(self._batch if limit is None else limit):
                if not self._pending:
                    break
                try:
                    self._writer(self._pending[0])
                except OSError as error:
                    self._attempts += 1
                    self._error_type = type(error).__name__
                    self._next_retry = self._clock() + min(30, 2 ** min(5, self._attempts))
                    return
                self._pending.popleft()
            if not self._pending:
                self._attempts, self._next_retry, self._error_type = 0, 0, None

    def state(self):
        with self._lock:
            return {'status': 'retrying' if self._error_type else 'draining' if self._pending else 'available',
                    'buffered': len(self._pending), 'dropped': self._dropped,
                    'attempts': self._attempts, 'error_type': self._error_type,
                    'retry_in_seconds': math.ceil(max(0, self._next_retry - self._clock()))}
