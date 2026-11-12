import json
import unittest
from dps_assistant.diagnostics import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_export_uses_allowlist_and_excludes_account_save_and_private_values(self):
        raw = {'now': 10, 'csrf': 'secret-token', 'config': {'running': True, 'strategy': {'battle_recovery_wait_seconds': 30}},
               'data_directory': 'C:/private/path', 'instances': [{'box': 'private-box-name', 'account': 'private-account',
                'error': 'C:/private/path secret-token', 'snapshot': {'account': 'private-account', 'nickname': 'private-name',
                'saveDirectory': 'private-save', 'squad': [400001], 'characters': [{'id': 400001, 'level': 2}],
                'battleReadiness': {'known': True, 'missing': [400001]}}}], 'events': [{'token': 'secret-token'}]}
        value = diagnostics(raw);text = json.dumps(value)
        for secret in ('private-', 'secret-token', 'C:/private'):
            self.assertNotIn(secret, text)
        self.assertTrue(value['instances'][0]['observation_error'])
        self.assertEqual(value['instances'][0]['battle_readiness']['missing'], [400001])

    def test_transition_diagnostics_expose_result_age_and_target_without_private_keys(self):
        raw={'now':30,'instances':[{'snapshot':{'at':25000,'combat':{'current':{
            'sequence':7,'level':1,'difficulty':0,'result':'Cleared','elapsed':90,'account':'private-account'}}},
            'pending_transitions':[{'kind':'progress','mode':'boss','level':10,'difficulty':0,'since':20,
                                    'key':'private-item-uid','ticketUid':'private-item-uid'}]}]}
        row=diagnostics(raw)['instances'][0]
        self.assertEqual(row['snapshot_age_seconds'],5)
        self.assertEqual(row['battle_result']['result'],'Cleared')
        self.assertEqual(row['pending_transitions'][0]['level'],10)
        self.assertNotIn('private-',json.dumps(row))


    def test_waiting_reasons_are_shareable_but_native_errors_and_ids_are_not(self):
        raw={'instances':[{'id':'1','feature_evidence':{
            'decompose':{'confirmed':3,'last_status':'waiting','last_reason':'native_material_not_reserved','last_at':5},
            'private-token':{'last_reason':'private-account'}},'snapshot':{}}],
            'events':[{'instance':'1','at':6,'status':'waiting','action':{'kind':'decompose','uid':'private-uid'},
                       'result':{'reason':'private-account','error':'private-path','step':'reserve'}}]}
        value=diagnostics(raw)['instances'][0]
        self.assertEqual(value['feature_status']['decompose']['last_reason'],'native_material_not_reserved')
        self.assertEqual(value['recent_operations'][0]['reason'],'other_native_condition')
        self.assertNotIn('private-',json.dumps(value))


    def test_inventory_diagnostics_share_counts_and_blockers_without_item_ids(self):
        raw={'instances':[{'snapshot':{'inventory':{'count':46,'capacity':46,'uid':'private-uid'},
            'storage':{'count':49,'capacity':49,'items':['private-uid']},
            'inventoryFlow':{'movable':90,'protectedMaterials':5,'blocked':True,'swapUid':'private-uid'},
            'combining':{'warehousePending':1,'needSpace':True,'uid':'private-uid'},
            'recycling':{'obsolete':2,'allowed':['private-uid']}}}]}
        row=diagnostics(raw)['instances'][0]
        self.assertEqual(row['inventory']['count'],46)
        self.assertEqual(row['storage']['capacity'],49)
        self.assertTrue(row['inventory_flow']['blocked'])
        self.assertTrue(row['combining']['needSpace'])
        self.assertEqual(row['recycling']['obsolete'],2)
        self.assertNotIn('private-',json.dumps(row))
