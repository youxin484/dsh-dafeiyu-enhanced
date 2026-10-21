"""The small "hardware plate" that floats above the companion's prompt bubble.

It is a separate, frameless, always-on-top, mouse-transparent window: keeping it
out of the pet window means the pet's drag / resize / bubble geometry math never
has to reserve space for it, and a plate that is transparent for input can never
steal a click from the character.

Layout: one group per metric (CPU, every GPU, memory) flowing left to right.
One GPU stays on a single line; several GPUs wrap onto more lines instead of
producing an unusably wide strip. Every GPU shows its VRAM as used/total.

Colours follow the same palette family as the status card but stay darker, so
the plate reads as a HUD rather than as another message card.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

try:
    from .hardware_stats import HardwareStats
except ImportError:
    from hardware_stats import HardwareStats


BASE_FONT_PT = 8.5
PADDING_X = 10
PADDING_Y = 4
LINE_HEIGHT = 22
DOT_SIZE = 5
SEGMENT_GAP = 5
GROUP_GAP = 12
MAX_ROW_WIDTH = 430

LABEL_COLOR = QColor("#A9B6C6")
VALUE_COLORS = {
    "ok": QColor("#F2F7FD"),
    "warn": QColor("#FFD07A"),
    "error": QColor("#FF9B9B"),
    "idle": QColor("#8A97A5"),
}
DOT_COLORS = {
    "ok": QColor("#63C8FF"),
    "warn": QColor("#FFC65C"),
    "error": QColor("#FF7A7A"),
    "idle": QColor("#5C6875"),
}
BACKGROUND = QColor(15, 19, 26, 214)
BORDER = QColor(255, 255, 255, 34)


def level_of(value: float | None) -> str:
    if value is None:
        return "idle"
    if value >= 90.0:
        return "error"
    if value >= 75.0:
        return "warn"
    return "ok"


def _percent_text(value: float | None) -> str:
    if value is None:
        return "--"
    return str(int(round(value))) + "%"


def _gigabytes(value: int | None) -> str | None:
    if value is None or value <= 0:
        return None
    return f"{value / (1024 ** 3):.1f}"


def _gpu_value(gpu) -> str:
    parts = [_percent_text(gpu.usage_percent)]
    used = _gigabytes(gpu.memory_used_bytes)
    total = _gigabytes(gpu.memory_total_bytes)
    if used is not None and total is not None:
        parts.append(f"{used}/{total}G")
    if gpu.temperature_c is not None:
        parts.append(str(int(round(gpu.temperature_c))) + "°")
    return " ".join(parts)


class HardwarePlate(QWidget):
    """Always-on-top pill: ``CPU 23%  GPU0 99% 10.6/12.0G 57°  内存 41%``."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("DSH 大肥鱼 · 硬件状态")
        self._stats = HardwareStats()
        self._scale = 1.0
        self._label_font = QFont("Microsoft YaHei UI")
        self._value_font = QFont("Microsoft YaHei UI")
        self._row_indexes: list[list[int]] = []
        self._segments_cache: list[tuple[str, str, str]] = []
        self._widths: list[int] = []
        self._metrics: dict[str, int] = {}
        self._apply_fonts()
        self._relayout()

    # ------------------------------------------------------------------ data

    def set_stats(self, stats: HardwareStats) -> None:
        self._stats = stats
        self._relayout()

    def set_scale(self, scale: float) -> None:
        value = max(0.7, min(1.7, float(scale)))
        if abs(value - self._scale) < 0.001:
            return
        self._scale = value
        self._apply_fonts()
        self._relayout()

    def _apply_fonts(self) -> None:
        size = max(6.0, BASE_FONT_PT * self._scale)
        self._label_font.setPointSizeF(size)
        self._value_font.setPointSizeF(size)
        self._value_font.setWeight(QFont.Weight.DemiBold)

    # --------------------------------------------------------------- segments

    def _segments(self) -> list[tuple[str, str, str]]:
        """(label, value, level) groups: CPU, one per GPU, memory."""
        segments: list[tuple[str, str, str]] = [
            ("CPU", _percent_text(self._stats.cpu_percent), level_of(self._stats.cpu_percent))
        ]
        gpus = self._stats.gpus
        if not gpus:
            segments.append(("GPU", "--", "idle"))
        else:
            multiple = len(gpus) > 1
            for gpu in gpus:
                label = f"GPU{gpu.index}" if multiple else "GPU"
                segments.append((label, _gpu_value(gpu), level_of(gpu.usage_percent)))
        segments.append(
            ("内存", _percent_text(self._stats.memory_percent), level_of(self._stats.memory_percent))
        )
        return segments

    # ---------------------------------------------------------------- layout

    def _measured(self) -> tuple[dict[str, int], list[int]]:
        s = self._scale
        metrics = {
            "padding_x": max(6, int(round(PADDING_X * s))),
            "padding_y": max(3, int(round(PADDING_Y * s))),
            "line": max(16, int(round(LINE_HEIGHT * s))),
            "dot": max(3, int(round(DOT_SIZE * s))),
            "segment_gap": max(3, int(round(SEGMENT_GAP * s))),
            "group_gap": max(6, int(round(GROUP_GAP * s))),
            "radius": max(7, int(round(11 * s))),
        }
        labels = QFontMetrics(self._label_font)
        values = QFontMetrics(self._value_font)
        widths = []
        for label, value, _level in self._segments():
            widths.append(
                metrics["dot"]
                + metrics["segment_gap"]
                + labels.horizontalAdvance(label)
                + metrics["segment_gap"]
                + values.horizontalAdvance(value)
            )
        return metrics, widths

    def _relayout(self) -> None:
        metrics, widths = self._measured()
        segments = self._segments()
        max_row = max(120, int(round(MAX_ROW_WIDTH * min(1.6, self._scale))))

        def flow(limit: int) -> list[list[int]]:
            rows: list[list[int]] = []
            current: list[int] = []
            used = 0
            for index, width in enumerate(widths):
                extra = width if not current else metrics["group_gap"] + width
                if current and used + extra > limit:
                    rows.append(current)
                    current = [index]
                    used = width
                else:
                    current.append(index)
                    used += extra
            if current:
                rows.append(current)
            return rows

        rows = flow(max_row)
        if len(rows) > 1:
            # Greedy filling leaves a tiny last row (e.g. only 内存 under two
            # GPUs); re-flow toward the average so both rows carry a similar
            # amount of information.
            total = sum(widths) + metrics["group_gap"] * (len(widths) - 1)
            target = max(120, int(total / len(rows)) + metrics["group_gap"])
            rows = flow(min(max_row, target))

        row_widths = []
        for row in rows:
            total = sum(widths[index] for index in row)
            total += metrics["group_gap"] * (len(row) - 1)
            row_widths.append(total)
        width = max(row_widths) + metrics["padding_x"] * 2
        height = metrics["line"] * len(rows) + metrics["padding_y"] * 2
        self._metrics = metrics
        self._row_indexes = rows
        self._widths = widths
        self._segments_cache = segments
        self.setFixedSize(max(96, int(width)), max(20, int(height)))

    def follow(self, anchor_rect: QRect, screen_rect: QRect | None = None, gap: int = 6) -> None:
        """Center the plate above the anchor (the prompt bubble) and clamp to the screen."""
        width, height = self.width(), self.height()
        x = anchor_rect.center().x() - width // 2
        y = anchor_rect.top() - height - gap
        if screen_rect is not None:
            x = min(max(x, screen_rect.left() + 6), max(screen_rect.left() + 6, screen_rect.right() - width - 6))
            y = min(max(y, screen_rect.top() + 6), max(screen_rect.top() + 6, screen_rect.bottom() - height - 6))
        target = QPoint(int(x), int(y))
        if self.pos() != target:
            self.move(target)

    # --------------------------------------------------------------- painting

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        metrics = self._metrics
        radius = min(self.height() / 2.0, float(metrics["radius"]))
        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        labels = QFontMetrics(self._label_font)
        values = QFontMetrics(self._value_font)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        line = metrics["line"]
        for row_index, row in enumerate(self._row_indexes):
            y = metrics["padding_y"] + row_index * line
            center_y = y + line / 2.0
            x = metrics["padding_x"]
            for position, segment_index in enumerate(row):
                label, value, level = self._segments_cache[segment_index]
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(DOT_COLORS.get(level, DOT_COLORS["idle"]))
                painter.drawEllipse(
                    QRectF(x, center_y - metrics["dot"] / 2.0, metrics["dot"], metrics["dot"])
                )
                x += metrics["dot"] + metrics["segment_gap"]

                painter.setFont(self._label_font)
                painter.setPen(LABEL_COLOR)
                label_width = labels.horizontalAdvance(label)
                painter.drawText(QRect(x, y, label_width, line), align, label)
                x += label_width + metrics["segment_gap"]

                painter.setFont(self._value_font)
                painter.setPen(VALUE_COLORS.get(level, VALUE_COLORS["ok"]))
                value_width = values.horizontalAdvance(value)
                painter.drawText(QRect(x, y, value_width, line), align, value)
                x += value_width
                if position != len(row) - 1:
                    x += metrics["group_gap"]
