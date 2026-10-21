"""CPU / memory / GPU sampling for the companion hardware plate.

The module is deliberately stdlib-only (``ctypes`` + ``subprocess`` +
``threading``): PySide6 is never imported here, so it can be exercised with any
Python 3.9+ interpreter and frozen into the helper without extra hooks.

Design notes
------------
* CPU and memory are read synchronously; both are single cheap OS calls
  (>0.2 ms), safe to run from the Qt timer every second.
* ``nvidia-smi`` takes 40-60 ms per call, so the GPU lives in a background
  daemon thread and the UI only ever reads the cached value.
* Every reader degrades to ``None`` instead of raising: a machine without a
  NVIDIA card (or without ``nvidia-smi`` on an unusual path) still shows
  CPU / memory, and the plate renders ``--`` for the missing metric.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass

CREATE_NO_WINDOW = 0x08000000
GPU_QUERY_FIELDS = "utilization.gpu,memory.used,memory.total,temperature.gpu"
MIB = 1024 * 1024


@dataclass
class GpuStats:
    usage_percent: float | None = None
    temperature_c: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None


@dataclass
class HardwareStats:
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    gpu: GpuStats | None = None


# --------------------------------------------------------------- CPU / memory


if sys.platform == "win32":

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    def _filetime_value(value: "_FILETIME") -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def _read_cpu_times() -> tuple[int, int]:
        """Return cumulative (idle, total) CPU ticks; kernel time includes idle."""
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise OSError("GetSystemTimes failed")
        return _filetime_value(idle), _filetime_value(kernel) + _filetime_value(user)

    def _read_memory() -> tuple[int, int, float]:
        """Return (used bytes, total bytes, used percent)."""
        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        total = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
        return total - available, total, float(status.dwMemoryLoad)

elif os.path.exists("/proc/stat"):

    def _read_cpu_times() -> tuple[int, int]:
        with open("/proc/stat", "r", encoding="utf-8") as stream:
            fields = stream.readline().split()
        values = [int(field) for field in fields[1:9]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)

    def _read_memory() -> tuple[int, int, float]:
        info: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as stream:
            for line in stream:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    info[key] = int(parts[0]) * 1024
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        if total <= 0:
            raise OSError("MemTotal unavailable")
        percent = (total - available) / total * 100.0
        return total - available, total, percent

else:  # macOS and anything else: the plate degrades to "--"

    def _read_cpu_times() -> tuple[int, int]:
        raise OSError("CPU sampling is not supported on this platform")

    def _read_memory() -> tuple[int, int, float]:
        raise OSError("memory sampling is not supported on this platform")


# ------------------------------------------------------------------------ GPU


def nvidia_smi_path() -> str | None:
    """Return the first existing nvidia-smi executable, or None."""
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    candidates = [
        os.path.join(system_root, "System32", "nvidia-smi.exe"),
        shutil.which("nvidia-smi"),
        "C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _number(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return None


def _read_gpu() -> GpuStats | None:
    executable = nvidia_smi_path()
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=" + GPU_QUERY_FIELDS,
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    line = next((row for row in completed.stdout.splitlines() if row.strip()), "")
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        return None
    used = _number(parts[1])
    total = _number(parts[2])
    return GpuStats(
        usage_percent=_number(parts[0]),
        memory_used_bytes=int(used * MIB) if used is not None else None,
        memory_total_bytes=int(total * MIB) if total is not None else None,
        temperature_c=_number(parts[3]),
    )


# -------------------------------------------------------------------- sampler


class HardwareSampler:
    """Synchronous CPU/memory reads plus one background nvidia-smi poller."""

    def __init__(self, gpu_interval_seconds: float = 2.0) -> None:
        self._lock = threading.Lock()
        self._gpu: GpuStats | None = None
        self._gpu_interval = max(1.0, float(gpu_interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            self._last_cpu_times: tuple[int, int] | None = _read_cpu_times()
        except OSError:
            self._last_cpu_times = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._gpu_loop, name="dafeiyu-gpu-stats", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _gpu_loop(self) -> None:
        delay = 0.0
        while not self._stop.wait(delay):
            stats = _read_gpu()
            with self._lock:
                self._gpu = stats
            # No NVIDIA card / no nvidia-smi: retry rarely instead of twice a
            # second, so the plate stays silent without burning CPU on spawns.
            delay = self._gpu_interval if stats is not None else 15.0

    def snapshot(self) -> HardwareStats:
        current: tuple[int, int] | None
        try:
            current = _read_cpu_times()
        except OSError:
            current = None
        cpu_percent: float | None = None
        if current is not None and self._last_cpu_times is not None:
            idle_delta = current[0] - self._last_cpu_times[0]
            total_delta = current[1] - self._last_cpu_times[1]
            if total_delta > 0:
                cpu_percent = max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))
        if current is not None:
            self._last_cpu_times = current
        memory_percent: float | None = None
        memory_used: int | None = None
        memory_total: int | None = None
        try:
            memory_used, memory_total, memory_percent = _read_memory()
        except OSError:
            pass
        with self._lock:
            gpu = self._gpu
        return HardwareStats(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_used_bytes=memory_used,
            memory_total_bytes=memory_total,
            gpu=gpu,
        )
