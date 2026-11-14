import copy
import unittest

from test_farm_efficiency import fixture, visit
from dps_assistant.training import observe_farming
from dps_assistant.policy import choose, observe_growth


class ExplorationTests(unittest.TestCase):
    def test_level_up_preserves_coverage_and_prioritizes_the_highest_map(self):
        s, state, config = fixture()
        visit(s, state, config, 100, 10, 9, 1)
        s['characters'][0]['level'] += 1
        result = observe_farming(s, state, 'game', 140, config)
        self.assertEqual(result['level'], 9)
        self.assertEqual(result['efficiency']['visited_count'], 1)
        self.assertFalse(result['efficiency']['measurements'])

    def test_old_low_maps_cannot_reenter_after_level_changes_or_stale_candidates(self):
        s, state, config = fixture()
        s['record']['maxCleared'] = 30
        s['progression']['farmCandidates'] = [{'level': n, 'difficulty': 0} for n in range(1, 30)]
        for index in range(5):
            result = observe_farming(s, state, 'game', 100+index*20, config)
            self.assertEqual(result['level'], 29)
            s['characters'][0]['level'] += 1
        s['progression']['farmCandidates'] = [{'level': 19, 'difficulty': 0}]
        self.assertIsNone(observe_farming(s, state, 'game', 220, config))
        state['growth']['phase'] = 'farm';state.pop('farm_route', None)
        actions=[{'kind':'progress','key':'low','mode':'farm','level':19,'difficulty':0,'priority':107}]
        self.assertIsNone(choose({'snapshot':s,'actions':actions},config,state,220))

    def test_previous_chapter_stage_zero_is_rejected_even_if_stale_band_says_it_is_free(self):
        s, state, config = fixture()
        s['record']['maxCleared'] = 39
        s['progression']['farmBand'] = {'start':30,'end':39,'minLevel':30,'maxLevel':39,
                                        'chapter':3,'policy':'chapter_exp_efficiency'}
        s['progression']['farmCandidates'] = [{'level':n,'difficulty':0} for n in (39,38,31,30)]
        result = observe_farming(s, state, 'game', 100, config)
        self.assertEqual(result['level'], 39)
        state['farm_route'].update(level=30,difficulty=0)
        result = observe_farming(s, state, 'game', 110, config)
        self.assertEqual(result['level'], 39)
        self.assertEqual(result['efficiency']['chapter'], 4)
        self.assertGreaterEqual(result['efficiency']['band_min'], 31)

    def test_a_cleared_paid_boss_keeps_the_highest_free_map_with_a_one_map_range(self):
        s, state, config = fixture();config['strategy']['farm_candidate_count'] = 1
        s['progression']['farmBand'] = {'maxLevel':9,'minLevel':9}
        self.assertEqual(observe_farming(s,state,'game',100,config)['level'],9)

    def test_an_unkillable_high_map_times_out_without_a_fake_experience_rate(self):
        s, state, config = fixture();config['strategy']['farm_probe_seconds'] = 60
        for at in range(100, 161, 10):
            s['characters'][0]['expTotal'] += 10
            s['combat']['current']['elapsed'] = at
            result = observe_farming(s, state, 'game', at, config)
        self.assertEqual(result['level'], 8)
        self.assertEqual(state['farm_route']['failed_stages'], ['9:0'])
        self.assertIsNone(result['efficiency']['measurements'][0]['per_minute'])

    def test_pause_and_unobserved_wall_time_do_not_exhaust_a_probe(self):
        s, state, config = fixture();config['strategy']['farm_probe_seconds'] = 60
        observe_farming(s, state, 'game', 100, config)
        observe_farming(s, state, 'game', 110, config)
        config['running'] = False
        observe_farming(s, state, 'game', 500, config)
        config['running'] = True
        result = observe_farming(s, state, 'game', 1000, config)
        self.assertEqual(result['level'], 9)
        self.assertEqual(state['farm_route']['active_seconds'], 10)

    def test_already_selected_destination_is_not_replaced_before_arrival(self):
        s, state, config = fixture()
        visit(s, state, config, 100, 10, 9, 1)
        s['progression']['farmCandidates'].append({'level': 7, 'difficulty': 0})
        result = observe_farming(s, state, 'game', 131, config)
        self.assertEqual(result['level'], 8)

    def test_a_real_gear_upgrade_releases_failed_map_exclusions(self):
        s, state, config = fixture()
        observe_farming(s, state, 'game', 100, config)
        state['farm_route'].update(failed_stages=['9:0'],failed_at={'9:0':100})
        s['characters'][0]['equipment'] = [{'slot': 0, 'uid': 'new-weapon'}]
        observe_farming(s, state, 'game', 110, config)
        self.assertFalse(state['farm_route']['failed_stages'])

    def test_new_process_does_not_inherit_old_map_coverage(self):
        s, state, config = fixture();visit(s, state, config, 100, 10, 9, 1)
        result = observe_farming(s, state, 'another-game', 140, config)
        self.assertEqual(result['efficiency']['tested_count'], 0)

    def test_a_missing_frontier_ticket_selects_exploration_without_waiting_for_impossible_failures(self):
        s, state, config = fixture()
        s['progression']['gate'] = {'level': 11, 'reason': 'ticket_missing'}
        state['growth'] = {'phase':'push','frontier':10,'since':100,'deaths':0}
        self.assertEqual(observe_growth(s, state, 101, config)['phase'], 'farm')
        actions = [{'kind':'progress','key':'f','mode':'farm','level':9,'difficulty':0,'priority':107},
                   {'kind':'progress','key':'p','mode':'push','level':11,'difficulty':0,'priority':108}]
        self.assertEqual(choose({'snapshot':s,'actions':actions}, config, state, 101)['mode'], 'farm')

    def test_ready_synthesis_always_precedes_recycling_even_with_scheduler_aging(self):
        s, state, config = fixture()
        actions=[{'kind':'combine','key':'c','priority':108}, {'kind':'decompose','key':'d','priority':102}]
        state.update(last_module={'combine':1000,'decompose':0},scheduling_started=0)
        self.assertEqual(choose({'snapshot':s,'actions':actions}, config, state, 1000)['kind'], 'combine')
        actions[0]={'kind':'withdraw','key':'w','purpose':'combine','priority':107}
        self.assertEqual(choose({'snapshot':s,'actions':actions}, config, state, 1000)['kind'], 'withdraw')


if __name__ == '__main__':
    unittest.main()
