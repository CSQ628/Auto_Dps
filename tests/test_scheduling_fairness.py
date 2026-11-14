"""Persistent module rotation must work even for the lowest native priorities."""
import copy
import json
import unittest
from dps_assistant.engine import DEFAULT
from dps_assistant.policy import choose, module_for, ranked_actions


def fixture():
    config = copy.deepcopy(DEFAULT)
    value = {'snapshot': {'loaded': True, 'currencies': {'soul': 1000, 'premium': 5}},
             'actions': [{'kind': 'box', 'key': 'box:0', 'priority': 99},
                         {'kind': 'rune', 'key': 'rune:1', 'header': 'NormalMonster',
                          'priority': 60, 'cost': {'goods': 201, 'amount': 50}}]}
    return config, value


class SchedulingFairnessTests(unittest.TestCase):
    def test_low_priority_rune_eventually_runs_with_an_endless_box_backlog(self):
        config, value = fixture()
        state = {'scheduling_started': 1000, 'last_module': {}}
        selected = []
        for offset in range(0, 1300, 10):
            now = 1000+offset
            # Native state-specific keys change on every successful action.
            for action in value['actions']:action['key'] = action['kind']+':'+str(offset)
            action = choose(value, config, state, now)
            state['last_module'][module_for(action['kind'])] = now
            if action['kind'] == 'rune':selected.append(offset)
            # Simulate the scheduler's durable checkpoint and restart.
            state = json.loads(json.dumps(state))
        self.assertGreaterEqual(len(selected), 2)
        self.assertLessEqual(selected[0], 650)
        self.assertLessEqual(selected[1]-selected[0], 650)

    def test_long_untouched_modules_all_get_a_turn_without_losing_internal_preferences(self):
        config, value = fixture()
        value['actions'] += [
            {'kind': 'rune', 'key': 'growth', 'header': 'KillExpGain', 'priority': 89},
            {'kind': 'refine', 'key': 'socket', 'priority': 90},
            {'kind': 'pet_equip', 'key': 'pet', 'priority': 80},
            {'kind': 'equipment', 'key': 'gear', 'id': 1, 'slot': 0, 'priority': 99, 'gain': .2}]
        state = {'scheduling_started': 1000, 'last_module': {}}
        selected = []
        for now in range(1000, 2801, 10):
            action = choose(value, config, state, now)
            selected.append(action)
            state['last_module'][module_for(action['kind'])] = now
        self.assertTrue({'box', 'rune', 'refine', 'pet_equip', 'equipment'} <= {a['kind'] for a in selected})
        self.assertTrue(all(a['key'] == 'growth' for a in selected if a['kind'] == 'rune'))

    def test_emergency_and_return_to_main_stay_ahead_of_arbitrarily_old_growth(self):
        config, value = fixture()
        state = {'scheduling_started': 0, 'last_module': {'rune': 0, 'progress': 999999}}
        rune = value['actions'][1]
        for action in ({'kind': 'progress', 'mode': 'guard', 'key': 'guard', 'priority': 130},
                       {'kind': 'tower_return', 'key': 'return', 'priority': 112}):
            with self.subTest(kind=action['kind']):
                value['actions'] = [rune, action]
                self.assertEqual(choose(value, config, state, 1000000)['key'], action['key'])

    def test_old_waiting_never_breaks_forge_combine_recycle_order(self):
        config, value = fixture()
        for first in ({'kind': 'forge', 'key': 'forge', 'priority': 85},
                      {'kind': 'withdraw', 'purpose': 'forge', 'key': 'materials', 'priority': 85}):
            value['actions'] = [first, {'kind': 'combine', 'key': 'combine', 'priority': 108},
                                {'kind': 'decompose', 'key': 'decompose', 'priority': 102}]
            state = {'scheduling_started': 0, 'last_module': {'forge': 1000000, 'storage': 1000000}}
            self.assertEqual(choose(value, config, state, 1000000)['key'], first['key'])
            state['cooldowns'] = {first['key']: 1000010}
            self.assertEqual(choose(value, config, state, 1000000)['key'], 'combine')
            state['cooldowns']['combine'] = 1000010
            self.assertEqual(choose(value, config, state, 1000000)['key'], 'decompose')

    def test_long_wait_cannot_override_existing_eligibility_protections(self):
        base_config, base_value = fixture()
        base_value['actions'] = [base_value['actions'][1]]
        for condition in ('paused', 'disabled', 'budget', 'manual_panel',
                          'offline', 'sync', 'cooldown', 'uncertain', 'kind_cooldown'):
            with self.subTest(condition=condition):
                config, value = copy.deepcopy(base_config), copy.deepcopy(base_value)
                state = {'scheduling_started': 0, 'last_module': {'rune': 0}}
                if condition == 'paused':config['running'] = False
                if condition == 'disabled':config['modules']['rune'] = False
                if condition == 'budget':config['soul_reserve'] = 1000
                if condition == 'manual_panel':value['snapshot']['manualBlockedKinds'] = ['rune']
                if condition == 'offline':value['snapshot']['connection'] = {'online': False}
                if condition == 'sync':value['snapshot']['sync'] = {'blocked': True}
                if condition == 'cooldown':state['cooldowns'] = {'rune:1': 1000010}
                if condition == 'uncertain':state['uncertain'] = {'rune:1': 1}
                if condition == 'kind_cooldown':state['kind_cooldowns'] = {'rune': 1000010}
                self.assertIsNone(choose(value, config, state, 1000000))

    def test_future_timestamp_and_inspection_do_not_change_source_priorities_or_state(self):
        config, value = fixture()
        state = {'scheduling_started': 2000, 'last_module': {'rune': 3000}}
        previous = copy.deepcopy((value, state))
        self.assertEqual(ranked_actions(value, config, state, 1000)[0]['kind'], 'box')
        self.assertEqual((value, state), previous)


if __name__ == '__main__':unittest.main()
