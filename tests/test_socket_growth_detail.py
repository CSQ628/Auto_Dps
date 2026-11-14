import copy
import json
import unittest

from dps_assistant.policy import (choose, equipment_growth_signature, observe_growth,
                                  progression_baseline, strength_signature)
from dps_assistant.training import observe_farming
from test_growth_quality import party_fixture


def details(snapshot):
    for character in snapshot['characters']:
        for item in character.get('equipment', []):
            item['id'] = 100
            sockets = [{'index': 0, 'id': 410101, 'ability': 2, 'value': 2.2}]
            item['revision'] = json.dumps([item['uid'], item['id'], sockets[:item['sockets']]])


class SocketGrowthDetailTests(unittest.TestCase):
    def test_same_count_effect_changes_invalidate_rates_and_request_main_retry(self):
        for field, value in [('id', 410102), ('ability', 3), ('value', 3.3)]:
            with self.subTest(field=field):
                snapshot, state, config = party_fixture()
                details(snapshot)
                state['growth'].update(progression_baseline(snapshot))
                observe_farming(snapshot, state, 'game', 100, config)
                snapshot['characters'][0]['expTotal'] += 10
                observe_farming(snapshot, state, 'game', 110, config)
                item = snapshot['characters'][0]['equipment'][0]
                revision = json.loads(item['revision'])
                revision[2][0][field] = value
                item['revision'] = json.dumps(revision)
                result = observe_farming(snapshot, state, 'game', 120, config)
                self.assertEqual(result['efficiency']['measurements'], [])
                self.assertEqual(observe_growth(snapshot, state, 280, config)['retry_trigger'], 'party_growth')

    def test_revision_order_and_nonbattle_flags_do_not_reset_a_sample(self):
        snapshot, _, _ = party_fixture()
        item = snapshot['characters'][0]['equipment'][0]
        item['sockets'] = 2
        details(snapshot)
        revision = json.loads(item['revision'])
        revision[2].append({'index': 0, 'id': 420101, 'ability': 3, 'value': 4})
        item['revision'] = json.dumps(revision)
        before = strength_signature(snapshot)
        revision[2].reverse()
        item.update(revision=json.dumps(revision, indent=2), locked=True, confirmed=False)
        self.assertEqual(strength_signature(snapshot), before)

    def test_revision_upgrade_preserves_existing_retry_and_settlement_wait(self):
        snapshot, state, config = party_fixture()
        state['growth'].update(progression_baseline(snapshot), retry_requested_at=250, retry_trigger='party_growth')
        snapshot['combat']['current']['elapsed'] = 80
        details(snapshot)
        result = observe_growth(snapshot, state, 280, config)
        self.assertEqual(state['growth']['since'], 100)
        self.assertEqual(state['growth']['retry_requested_at'], 250)
        self.assertTrue(result['retry_pending'])
        self.assertEqual(state['growth']['equipment_strength_scope'], 'socket_effects_v1')

    def test_missing_or_wrong_item_revision_uses_the_existing_count_fallback(self):
        snapshot, _, _ = party_fixture()
        before = strength_signature(snapshot)
        details(snapshot)
        item = snapshot['characters'][0]['equipment'][0]
        for revision in ['not-json', '[]', '["other",100,[]]',
                         json.dumps(['weapon', 100, [{'index': 0, 'id': 1, 'ability': 2, 'value': float('nan')}]]),
                         json.dumps(['weapon', 100, [{'index': True, 'id': 1, 'ability': 2, 'value': 1}]]),
                         json.dumps(['weapon', 100, [{'index': 0, 'id': 1, 'ability': 2, 'value': 10**400}]]),
                         json.dumps(['weapon', 100, []])]:
            item['revision'] = revision
            self.assertEqual(strength_signature(snapshot), before)

    def test_tower_cooldown_rebases_metadata_but_detects_a_later_effect_change(self):
        snapshot, state, config = party_fixture()
        config['modules']['tower'] = True
        snapshot['catalogue'] = {'normalMax': 10}
        snapshot['record']['maxStage'] = 10
        snapshot['stage'].update(running=False, ending=True)
        state['growth']['phase'] = 'endgame'
        state['tower_attempt'] = {'level': 1, 'max_stage': 10, 'at': 100, **progression_baseline(snapshot)}
        details(snapshot)
        scan = {'snapshot': snapshot, 'actions': [{'kind': 'tower', 'key': 'tower', 'level': 1, 'priority': 79}]}
        self.assertIsNone(choose(scan, config, state, 500))
        self.assertEqual(state['tower_attempt']['at'], 100)
        item = snapshot['characters'][0]['equipment'][0]
        revision = json.loads(item['revision'])
        revision[2][0]['value'] += 1
        item['revision'] = json.dumps(revision)
        self.assertIsNotNone(choose(scan, config, state, 501))

    def test_bench_details_and_gear_independent_swap_epoch_stay_unchanged(self):
        snapshot, _, _ = party_fixture()
        details(snapshot)
        before = strength_signature(snapshot)
        epoch = equipment_growth_signature(snapshot)
        reserve = snapshot['characters'][1]
        reserve['equipment'] = copy.deepcopy(snapshot['characters'][0]['equipment'])
        reserve['equipment'][0]['revision'] = 'different reserve metadata'
        self.assertEqual(strength_signature(snapshot), before)
        item = snapshot['characters'][0]['equipment'][0]
        revision = json.loads(item['revision'])
        revision[2][0]['value'] += 1
        item['revision'] = json.dumps(revision)
        self.assertEqual(equipment_growth_signature(snapshot), epoch)


if __name__ == '__main__':
    unittest.main()
