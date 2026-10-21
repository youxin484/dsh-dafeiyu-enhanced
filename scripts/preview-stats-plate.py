"""Render the hardware plate without the pet, for visual checks and docs.

    .build\\python-env\\Scripts\\python.exe scripts\\preview-stats-plate.py out.png

Uses the ``offscreen`` Qt platform by default; the offscreen plugin has no fonts
here, so pass ``QT_QPA_PLATFORM=windows`` to check real glyphs (it flashes one
tiny window for a moment). Renders single-GPU, dual-GPU and no-GPU states, plus
the 1.3x plate scale.
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


GB = 1024 ** 3
RTX = GpuStats(
    index=0,
    name="NVIDIA GeForce RTX 4070 Ti",
    usage_percent=99.0,
    temperature_c=59.0,
    memory_used_bytes=int(10.6 * GB),
    memory_total_bytes=int(12.0 * GB),
)
SECOND = GpuStats(
    index=1,
    name="NVIDIA GeForce RTX 4070 Ti",
    usage_percent=41.0,
    temperature_c=47.0,
    memory_used_bytes=int(3.2 * GB),
    memory_total_bytes=int(12.0 * GB),
)

SAMPLES = {
    "single": HardwareStats(
        cpu_percent=23.0,
        memory_percent=79.8,
        memory_used_bytes=int(24.8 * GB),
        memory_total_bytes=int(31.0 * GB),
        gpus=[RTX],
    ),
    "dual": HardwareStats(
        cpu_percent=23.0,
        memory_percent=79.8,
        memory_used_bytes=int(24.8 * GB),
        memory_total_bytes=int(31.0 * GB),
        gpus=[RTX, SECOND],
    ),
    "nogpu": HardwareStats(cpu_percent=97.0, memory_percent=92.5),
}


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "stats-plate-preview.png")
    application = QApplication(sys.argv[:1])
    plate = HardwarePlate()
    cases = [("single", 1.0), ("dual", 1.0), ("dual", 1.3), ("nogpu", 1.0)]
    for name, scale in cases:
        plate.set_scale(scale)
        plate.set_stats(SAMPLES[name])
        plate.show()
        application.processEvents()
        suffix = "" if (name, scale) == ("single", 1.0) else f"-{name}-x{scale:.2f}".replace(".", "_")
        target = output.with_name(output.stem + suffix + output.suffix)
        saved = plate.grab().save(str(target), "PNG")
        print(f"{target} {plate.width()}x{plate.height()} saved={saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
