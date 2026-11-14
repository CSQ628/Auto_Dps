import copy
import unittest
from dps_assistant.boxes import box_status


class BoxStatusTests(unittest.TestCase):
    def setUp(self):
        self.action={'kind':'box','key':'box:0:205','priority':99}
        self.scan={'snapshot':{'boxes':{'counts':[10,2,1],'total':13,'freeSlots':8},
            'inventory':{'count':38,'capacity':46},'connection':{'online':True},'sync':{},
            'manualBlockedKinds':[]},'actions':[self.action]}
        self.config={'running':True,'modules':{'box':True}}

    def reason(self,state=None,ranked=None):
        return box_status(self.scan,self.config,state or {},[self.action] if ranked is None else ranked,100)['reason']

    def test_locked_items_and_kept_storage_or_cube_do_not_imply_a_box_block(self):
        self.scan['snapshot'].update(manualPanelOpen=True,cubeBusy=True,manualPanels=['DG.UI.Popup.StoragePopup'])
        self.scan['snapshot']['recycling']={'locked':4}
        self.assertEqual(self.reason(),'box_ready')
        self.assertEqual(self.reason(ranked=[{'kind':'forge'},self.action]),'box_queued')

    def test_reports_each_guard_without_claiming_a_locked_item_causes_it(self):
        for field,value,expected in [('itemInputHolding',True,'item_drag_active'),
                ('automationBlocked',['unknown-modal'],'native_modal_active'),('trading',True,'trade_panel_active'),
                ('manualBlockedKinds',['box'],'manual_panel_conflict'),('sync',{'blocked':True},'native_sync_blocked'),
                ('sync',{'queue':101},'native_sync_backlog'),('connection',{'online':False},'native_offline')]:
            with self.subTest(expected=expected):
                original=copy.deepcopy(self.scan);self.scan['snapshot'][field]=value
                self.assertEqual(self.reason(ranked=[]),expected);self.scan=original

    def test_pending_is_observed_without_mutating_or_expiring_the_reservation(self):
        state={'uncertain':{self.action['key']:1}};before=copy.deepcopy(state)
        self.assertEqual(self.reason(state,[]),'box_result_unconfirmed');self.assertEqual(state,before)

    def test_native_rejection_and_cooldowns_are_visible(self):
        state={'cooldowns':{self.action['key']:101}}
        self.assertEqual(self.reason(state,[]),'box_retry_wait')
        state['features']={'box':{'last_status':'rejected'}}
        self.assertEqual(self.reason(state,[]),'native_box_rejected')

    def test_full_bag_and_empty_queue_are_distinct(self):
        self.scan['snapshot']['boxes']['freeSlots']=0
        self.assertEqual(self.reason(ranked=[]),'inventory_full')
        self.scan['snapshot']['boxes']['total']=0
        self.assertEqual(self.reason(ranked=[]),'box_empty')

    def test_disabled_and_paused_are_visible(self):
        self.config['modules']['box']=False;self.assertEqual(self.reason(ranked=[]),'box_disabled')
        self.config['running']=False;self.assertEqual(self.reason(ranked=[]),'box_paused')

    def test_old_or_loading_snapshot_never_claims_no_boxes(self):
        self.scan['snapshot'].pop('boxes');self.assertEqual(self.reason(ranked=[]),'box_reading')
