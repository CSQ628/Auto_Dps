"""Summarize recorded observation evidence without accessing or changing the game."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path


def summarize(report, samples_path=None):
    result = {
        'started': datetime.fromtimestamp(report['started']).astimezone().isoformat(),
        'observed_until': datetime.fromtimestamp(report['observed_until']).astimezone().isoformat(),
        'elapsed_seconds': round(report['observed_until'] - report['started'], 1),
        'required_seconds': report['required_seconds'],
        'complete': report['complete'],
        'samples': report['samples'],
        'poll_errors': report['errors'],
        'instances': {},
    }
    for identity, last in report['latest'].items():
        first = report['first'][identity]
        before, after = first['snapshot'], last['snapshot']
        events = [e for e in report['events'] if e.get('identity') == identity
                  or (not e.get('identity') and str(e.get('instance')) == str(last['pid']))]
        confirmed = [e for e in events if e['status'] == 'confirmed']
        level_before = {str(c['id']): c['level'] for c in before['characters']}
        level_after = {str(c['id']): c['level'] for c in after['characters']}
        result['instances'][identity] = {
            'pid': last['pid'],
            'status': last['status'],
            'error': last.get('error'),
            'connection': after.get('connection'),
            'sync': after.get('sync'),
            'stage': after['stage'],
            'levels_before': level_before,
            'levels_after': level_after,
            'record_before': before.get('record'),
            'record_after': after.get('record'),
            'confirmed_actions': len(confirmed),
            'confirmed_kinds': dict(Counter(e.get('action', {}).get('kind', 'backup') for e in confirmed)),
            'event_statuses': dict(Counter(e['status'] for e in events)),
            'action_errors': [e for e in events if e['status'] == 'error'],
            'protected_differences': [e for e in events if e.get('result', {}).get('protectedChanged')],
            'protected_checks': sum('protectedChanged' in e.get('result', {}) for e in confirmed),
            'milestones': last.get('milestones'),
        }
    if samples_path and samples_path.is_file():
        health = {}
        previous_at = None
        gaps = []
        partial_lines = 0
        with samples_path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError:
                    partial_lines += 1
                    continue
                if previous_at is not None:
                    gaps.append(sample['at'] - previous_at)
                previous_at = sample['at']
                for row in sample.get('instances', []):
                    identity = row.get('identity')
                    snap = row.get('snapshot') or {}
                    if not identity or not snap:
                        continue
                    entry = health.setdefault(identity, {'observed_pids': set(), 'statuses': Counter(),
                        'offline_samples': 0, 'sync_blocked_samples': 0, 'max_sync_queue': 0,
                        'error_samples': 0, 'noncombat_samples': 0, 'source_hashes': set()})
                    entry['observed_pids'].add(row['pid'])
                    entry['statuses'][row['status']] += 1
                    entry['offline_samples'] += snap.get('connection', {}).get('online') is False
                    entry['sync_blocked_samples'] += bool(snap.get('sync', {}).get('blocked'))
                    entry['max_sync_queue'] = max(entry['max_sync_queue'], snap.get('sync', {}).get('queue', 0))
                    entry['error_samples'] += bool(row.get('error'))
                    entry['noncombat_samples'] += snap.get('stage', {}).get('running') is False
                    if snap.get('bridgeSourceHash'):
                        entry['source_hashes'].add(snap['bridgeSourceHash'])
        for entry in health.values():
            entry['observed_pids'] = sorted(entry['observed_pids'])
            entry['source_hashes'] = sorted(entry['source_hashes'])
            entry['statuses'] = dict(entry['statuses'])
        result['sampling'] = {'max_gap_seconds': round(max(gaps, default=0), 2),
            'partial_lines': partial_lines, 'health': health}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = summarize(json.loads(args.report.read_text(encoding='utf-8')), args.report.with_name('samples.jsonl'))
    rendered = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(rendered, encoding='utf-8')
        temporary.replace(args.output)
    print(rendered)
