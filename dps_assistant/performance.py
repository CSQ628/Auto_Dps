"""Bound repeated main-thread scan work using measured cost, independently per instance."""
import math


def observe_scan_cost(row, performance, configured_interval, now):
    if not isinstance(performance, dict):
        return
    cost = performance.get('scanMs')
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        return
    previous = row.get('bridge_performance', {}).get('scanMs', cost)
    # Increase the gap immediately; ease it down gradually after cheaper scans.
    smoothed = max(cost, previous * .8 + cost * .2)
    interval = max(configured_interval, min(30, smoothed / 1000 / .02))
    row['bridge_performance'] = {'scanMs': smoothed, 'lastScanMs': cost,
                                **{key:performance[key] for key in ('nativeCalls', 'cacheHits')
                                   if isinstance(performance.get(key), int) and performance[key] >= 0}}
    row['effective_scan_interval'] = interval
    row['native_next_scan_at'] = max(row.get('native_next_scan_at', 0), now + interval)
