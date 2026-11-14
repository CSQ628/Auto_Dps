import copy
import threading
import unittest

import test_box_throughput as box_fixture
import test_scheduler as scheduler_fixture
import test_instance_retry_isolation as isolation_fixture


class PlayerChangeBoundaryTests(unittest.TestCase):
    setUp = scheduler_fixture.SchedulerTests.setUp
    tearDown = scheduler_fixture.SchedulerTests.tearDown
    add = scheduler_fixture.SchedulerTests.add
    prepare = isolation_fixture.InstanceRetryIsolationTests.prepare

    def test_global_pause_waits_both_inflight_accounts_and_blocks_new_submission(self):
        slow = [self.prepare(str(n), str(1000+n), 'sandbox'+str(n)) for n in (1, 2)]
        later = self.prepare('3', '1003', 'sandbox3')
        for bridge in slow: bridge.entered, bridge.release = threading.Event(), threading.Event()
        workers = [threading.Thread(target=self.engine.tick, args=(str(n),)) for n in (1, 2)]
        for worker in workers: worker.start()
        paused = threading.Event()
        def change():
            self.engine.update({'running': False}); paused.set()
        setter = threading.Thread(target=change)
        newcomer = threading.Thread(target=self.engine.tick, args=('3',))
        try:
            self.assertTrue(all(bridge.entered.wait(1) for bridge in slow))
            setter.start()
            with self.engine.submit_gate._condition:
                self.assertTrue(self.engine.submit_gate._condition.wait_for(
                    lambda: self.engine.submit_gate._waiting_writers == 1, .5))
            newcomer.start()
            slow[0].release.set()
            self.assertFalse(paused.wait(.05))
            slow[1].release.set()
            self.assertTrue(paused.wait(1))
        finally:
            for bridge in slow: bridge.release.set()
            for worker in [*workers, setter, newcomer]:
                if worker.ident is not None: worker.join(4)
        self.assertFalse(self.engine.config['running'])
        self.assertEqual(later.commands, [])
        self.assertTrue(all(len(bridge.commands) == 1 for bridge in slow))

    def test_completed_pause_migration_does_not_hold_discovery_behind_native_wait(self):
        slow = self.prepare('1', '1001', 'sandbox1')
        slow.entered, slow.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.engine.tick, args=('1',))
        recovered = threading.Event()
        def migrate(): self.engine.recover_automatic_pauses(); recovered.set()
        observer = threading.Thread(target=migrate)
        worker.start()
        try:
            self.assertTrue(slow.entered.wait(1))
            observer.start()
            self.assertTrue(recovered.wait(1))
        finally:
            slow.release.set(); worker.join(4)
            if observer.ident is not None: observer.join(4)


class BoxSubmissionBoundaryTests(unittest.TestCase):
    setUp = box_fixture.FastBoxEngineTests.setUp
    tearDown = box_fixture.FastBoxEngineTests.tearDown

    def test_slow_growth_does_not_hold_another_accounts_box_consumption(self):
        bridge = scheduler_fixture.FakeBridge('another', 'sandbox2')
        bridge.identity['pid'] = 2
        bridge.entered, bridge.release = threading.Event(), threading.Event()
        self.app.bridges['2'] = bridge
        self.app.instances['2'] = {'id': '2', 'status': 'connecting', 'confirmed': 0}
        self.app.durable['sandbox2:another'] = copy.deepcopy(self.state)
        first = threading.Thread(target=self.app.tick, args=('2',))
        completed = threading.Event()
        def tick_boxes(): self.app.tick_boxes('1'); completed.set()
        second = threading.Thread(target=tick_boxes)
        first.start()
        try:
            self.assertTrue(bridge.entered.wait(1))
            second.start()
            self.assertTrue(completed.wait(1))
            self.assertEqual(self.queue, 12)
            self.assertEqual(self.state['features']['box']['opened'], 8)
        finally:
            bridge.release.set(); first.join(4)
            if second.ident is not None: second.join(4)

    def test_concurrent_box_ticks_preserve_batch_and_scan_spacing(self):
        original = self.app.bridges['1'].call
        entered, release = threading.Event(), threading.Event()
        def call(op, args=None):
            if op == 'openboxes':
                entered.set()
                if not release.wait(3): raise TimeoutError('test release')
            return original(op, args)
        self.app.bridges['1'].call = call
        first = threading.Thread(target=self.app.tick_boxes, args=('1',))
        second = threading.Thread(target=self.app.tick_boxes, args=('1',))
        first.start()
        try:
            self.assertTrue(entered.wait(1)); second.start()
        finally:
            release.set(); first.join(4)
            if second.ident is not None: second.join(4)
        self.assertEqual(self.calls.count('openboxes'), 1)
        self.assertEqual(self.state['features']['box']['opened'], 8)
        self.assertNotIn('box_pending', self.state)


if __name__ == '__main__':
    unittest.main()
