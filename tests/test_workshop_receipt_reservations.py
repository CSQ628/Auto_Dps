"""Unknown workshop consumption owns its materials across replans and restarts."""
import copy
import unittest
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.policy import choose
from dps_assistant.diagnostics import diagnostics
import test_scheduler


def action(kind='combine', uid='material', key='workshop:old'):
    value = {'kind': kind, 'key': key, 'label': '工坊', 'priority': 109,
            'category': 2, 'tier': 0, 'maxGrade': 1, 'part': 1, 'id': 1, 'slot': 0,
            'allowed': [uid], 'materialCounts': {uid: 9}, 'batchSize': 9}
    if kind == 'refine':
        value['uid'] = 'target'
    return value


class WorkshopReceiptTests(unittest.TestCase):
    def run_engine(self, kind, response='pending'):
        harness = test_scheduler.SchedulerTests()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        bridge = harness.add()
        value = test_scheduler.scan()
        value['actions'] = [action(kind)]
        original = bridge.call

        def call(op, args=None):
            if op == 'opportunities':
                return copy.deepcopy(value)
            if op == 'execute':
                saved = storage.load_json(engine.DATA / 'scheduler.json', {})['host:1001']
                self.assertIn(args['key'], saved['pending_results'])
                bridge.commands.append(args)
                if response == 'lost':
                    raise TimeoutError('lost workshop reply')
                return {'status': response}
            return original(op, args)

        bridge.call = call
        harness.engine.tick('1')
        return harness, bridge, value

    def test_pending_consumption_is_durable_before_native_submission(self):
        for kind in ('combine', 'forge', 'refine', 'decompose'):
            with self.subTest(kind=kind):
                harness, bridge, value = self.run_engine(kind)
                saved = storage.load_json(engine.DATA / 'scheduler.json', {})['host:1001']
                self.assertEqual(saved['pending_results']['workshop:old']['action']['allowed'], ['material'])
                self.assertEqual(len(bridge.commands), 1)

    def test_lost_and_pending_receipts_survive_replanning_and_reload_without_reconsumption(self):
        for response in ('pending', 'lost'):
            for kind in ('combine', 'forge', 'refine', 'decompose'):
                with self.subTest(response=response, kind=kind):
                    harness, bridge, value = self.run_engine(kind, response)
                    value['actions'] = []
                    harness.engine.tick('1')
                    harness.engine.durable = storage.load_json(engine.DATA / 'scheduler.json', {})
                    state = harness.engine.durable['host:1001']
                    self.assertIn('workshop:old', state['uncertain'])
                    changed = action(kind, key='workshop:new-count-and-position')
                    independent = action('forge', uid='other-material', key='independent')
                    value['actions'] = [changed, independent]
                    harness.engine.tick('1')
                    self.assertEqual([c['key'] for c in bridge.commands], ['workshop:old', 'independent'])
                    self.assertTrue(harness.engine.config['running'])

    def test_known_terminal_results_release_the_material_reservation(self):
        for status in ('confirmed', 'rejected', 'waiting', 'stale', 'no_change'):
            with self.subTest(status=status):
                harness, bridge, _ = self.run_engine('combine', status)
                self.assertFalse(harness.engine.durable['host:1001'].get('pending_results'))
                self.assertFalse(harness.engine.durable['host:1001']['uncertain'])

    def test_unsent_disk_failure_rolls_back_material_reservations(self):
        harness, bridge, value = self.run_engine('combine', 'confirmed')
        value['actions'] = [action(key='second')]
        with patch.object(harness.engine, 'save', side_effect=OSError('disk busy')):
            harness.engine.tick('1')
        state = harness.engine.durable['host:1001']
        self.assertFalse(state.get('pending_results'))
        self.assertNotIn('second', state['uncertain'])
        self.assertEqual(len(bridge.commands), 1)

    def test_unknown_materials_are_not_moved_equipped_sorted_or_consumed_by_another_recipe(self):
        state = {'pending_results': {'old': {'at': 1, 'action': action('refine')}}}
        shared = [action('forge', key='forge-other'), action('decompose', key='recycle'),
                  {'kind': 'withdraw', 'key': 'take', 'uid': 'material', 'purpose': 'combine', 'priority': 110},
                  {'kind': 'withdraw', 'key': 'swap', 'uid': 'other', 'swapUid': 'material', 'purpose': 'forge', 'priority': 110},
                  {'kind': 'equipment', 'key': 'equip', 'uid': 'new', 'previousUid': 'target', 'id': 1, 'slot': 0, 'priority': 110},
                  {'kind': 'sort', 'key': 'sort', 'place': 'inventory', 'priority': 110}]
        value = test_scheduler.scan()
        independent = value['actions'][0]
        for candidate in shared:
            with self.subTest(kind=candidate['kind']):
                value['actions'] = [candidate, independent]
                self.assertEqual(choose(value, engine.DEFAULT, state)['key'], independent['key'])

    def test_other_accounts_and_unrelated_materials_remain_available(self):
        value = test_scheduler.scan()
        value['actions'] = [action()]
        reserved = {'pending_results': {'old': {'at': 1, 'action': action()}}}
        self.assertIsNone(choose(value, engine.DEFAULT, reserved))
        self.assertEqual(choose(value, engine.DEFAULT, {})['key'], 'workshop:old')
        value['actions'][0] = action(uid='independent')
        self.assertIsNotNone(choose(value, engine.DEFAULT, reserved))

    def test_workshop_waiting_diagnostics_exclude_material_and_account_identifiers(self):
        result = diagnostics({'instances': [{'workshop_pending': [
            {'kind': 'combine', 'since': 100, 'uid': 'private-item', 'account': 'private-player'},
            {'kind': 'private-kind', 'since': 200}]}]})
        self.assertEqual(result['instances'][0]['workshop_pending'], [{'kind': 'combine', 'since': 100}])
        self.assertNotIn('private', str(result))


if __name__ == '__main__':
    unittest.main()
