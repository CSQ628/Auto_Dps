import json
import unittest
from dps_assistant.diagnostics import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_box_speed_export_includes_actual_opened_count_but_no_receipt_identity(self):
        row=diagnostics({'instances':[{'box_performance':{'scanMs':2,'interval':1,'requestId':'private-receipt'},
            'feature_evidence':{'box':{'opened':20,'confirmed':3,'requestId':'private-receipt'}},
            'box_pending':{'request_id':'private-receipt'},'snapshot':{}}]})['instances'][0]
        self.assertEqual(row['box_performance'],{'scanMs':2,'interval':1})
        self.assertEqual(row['feature_status']['box']['opened'],20)
        self.assertEqual(row['feature_status']['box']['confirmed'],3)
        self.assertNotIn('private-',json.dumps(row))

    def test_growth_export_shares_retry_trigger_without_party_or_item_signatures(self):
        row=diagnostics({'instances':[{'growth':{'phase':'farm','frontier':29,'since':100,
            'retry_pending':True,'retry_trigger':'party_growth','progress_strength':'private-item-id',
            'strength':'private-account'},'snapshot':{}}]})['instances'][0]
        self.assertEqual(row['growth']['retry_trigger'],'party_growth')
        self.assertTrue(row['growth']['retry_pending'])
        self.assertNotIn('private-',json.dumps(row))
        row=diagnostics({'instances':[{'growth':{'phase':'private-phase','retry_trigger':'private-token'}}]})['instances'][0]
        self.assertIsNone(row['growth']['phase'])
        self.assertIsNone(row['growth']['retry_trigger'])

    def test_mail_diagnostics_exclude_ids_accounts_and_receipt_payloads(self):
        row=diagnostics({'instances':[{'mail_settlement':{'pending':1,'remaining':2,'since':10,'ids':['private-id']},
            'snapshot':{'mail':{'claims':{'available':True,'readError':False,'observer':'private-session',
                'receipts':[{'account':'private-account','results':[{'id':'private-id','status':'CLAIMED'}]}]}}}}]})['instances'][0]
        self.assertEqual(row['mail_settlement'],{'pending':1,'remaining':2,'since':10})
        self.assertEqual(row['mail_observer'],{'available':True,'readError':False})
        self.assertNotIn('private-',json.dumps(row))

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

    def test_maintenance_diagnostics_only_expose_wait_status_and_times(self):
        row=diagnostics({'instances':[{'maintenance':{'active':True,'since':10,'retry_at':310,'attempts':1,
            'session':'private-session','identity':'private-account','exit_session':'private-pid'},
            'snapshot':{'recycling':{'nativeCapacity':9,'batchLimit':9}}}]})['instances'][0]
        self.assertEqual(row['maintenance'],{'active':True,'since':10,'retry_at':310,'attempts':1})
        self.assertEqual(row['recycling']['batchLimit'],9)
        self.assertNotIn('private-',json.dumps(row))

    def test_bridge_startup_and_performance_are_shareable_without_identity_or_raw_error(self):
        raw={'instances':[{'bridge_health':{'pid':123,'phase':'starting','step':'load','ageSeconds':24,
            'error':'private-path private-account','transport':{'token':'secret-token'}},
            'bridge_performance':{'scanMs':40,'lastScanMs':35,'nativeCalls':120,'cacheHits':300,'account':'private-account'},
            'effective_scan_interval':2}]}
        row=diagnostics(raw)['instances'][0]
        self.assertEqual(row['bridge_health'],{'phase':'starting','step':'load','ageSeconds':24})
        self.assertEqual(row['bridge_performance']['cacheHits'],300)
        self.assertEqual(row['effective_scan_interval'],2)
        for secret in ('private-','secret-token','123'):
            self.assertNotIn(secret,json.dumps(row))

    def test_box_diagnostics_include_queues_and_exact_wait_without_private_item_data(self):
        raw={'instances':[{'snapshot':{'boxes':{'counts':[10,2,1],'total':13,'freeSlots':8,'uid':'private-box'},
            'cubeBusy':True,'manualPanelOpen':True,'manualPanels':['private-modal'],'manualBlockedKinds':[],
            'inventory':{'count':38,'capacity':46}},'box_status':{'total':13,'freeSlots':8,
            'reason':'box_ready','account':'private-account'}}]}
        row=diagnostics(raw)['instances'][0]
        self.assertEqual(row['boxes'],{'counts':[10,2,1],'total':13,'freeSlots':8})
        self.assertEqual(row['box_status']['reason'],'box_ready')
        self.assertTrue(row['cube_busy']);self.assertFalse(row['box_panel_blocked'])
        self.assertNotIn('private-',json.dumps(row))
        raw['instances'][0]['box_status']['reason']='private-token'
        self.assertEqual(diagnostics(raw)['instances'][0]['box_status']['reason'],'other_native_condition')


class PauseDiagnosticTests(unittest.TestCase):
    def test_pause_export_has_reason_and_operation_but_no_account_or_item_details(self):
        row=diagnostics({'instances':[{'pause':{'reason':'protected_item_changed','scope':'instance',
            'at':10,'changed_count':2,'action_kind':'sort','account':'private-account',
            'changes':[{'uid':'private-uid'}],'error':'private-path'}}]})['instances'][0]
        self.assertEqual(row['pause'],{'reason':'protected_item_changed','scope':'instance','at':10,'changed_count':2,'action_kind':'sort'})
        self.assertNotIn('private-',json.dumps(row))
        row=diagnostics({'instances':[{'pause':{'reason':'manual_instance_pause','scope':'private-account',
            'at':'private-path','changed_count':'private-uid','action_kind':'private-kind'}}]})['instances'][0]
        self.assertEqual(row['pause'],{'reason':'manual_instance_pause'})


    def test_trade_warning_is_exported_without_item_identity_or_pausing(self):
        value=diagnostics({'config':{'running':True},'instances':[{'id':'1'}],
            'events':[{'instance':'1','at':10,'status':'warning','action':{'kind':'sort'},
                       'result':{'reason':'tradable_state_changed','uid':'private-item'}}]})
        self.assertTrue(value['running']);self.assertIsNone(value['instances'][0]['pause'])
        self.assertEqual(value['instances'][0]['recent_operations'][0]['status'],'warning')
        self.assertEqual(value['instances'][0]['recent_operations'][0]['reason'],'tradable_state_changed')
        self.assertNotIn('private-',json.dumps(value))
