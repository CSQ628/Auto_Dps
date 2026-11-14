import json
import unittest

from test_farm_efficiency import fixture
from dps_assistant.policy import choose, observe_growth, progression_signature
from dps_assistant.training import observe_farming


class GrowthRetryBoundaryTests(unittest.TestCase):
    def prepare(self):
        snapshot, state, config = fixture()
        snapshot['record']['deaths'] = 0
        snapshot['combat']['current']['elapsed'] = 80
        state['growth'].update(frontier=10, since=100, deaths=0,
                               progress_strength=progression_signature(snapshot))
        config['strategy'].update(farm_min_seconds=30, farm_retry_seconds=60,
                                  farm_retry_finish_seconds=90)
        self.actions = [{'kind': 'progress', 'key': 'boss:11', 'mode': 'boss',
                         'phase': 'travel', 'level': 11, 'difficulty': 0, 'priority': 108}]
        return snapshot, state, config

    def test_growth_retry_waits_for_the_free_battle_to_finish(self):
        snapshot, state, config = self.prepare()
        snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'upgrade'}]
        growth = observe_growth(snapshot, state, 130, config)
        self.assertEqual(growth['phase'], 'farm')
        self.assertTrue(growth['retry_pending'])
        self.assertIsNone(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 130))
        snapshot['combat']['current']['result'] = 'Cleared'
        self.assertEqual(observe_growth(snapshot, state, 140, config)['phase'], 'push')
        self.assertEqual(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 140)['mode'], 'boss')

    def test_periodic_retry_accepts_a_new_round_or_native_settlement(self):
        for boundary in ('new_round', 'Cleared', 'Failed'):
            with self.subTest(boundary=boundary):
                snapshot, state, config = self.prepare()
                self.assertEqual(observe_growth(snapshot, state, 160, config)['phase'], 'farm')
                if boundary == 'new_round':
                    snapshot['combat']['current'].update(sequence=2, elapsed=1)
                else:
                    snapshot['combat']['current']['result'] = boundary
                self.assertEqual(observe_growth(snapshot, state, 170, config)['phase'], 'push')

    def test_delayed_dispatch_checks_the_battle_again(self):
        snapshot, state, config = self.prepare()
        snapshot['combat']['current']['elapsed'] = 1
        self.assertEqual(observe_growth(snapshot, state, 160, config)['phase'], 'push')
        snapshot['combat']['current'].update(sequence=2, elapsed=65)
        self.assertIsNone(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 175))
        snapshot['combat']['current']['elapsed'] = 1
        self.assertIsNotNone(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 180))

    def test_wait_has_a_limit_even_when_the_battle_or_statistics_are_stuck(self):
        for stats in (True, False):
            with self.subTest(stats=stats):
                snapshot, state, config = self.prepare()
                snapshot['combat']['available'] = stats
                self.assertEqual(observe_growth(snapshot, state, 160, config)['phase'], 'farm')
                self.assertEqual(observe_growth(snapshot, state, 249, config)['phase'], 'farm')
                self.assertEqual(observe_growth(snapshot, state, 250, config)['phase'], 'push')
                self.assertIsNotNone(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 250))

    def test_missing_ticket_keeps_farming_until_the_native_gate_clears(self):
        snapshot, state, config = self.prepare()
        snapshot['combat']['current']['elapsed'] = 1
        snapshot['progression']['gate'] = {'level': 11, 'reason': 'ticket_missing'}
        self.assertEqual(observe_growth(snapshot, state, 1000, config)['phase'], 'farm')
        self.assertNotIn('retry_requested_at', state['growth'])
        snapshot['progression']['gate'] = None
        self.assertEqual(observe_growth(snapshot, state, 1001, config)['phase'], 'push')

    def test_initial_frontier_push_keeps_existing_entry_reservation_behavior(self):
        snapshot, state, config = self.prepare()
        state['growth']['phase'] = 'push'
        self.assertIsNotNone(choose({'snapshot': snapshot, 'actions': self.actions}, config, state, 160))

    def test_frontier_progress_clears_an_old_retry_request(self):
        snapshot, state, config = self.prepare()
        observe_growth(snapshot, state, 160, config)
        snapshot['record']['maxCleared'] = 11
        self.assertEqual(observe_growth(snapshot, state, 170, config)['phase'], 'push')
        self.assertNotIn('retry_requested_at', state['growth'])


class FarmProbeEpochTests(unittest.TestCase):
    def test_frequent_growth_cannot_extend_one_unmeasurable_map_without_a_bound(self):
        for change in ('rune', 'equipment', 'pet'):
            with self.subTest(change=change):
                snapshot, state, config = fixture()
                config['strategy']['farm_probe_seconds'] = 60
                for at in range(100, 221, 10):
                    if at > 100 and (at - 100) % 20 == 0:
                        if change == 'rune': snapshot['runes'] = {'learned': at}
                        if change == 'equipment': snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': str(at)}]
                        if change == 'pet': snapshot['pets'] = {'unlocked': at}
                    snapshot['characters'][0]['expTotal'] += 100
                    result = observe_farming(snapshot, state, 'game', at, config)
                    self.assertEqual(result['level'], 8 if at == 220 else 9)
                self.assertEqual(state['farm_route']['visit_active_seconds'], 120)
                self.assertEqual(state['farm_route']['active_seconds'], 0)
                self.assertFalse(result['efficiency']['measurements'])
                self.assertEqual(result['efficiency']['recent_tested_count'], 0)

    def test_total_probe_survives_scheduler_reload_but_not_unobserved_time(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        for at in range(100, 151, 10):
            snapshot['runes'] = {'learned': at}
            observe_farming(snapshot, state, 'game', at, config)
        state = json.loads(json.dumps(state))
        config['running'] = False
        observe_farming(snapshot, state, 'game', 160, config)
        config['running'] = True
        snapshot['runes'] = {'learned': 1000}
        observe_farming(snapshot, state, 'game', 1000, config)
        self.assertEqual(state['farm_route']['visit_active_seconds'], 50)
        for at in range(1010, 1071, 10):
            snapshot['runes'] = {'learned': at}
            result = observe_farming(snapshot, state, 'game', at, config)
        self.assertEqual(result['level'], 8)

    def test_new_visit_party_or_process_does_not_inherit_a_probe_budget(self):
        for change in ('destination', 'party', 'session', 'frontier'):
            with self.subTest(change=change):
                snapshot, state, config = fixture()
                snapshot['record']['maxCleared'] = 9
                config['strategy']['farm_probe_seconds'] = 60
                for at in range(100, 151, 10):
                    observe_farming(snapshot, state, 'game', at, config)
                session = 'game'
                if change == 'destination':
                    state['farm_route'].update(level=8, since=155)
                    snapshot['stage']['level'] = snapshot['combat']['current']['level'] = 8
                if change == 'party':
                    snapshot['squad'] = [2]
                    snapshot['characters'][0]['id'] = 2
                if change == 'session': session = 'new-game'
                if change == 'frontier': snapshot['record']['maxCleared'] = 10
                observe_farming(snapshot, state, session, 160, config)
                self.assertEqual(state['farm_route']['visit_active_seconds'], 0)

    def test_frontier_retry_owns_the_boundary_even_after_repeated_growth_probe_expires(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        state['growth']['retry_requested_at'] = 100
        for at in range(100, 231, 10):
            snapshot['runes'] = {'learned': at}
            result = observe_farming(snapshot, state, 'game', at, config)
            self.assertEqual(result['level'], 9)
        self.assertFalse(state['farm_route']['failed_stages'])
        state['growth'].pop('retry_requested_at')
        self.assertEqual(observe_farming(snapshot, state, 'game', 240, config)['level'], 8)

    def test_ready_current_strength_sample_wins_over_expired_visit_clock(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        snapshot['progression']['farmCandidates'] = [{'level': 9, 'difficulty': 0}]
        for at in range(100, 251, 10):
            snapshot['characters'][0]['expTotal'] += 10
            state['battle_observation'] = {'outcomes': [{'sequence': 1, 'category': 0, 'level': 9,
                'difficulty': 0, 'result': 'Cleared', 'farming': True, 'started': 100.1, 'observed': 130}]}
            result = observe_farming(snapshot, state, 'game', at, config)
        self.assertEqual(result['level'], 9)
        self.assertEqual(result['efficiency']['recent_tested_count'], 1)
        self.assertFalse(state['farm_route']['failed_stages'])

    def test_ineligible_observations_do_not_spend_either_probe_clock(self):
        for boundary in ('offline', 'popup', 'loading', 'transition', 'tower_without_candidates'):
            with self.subTest(boundary=boundary):
                snapshot, state, config = fixture()
                observe_farming(snapshot, state, 'game', 100, config)
                observe_farming(snapshot, state, 'game', 110, config)
                if boundary == 'offline': snapshot['connection']['online'] = False
                if boundary == 'popup': snapshot['experienceBlocked'] = True
                if boundary == 'loading': snapshot['battleReadiness']['syncRunning'] = True
                if boundary == 'transition': state['pending_results'] = {'travel': {'action': {'kind': 'progress', 'phase': 'travel'}}}
                if boundary == 'tower_without_candidates':
                    snapshot['stage']['category'] = 1
                    snapshot['progression']['farmCandidates'] = []
                observe_farming(snapshot, state, 'game', 112, config)
                snapshot['connection']['online'] = True
                snapshot['experienceBlocked'] = False
                snapshot['battleReadiness']['syncRunning'] = False
                state.pop('pending_results', None)
                snapshot['stage']['category'] = 0
                snapshot['progression']['farmCandidates'] = [{'level': 9, 'difficulty': 0}, {'level': 8, 'difficulty': 0}]
                observe_farming(snapshot, state, 'game', 114, config)
                self.assertEqual(state['farm_route']['active_seconds'], 10)
                self.assertEqual(state['farm_route']['visit_active_seconds'], 10)

    def test_minimum_sample_window_also_bounds_the_total_visit_grant(self):
        snapshot, state, config = fixture()
        config['strategy'].update(farm_probe_seconds=60, farm_sample_seconds=90)
        for at in range(100, 281, 10):
            snapshot['runes'] = {'learned': at}
            result = observe_farming(snapshot, state, 'game', at, config)
            self.assertEqual(result['level'], 8 if at == 280 else 9)

    def test_upgrade_gives_the_new_strength_a_full_probe_without_old_rates(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        for at in range(100, 151, 10):
            observe_farming(snapshot, state, 'game', at, config)
        self.assertEqual(state['farm_route']['active_seconds'], 50)
        snapshot['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'upgrade'}]
        result = observe_farming(snapshot, state, 'game', 160, config)
        self.assertEqual(result['level'], 9)
        self.assertEqual(state['farm_route']['active_seconds'], 0)
        self.assertFalse(result['efficiency']['measurements'])
        for at in range(170, 220, 10):
            result = observe_farming(snapshot, state, 'game', at, config)
            self.assertEqual(result['level'], 9)
        result = observe_farming(snapshot, state, 'game', 220, config)
        self.assertEqual(result['level'], 8)

    def test_a_pending_frontier_retry_does_not_first_move_to_another_farming_map(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        for at in range(100, 151, 10):
            observe_farming(snapshot, state, 'game', at, config)
        state['growth']['retry_requested_at'] = 155
        result = observe_farming(snapshot, state, 'game', 160, config)
        self.assertEqual(result['level'], 9)
        self.assertFalse(state['farm_route']['failed_stages'])
        state['growth'].pop('retry_requested_at')
        self.assertEqual(observe_farming(snapshot, state, 'game', 170, config)['level'], 8)

    def test_cache_reinitialization_does_not_inherit_an_almost_expired_probe(self):
        snapshot, state, config = fixture()
        config['strategy']['farm_probe_seconds'] = 60
        for at in range(100, 151, 10):
            observe_farming(snapshot, state, 'game', at, config)
        state['farm_efficiency'].pop('schema')
        result = observe_farming(snapshot, state, 'game', 160, config)
        self.assertEqual(result['level'], 9)
        self.assertEqual(state['farm_route']['active_seconds'], 0)
        self.assertFalse(result['efficiency']['measurements'])


if __name__ == '__main__':
    unittest.main()
