import threading
import unittest

from dps_assistant.submission import SubmissionGate


class SubmissionGateTests(unittest.TestCase):
    def test_same_instance_is_serial_but_other_instances_can_enter(self):
        gate = SubmissionGate()
        same, other = threading.Event(), threading.Event()
        def run(key, entered):
            with gate.operation(key): entered.set()
        with gate.operation('a'):
            first = threading.Thread(target=run, args=('a', same))
            second = threading.Thread(target=run, args=('b', other))
            first.start(); second.start()
            self.assertTrue(other.wait(1))
            self.assertFalse(same.wait(.05))
        first.join(2); second.join(2)
        self.assertTrue(same.is_set())
        self.assertFalse(gate._operations)

    def test_queued_player_change_precedes_new_work_and_waits_all_inflight(self):
        gate = SubmissionGate()
        first, second, writer, later = [threading.Event() for _ in range(4)]
        release_first, release_second, release_writer = [threading.Event() for _ in range(3)]
        order = []
        def operate(key, entered, release=None):
            with gate.operation(key):
                order.append(key); entered.set()
                if release is not None: release.wait(3)
        def configure():
            with gate:
                order.append('settings'); writer.set(); release_writer.wait(3)
        workers = [threading.Thread(target=operate, args=('a', first, release_first)),
                   threading.Thread(target=operate, args=('b', second, release_second))]
        for worker in workers: worker.start()
        setter = threading.Thread(target=configure)
        newcomer = threading.Thread(target=operate, args=('c', later))
        try:
            self.assertTrue(first.wait(1)); self.assertTrue(second.wait(1))
            setter.start()
            with gate._condition:
                self.assertTrue(gate._condition.wait_for(lambda: gate._waiting_writers == 1, .5))
            newcomer.start()
            release_first.set()
            self.assertFalse(writer.wait(.05)); self.assertFalse(later.is_set())
            release_second.set()
            self.assertTrue(writer.wait(1)); self.assertFalse(later.is_set())
            release_writer.set()
            self.assertTrue(later.wait(1))
        finally:
            for release in (release_first, release_second, release_writer): release.set()
            for worker in [*workers, setter, newcomer]:
                if worker.ident is not None: worker.join(4)
        self.assertLess(order.index('settings'), order.index('c'))
        self.assertFalse(gate._operations)
        self.assertIsNone(gate._writer)

    def test_reentrant_settings_and_operation_contexts_release_completely(self):
        gate = SubmissionGate()
        with gate:
            with gate:
                with gate.operation('a'):
                    with gate.operation('a'):
                        self.assertEqual(gate._operations['a'][1], 2)
        self.assertFalse(gate._operations)
        self.assertIsNone(gate._writer)
        self.assertEqual(gate._depth, 0)

    def test_exceptions_release_operations_and_settings_barrier(self):
        gate = SubmissionGate()
        with self.assertRaises(ConnectionResetError):
            with gate.operation('broken'): raise ConnectionResetError('native response lost')
        with self.assertRaises(OSError):
            with gate: raise OSError('settings disk unavailable')
        with gate.operation('healthy'): pass
        with gate: pass
        self.assertFalse(gate._operations)
        self.assertIsNone(gate._writer)

    def test_inflight_operation_cannot_deadlock_by_upgrading_to_settings(self):
        gate = SubmissionGate()
        with gate.operation('a'):
            with self.assertRaises(RuntimeError):
                with gate: pass
        with gate: pass


if __name__ == '__main__':
    unittest.main()
