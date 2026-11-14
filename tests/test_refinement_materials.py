import copy
import unittest

from dps_assistant.engine import DEFAULT
from dps_assistant.policy import ranked_actions
from dps_assistant.diagnostics import diagnostics


class RefinementCoordinationTests(unittest.TestCase):
    def scan(self):
        return {'snapshot': {'loaded': True, 'characters': [], 'currencies': {}}, 'actions': [
            {'kind': 'refine', 'key': 'append', 'id': 1, 'slot': 0, 'uid': 'old', 'priority': 90},
            {'kind': 'equipment', 'key': 'equip', 'id': 1, 'slot': 0, 'uid': 'new', 'previousUid': 'old', 'empty': True, 'priority': 99}]}

    def ranked(self, scan=None, config=None, state=None):
        return ranked_actions(scan or self.scan(), config or copy.deepcopy(DEFAULT), state or {}, 1000)

    def test_eligible_same_slot_replacement_precedes_refinement(self):
        self.assertEqual([a['kind'] for a in self.ranked()], ['equipment'])

    def test_other_slots_and_heroes_can_refine_during_equipment_growth(self):
        for change in ({'slot': 1}, {'id': 2}):
            scan = self.scan(); scan['actions'][1].update(change)
            self.assertIn('refine', [a['kind'] for a in self.ranked(scan)])

    def test_disabled_and_cooling_equipment_plans_do_not_starve_refinement(self):
        config = copy.deepcopy(DEFAULT); config['modules']['equipment'] = False
        self.assertEqual([a['kind'] for a in self.ranked(config=config)], ['refine'])
        self.assertEqual([a['kind'] for a in self.ranked(state={'cooldowns': {'equip': 2000}})], ['refine'])

    def test_pending_slot_swap_defers_its_old_target_but_other_growth_continues(self):
        scan = self.scan(); scan['actions'].append({'kind': 'rune', 'key': 'growth', 'priority': 89})
        state = {'pending_results': {'equip': {'action': scan['actions'][1], 'at': 999}}}
        self.assertEqual([a['kind'] for a in self.ranked(scan, state=state)], ['rune'])

    def test_uncertain_refinement_key_is_not_resubmitted_while_other_growth_continues(self):
        scan = self.scan(); scan['actions'] = [scan['actions'][0], {'kind': 'rune', 'key': 'growth', 'priority': 89}]
        self.assertEqual([a['kind'] for a in self.ranked(scan, state={'uncertain': {'append': 900}})], ['rune'])

    def test_refinement_diagnostics_exclude_item_identifiers(self):
        output = diagnostics({'instances': [{'snapshot': {'refining': {'status': 'ready', 'reservedMaterials': 2,
            'ready': 2, 'uid': 'private-item', 'allowed': ['private-item']}}}]})
        self.assertEqual(output['instances'][0]['refining']['reservedMaterials'], 2)
        self.assertNotIn('private-item', str(output))

    def test_material_synthesis_diagnostics_report_counts_without_item_identity(self):
        state={'status':'ready','reservedForSynthesis':9,'reservedForEquipment':1,
               'groups':1,'ready':1,'allowed':['private-material'],'account':'private-player'}
        output=diagnostics({'instances':[{'snapshot':{'combining':{'refinementMaterials':state}}}]})
        summary=output['instances'][0]['refinement_material_synthesis']
        self.assertEqual(summary['reservedForSynthesis'],9)
        self.assertEqual(summary['reservedForEquipment'],1)
        self.assertNotIn('private-material',str(output));self.assertNotIn('private-player',str(output))


if __name__ == '__main__':
    unittest.main()
