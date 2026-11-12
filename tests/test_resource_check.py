# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 TheCustomizeWindows.com
# This program is free software under GPL-3.0-only; see LICENSE.

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import resource_check as rc  # noqa: E402

DiskUsage = namedtuple('DiskUsage', 'total used free')
GIB = 1024 ** 3
# A 2 GiB VPS with no swap (the Ubuntu cloud-image default).
MEM_2G = {'MemTotal': 2 * GIB, 'MemFree': GIB // 4, 'MemAvailable': GIB,
          'Buffers': 0, 'Cached': GIB // 2, 'SwapTotal': 0, 'SwapFree': 0}
LINUX = sys.platform.startswith('linux') and os.path.exists('/proc/meminfo')


def fake_snapshot(mem=MEM_2G, disk=DiskUsage(100, 50, 45), load=(0.5, 0.4, 0.3), cores=1):
    """Build a snapshot from fixed inputs instead of the live system."""
    with patch.object(rc, 'meminfo', return_value=dict(mem)), \
            patch.object(rc.shutil, 'disk_usage', return_value=disk), \
            patch.object(rc.os, 'getloadavg', return_value=load), \
            patch.object(rc.os, 'cpu_count', return_value=cores):
        return rc.snapshot('/')


def run_main(argv, data=None):
    """Run main(); return (exit_code, stdout, stderr). data=None uses the live system."""
    out, err = io.StringIO(), io.StringIO()
    snap = patch.object(rc, 'snapshot', return_value=data) if data is not None else contextlib.nullcontext()
    with snap, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = rc.main(argv)
        except SystemExit as e:  # argparse usage errors
            code = e.code
    return code, out.getvalue(), err.getvalue()


class ResourceCheckTests(unittest.TestCase):
    """Original v0.1 tests, unchanged."""

    def test_percent(self):
        self.assertEqual(rc.percent(1, 4), 25.0)
        self.assertIsNone(rc.percent(1, 0))

    def test_meminfo(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Path(directory) / 'meminfo'
            f.write_text('MemTotal: 2048 kB\nMemAvailable: 1024 kB\nSwapTotal: 0 kB\n')
            self.assertEqual(rc.meminfo(f)['MemTotal'], 2097152)

    def test_warning_thresholds(self):
        d = {'memory': {'used_percent': 90}, 'disk': {'used_percent': 20},
             'cpu': {'load_1_per_core': 0.2}}
        self.assertEqual(len(rc.evaluate(d)), 1)
        self.assertIn('memory', rc.evaluate(d)[0])

    def test_load_warning(self):
        d = {'memory': {'used_percent': 10}, 'disk': {'used_percent': 20},
             'cpu': {'load_1_per_core': 2.0}}
        self.assertEqual(len(rc.evaluate(d)), 1)

    def test_unsupported_path(self):
        with patch.object(rc, 'snapshot', side_effect=OSError('unavailable')):
            self.assertEqual(run_main(['--json'])[0], 2)


class MeminfoParsingTests(unittest.TestCase):
    def test_units_and_malformed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Path(directory) / 'meminfo'
            f.write_text('HugePages_Total:       4\nHugepagesize:    2048 kB\n'
                         'garbage line\nOdd: abc kB\nEmpty:\n')
            m = rc.meminfo(f)
        self.assertEqual(m, {'HugePages_Total': 4, 'Hugepagesize': 2048 * 1024})


class SnapshotMathTests(unittest.TestCase):
    def test_memory_uses_memavailable(self):
        self.assertEqual(fake_snapshot()['memory']['used_percent'], 50.0)

    def test_memory_fallback_treats_cache_as_available(self):
        mem = {k: v for k, v in MEM_2G.items() if k != 'MemAvailable'}
        m = fake_snapshot(mem=mem)['memory']
        # MemFree 0.25 + Buffers 0 + Cached 0.5 GiB available; MemFree alone would say 87.5%.
        self.assertEqual(m['available_bytes'], 3 * GIB // 4)
        self.assertEqual(m['used_percent'], 62.5)

    def test_missing_memtotal_is_an_error(self):
        mem = {k: v for k, v in MEM_2G.items() if k != 'MemTotal'}
        with self.assertRaises(ValueError):
            fake_snapshot(mem=mem)
        with patch.object(rc, 'meminfo', return_value=mem):
            code, out, err = run_main([])
        self.assertEqual(code, 2)
        self.assertIn('MemTotal', err)

    def test_available_never_exceeds_total(self):
        m = fake_snapshot(mem=dict(MEM_2G, MemAvailable=3 * GIB))['memory']
        self.assertEqual(m['available_bytes'], 2 * GIB)
        self.assertEqual(m['used_percent'], 0.0)

    def test_disk_percent_matches_df_with_reserved_blocks(self):
        # ext4 with 5% root-reserved: 1000 blocks, 900 used, 50 reserved, 50 available.
        disk = fake_snapshot(disk=DiskUsage(1000, 900, 50))['disk']
        self.assertEqual(disk['used_percent'], 94.7)   # df: 900 / (900 + 50); v0.1 said 90.0
        self.assertEqual(disk['used_bytes'], 900)
        # Full for non-root users (only reserved blocks left) must read 100%, not 95%.
        self.assertEqual(fake_snapshot(disk=DiskUsage(1000, 950, 0))['disk']['used_percent'], 100.0)

    def test_zero_size_filesystem(self):
        self.assertIsNone(fake_snapshot(disk=DiskUsage(0, 0, 0))['disk']['used_percent'])

    def test_no_swap(self):
        swap = fake_snapshot()['swap']
        self.assertEqual((swap['used_bytes'], swap['used_percent']), (0, None))

    def test_load_per_core(self):
        self.assertEqual(fake_snapshot(load=(1.8, 1.0, 0.5), cores=1)['cpu']['load_1_per_core'], 1.8)
        self.assertEqual(fake_snapshot(load=(1.8, 1.0, 0.5), cores=2)['cpu']['load_1_per_core'], 0.9)

    def test_unknown_cpu_count_falls_back_to_one(self):
        with patch.object(rc, 'meminfo', return_value=dict(MEM_2G)), \
                patch.object(rc.shutil, 'disk_usage', return_value=DiskUsage(100, 50, 45)), \
                patch.object(rc.os, 'getloadavg', return_value=(0.7, 0.5, 0.2)), \
                patch.object(rc.os, 'cpu_count', return_value=None):
            cpu = rc.snapshot('/')['cpu']
        self.assertEqual((cpu['logical_cores'], cpu['load_1_per_core']), (1, 0.7))


class EvaluateTests(unittest.TestCase):
    def test_unknown_values_never_warn(self):
        d = {'memory': {'used_percent': None}, 'disk': {'used_percent': None},
             'cpu': {'load_1_per_core': 0.0}}
        self.assertEqual(rc.evaluate(d), [])

    def test_threshold_is_inclusive(self):
        d = {'memory': {'used_percent': 85.0}, 'disk': {'used_percent': 84.9},
             'cpu': {'load_1_per_core': 1.5}}
        self.assertEqual(len(rc.evaluate(d)), 2)


class CliTests(unittest.TestCase):
    def test_exit_0_when_healthy(self):
        code, out, _ = run_main([], fake_snapshot())
        self.assertEqual(code, 0)
        self.assertIn('| OK', out)

    def test_exit_1_when_threshold_exceeded(self):
        code, out, _ = run_main([], fake_snapshot(load=(2.0, 1.0, 0.5)))
        self.assertEqual(code, 1)
        self.assertIn('WARNING: 1-minute load per core 2.0 >= 1.5', out)

    def test_json_output(self):
        code, out, _ = run_main(['--json'], fake_snapshot(disk=DiskUsage(1000, 900, 50)))
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data['status'], 'WARN')
        self.assertEqual(data['disk']['used_percent'], 94.7)
        self.assertIsNone(data['swap']['used_percent'])

    def test_text_output_without_swap_or_size(self):
        code, out, _ = run_main(['--path', '/proc'], fake_snapshot(disk=DiskUsage(0, 0, 0)))
        self.assertNotIn('None', out)
        self.assertIn('Swap: none configured', out)
        self.assertIn('Disk: n/a', out)

    def test_rejects_invalid_thresholds(self):
        for argv in (['--memory-warn', 'nan'], ['--disk-warn', 'inf'], ['--load-warn', '-1'],
                     ['--load-warn', 'nan'], ['--disk-warn', '101'], ['--memory-warn', '85%']):
            with self.subTest(argv=argv):
                code, out, err = run_main(argv, fake_snapshot())
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertIn('error', err)

    def test_accepts_boundary_thresholds(self):
        code, _, _ = run_main(['--memory-warn', '0', '--disk-warn', '100', '--load-warn', '0'],
                              fake_snapshot())
        self.assertEqual(code, 1)  # valid arguments; 0 thresholds always warn

    def test_output_write_failure_is_exit_2(self):
        class FullDisk(io.StringIO):
            def write(self, s):
                raise OSError(28, 'No space left on device')
        err = io.StringIO()
        with patch.object(rc, 'snapshot', return_value=fake_snapshot()), \
                contextlib.redirect_stdout(FullDisk()), contextlib.redirect_stderr(err):
            code = rc.main([])
        self.assertEqual(code, 2)  # not 1, which means "threshold exceeded"
        self.assertIn('cannot write output', err.getvalue())


@unittest.skipUnless(LINUX, 'requires Linux /proc')
class LinuxSmokeTests(unittest.TestCase):
    def test_live_snapshot_is_sane(self):
        d = rc.snapshot('/')
        self.assertGreaterEqual(d['cpu']['logical_cores'], 1)
        self.assertEqual(len(d['cpu']['load_average_1_5_15']), 3)
        self.assertGreater(d['memory']['total_bytes'], 0)
        self.assertTrue(0 <= d['memory']['used_percent'] <= 100)
        self.assertGreater(d['disk']['total_bytes'], 0)
        self.assertTrue(0 <= d['disk']['used_percent'] <= 100)

    def test_live_cli(self):
        code, out, err = run_main(['--json'])
        self.assertIn(code, (0, 1))
        self.assertEqual(json.loads(out)['status'], 'OK' if code == 0 else 'WARN')

    def test_missing_path_is_exit_2(self):
        code, out, err = run_main(['--path', '/nonexistent/aster-resource-check-test'])
        self.assertEqual(code, 2)
        self.assertIn('No such file or directory', err)


if __name__ == '__main__':
    unittest.main()
