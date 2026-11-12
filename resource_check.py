#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 TheCustomizeWindows.com
# This program is free software under GPL-3.0-only; see LICENSE.
"""Read-only, dependency-free Linux resource snapshot."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone


def meminfo(path='/proc/meminfo'):
    vals = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split(':', 1)
        if len(parts) == 2:
            number = parts[1].strip().split()
            if number and number[0].isdigit():
                vals[parts[0]] = int(number[0]) * (1024 if len(number) > 1 and number[1] == 'kB' else 1)
    return vals


def percent(n, d):
    return round(n * 100 / d, 1) if d else None


def snapshot(path='/'):
    m = meminfo()
    total = m.get('MemTotal', 0)
    if total <= 0:
        raise ValueError('MemTotal missing from /proc/meminfo')
    if 'MemAvailable' in m:
        avail = m['MemAvailable']
    else:  # kernels < 3.14: estimate like old `free`, treating page cache as reclaimable
        avail = m.get('MemFree', 0) + m.get('Buffers', 0) + m.get('Cached', 0)
    avail = min(avail, total)
    swap_total = m.get('SwapTotal', 0)
    swap_free = m.get('SwapFree', 0)
    d = shutil.disk_usage(path)
    load = os.getloadavg()
    cores = os.cpu_count() or 1
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'hostname': os.uname().nodename,
        'cpu': {'logical_cores': cores, 'load_average_1_5_15': [round(x, 2) for x in load],
                'load_1_per_core': round(load[0] / cores, 2)},
        'memory': {'total_bytes': total, 'available_bytes': avail,
                   'used_percent': percent(total-avail, total)},
        'swap': {'total_bytes': swap_total, 'used_bytes': swap_total-swap_free,
                 'used_percent': percent(swap_total-swap_free, swap_total)},
        # d.free is space available to non-root users; root-reserved blocks are in
        # neither used nor free, so used/(used+free) matches `df` Use%.
        'disk': {'path': str(Path(path).resolve()), 'total_bytes': d.total,
                 'used_bytes': d.used, 'free_bytes': d.free,
                 'used_percent': percent(d.used, d.used + d.free)},
    }


def evaluate(data, memory_threshold=85, disk_threshold=85, load_threshold=1.5):
    warnings = []
    for key, threshold in [('memory', memory_threshold), ('disk', disk_threshold)]:
        value = data[key]['used_percent']
        if value is not None and value >= threshold:
            warnings.append(f'{key} usage {value}% >= {threshold}%')
    load = data['cpu']['load_1_per_core']
    if load >= load_threshold:
        warnings.append(f'1-minute load per core {load} >= {load_threshold}')
    return warnings


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only Linux server resource snapshot')
    p.add_argument('--path', default='/', help='filesystem path to inspect (default: /)')
    p.add_argument('--json', action='store_true', help='machine-readable output')
    p.add_argument('--memory-warn', type=float, default=85,
                   help='memory used percent, 0-100 (default: 85)')
    p.add_argument('--disk-warn', type=float, default=85,
                   help='disk used percent, 0-100 (default: 85)')
    p.add_argument('--load-warn', type=float, default=1.5,
                   help='1-minute load divided by CPU count (default: 1.5)')
    args = p.parse_args(argv)
    if not all(math.isfinite(x) and x >= 0 for x in (args.memory_warn, args.disk_warn, args.load_warn)):
        p.error('warning thresholds must be finite, non-negative numbers')
    if args.memory_warn > 100 or args.disk_warn > 100:
        p.error('--memory-warn and --disk-warn are percentages (0-100)')
    try:
        data = snapshot(args.path)
    except (OSError, ValueError) as e:
        print(f'resource-check: {e}', file=sys.stderr)
        return 2
    warnings = evaluate(data, args.memory_warn, args.disk_warn, args.load_warn)
    data['warnings'] = warnings
    data['status'] = 'WARN' if warnings else 'OK'
    try:
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"{data['hostname']} | {data['timestamp_utc']} | {data['status']}")
            print(f"CPU: {data['cpu']['logical_cores']} cores; load 1/5/15: {data['cpu']['load_average_1_5_15']}; load/core: {data['cpu']['load_1_per_core']}")
            for key in ('memory', 'swap', 'disk'):
                item = data[key]
                used = item['used_percent']
                state = f'{used}% used' if used is not None else ('none configured' if key == 'swap' else 'n/a')
                print(f"{key.capitalize()}: {state}" + (f" ({item['path']})" if key == 'disk' else ''))
            for warning in warnings:
                print(f'WARNING: {warning}')
        sys.stdout.flush()
    except OSError as e:  # e.g. stdout redirected to a full disk; exit 1 is reserved for WARN
        try:  # stop Python's exit-time flush from raising again (stdlib-documented pattern)
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        print(f'resource-check: cannot write output: {e}', file=sys.stderr)
        return 2
    return 1 if warnings else 0


if __name__ == '__main__':
    sys.exit(main())
