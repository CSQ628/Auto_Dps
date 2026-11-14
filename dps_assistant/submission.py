"""Independent native submissions, with an exclusive barrier for player settings."""
from contextlib import contextmanager
import threading


class SubmissionGate:
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._operations = {}
        self._writer = None
        self._depth = 0
        self._waiting_writers = 0

    def __enter__(self):
        owner = threading.get_ident()
        with self._condition:
            if self._writer == owner:
                self._depth += 1
                return self
            if any(value[0] == owner for value in self._operations.values()):
                raise RuntimeError('cannot change settings within a native submission')
            self._waiting_writers += 1
            try:
                self._condition.wait_for(lambda: self._writer is None and not self._operations)
                self._writer, self._depth = owner, 1
            finally:
                self._waiting_writers -= 1
                self._condition.notify_all()
        return self

    def __exit__(self, *exception):
        with self._condition:
            if self._writer != threading.get_ident():
                raise RuntimeError('submission settings barrier is not owned')
            self._depth -= 1
            if not self._depth:
                self._writer = None
                self._condition.notify_all()

    @contextmanager
    def operation(self, key):
        owner = threading.get_ident()
        with self._condition:
            def available():
                existing = self._operations.get(key)
                if existing and existing[0] != owner:
                    return False
                if self._writer is not None:
                    return self._writer == owner
                # Waiting manual changes take priority over new native work.
                return not self._waiting_writers or any(
                    value[0] == owner for value in self._operations.values())
            self._condition.wait_for(available)
            previous = self._operations.get(key)
            self._operations[key] = (owner, previous[1] + 1 if previous else 1)
        try:
            yield
        finally:
            with self._condition:
                depth = self._operations[key][1] - 1
                if depth:
                    self._operations[key] = (owner, depth)
                else:
                    del self._operations[key]
                self._condition.notify_all()
