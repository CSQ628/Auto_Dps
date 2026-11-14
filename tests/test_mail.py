import copy
import unittest
from dps_assistant.mail import settle_mail


class MailReceiptTests(unittest.TestCase):
    def pending(self):
        return {'action': {'kind': 'mail_claim', 'ids': ['a', 'b']}, 'at': 10,
                'mail_observer': 'session', 'mail_sequence': 2}

    def snapshot(self, results, **change):
        receipt = {'at': 11, 'sequence': 3, 'account': 'acct', 'results': results, **change}
        return {'account': 'acct', 'mail': {'claims': {'observer': 'session', 'receipts': [receipt]}}}

    def test_ui_absence_unread_decrease_and_timeout_never_prove_claim(self):
        pending = self.pending()
        for snap in ({}, {'mail': {'unread': 0, 'claiming': False}},
                     {'mail': {'unread': 2, 'claiming': True}},
                     self.snapshot([{'id': 'a', 'status': 'unknown'}, {'id': 'b', 'status': 'CLAIMED'}])):
            self.assertIsNone(settle_mail(pending, snap))

    def test_partial_receipts_persist_and_only_complete_native_results_settle(self):
        pending = self.pending()
        self.assertIsNone(settle_mail(pending, self.snapshot([{'id': 'a', 'status': 'CLAIMED'}])))
        pending = copy.deepcopy(pending)  # Models a scheduler reload.
        snap = self.snapshot([{'id': 'b', 'status': 'ALREADY_CLAIMED'}])
        snap['mail']['claims']['observer'] = 'reconnected'
        result = settle_mail(pending, snap)
        self.assertEqual((result['status'], result['claimed'], result['alreadyClaimed']), ('confirmed', 1, 1))

    def test_prior_sequence_wrong_account_old_time_and_unrelated_ids_do_not_settle(self):
        rows = [{'id': i, 'status': 'CLAIMED'} for i in ('a', 'b')]
        for change in ({'account': 'other'}, {'at': float('nan')}, {'sequence': 2}):
            self.assertIsNone(settle_mail(self.pending(), self.snapshot(rows, **change)))
        old=self.snapshot(rows,at=9);old['mail']['claims']['observer']='reconnected'
        self.assertIsNone(settle_mail(self.pending(),old))
        self.assertIsNone(settle_mail(self.pending(), self.snapshot([{'id': 'c', 'status': 'CLAIMED'}])))

    def test_already_claimed_only_resolves_without_fabricating_grant_evidence(self):
        result = settle_mail(self.pending(), self.snapshot([{'id': i, 'status': 'ALREADY_CLAIMED'} for i in ('a', 'b')]))
        self.assertEqual((result['status'], result['claimed']), ('no_change', 0))

    def test_duplicate_and_manual_already_claimed_receipts_do_not_double_count(self):
        pending = self.pending()
        self.assertIsNone(settle_mail(pending, self.snapshot([{'id': 'a', 'status': 'CLAIMED'}])))
        rows = [{'id': 'a', 'status': 'ALREADY_CLAIMED'}, {'id': 'b', 'status': 'CLAIMED'}]
        self.assertEqual(settle_mail(pending, self.snapshot(rows))['claimed'], 2)

    def test_immediate_receipt_uses_sequence_and_survives_millisecond_precision(self):
        pending=self.pending();pending['at']=10.0009
        rows=[{'id':i,'status':'CLAIMED'} for i in ('a','b')]
        for observer in ('session','reconnected'):
            snap=self.snapshot(rows,at=10.000);snap['mail']['claims']['observer']=observer
            self.assertEqual(settle_mail(copy.deepcopy(pending),snap)['claimed'],2)
