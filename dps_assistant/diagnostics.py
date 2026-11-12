"""Explicit diagnostic fields suitable for a player to share with a bug report."""
from .platform_paths import VERSION


def diagnostics(state):
    instances = []
    for row in state.get('instances', []):
        snap = row.get('snapshot') or {}
        instances.append({'instance': len(instances) + 1, 'sandboxed': bool(row.get('box')),
            'status': row.get('status'), 'observation_error': bool(row.get('error')),
            'loaded': snap.get('loaded'), 'stage': snap.get('stage'),
            'characters': [{k: c.get(k) for k in ('id', 'level', 'points')} for c in snap.get('characters', [])],
            'squad': snap.get('squad'), 'battle_readiness': snap.get('battleReadiness'),
            'battle_recovery': row.get('battle_recovery'), 'record': snap.get('record'),
            'connection': snap.get('connection'), 'sync': snap.get('sync'),
            'bridge_source_hash': snap.get('bridgeSourceHash'),
            'feature_confirmations': {k: v.get('confirmed', 0) for k, v in row.get('feature_evidence', {}).items()}})
    config = state.get('config', {})
    return {'version': VERSION, 'captured_at': state.get('now'), 'running': config.get('running'),
            'modules': config.get('modules'), 'parameters': config.get('strategy'), 'instances': instances,
            'note': '诊断仅含运行状态、角色编号和策略参数；不含账号、昵称、存档、文件路径或控制令牌。'}
