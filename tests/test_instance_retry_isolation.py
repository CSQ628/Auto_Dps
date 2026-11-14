"""A slow native submission must not hold another account's automatic work."""
import copy
import threading
import unittest
from pathlib import Path

import test_scheduler as scheduler_fixture


class InstanceRetryIsolationTests(unittest.TestCase):
    setUp = scheduler_fixture.SchedulerTests.setUp
    tearDown = scheduler_fixture.SchedulerTests.tearDown
    add = scheduler_fixture.SchedulerTests.add

    def prepare(self, key, account, box):
        bridge = self.add(key, account, box)
        bridge.identity['pid'] = int(key)
        saved = Path(self.directory.name) / (key + '.zip')
        saved.touch()
        identity = (box or 'host') + ':' + account
        self.engine.durable[identity] = {
            'backup': {'status': 'created', 'version': 2, 'path': str(saved)},
            'cooldowns': {}, 'uncertain': {}, 'last_equipment': {}}
        return bridge

    def test_slow_growth_submission_does_not_block_another_accounts_growth(self):
        slow = self.prepare('1', '1001', 'sandbox1')
        fast = self.prepare('2', '1002', 'sandbox2')
        slow.entered, slow.release = threading.Event(), threading.Event()
        finished = threading.Event()
        first = threading.Thread(target=self.engine.tick, args=('1',))
        second = threading.Thread(target=lambda: (self.engine.tick('2'), finished.set()))
        first.start()
        try:
            self.assertTrue(slow.entered.wait(2))
            second.start()
            self.assertTrue(finished.wait(1), 'a slow sandbox held another account')
            self.assertEqual(len(fast.commands), 1)
            self.assertFalse(slow.release.is_set())
        finally:
            slow.release.set()
            first.join(4)
            if second.ident is not None: second.join(4)
        self.assertTrue(self.engine.config['running'])
        self.assertFalse(self.engine.config['instances'])

    def test_slow_box_read_does_not_block_another_accounts_growth(self):
        slow = self.prepare('1', '1001', 'sandbox1')
        fast = self.prepare('2', '1002', 'sandbox2')
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = slow.call
        def call(op, args=None):
            if op == 'boxscan':
                entered.set()
                if not release.wait(4): raise TimeoutError('test release')
                raise ConnectionResetError('one sandbox temporarily unavailable')
            return original(op, args)
        slow.call = call
        self.engine.instances['1'].update(status='running', account='1001', identity='sandbox1:1001',
            snapshot=copy.deepcopy(scheduler_fixture.scan()['snapshot']), box_fast_supported=True)
        first = threading.Thread(target=self.engine.tick_boxes, args=('1',))
        second = threading.Thread(target=lambda: (self.engine.tick('2'), finished.set()))
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            second.start()
            self.assertTrue(finished.wait(1), 'a retrying box read held another account')
            self.assertEqual(len(fast.commands), 1)
        finally:
            release.set()
            first.join(5)
            if second.ident is not None: second.join(5)
        self.assertEqual(self.engine.instances['1']['box_retry']['delay'], 2)
        self.assertTrue(self.engine.config['running'])
        self.assertFalse(self.engine.config['instances'])


if __name__ == '__main__':
    unittest.main()
