"""Reject incomplete/changed host evidence; retain errors on benchmark failure."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest

from observe_windows_host import HostMonitor, parse_cpu_sets, summarize


def samples():
    a = {'monotonic_ns': 0, 'collection_ns': 1000, 'power_status_raw': {'ac_line_status': 1, 'system_status_flag': 0},
         'active_scheme_guid': 'scheme', 'observer_affinity': {'process_mask': 65535, 'system_mask': 65535},
         'cpu_sets': [{'id': 256, 'group': 0, 'logical_processor': 0, 'core': 0, 'efficiency_class': 1}],
         'system_cpu_100ns': {'idle': 0, 'kernel_including_idle': 0, 'user': 0},
         'processor_power_os_report': [{'current_mhz': 2200}]}
    b = copy.deepcopy(a); b['monotonic_ns'] = 10**9
    b['system_cpu_100ns'] = {'idle': 60, 'kernel_including_idle': 80, 'user': 20}
    return [a, b]


class HostTests(unittest.TestCase):
    def test_valid_and_scope(self):
        row = summarize(samples(), 1)
        self.assertTrue(row['sampled_conditions_passed'])
        self.assertEqual(row['system_busy_percent_max'], 40)
        self.assertFalse(row['hardware_frequency_measured'])
        self.assertFalse(row['compute_affinity_controlled'])

    def test_unknown_ac_and_saver_rejected(self):
        for key, value in [('ac_line_status', 255), ('ac_line_status', 0), ('system_status_flag', 1), ('system_status_flag', 255)]:
            rows = samples(); rows[1]['power_status_raw'][key] = value
            self.assertFalse(summarize(rows, 1)['sampled_conditions_passed'])

    def test_scheme_affinity_topology_change_rejected(self):
        for key, value in [('active_scheme_guid', 'other'), ('observer_affinity', {}), ('cpu_sets', [])]:
            rows = samples(); rows[1][key] = value
            self.assertFalse(summarize(rows, 1)['sampled_conditions_passed'])

    def test_missing_gap_error_and_counter_rejected(self):
        self.assertFalse(summarize([], 1)['sampled_conditions_passed'])
        self.assertFalse(summarize(samples()[:1], 1)['sampled_conditions_passed'])
        self.assertFalse(summarize(samples(), 1, ['sensor error'])['sampled_conditions_passed'])
        rows = samples(); rows[1]['monotonic_ns'] = 3*10**9
        self.assertFalse(summarize(rows, 1)['sampled_conditions_passed'])
        rows = samples(); rows[1]['system_cpu_100ns']['idle'] = 200
        self.assertFalse(summarize(rows, 1)['sampled_conditions_passed'])

    def test_cpu_records_skip_unknown_and_reject_truncation_duplicates(self):
        record = struct.pack('<IIIHBBBBBBIQ', 32, 0, 256, 0, 0, 0, 0, 0, 1, 1, 0, 0)
        parsed = parse_cpu_sets(struct.pack('<II', 8, 99)+record)
        self.assertEqual(parsed[0]['efficiency_class'], 1)
        self.assertTrue(parsed[0]['parked'])
        for data in [b'', record[:7], record[:-1], struct.pack('<II', 0, 0), record+record]:
            with self.assertRaises(ValueError):
                parse_cpu_sets(data)

    def test_monitor_retains_original_failure(self):
        def reader():
            row = samples()[0]; row['monotonic_ns'] = time.perf_counter_ns()
            # Simulate monotonic Windows cumulative counters.
            row['system_cpu_100ns']['kernel_including_idle'] = row['monotonic_ns']//100
            return row
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.venv') as temp:
            with self.assertRaisesRegex(ValueError, 'original child failure'):
                with HostMonitor(temp, 'failed', .1, reader):
                    time.sleep(.12)
                    raise ValueError('original child failure')
            self.assertTrue((Path(temp)/'failed.host.jsonl').exists())
            self.assertIn('samples', json.loads((Path(temp)/'failed.host-summary.json').read_text()))

    def test_initial_reader_failure_is_saved(self):
        def broken():
            raise OSError('sensor unavailable')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.venv') as temp:
            with self.assertRaises(OSError):
                with HostMonitor(temp, 'broken', .1, broken):
                    self.fail('child must not start')
            row = json.loads((Path(temp)/'broken.host-summary.json').read_text())
            self.assertFalse(row['sampled_conditions_passed'])
            self.assertIn('sensor unavailable', row['reasons'][0])


if __name__ == '__main__':
    unittest.main()
