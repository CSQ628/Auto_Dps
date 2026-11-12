import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dps_assistant import engine, storage
from dps_assistant.parameters import PARAMETERS, DEFAULT_STRATEGY, apply_patch, normalize_config
from dps_assistant.policy import choose, observe_growth, equipment_ready, strength_signature


class ParameterTests(unittest.TestCase):
    def test_legacy_config_retains_budget_and_gets_every_editable_default(self):
        old = {'soul_reserve': 123, 'modules': {'box': False}, 'strategy': {'pet_mode': 'keep'}}
        config = normalize_config(old)
        self.assertEqual(len(PARAMETERS), 40)
        self.assertEqual(len({(p['scope'], p['key']) for p in PARAMETERS}), 40)
        for spec in PARAMETERS:
            values = config if spec['scope'] == 'root' else config['strategy']
            self.assertIn(spec['key'], values)
        self.assertEqual(config['soul_reserve'], 123)
        self.assertEqual(config['strategy']['pet_mode'], 'keep')
        self.assertFalse(config['modules']['box'])
        self.assertNotIn('interval', old)

    def test_partial_patch_merges_and_rejects_invalid_values_without_partial_changes(self):
        config = copy.deepcopy(engine.DEFAULT)
        changed = apply_patch(config, {'strategy': {'farm_min_seconds': 90}, 'premium_reserve': 5})
        self.assertEqual(changed['strategy']['farm_min_seconds'], 90)
        self.assertEqual(changed['strategy']['tower_retry_seconds'], DEFAULT_STRATEGY['tower_retry_seconds'])
        self.assertEqual(config, engine.DEFAULT)
        invalid = [
            {'interval': True}, {'interval': float('nan')}, {'interval': float('inf')},
            {'strategy': {'recycle_batch': 1.5}}, {'strategy': {'farm_level_offset': 0}},
            {'strategy': {'unknown': 1}}, {'strategy': {'pet_mode': 'unknown'}},
            {'strategy': {'recommended_actives': 1}}, {'strategy': []}, {'unknown': 1},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_patch(config, {'soul_reserve': 5, **value})
            self.assertEqual(config, engine.DEFAULT)

    def test_bad_saved_values_migrate_to_defaults(self):
        config = normalize_config({'interval': 'wrong', 'strategy': {'recycle_batch': False}})
        self.assertEqual(config['interval'], 2)
        self.assertEqual(config['strategy']['recycle_batch'], 12)

    def test_changed_failure_threshold_and_farm_duration_control_transition(self):
        config = copy.deepcopy(engine.DEFAULT)
        snapshot = {'record': {'maxCleared': 10, 'deaths': 0}, 'characters': [],
                    'stage': {'category': 0}, 'combat': {'available': True}}
        state = {'growth': {'phase': 'push', 'since': 100, 'frontier': 10, 'deaths': 0},
                 'battle_observation': {'outcomes': [{'category': 0, 'result': 'Failed', 'level': 11, 'observed': 110}]}}
        self.assertEqual(observe_growth(snapshot, copy.deepcopy(state), 150, config)['phase'], 'push')
        config['strategy'].update(push_wait_seconds=30, push_failure_limit=1, farm_min_seconds=30, farm_retry_seconds=30)
        self.assertEqual(observe_growth(snapshot, state, 150, config)['phase'], 'farm')
        self.assertEqual(observe_growth(snapshot, state, 179, config)['phase'], 'farm')
        self.assertEqual(observe_growth(snapshot, state, 180, config)['phase'], 'push')

    def test_tower_growth_requirement_and_retry_are_independent(self):
        config = copy.deepcopy(engine.DEFAULT)
        snap = {'loaded': True, 'record': {'maxStage': 20}, 'characters': [], 'currencies': {}}
        scan = {'snapshot': snap, 'actions': [{'kind': 'tower', 'key': 'tower:5', 'level': 5, 'priority': 90}]}
        state = {'tower_attempt': {'level': 5, 'max_stage': 20, 'strength': strength_signature(snap), 'at': 100}}
        self.assertIsNone(choose(scan, config, state, now=400))
        config['strategy'].update(tower_require_growth=False, tower_retry_seconds=60)
        self.assertIsNone(choose(scan, config, state, now=159))
        self.assertIsNotNone(choose(scan, config, state, now=160))

    def test_equipment_gain_and_retirement_settings_affect_existing_holds(self):
        config = copy.deepcopy(engine.DEFAULT)
        action = {'kind': 'equipment', 'key': 'e', 'id': 1, 'slot': 0, 'uid': 'a', 'previousUid': 'b', 'priority': 99, 'gain': .03}
        state = {'equipment_holds': {'1:0': {'uid': 'b', 'at': 100, 'retired': {'a': 400}, 'retired_at': {'a': 100}}}}
        self.assertFalse(equipment_ready(action, state, 150, config))
        config['strategy'].update(equipment_hold_seconds=10, equipment_return_seconds=30, equipment_min_gain_percent=4)
        self.assertTrue(equipment_ready(action, state, 150, config))
        scan = {'snapshot': {'loaded': True, 'currencies': {}}, 'actions': [action]}
        self.assertIsNone(choose(scan, config, state, now=150))
        config['strategy']['equipment_min_gain_percent'] = 2
        self.assertIsNotNone(choose(scan, config, state, now=150))

    def test_atomic_save_restart_and_failed_patch_keep_the_last_complete_config(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(engine, 'DATA', folder), patch.object(storage, 'DATA', folder):
                first = engine.Engine(start=False)
                second = None
                try:
                    first.update({'interval': 3.5, 'strategy': {'pet_mode': 'keep', 'recycle_batch': 4}})
                    disk = (folder/'config.json').read_bytes()
                    with self.assertRaises(ValueError):
                        first.update({'interval': 4, 'strategy': {'recycle_batch': 0}})
                    self.assertEqual((folder/'config.json').read_bytes(), disk)
                    self.assertEqual(first.config['interval'], 3.5)
                    with patch.object(engine, 'atomic_json', side_effect=OSError('disk unavailable')):
                        with self.assertRaises(OSError):
                            first.update({'interval': 4})
                    self.assertEqual(first.config['interval'], 3.5)
                    second = engine.Engine(start=False)
                    self.assertEqual(second.config, json.loads(disk))
                    self.assertEqual(second.config['strategy']['pet_mode'], 'keep')
                    self.assertEqual(len(second.public_state()['parameters']['fields']), 40)
                finally:
                    first.stop()
                    if second:
                        second.stop()
