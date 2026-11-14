import unittest

from test_farm_efficiency import fixture
from dps_assistant import policy
from dps_assistant.training import observe_farming


def party_fixture():
    snapshot, state, config = fixture()
    snapshot['stage']['level'] = 9
    snapshot['combat']['current'].update(level=9, elapsed=1)
    snapshot['pets'] = {'equipped': 'combat-pet', 'unlocked': 2}
    snapshot['characters'][0].update(equipment=[{'slot': 0, 'uid': 'weapon', 'sockets': 1},
                                                {'slot': 1, 'uid': 'shield', 'sockets': 0}],
                                     skills=[{'kind': 'active', 'skill': 'strike', 'level': 2},
                                             {'kind': 'passive', 'skill': 'health', 'level': 1}],
                                     activeLoadout=['strike'])
    snapshot['characters'].append({'id': 2, 'level': 5, 'expTotal': 500, 'skills': []})
    snapshot['record']['deaths'] = 0
    config['strategy'].update(farm_min_seconds=180, farm_retry_seconds=600)
    state['growth'] = {'phase': 'push', 'since': 0, 'frontier': 10, 'deaths': 0}
    snapshot['progression']['gate'] = {'level': 11, 'reason': 'ticket_missing'}
    policy.observe_growth(snapshot, state, 100, config)
    snapshot['progression']['gate'] = None
    return snapshot, state, config


class GrowthQualityTests(unittest.TestCase):
    def test_contextual_pet_switch_does_not_create_growth_or_bypass_the_periodic_interval(self):
        snapshot, state, config = party_fixture()
        snapshot['pets']['equipped'] = 'growth-pet'
        self.assertEqual(policy.observe_growth(snapshot, state, 280, config)['phase'], 'farm')
        self.assertEqual(policy.observe_growth(snapshot, state, 699, config)['phase'], 'farm')
        result = policy.observe_growth(snapshot, state, 700, config)
        self.assertEqual(result['phase'], 'push')
        self.assertEqual(result['retry_trigger'], 'retry_interval')

    def test_bench_hero_growth_does_not_retry_the_unchanged_frontline(self):
        for change in ('level', 'skill', 'equipment'):
            with self.subTest(change=change):
                snapshot, state, config = party_fixture()
                reserve = snapshot['characters'][1]
                if change == 'level': reserve['level'] += 1
                if change == 'skill': reserve['skills'] = [{'skill': 'reserve-skill', 'level': 2}]
                if change == 'equipment': reserve['equipment'] = [{'slot': 0, 'uid': 'reserve-weapon'}]
                self.assertEqual(policy.observe_growth(snapshot, state, 280, config)['phase'], 'farm')

    def test_party_growth_new_pet_unlock_and_permanent_runes_still_retry(self):
        for change in ('level', 'skill', 'equipment', 'socket', 'loadout', 'formation', 'rune', 'pet_unlock'):
            with self.subTest(change=change):
                snapshot, state, config = party_fixture()
                hero = snapshot['characters'][0]
                if change == 'level': hero['level'] += 1
                if change == 'skill': hero['skills'][0]['level'] += 1
                if change == 'equipment': hero['equipment'][0]['uid'] = 'better-weapon'
                if change == 'socket': hero['equipment'][0]['sockets'] += 1
                if change == 'loadout': hero['activeLoadout'].append('new-skill')
                if change == 'formation': snapshot['squad'] = [2]
                if change == 'rune': snapshot['runes'] = {'learned': 1}
                if change == 'pet_unlock': snapshot['pets']['unlocked'] += 1
                self.assertEqual(policy.observe_growth(snapshot, state, 279, config)['phase'], 'farm')
                result = policy.observe_growth(snapshot, state, 280, config)
                self.assertEqual(result['phase'], 'push')
                self.assertEqual(result['retry_trigger'], 'party_growth')

    def test_native_collection_order_does_not_change_the_party_state(self):
        snapshot, state, config = party_fixture()
        before = policy.strength_signature(snapshot)
        hero = snapshot['characters'][0]
        hero['skills'].reverse();hero['equipment'].reverse();snapshot['characters'].reverse()
        self.assertEqual(policy.strength_signature(snapshot), before)
        self.assertEqual(policy.observe_growth(snapshot, state, 280, config)['phase'], 'farm')

    def test_old_farm_baseline_is_rebased_once_without_forcing_an_upgrade_retry(self):
        snapshot, state, config = party_fixture()
        state['growth'].pop('progress_strength', None)
        state['growth']['strength'] = 'legacy-baseline-with-private-ids'
        state['growth']['retry_requested_at'] = 200
        state['growth']['retry_trigger'] = 'party_growth'
        result = policy.observe_growth(snapshot, state, 280, config)
        self.assertEqual(result['phase'], 'farm')
        self.assertNotIn('retry_requested_at', state['growth'])
        baseline = state['growth']['progress_strength']
        policy.observe_growth(snapshot, state, 290, config)
        self.assertEqual(state['growth']['progress_strength'], baseline)
        self.assertEqual(state['growth']['since'], 100)
        self.assertEqual(policy.observe_growth(snapshot, state, 700, config)['phase'], 'push')

    def test_upgrade_keeps_the_finish_wait_for_an_already_requested_push(self):
        snapshot, state, config = party_fixture()
        state['growth'].update(phase='push', retry_requested_at=250)
        state['growth'].pop('progress_strength')
        snapshot['combat']['current']['elapsed'] = 80
        result = policy.observe_growth(snapshot, state, 280, config)
        self.assertTrue(result['retry_pending'])
        self.assertEqual(state['growth']['retry_requested_at'], 250)
        actions = [{'kind':'progress','mode':'boss','phase':'travel','level':11,
                    'difficulty':0,'key':'boss','priority':108}]
        self.assertIsNone(policy.choose({'snapshot':snapshot,'actions':actions},config,state,280))

    def test_experience_samples_keep_pet_changes_but_ignore_reserve_growth_and_order(self):
        snapshot, state, config = party_fixture()
        observe_farming(snapshot, state, 'game', 100, config)
        snapshot['characters'][0]['expTotal'] += 10
        observe_farming(snapshot, state, 'game', 110, config)
        route_since = state['farm_route']['since']
        snapshot['characters'][1]['level'] += 1
        snapshot['characters'][0]['skills'].reverse()
        snapshot['characters'][0]['expTotal'] += 10
        result = observe_farming(snapshot, state, 'game', 120, config)
        self.assertEqual(state['farm_route']['since'], route_since)
        self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'], 20)
        snapshot['pets']['equipped'] = 'growth-pet'
        result = observe_farming(snapshot, state, 'game', 130, config)
        self.assertEqual(result['efficiency']['measurements'][0]['observed_seconds'], 30)
        self.assertEqual(state['farm_route']['active_seconds'], 30)

    def test_tower_requires_real_growth_after_returning_to_a_different_pet(self):
        snapshot, state, config = party_fixture()
        config['modules']['tower'] = True
        snapshot.update(catalogue={'normalMax': 10}, runes={'learned': 2})
        snapshot['record']['maxStage'] = 10
        snapshot['stage'].update(running=False, ending=True)
        state['growth']['phase'] = 'endgame'
        signature = getattr(policy, 'progression_signature', policy.strength_signature)(snapshot)
        state['tower_attempt'] = {'level': 1, 'max_stage': 10, 'at': 100,
                                  'strength': policy.strength_signature(snapshot), 'progress_strength': signature}
        snapshot['pets']['equipped'] = 'growth-pet'
        actions = [{'kind': 'tower', 'key': 'tower:1', 'level': 1, 'priority': 79}]
        self.assertIsNone(policy.choose({'snapshot': snapshot, 'actions': actions}, config, state, 500))
        snapshot['characters'][0]['level'] += 1
        self.assertIsNotNone(policy.choose({'snapshot': snapshot, 'actions': actions}, config, state, 501))

    def test_legacy_tower_attempt_does_not_count_a_pet_execution_as_growth(self):
        snapshot, state, config = party_fixture()
        config['modules']['tower'] = True
        snapshot['catalogue'] = {'normalMax': 10}
        snapshot['record']['maxStage'] = 10
        snapshot['stage'].update(running=False, ending=True)
        state['growth']['phase'] = 'endgame'
        state['tower_attempt'] = {'level': 1, 'max_stage': 10, 'at': 100}
        state['features'] = {'pet_equip': {'last_status': 'confirmed', 'last_at': 200}}
        actions = [{'kind': 'tower', 'key': 'tower:1', 'level': 1, 'priority': 79}]
        self.assertIsNone(policy.choose({'snapshot': snapshot, 'actions': actions}, config, state, 500))
        state['features']['equipment'] = {'last_status': 'confirmed', 'last_at': 250}
        self.assertIsNotNone(policy.choose({'snapshot': snapshot, 'actions': actions}, config, state, 501))


if __name__ == '__main__':
    unittest.main()
