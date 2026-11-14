import copy
import unittest

from dps_assistant.policy import (choose, observe_growth, progression_baseline,
                                  progression_signature, strength_signature)
from dps_assistant.training import observe_farming
from test_growth_quality import party_fixture


def fixture():
    snapshot, state, config = party_fixture()
    snapshot['runes'] = {'learned': 15, 'onlineLearned': 10, 'offlineLearned': 5,
                         'progressKnown': True}
    state['growth'].update(progression_baseline(snapshot))
    return snapshot, state, config


class OnlineRuneGrowthTests(unittest.TestCase):
    def test_offline_investment_keeps_the_periodic_main_retry_clock(self):
        snap, state, config = fixture()
        signature = progression_signature(snap)
        snap['runes'].update(learned=16, offlineLearned=6)
        self.assertEqual(progression_signature(snap), signature)
        self.assertEqual(observe_growth(snap, state, 280, config)['phase'], 'farm')
        self.assertNotIn('retry_requested_at', state['growth'])
        self.assertEqual(observe_growth(snap, state, 699, config)['phase'], 'farm')
        result = observe_growth(snap, state, 700, config)
        self.assertEqual(result['phase'], 'push')
        self.assertEqual(result['retry_trigger'], 'retry_interval')

    def test_online_prerequisite_and_battle_growth_still_schedule_retry(self):
        snap, state, config = fixture()
        snap['runes'].update(learned=16, onlineLearned=11)
        result = observe_growth(snap, state, 280, config)
        self.assertEqual(result['phase'], 'push')
        self.assertEqual(result['retry_trigger'], 'party_growth')

    def test_offline_growth_preserves_native_experience_sample_and_probe_time(self):
        snap, state, config = fixture()
        observe_farming(snap, state, 'game', 100, config)
        snap['characters'][0]['expTotal'] += 10
        observe_farming(snap, state, 'game', 110, config)
        snap['runes'].update(learned=16, offlineLearned=6)
        snap['characters'][0]['expTotal'] += 10
        result = observe_farming(snap, state, 'game', 120, config)
        sample = result['efficiency']['measurements'][0]
        self.assertEqual(sample['observed_seconds'], 20)
        self.assertEqual(sample['gained'], 20)
        self.assertEqual(state['farm_route']['active_seconds'], 20)
        snap['runes'].update(learned=17, onlineLearned=11)
        self.assertFalse(observe_farming(snap, state, 'game', 130, config)['efficiency']['measurements'])

    def test_migration_and_restart_preserve_an_existing_finish_wait(self):
        snap, state, config = fixture()
        old = copy.deepcopy(snap)
        old['runes'] = {'learned': 15}
        state['growth'].update(progress_strength=progression_signature(old),
                               retry_requested_at=250, retry_trigger='party_growth')
        state['growth'].pop('rune_strength_scope')
        snap['combat']['current']['elapsed'] = 80
        result = observe_growth(snap, state, 280, config)
        self.assertEqual(state['growth']['since'], 100)
        self.assertEqual(state['growth']['retry_requested_at'], 250)
        self.assertTrue(result['retry_pending'])
        self.assertEqual(state['growth']['rune_strength_scope'], 'online')
        restored = copy.deepcopy(state)
        observe_growth(snap, restored, 290, config)
        self.assertEqual(restored['growth']['retry_requested_at'], 250)
        restored['growth'].pop('retry_requested_at')
        restored['growth'].pop('retry_trigger')
        snap['runes'].update(learned=16, onlineLearned=11)
        self.assertTrue(observe_growth(snap, restored, 300, config)['retry_pending'])
        self.assertEqual(restored['growth']['retry_requested_at'], 300)

    def test_migration_without_a_request_does_not_report_format_as_growth(self):
        snap, state, config = fixture()
        legacy = copy.deepcopy(snap)
        legacy['runes'] = {'learned': 15}
        state['growth'].update(progress_strength=progression_signature(legacy))
        state['growth'].pop('rune_strength_scope')
        result = observe_growth(snap, state, 280, config)
        self.assertEqual(result['phase'], 'farm')
        self.assertNotIn('retry_requested_at', state['growth'])
        snap['runes'].update(learned=16, onlineLearned=11)
        self.assertEqual(observe_growth(snap, state, 281, config)['phase'], 'push')

    def test_tower_retries_ignore_offline_growth_and_keep_migrated_cooldown(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                snap, state, config = fixture()
                config['modules']['tower'] = True
                snap['catalogue'] = {'normalMax': 10}
                snap['record']['maxStage'] = 10
                snap['stage'].update(running=False, ending=True)
                state['growth']['phase'] = 'endgame'
                baseline = progression_baseline(snap)
                if legacy:
                    old = copy.deepcopy(snap)
                    old['runes'] = {'learned': 15}
                    baseline = {'progress_strength': progression_signature(old)}
                state['tower_attempt'] = {'level': 1, 'max_stage': 10, 'at': 100, **baseline}
                snap['runes'].update(learned=16, offlineLearned=6)
                scan = {'snapshot': snap, 'actions': [{'kind': 'tower', 'key': 'tower', 'level': 1, 'priority': 79}]}
                self.assertIsNone(choose(scan, config, state, 500))
                self.assertEqual(state['tower_attempt']['at'], 100)
                snap['runes'].update(learned=17, onlineLearned=11)
                self.assertIsNotNone(choose(scan, config, state, 501))

    def test_legacy_and_unverified_split_counts_use_total_without_guessing(self):
        snap = {'runes': {'learned': 15}}
        original = strength_signature(snap)
        for metadata in ({'onlineLearned': 10},
                         {'onlineLearned': True, 'offlineLearned': 14, 'progressKnown': True},
                         {'onlineLearned': 10, 'offlineLearned': 4, 'progressKnown': True},
                         {'onlineLearned': 10, 'offlineLearned': 5, 'progressKnown': False}):
            snap['runes'] = {'learned': 15, **metadata}
            self.assertEqual(strength_signature(snap), original)
        snap['runes'] = {'learned': 16}
        self.assertNotEqual(strength_signature(snap), original)
