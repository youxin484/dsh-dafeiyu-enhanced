"""Render the hardware plate without the pet, for visual checks and docs.

    .build\\python-env\\Scripts\\python.exe scripts\\preview-stats-plate.py out.png

Uses the ``offscreen`` Qt platform by default, so it never flashes a window on
the desktop. Pass ``--platform windows`` (or set QT_QPA_PLATFORM) to see it live.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from hardware_stats import GpuStats, HardwareStats  # noqa: E402
from stats_plate import HardwarePlate  # noqa: E402


SAMPLES = {
    "idle": HardwareStats(
        cpu_percent=7.0,
        memory_percent=38.2,
        memory_used_bytes=int(12.3 * 1024 ** 3),
        memory_total_bytes=int(31.9 * 1024 ** 3),
        gpu=GpuStats(usage_percent=2.0, temperature_c=41.0),
    ),
    "busy": HardwareStats(
        cpu_percent=23.0,
        memory_percent=79.8,
        memory_used_bytes=int(24.8 * 1024 ** 3),
        memory_total_bytes=int(31.0 * 1024 ** 3),
        gpu=GpuStats(usage_percent=99.0, temperature_c=59.0),
    ),
    "hot": HardwareStats(
        cpu_percent=97.0,
        memory_percent=92.5,
        gpu=None,
    ),
}


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "stats-plate-preview.png")
    application = QApplication(sys.argv[:1])
    plate = HardwarePlate()
    plate.set_stats(SAMPLES["busy"])
    plate.show()
    application.processEvents()
    saved = plate.grab().save(str(output), "PNG")
    print(f"{output} {plate.width()}x{plate.height()} saved={saved}")
    for name in ("idle", "hot"):
        plate.set_stats(SAMPLES[name])
        plate.show()
        application.processEvents()
        target = output.with_name(output.stem + "-" + name + output.suffix)
        plate.grab().save(str(target), "PNG")
        print(f"{target} {plate.width()}x{plate.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
