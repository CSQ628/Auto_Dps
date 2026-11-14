"""A lost storage reply must not leave a full bag permanently reserved."""
import copy
import time
import unittest
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.policy import choose
import test_scheduler as fixture
import test_workshop_receipt_recovery as recovery_fixture


def transfer(kind='deposit', key='deposit:held:revision'):
    return {'kind': kind, 'key': key, 'uid': 'held', 'priority': 101, 'label': '存取仓库'}


class StorageRetryTests(unittest.TestCase):
    setUp = fixture.SchedulerTests.setUp
    tearDown = fixture.SchedulerTests.tearDown
    add = fixture.SchedulerTests.add

    def prepare(self):
        bridge = self.add()
        snapshot = fixture.scan()
        snapshot['actions'] = [transfer()]
        snapshot['snapshot']['inventory'] = {'count': 30, 'capacity': 30}
        original = bridge.call
        bridge.call = lambda op, args=None: copy.deepcopy(snapshot) if op == 'opportunities' else original(op, args)
        self.engine.tick('1')
        bridge.commands.clear()
        state = self.engine.durable['host:1001']
        state['uncertain'] = {transfer()['key']: time.time() - 100}
        state['cooldowns'] = {}
        return bridge, snapshot, state

    def test_legacy_full_bag_reservation_replans_only_after_native_barrier(self):
        bridge, snapshot, state = self.prepare()
        snapshot.update(storageRecoveryBarrier=1, bridgeSourceHash='new-authenticated-script')
        self.engine.tick('1')
        self.assertNotIn(transfer()['key'], state['uncertain'])
        self.assertEqual(len(bridge.commands), 0)
        state['cooldowns'] = {}
        self.engine.tick('1')
        self.assertEqual(len(bridge.commands), 1)
        self.assertTrue(self.engine.config['running'])

    def test_missing_barrier_incomplete_section_or_numbered_request_cannot_clear_unknown(self):
        for case in ('missing', 'incomplete', 'numbered'):
            bridge, snapshot, state = self.prepare()
            snapshot.update(storageRecoveryBarrier=1, bridgeSourceHash='new-authenticated-script')
            if case == 'missing': snapshot.pop('storageRecoveryBarrier')
            if case == 'incomplete': snapshot['snapshot']['planningUnavailable'] = {'workshop': 'read failed'}
            if case == 'numbered':
                state.setdefault('pending_results', {})[transfer()['key']] = {
                    'action': transfer(), 'at': time.time() - 100, 'request_id': 'unknown-request',
                    'process': {'pid': 1, 'created': 1}}
            self.engine.tick('1')
            self.assertIn(transfer()['key'], state['uncertain'], case)
            self.assertEqual(len(bridge.commands), 0, case)
            self.engine.instances, self.engine.bridges, self.engine.durable = {}, {}, {}

    def test_pending_transfer_reserves_both_sides_of_swap_but_other_growth_continues(self):
        pending = transfer('withdraw', 'withdraw:stored:swap:held')
        pending.update(uid='stored', swapUid='held')
        scan = fixture.scan()
        scan['actions'] = [{'kind': 'combine', 'key': 'combine:held', 'allowed': ['held'], 'priority': 109},
                           {'kind': 'withdraw', 'key': 'withdraw:stored:new', 'uid': 'stored', 'priority': 108},
                           scan['actions'][0]]
        state = {'pending_results': {pending['key']: {'action': pending, 'at': 100}}}
        self.assertEqual(choose(scan, engine.DEFAULT, state, now=1000)['kind'], 'rune')


class TransferReceiptTests(unittest.TestCase):
    setUp = recovery_fixture.RecoveryTests.setUp
    host = recovery_fixture.RecoveryTests.host
    connect = recovery_fixture.RecoveryTests.connect
    before_native = recovery_fixture.RecoveryTests.before_native
    close_hosts = recovery_fixture.RecoveryTests.close_hosts

    def test_lost_transfer_reply_recovers_from_disk_after_bridge_recreation(self):
        for kind in ('deposit', 'withdraw'):
            self.world['scan']['actions'] = [transfer(kind, kind + ':held')]
            first = self.host()
            self.connect(first, lose=True)
            self.harness.engine.tick('1')
            state = self.harness.engine.durable['host:1001']
            self.assertIn(kind + ':held', state['pending_results'])
            first.close()
            self.connect(self.host())
            self.world['scan']['actions'] = []
            self.harness.engine.tick('1')
            self.harness.engine.tick('1')
            self.assertFalse(state['pending_results'])
            self.assertEqual(state['features'][kind]['confirmed'], 1)
        self.assertEqual(self.world['native_calls'], 2)


if __name__ == '__main__':
    unittest.main()
