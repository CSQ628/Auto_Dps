"""Log failures must not kill discovery or disable unrelated native work."""
import copy
import json
import threading
from concurrent.futures import Future
from unittest.mock import patch
import unittest

from dps_assistant import engine
from dps_assistant.diagnostics import diagnostics
from dps_assistant.eventlog import RetryingEventLog
import test_scheduler as fixture


class JournalRetryTests(unittest.TestCase):
    setUp = fixture.SchedulerTests.setUp
    tearDown = fixture.SchedulerTests.tearDown
    add = fixture.SchedulerTests.add

    def test_log_failure_cannot_exit_discovery_exception_handler(self):
        calls = []
        def discover():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError('transient discovery failure')
            self.engine.stopping.set()
            return []
        before = copy.deepcopy(self.engine.config)
        with patch.object(engine, 'event', side_effect=OSError('journal temporarily locked')), \
             patch.object(self.engine, 'discovered_processes', side_effect=discover), \
             patch.object(self.engine, 'launch_missing'):
            self.engine.loop()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.engine.config, before)
        self.assertTrue(any('自动连接' in e['message'] for e in self.engine.events))

    def test_log_unavailable_does_not_replay_confirmed_consumption(self):
        bridge = self.add()
        before = copy.deepcopy(self.engine.config)
        with patch.object(engine, 'event', side_effect=PermissionError('journal temporarily locked')):
            self.engine.tick('1')
            self.engine.tick('1')
        self.assertEqual(len(bridge.commands), 1)
        self.assertEqual(self.engine.instances['1']['status'], 'running')
        self.assertEqual(self.engine.durable['host:1001']['confirmed'], 1)
        self.assertEqual(self.engine.config, before)

    def test_discovery_flushes_buffer_even_without_new_events_and_exports_safe_diagnostics(self):
        now = [100.0]
        self.engine.event_log = RetryingEventLog(lambda value: engine.event(value), clock=lambda: now[0])
        with patch.object(engine, 'event', side_effect=OSError('secret/path/account')):
            self.engine.record('system', 'warning', 'original failure')
        state = self.engine.public_state()
        self.assertEqual(state['event_log']['status'], 'retrying')
        safe = diagnostics(state)
        self.assertEqual(safe['event_log']['buffered'], 2)
        self.assertNotIn('secret/path/account', json.dumps(safe))
        now[0] += 2
        with patch.object(self.engine, 'discovered_processes', return_value=[]), \
             patch.object(self.engine, 'launch_missing'), \
             patch.object(self.engine.stopping, 'wait', side_effect=lambda _: self.engine.stopping.set()):
            self.engine.loop()
        persisted = [json.loads(line) for line in (engine.DATA / 'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(sum(e['message'] == 'original failure' for e in persisted), 1)
        self.assertEqual(persisted[-1]['result']['reason'], 'event_log_recovered')
        self.assertEqual(self.engine.public_state()['event_log']['status'], 'available')

    def test_worker_failure_retries_indefinitely_without_holding_other_instance(self):
        self.add('1', '1001', 'sandbox1')
        self.add('2', '1002', 'sandbox2')
        before = copy.deepcopy(self.engine.config)
        now = 1000.0
        with patch.object(self.engine.pool, 'submit', side_effect=lambda *args: Future()) as submit:
            for attempt in range(1, 10):
                failed = Future()
                failed.set_exception(RuntimeError('private native detail'))
                self.engine.jobs['1'] = failed
                with patch.object(engine.time, 'time', return_value=now):
                    self.engine.schedule_instance('1')
                    self.engine.schedule_instance('2')
                    self.assertNotIn('1', self.engine.jobs)
                    self.assertIn('2', self.engine.jobs)
                    delay = self.engine.instances['1']['worker_retry']['delay']
                    self.assertEqual(delay, min(30, 2 ** attempt))
                    self.engine.schedule_instance('1')
                    self.assertNotIn('1', self.engine.jobs)
                self.engine.jobs['2'].set_result(None)
                now += delay
                with patch.object(engine.time, 'time', return_value=now):
                    self.engine.schedule_instance('1')
                    self.assertIn('1', self.engine.jobs)
            self.engine.jobs['1'].set_result(None)
            with patch.object(engine.time, 'time', return_value=now):
                self.engine.schedule_instance('1')
            self.assertNotIn('worker_retry', self.engine.instances['1'])
            self.assertGreater(submit.call_count, 9)
        self.assertEqual(self.engine.config, before)
        self.assertEqual(sum(e.get('result', {}).get('reason') == 'instance_worker_failed' for e in self.engine.events), 1)
        self.assertEqual(sum(e.get('result', {}).get('reason') == 'instance_worker_recovered' for e in self.engine.events), 1)

    def test_worker_recovery_cannot_override_manual_pause(self):
        self.add()
        self.engine.update({'instances': {'host:1001': False}})
        failed = Future()
        failed.set_exception(OSError('worker failure'))
        self.engine.jobs['1'] = failed
        self.engine.schedule_instance('1')
        self.engine.instances['1']['worker_retry']['next_at'] = 0
        self.engine.schedule_instance('1')
        self.engine.jobs['1'].result(3)
        self.assertFalse(self.engine.config['instances']['host:1001'])
        self.assertIsNotNone(self.engine.public_state()['instances'][0]['pause'])


class EventLogTests(unittest.TestCase):
    def test_persistent_outage_has_bounded_delay_unlimited_attempts_and_ordered_recovery(self):
        now, calls, saved = [0.0], [], []
        unavailable = [True]
        def writer(value):
            calls.append(now[0])
            if unavailable[0]:
                raise OSError('locked')
            saved.append(value)
        log = RetryingEventLog(writer, clock=lambda: now[0])
        log.append({'at': 7, 'message': 'first'})
        log.append({'at': 8, 'message': 'second'})
        self.assertEqual(len(calls), 1)
        for attempt, delay in enumerate((2, 4, 8, 16, 30, 30, 30, 30), start=1):
            self.assertEqual(log.state()['retry_in_seconds'], delay)
            now[0] += delay - .01
            log.flush()
            self.assertEqual(len(calls), attempt)
            now[0] += .01
            log.flush()
            self.assertEqual(len(calls), attempt + 1)
        unavailable[0] = False
        now[0] += 30
        log.flush()
        self.assertEqual([e['at'] for e in saved], [7, 8])
        self.assertEqual(log.state()['status'], 'available')
        self.assertEqual(log.state()['buffered'], 0)

    def test_long_outage_limits_memory_and_reports_dropped_diagnostics(self):
        def writer(value):
            raise OSError('locked')
        log = RetryingEventLog(writer, clock=lambda: 0)
        for index in range(600):
            log.append({'index': index})
        self.assertEqual(log.state()['buffered'], 512)
        self.assertEqual(log.state()['dropped'], 88)
        saved = []
        log._writer = saved.append
        log.flush(force=True, limit=512)
        self.assertEqual([e['index'] for e in saved], list(range(88, 600)))
        self.assertEqual(log.state()['dropped'], 88)

    def test_concurrent_accounts_preserve_buffered_evidence_without_mutable_aliases(self):
        saved, now = [], [0]
        unavailable = [True]
        def writer(value):
            if unavailable[0]:
                raise PermissionError('busy')
            saved.append(value)
        log = RetryingEventLog(writer, clock=lambda: now[0])
        def append(account):
            for index in range(30):
                evidence = {'account': account, 'index': index, 'receipt': {'status': 'confirmed'}}
                log.append(evidence)
                evidence['receipt']['status'] = 'changed later'
        threads = [threading.Thread(target=append, args=(account,)) for account in range(6)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        unavailable[0], now[0] = False, 2
        for _ in range(12): log.flush()
        self.assertEqual(len(saved), 180)
        self.assertEqual(len({(e['account'], e['index']) for e in saved}), 180)
        self.assertTrue(all(e['receipt']['status'] == 'confirmed' for e in saved))
        self.assertEqual(log.state()['buffered'], 0)


if __name__ == '__main__':
    unittest.main()
