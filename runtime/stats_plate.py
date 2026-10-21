"""The small "hardware plate" that floats beside the desktop companion.

It is a separate, frameless, always-on-top, mouse-transparent window: keeping it
out of the pet window means the pet's drag / resize / bubble geometry math never
has to reserve space for it, and a plate that is transparent for input can never
steal a click from the character.

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


PLATE_HEIGHT = 24
PLATE_PADDING_X = 10
DOT_SIZE = 5
SEGMENT_GAP = 5
GROUP_GAP = 12

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


class HardwarePlate(QWidget):
    """Always-on-top pill: ``CPU 23%  GPU 99% 57°  内存 41%``."""

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
        self._label_font = QFont("Microsoft YaHei UI")
        self._label_font.setPointSizeF(8.5)
        self._value_font = QFont("Microsoft YaHei UI")
        self._value_font.setPointSizeF(8.5)
        self._value_font.setWeight(QFont.Weight.DemiBold)
        self._widths: list[int] = []
        self._resize_to_content()

    # ------------------------------------------------------------------ data

    def set_stats(self, stats: HardwareStats) -> None:
        self._stats = stats
        self._resize_to_content()
        self.update()

    def _segments(self) -> list[tuple[str, str, str]]:
        gpu = self._stats.gpu
        if gpu is None or gpu.usage_percent is None:
            gpu_value = "--"
            gpu_level = "idle"
        else:
            gpu_value = _percent_text(gpu.usage_percent)
            if gpu.temperature_c is not None:
                gpu_value += " " + str(int(round(gpu.temperature_c))) + "°"
            gpu_level = level_of(gpu.usage_percent)
        return [
            ("CPU", _percent_text(self._stats.cpu_percent), level_of(self._stats.cpu_percent)),
            ("GPU", gpu_value, gpu_level),
            ("内存", _percent_text(self._stats.memory_percent), level_of(self._stats.memory_percent)),
        ]

    # ---------------------------------------------------------------- layout

    def _resize_to_content(self) -> None:
        label_metrics = QFontMetrics(self._label_font)
        value_metrics = QFontMetrics(self._value_font)
        widths: list[int] = []
        for label, value, _level in self._segments():
            widths.append(
                DOT_SIZE
                + SEGMENT_GAP
                + label_metrics.horizontalAdvance(label)
                + SEGMENT_GAP
                + value_metrics.horizontalAdvance(value)
            )
        total = PLATE_PADDING_X * 2 + sum(widths) + GROUP_GAP * (len(widths) - 1)
        self._widths = widths
        self.setFixedSize(max(96, int(total)), PLATE_HEIGHT)

    def follow(self, pet_rect: QRect, screen_rect: QRect | None = None) -> None:
        """Hang the plate at the character's feet, left side when there is room."""
        width, height = self.width(), self.height()
        x = pet_rect.left() - width - 10
        y = pet_rect.bottom() - height - 8
        if screen_rect is not None:
            if x < screen_rect.left() + 6:
                # No room on the left: flip to the character's right side.
                x = pet_rect.right() + 10
            x = min(max(x, screen_rect.left() + 6), max(screen_rect.left() + 6, screen_rect.right() - width - 6))
            y = min(max(y, screen_rect.top() + 6), max(screen_rect.top() + 6, screen_rect.bottom() - height - 6))
        target = QPoint(int(x), int(y))
        if self.pos() != target:
            self.move(target)

    # --------------------------------------------------------------- painting

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2.0
        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        labels = QFontMetrics(self._label_font)
        values = QFontMetrics(self._value_font)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        x = PLATE_PADDING_X
        center_y = self.height() / 2.0
        for label, value, level in self._segments():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(DOT_COLORS.get(level, DOT_COLORS["idle"]))
            painter.drawEllipse(QRectF(x, center_y - DOT_SIZE / 2.0, DOT_SIZE, DOT_SIZE))
            x += DOT_SIZE + SEGMENT_GAP

            painter.setFont(self._label_font)
            painter.setPen(LABEL_COLOR)
            label_width = labels.horizontalAdvance(label)
            painter.drawText(QRect(x, 0, label_width, self.height()), align, label)
            x += label_width + SEGMENT_GAP

            painter.setFont(self._value_font)
            painter.setPen(VALUE_COLORS.get(level, VALUE_COLORS["ok"]))
            value_width = values.horizontalAdvance(value)
            painter.drawText(QRect(x, 0, value_width, self.height()), align, value)
            x += value_width + GROUP_GAP
