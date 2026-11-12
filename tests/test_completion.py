import unittest
from dps_assistant.completion import milestones


class CompletionTests(unittest.TestCase):
    def test_missing_or_partial_observation_cannot_meet_milestones(self):
        result=milestones({})
        self.assertFalse(result['all_milestones_met'])
        self.assertTrue(all(not r['known'] and not r['met'] for r in result['items']))
        self.assertIn('邮件与离线收益', result['unverified_systems'])

    def test_caps_and_minimum_roster_level_come_from_native_snapshot(self):
        snap={'catalogue':{'normalMax':160,'towerMax':20,'characterMax':101},
              'record':{'maxCleared':19,'towerMaxCleared':0},
              'characters':[{'id':1,'level':101},{'id':2,'level':21}],
              'runes':{'learned':202,'total':1309},'pets':{'unlocked':2,'total':10},
              'equipmentPlanning':[{'slots':10,'equipped':8},{'slots':10,'equipped':7}]}
        result=milestones(snap, {'equipment':{'confirmed':2}})
        values={r['id']:r for r in result['items']}
        self.assertEqual((values['level']['current'],values['level']['target']),(21,101))
        self.assertEqual((values['gear']['current'],values['gear']['target']),(15,20))
        self.assertFalse(values['main']['met'])
        self.assertNotIn('换装',result['unverified_systems'])
        self.assertFalse(result['all_milestones_met'])

    def test_numeric_caps_do_not_fabricate_feature_evidence(self):
        snap={'catalogue':{'normalMax':1,'towerMax':1,'characterMax':2},
              'record':{'maxCleared':1,'towerMaxCleared':1},'characters':[{'level':2}],
              'runes':{'learned':1,'total':1},'pets':{'unlocked':1,'total':1},
              'equipmentPlanning':[{'slots':1,'equipped':1}]}
        result=milestones(snap)
        self.assertTrue(result['all_milestones_met'])
        self.assertEqual(result['met'],6)
        self.assertIn('邮件与离线收益',result['unverified_systems'])


    def test_owned_content_goals_exclude_unowned_dlc_and_keep_unknown_ownership_unknown(self):
        snap={'pets':{'unlocked':2,'total':10,'eligibleUnlocked':2,'eligibleTotal':7,'excludedDlc':3},
              'roster':{'eligibleUnlocked':3,'eligibleTotal':3,'excludedDlc':2}}
        values={r['id']:r for r in milestones(snap)['items']}
        self.assertEqual((values['pets']['current'],values['pets']['target']),(2,7))
        self.assertTrue(values['roster']['met'])
        self.assertIn('3',values['pets']['detail'])
        snap['pets'].update(eligibleUnlocked=None,eligibleTotal=None)
        self.assertFalse(next(r for r in milestones(snap)['items'] if r['id']=='pets')['known'])
