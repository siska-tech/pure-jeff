"""Windows process-tree memory sampling for benchmark children (shared pages counted per process)."""
import ctypes as c
from ctypes import wintypes as w
import threading


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ProcessEntry(c.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", c.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


class Counters(c.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, c.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
        "PrivateUsage")]


_kernel = c.WinDLL("kernel32", use_last_error=True)
_psapi = c.WinDLL("psapi", use_last_error=True)
_kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
_kernel.OpenProcess.restype = w.HANDLE


def descendants(root):
    snapshot = _kernel.CreateToolhelp32Snapshot(2, 0)
    entry, children = ProcessEntry(dwSize=c.sizeof(ProcessEntry)), {}
    more = _kernel.Process32FirstW(snapshot, c.byref(entry))
    while more:
        children.setdefault(entry.th32ParentProcessID, []).append((entry.th32ProcessID, entry.szExeFile))
        more = _kernel.Process32NextW(snapshot, c.byref(entry))
    _kernel.CloseHandle(snapshot)
    out, pending = [], [(root, None)]
    while pending:
        pid, name = pending.pop()
        out.append((pid, name))
        pending.extend(children.get(pid, []))
    return out


def counters(pid):
    handle = _kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        value = Counters(cb=c.sizeof(Counters))
        ok = _psapi.GetProcessMemoryInfo(w.HANDLE(handle), c.byref(value), c.sizeof(value))
        return value if ok else None
    finally:
        _kernel.CloseHandle(handle)


class TreeSampler:
    """Samples a process tree until stopped. Peaks between samples or after a child exits can be
    missed; per-process lifetime peaks are read at every sample."""

    def __init__(self, root_pid, interval=0.1):
        self.root, self.interval = root_pid, interval
        self.max_tree_working_set = 0
        self.max_tree_private = 0
        self.max_process_peak_working_set = 0
        self.max_process_page_faults = 0
        self.samples = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            tree_ws = tree_private = 0
            for pid, _ in descendants(self.root):
                value = counters(pid)
                if value is None:
                    continue
                tree_ws += value.WorkingSetSize
                tree_private += value.PrivateUsage
                self.max_process_peak_working_set = max(self.max_process_peak_working_set, value.PeakWorkingSetSize)
                self.max_process_page_faults = max(self.max_process_page_faults, value.PageFaultCount)
            self.max_tree_working_set = max(self.max_tree_working_set, tree_ws)
            self.max_tree_private = max(self.max_tree_private, tree_private)
            self.samples += 1
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()

    def result(self):
        return {"max_tree_working_set": self.max_tree_working_set, "max_tree_private": self.max_tree_private,
                "max_process_peak_working_set": self.max_process_peak_working_set,
                "max_process_page_faults": self.max_process_page_faults, "samples": self.samples}


