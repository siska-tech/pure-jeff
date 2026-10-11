"""Read-only Windows benchmark telemetry; development tool, not runtime code."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import struct
import threading
import time
import uuid

from benchmark_pilot import invoke, save, sha
from diagnose_native_repeats import host_state


def parse_cpu_sets(data):
    """Walk variable-sized SDK records, skipping unknown future types."""
    result = []
    offset = 0
    while offset < len(data):
        if len(data)-offset < 8:
            raise ValueError('truncated CPU set header')
        size, kind = struct.unpack_from('<II', data, offset)
        if size < 8 or offset+size > len(data):
            raise ValueError('invalid CPU set record size')
        if kind == 0:
            if size < 32:
                raise ValueError('truncated CPU set record')
            values = struct.unpack_from('<IHBBBBBB', data, offset+8)
            names = ['id', 'group', 'logical_processor', 'core', 'last_level_cache',
                     'numa_node', 'efficiency_class', 'flags']
            row = dict(zip(names, values))
            row['parked'] = bool(row['flags'] & 1)
            result.append(row)
        offset += size
    if not result or len({(r['group'], r['logical_processor']) for r in result}) != len(result):
        raise ValueError('empty or duplicate CPU sets')
    return result


class ProcessorPower(c.Structure):
    _fields_ = [(name, w.ULONG) for name in
                ['number', 'max_mhz', 'current_mhz', 'mhz_limit', 'max_idle_state', 'current_idle_state']]


class WindowsReader:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows required')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.power = c.WinDLL('powrprof', use_last_error=True)
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
        self.kernel.GetProcessAffinityMask.restype = w.BOOL
        self.kernel.GetSystemCpuSetInformation.argtypes = [c.c_void_p, w.ULONG, c.POINTER(w.ULONG), w.HANDLE, w.ULONG]
        self.kernel.GetSystemCpuSetInformation.restype = w.BOOL
        self.kernel.LocalFree.argtypes = [c.c_void_p]
        self.kernel.LocalFree.restype = c.c_void_p
        self.power.PowerGetActiveScheme.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
        self.power.PowerGetActiveScheme.restype = w.DWORD
        self.power.CallNtPowerInformation.argtypes = [c.c_int, c.c_void_p, w.ULONG, c.c_void_p, w.ULONG]
        self.power.CallNtPowerInformation.restype = c.c_long

    def cpu_sets(self):
        needed = w.ULONG()
        process = self.kernel.GetCurrentProcess()
        ok = self.kernel.GetSystemCpuSetInformation(None, 0, c.byref(needed), process, 0)
        if not ok and c.get_last_error() != 122:
            raise OSError(c.get_last_error(), 'GetSystemCpuSetInformation size')
        if not 0 < needed.value < 1024*1024:
            raise ValueError('invalid CPU set buffer size')
        buf = c.create_string_buffer(needed.value)
        if not self.kernel.GetSystemCpuSetInformation(buf, len(buf), c.byref(needed), process, 0):
            raise OSError(c.get_last_error(), 'GetSystemCpuSetInformation')
        return parse_cpu_sets(buf.raw[:needed.value])

    def __call__(self):
        started = time.perf_counter_ns()
        row = host_state()
        guid = c.c_void_p()
        status = self.power.PowerGetActiveScheme(None, c.byref(guid))
        if status:
            raise OSError(status, 'PowerGetActiveScheme')
        try:
            row['active_scheme_guid'] = str(uuid.UUID(bytes_le=c.string_at(guid, 16)))
        finally:
            self.kernel.LocalFree(guid)
        process_mask = c.c_size_t(); system_mask = c.c_size_t()
        if not self.kernel.GetProcessAffinityMask(self.kernel.GetCurrentProcess(), c.byref(process_mask), c.byref(system_mask)):
            raise OSError(c.get_last_error(), 'GetProcessAffinityMask')
        row['observer_affinity'] = {'process_mask': process_mask.value, 'system_mask': system_mask.value}
        row['cpu_sets'] = self.cpu_sets()
        # Explicitly fail rather than mislabel multi-group processor numbering.
        if {r['group'] for r in row['cpu_sets']} != {0}:
            raise RuntimeError('single processor group required by this observer')
        buf = (ProcessorPower*len(row['cpu_sets']))()
        status = self.power.CallNtPowerInformation(11, None, 0, c.byref(buf), c.sizeof(buf))
        if status != 0:
            raise OSError(status, 'CallNtPowerInformation ProcessorInformation')
        row['processor_power_os_report'] = [{name: getattr(p, name) for name, _ in p._fields_} for p in buf]
        if {p['number'] for p in row['processor_power_os_report']} != {r['logical_processor'] for r in row['cpu_sets']}:
            raise ValueError('processor power/topology coverage mismatch')
        row.update(monotonic_ns=started, collection_ns=time.perf_counter_ns()-started,
                   temperature_celsius=None, temperature_status='unavailable; no temperature sensor queried by sampler')
        return row


def summarize(samples, interval, errors=()):
    reasons = list(errors)
    gaps = [(b['monotonic_ns']-a['monotonic_ns'])/1e9 for a, b in zip(samples, samples[1:])]
    if len(samples) < 2 or any(g <= 0 or g > 2.5*interval for g in gaps):
        reasons.append('insufficient samples or cadence gap')
    if any(s['power_status_raw']['ac_line_status'] != 1 or s['power_status_raw']['system_status_flag'] != 0 for s in samples):
        reasons.append('AC disconnected/unknown or battery saver enabled/unknown')
    if len({s['active_scheme_guid'] for s in samples}) != 1:
        reasons.append('power scheme changed or missing')
    if len({json.dumps(s['observer_affinity'], sort_keys=True) for s in samples}) != 1:
        reasons.append('observer affinity changed or missing')
    topology = lambda s: [(r['id'], r['group'], r['logical_processor'], r['core'], r['efficiency_class']) for r in s['cpu_sets']]
    if len({str(topology(s)) for s in samples}) != 1:
        reasons.append('CPU topology changed or missing')
    busy = []
    for a, b in zip(samples, samples[1:]):
        x = a['system_cpu_100ns']; y = b['system_cpu_100ns']
        total = y['kernel_including_idle']+y['user']-x['kernel_including_idle']-x['user']
        idle = y['idle']-x['idle']
        if total <= 0 or not 0 <= idle <= total:
            reasons.append('invalid system CPU counter delta')
        else:
            busy.append(100*(total-idle)/total)
    mhz = [p['current_mhz'] for s in samples for p in s['processor_power_os_report']]
    return {'sampled_conditions_passed': not reasons, 'reasons': reasons, 'samples': len(samples),
            'elapsed_seconds': sum(gaps), 'maximum_gap_seconds': max(gaps, default=None),
            'collection_ms_max': max((s['collection_ns']/1e6 for s in samples), default=None),
            'system_busy_percent_min': min(busy, default=None), 'system_busy_percent_max': max(busy, default=None),
            'os_reported_current_mhz_min': min(mhz, default=None), 'os_reported_current_mhz_max': max(mhz, default=None),
            'temperature_available': False, 'hardware_frequency_measured': False, 'compute_affinity_controlled': False,
            'background_load_controlled': False, 'formal_slo_acceptance': False,
            'scope': 'sampled host state only; gaps may hide changes; system busy includes all processes; observer masks are not child worker placement'}


class HostMonitor:
    """Always retain telemetry and propagate observation failures after the child exits."""
    def __init__(self, outdir, run_id, interval=1.0, reader=None):
        if not math.isfinite(interval) or not .1 <= interval <= 10:
            raise ValueError('interval must be finite and in [0.1,10] seconds')
        self.outdir = Path(outdir); self.run_id = run_id; self.interval = interval
        self.reader = reader if reader is not None else WindowsReader()
        self.samples = []; self.errors = []; self.stop = threading.Event()

    def sample(self):
        row = self.reader()
        self.samples.append(row)
        self.stream.write(json.dumps(row, allow_nan=False)+'\n'); self.stream.flush()

    def loop(self):
        while not self.stop.wait(self.interval):
            try:
                self.sample()
            except Exception as error:
                self.errors.append(repr(error)); return

    def __enter__(self):
        self.stream = (self.outdir/(self.run_id+'.host.jsonl')).open('x', encoding='utf-8')
        try:
            self.sample()
        except Exception as error:
            self.errors.append(repr(error)); self.finish()
            raise
        self.thread = threading.Thread(target=self.loop, name='host-observer', daemon=True)
        self.thread.start()
        return self

    def finish(self):
        self.stream.close()
        self.summary = summarize(self.samples, self.interval, self.errors)
        save(self.outdir/(self.run_id+'.host-summary.json'), self.summary)

    def __exit__(self, kind, error, trace):
        self.stop.set(); self.thread.join()
        try:
            self.sample()
        except Exception as sampling_error:
            self.errors.append(repr(sampling_error))
        self.finish()
        if kind is None and not self.summary['sampled_conditions_passed']:
            raise RuntimeError('host observation failed; retained telemetry and summary')
        return False


def invoke_observed(command, outdir, run_id, memory_limit, timeout=600, interval=1.0):
    """Opt-in wrapper; existing benchmark invoke and frozen exes remain unchanged."""
    with HostMonitor(outdir, run_id, interval) as monitor:
        record = invoke(command, outdir, run_id, memory_limit, timeout)
    return {**record, 'host_observation': monitor.summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--interval', type=float, default=1)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not 2 <= args.duration <= 300:
        raise ValueError('duration must be finite and in [2,300] seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'preregistration.json', {'utc': datetime.now(timezone.utc).isoformat(),
         'script_sha256': sha(__file__), 'host_helper_sha256': sha(Path(__file__).with_name('diagnose_native_repeats.py')),
         'benchmark_helper_sha256': sha(Path(__file__).with_name('benchmark_pilot.py')),
         'duration_seconds': args.duration, 'interval_seconds': args.interval,
         'acceptance': 'AC1,battery saver0,stable scheme/observer mask/topology,2+ samples,each gap <=2.5*interval',
         'purpose': 'observer smoke check only; no inference or performance acceptance',
         'settings_changed': False})
    with HostMonitor(args.output, 'preflight', args.interval) as monitor:
        time.sleep(args.duration)
    print(json.dumps(monitor.summary, indent=2))


if __name__ == '__main__':
    main()
