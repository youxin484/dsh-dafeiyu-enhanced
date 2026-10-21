"""Phase 0 native BigFish helper.

The DSH plugin owns this process and sends newline-delimited JSON over stdin.
Closing stdin is a lifecycle signal: the helper exits instead of becoming an
independent desktop application.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, TextIO

try:
    from .animation_model import AnimationModel, crossfade_duration
    from .layout_store import default_layout_path, load_layout, save_layout
    from .asset_paths import bundle_root
    from .hardware_stats import HardwareSampler, HardwareStats
    from .pet_geometry import bubble_top, position_window
    from .pet_sliders import fish_icon as _fish_icon, rheostat_style as _rheostat_style
except ImportError:
    from animation_model import AnimationModel, crossfade_duration
    from layout_store import default_layout_path, load_layout, save_layout
    from asset_paths import bundle_root
    from hardware_stats import HardwareSampler, HardwareStats
    from pet_geometry import bubble_top, position_window
    from pet_sliders import fish_icon as _fish_icon, rheostat_style as _rheostat_style


PROTOCOL_VERSION = 1
STATES = {"IDLE", "THINKING", "WORKING", "WAITING", "SUCCESS", "ERROR", "DISCONNECTED"}
# A decoded 412x344 ARGB32 frame costs ~0.55 MB, so keeping every frame of a
# 24 fps set resident would need well over a gigabyte. Frames are read from disk
# once as compressed bytes and decoded through a bounded cache instead.
DECODED_FRAME_CACHE = 24


def configure_qt_platform() -> None:
    """Prefer XWayland when available so desktop-window controls keep working."""
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM"):
        return
    platforms: list[str] = []
    if os.environ.get("DISPLAY"):
        platforms.append("xcb")
    if os.environ.get("WAYLAND_DISPLAY"):
        platforms.append("wayland")
    if platforms:
        os.environ["QT_QPA_PLATFORM"] = ";".join(platforms)


def configure_stdio() -> None:
    """Make the JSONL pipe UTF-8 regardless of the Windows console code page."""
    for stream, errors in ((sys.stdin, "strict"), (sys.stdout, "backslashreplace"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def parse_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    if message.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    kind = message.get("kind")
    if kind in {"state", "pulse"} and message.get("state") not in STATES:
        raise ValueError("unsupported companion state")
    return message


def emit_reply(kind: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"protocolVersion": PROTOCOL_VERSION, "kind": kind, "timestamp": int(time.time() * 1000), **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


# ---- Glove cursor (native Win32 .cur) ----
def _cursor_api() -> tuple[Any, Any, Any]:
    """Return configured (LoadCursorFromFileW, SetCursor, LoadCursorW) callables.

    Function signatures are declared explicitly so HCURSOR values are handled
    as pointer-sized handles: without argtypes/restype, ctypes treats the
    return value as a C int and truncates 64-bit HCURSORs. wintypes has no
    HCURSOR type, so ``wintypes.HANDLE`` (pointer-sized) is used.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    load_from_file = user32.LoadCursorFromFileW
    load_from_file.argtypes = [wintypes.LPCWSTR]
    load_from_file.restype = wintypes.HANDLE

    set_cursor = user32.SetCursor
    set_cursor.argtypes = [wintypes.HANDLE]
    set_cursor.restype = wintypes.HANDLE

    load_cursor = user32.LoadCursorW
    load_cursor.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    load_cursor.restype = wintypes.HANDLE

    return load_from_file, set_cursor, load_cursor


def load_native_cursor(path: Path) -> Any:
    """Load a .cur cursor with LoadCursorFromFileW (pointer-sized handles).

    Returns None outside Windows or on failure; callers then fall back to the
    Qt default cursor. The resource is loaded at its natural size: per the MSDN
    remarks, LoadCursorFromFileW does not participate in DPI virtualization, so
    the 32x32 .cur is NOT scaled up automatically; the OS renders the cursor
    bitmap on the same pipeline as system cursors.
    """
    if sys.platform != "win32":
        return None
    try:
        handle = _cursor_api()[0](str(path))
        return handle or None
    except Exception:
        return None


def set_native_cursor(handle: Any) -> None:
    """Set the current cursor immediately (bypasses Qt's cursor pipeline)."""
    try:
        _cursor_api()[1](handle)
    except Exception:
        pass


def reset_native_cursor() -> None:
    """Restore the default arrow cursor (IDC_ARROW)."""
    try:
        import ctypes

        # MAKEINTRESOURCE(32512): the identifier is passed as a pointer value.
        arrow = ctypes.cast(ctypes.c_void_p(32512), ctypes.c_wchar_p)
        _cursor_api()[2](None, arrow)
    except Exception:
        pass


class GloveCursorController:
    """Pure state machine for the glove cursor; no Qt or Win32 dependencies.

    ``open_h`` / ``closed_h`` may be None (non-Windows, or the .cur assets are
    missing): every query then returns None, so callers simply fall back to the
    default cursor. This keeps all cursor-state decisions testable.
    """

    WM_LBUTTONDOWN = 0x0201

    def __init__(self, open_h: Any, closed_h: Any) -> None:
        self.open_h = open_h
        self.closed_h = closed_h
        self.pressed = False

    def handle_for(self, closed: bool) -> Any:
        return self.closed_h if closed else self.open_h

    def on_enter(self) -> Any:
        """Pointer entered the pet window: show the open hand."""
        return self.open_h

    def on_leave(self) -> None:
        """Pointer left the pet window: clear the pressed flag, reset to arrow."""
        self.pressed = False
        return None

    def on_press(self) -> Any:
        """Left button pressed: show the closed fist."""
        self.pressed = True
        return self.closed_h

    def on_release(self, inside: bool) -> Any:
        """Left button released: open hand when still inside, otherwise None."""
        self.pressed = False
        return self.open_h if inside else None

    def on_wm_setcursor(self, mouse_msg: int) -> Any:
        """WM_SETCURSOR decision: closed on WM_LBUTTONDOWN (or while pressed)."""
        return self.handle_for(mouse_msg == self.WM_LBUTTONDOWN or self.pressed)


class EventRecorder:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._stream: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding="utf-8")

    def record(self, message: dict[str, Any]) -> None:
        if self._stream is None:
            return
        self._stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()


def run_headless(recorder: EventRecorder) -> int:
    try:
        emit_reply("ready")
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
                continue
            recorder.record(message)
            if message.get("kind") == "ping":
                emit_reply("pong")
                continue
            if message.get("kind") == "shutdown":
                break
    finally:
        recorder.close()
    return 0


def run_visual(recorder: EventRecorder, snapshot_path: Path | None = None) -> int:
    configure_qt_platform()
    try:
        from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
        from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QMouseEvent, QPainter, QPen, QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMenu,
            QSlider,
            QSystemTrayIcon,
            QWidget,
            QWidgetAction,
        )
    except ImportError as error:
        print(
            f"PySide6 is required for visual mode ({error}). Run with --headless for protocol tests.",
            file=sys.stderr,
        )
        recorder.close()
        return 2

    # 硬件状态小挂牌是可选的装饰层：模块缺失时桌宠本体照常工作。
    try:
        try:
            from .stats_plate import HardwarePlate
        except ImportError:
            from stats_plate import HardwarePlate
    except Exception as plate_error:  # noqa: BLE001 - optional chrome must never break the pet
        print(f"Hardware plate disabled: {plate_error}", file=sys.stderr)
        HardwarePlate = None  # type: ignore[assignment,misc]

    class Inbox(QObject):
        message = Signal(dict)
        closed = Signal()

    manifest_path = bundle_root() / "assets" / "pet-manifest.json"
    asset_root = manifest_path.parent / "pet"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Unable to load BigFish asset manifest: {error}", file=sys.stderr)
        recorder.close()
        return 2

    class GloveCursorFilter(QAbstractNativeEventFilter):
        """Owns WM_SETCURSOR while the pointer is over the pet window.

        The pet shows a glove hand cursor: an open hand on hover and a closed
        fist while the left button is held. Native .cur cursors are loaded with
        LoadCursorFromFileW and handed to the OS cursor pipeline directly (the
        same rendering path as system cursors; note the API loads the resource
        at its natural 32x32 size and does not participate in DPI
        virtualization). The message is consumed immediately instead of going
        through Qt's QCursor bitmaps, which are re-scaled by Qt and only take
        effect on the next cursor update cycle.
        """

        def __init__(self, widget: Any, open_h: Any, closed_h: Any) -> None:
            super().__init__()
            self.widget = widget
            self.open_h = open_h
            self.closed_h = closed_h

        def nativeEventFilter(self, event_type: bytes, message: Any):
            try:
                if event_type != b"windows_generic_MSG":
                    return False, 0
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message != 0x0020:  # WM_SETCURSOR
                    return False, 0
                hwnd = int(msg.hWnd) if msg.hWnd else 0
                if hwnd and hwnd != int(self.widget.winId()):
                    # Leave popups (context menu, …) to Qt's default cursor.
                    return False, 0
                hit_test = msg.lParam & 0xFFFF
                if hit_test != 1:  # HTCLIENT
                    return False, 0
                mouse_msg = (msg.lParam >> 16) & 0xFFFF
                handle = self.widget.glove.on_wm_setcursor(mouse_msg)
                if handle:
                    set_native_cursor(handle)
                    return True, 0
            except Exception:
                pass
            return False, 0

    class SliderMenuAction(QWidgetAction):
        """把一条滑块嵌进 QMenu。

        QMenu 本身不接受 QSlider 作为菜单项，必须借 QWidgetAction 的 createWidget
        在弹出菜单里创建真实控件；用 setDefaultWidget 在菜单里并不总是生效。
        """

        def __init__(self, parent: Any, minimum: int, maximum: int, value: int, on_change: Any, on_commit: Any, label_text: str = "大小") -> None:
            super().__init__(parent)
            self._minimum = minimum
            self._maximum = maximum
            self._value = value
            self._on_change = on_change
            self._on_commit = on_commit
            self._label_text = label_text

        def createWidget(self, parent: Any) -> Any:
            row = QWidget(parent)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(12, 6, 12, 6)
            layout.setSpacing(8)

            label = QLabel(self._label_text, row)
            label.setStyleSheet("color:#25282D; font-size:12px; font-family:'Microsoft YaHei UI';")

            slider = QSlider(Qt.Orientation.Horizontal, row)
            slider.setMinimum(self._minimum)
            slider.setMaximum(self._maximum)
            slider.setSingleStep(5)
            slider.setPageStep(10)
            slider.setValue(self._value)
            slider.setFixedWidth(170)
            # 滑动变阻器质感：绕线轨道 + DeepSeek 鲸鱼手柄（手柄由 pet_sliders 渲染成 PNG）
            slider.setStyleSheet(_rheostat_style())

            readout = QLabel(f"{self._value / 100:.2f}", row)
            readout.setFixedWidth(34)
            readout.setStyleSheet("color:#5B6270; font-size:12px;")

            def handle(value: int) -> None:
                readout.setText(f"{value / 100:.2f}")
                self._on_change(value / 100.0)

            def commit() -> None:
                self._on_commit(slider.value() / 100.0)

            slider.valueChanged.connect(handle)
            slider.sliderReleased.connect(commit)

            layout.addWidget(label)
            layout.addWidget(slider, 1)
            layout.addWidget(readout)
            return row

    class CompanionWindow(QWidget):
        LABELS = {
            "IDLE": "休息中",
            "THINKING": "思考中",
            "WORKING": "干活中",
            "WAITING": "等你呢",
            "SUCCESS": "完成啦",
            "ERROR": "出问题了",
            "DISCONNECTED": "已断开",
        }

        def __init__(self) -> None:
            super().__init__()
            self.layout_path = default_layout_path()
            self.layout = load_layout(self.layout_path)
            configured_scale = os.environ.get("DSH_DAFEIYU_SCALE")
            try:
                self.scale = min(1.4, max(0.1, float(configured_scale))) if configured_scale else self.layout["scale"]
            except ValueError:
                self.scale = self.layout["scale"]
            configured_bubble_scale = os.environ.get("DSH_DAFEIYU_BUBBLE_SCALE")
            try:
                self.bubble_scale = (
                    min(1.2, max(0.8, float(configured_bubble_scale)))
                    if configured_bubble_scale
                    else self.layout["bubbleScale"]
                )
            except ValueError:
                self.bubble_scale = self.layout["bubbleScale"]
            configured_reduced_motion = os.environ.get("DSH_DAFEIYU_REDUCED_MOTION")
            self.reduced_motion = (
                configured_reduced_motion == "1"
                if configured_reduced_motion is not None
                else self.layout["reducedMotion"]
            )
            configured_sound_enabled = os.environ.get("DSH_DAFEIYU_SOUND_ENABLED")
            self.sound_enabled = configured_sound_enabled != "0"
            self.activity_level = os.environ.get("DSH_DAFEIYU_ACTIVITY_LEVEL", "normal")
            configured_bubble_mode = os.environ.get("DSH_DAFEIYU_BUBBLE_MODE")
            self.bubble_mode = (
                configured_bubble_mode
                if configured_bubble_mode in {"always", "hidden", "custom"}
                else self.layout.get("bubbleMode", "always")
            )
            configured_bubble_states = os.environ.get("DSH_DAFEIYU_BUBBLE_STATES")
            if configured_bubble_states is not None:
                self.bubble_states = [part.strip() for part in configured_bubble_states.split(",") if part.strip()]
            else:
                self.bubble_states = list(self.layout.get("bubbleStates", ["SUCCESS", "ERROR", "WAITING"]))
            self.model = AnimationModel(manifest)
            self.frame_sources: dict[str, bytes] = {}
            for clip in self.model.clips.values():
                for frame in clip.frames:
                    if frame in self.frame_sources:
                        continue
                    try:
                        self.frame_sources[frame] = (asset_root / frame).read_bytes()
                    except OSError as error:
                        raise RuntimeError(f"Unable to load BigFish frame: {frame}") from error
            self.decoded_frames: OrderedDict[str, QPixmap] = OrderedDict()
            # Fail here, not on the first paint, when the assets are unreadable or
            # the bundled Qt has no WebP image plugin.
            for clip in self.model.clips.values():
                if clip.frames:
                    self._pixmap(clip.frames[0])
            self.decoded_frames.clear()

            self.display_state = "IDLE"
            self.status_state = "IDLE"
            self.status_message = "我在这儿等新任务哦"
            self.status_detail = "DSH · 等待下一次任务"
            self.status_deadline_ms: int | None = self._now_ms() + 4200
            # Glove cursor: native .cur handles (loaded at natural size).
            self.glove_open_h = load_native_cursor(asset_root.parent / "cursor_grab.cur")
            self.glove_closed_h = load_native_cursor(asset_root.parent / "cursor_grabbing.cur")
            self.glove = GloveCursorController(self.glove_open_h, self.glove_closed_h)
            self.overlay_state: str | None = None
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_deadline_ms: int | None = None
            self.task = ""
            self.tasks: list[dict[str, Any]] = []
            self.webui_url = os.environ.get("DSH_DAFEIYU_WEBUI_URL", "http://127.0.0.1:3080/")
            self.open_label = os.environ.get("DSH_DAFEIYU_OPEN_LABEL", "打开 DSH")
            self.balance_summary = ""
            self.drag_origin: QPoint | None = None
            self.pet_origin: QPoint | None = None
            self.pet_x = 0
            self.pet_y = 0
            self.dragging = False
            self.last_tick_ms = self._now_ms()
            self.fade_from_pixmap: QPixmap | None = None
            self.fade_started = 0.0
            self.fade_duration = 0.15
            self.animation_timer = QTimer(self)
            self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.animation_timer.timeout.connect(self._tick)
            self.animation_timer.start(self._animation_interval_ms())
            self.micro_timer = QTimer(self)
            self.micro_timer.setSingleShot(True)
            self.micro_timer.timeout.connect(self._play_idle_micro)
            if not self.reduced_motion:
                self._schedule_micro()
            self.snapshot_saved = False
            self.setWindowTitle("DSH 大肥鱼")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # 硬件状态小挂牌：独立置顶、鼠标穿透的小窗口，挂在发指令气泡上方。
            # CPU/内存在 UI 线程按秒读（单次 OS 调用 <0.2ms），GPU 由后台线程
            # 每 2 秒 spawn 一次 nvidia-smi（单次约 40–60ms，不能卡在 UI 里）。
            self.show_hardware = bool(self.layout.get("showHardware", True))
            self.plate_scale = self._clamp_plate_scale(self.layout.get("plateScale", 1.0))
            self.hardware_ready = False
            self.hardware_sampler = HardwareSampler()
            self.hardware_sampler.start()
            self.hardware_stats = HardwareStats()
            self.hardware_plate = HardwarePlate() if HardwarePlate is not None else None
            if self.hardware_plate is not None:
                self.hardware_plate.set_scale(self.plate_scale)
            self.hardware_timer = QTimer(self)
            self.hardware_timer.setInterval(1000)
            self.hardware_timer.timeout.connect(self._refresh_hardware)
            if self.show_hardware and self.hardware_plate is not None:
                self.hardware_timer.start()
            # 指令输入框：固定画在状态卡片上方（同一个原生窗口内）。
            # 回车把文字以 "prompt" 消息交回 Host，由 Host 提交给 DSH 会话。
            self.prompt_input = QLineEdit(self)
            self.prompt_input.setPlaceholderText("给 DSH 发指令，回车发送")
            self.prompt_input.setClearButtonEnabled(True)
            self.prompt_input.setStyleSheet(
                "QLineEdit {"
                " border: 1px solid rgba(218,221,226,220);"
                " border-radius: 11px;"
                " background: rgba(252,252,253,248);"
                " color: #25282D;"
                " padding: 0 10px;"
                " font-family: 'Microsoft YaHei UI';"
                " font-size: 12px;"
                "}"
                "QLineEdit:focus { border-color: #4D6BFE; }"
            )
            self.prompt_input.returnPressed.connect(self._submit_prompt)
            self.prompt_input.show()
            self._apply_window_size()
            # 自检钩子：设置 DSH_DAFEIYU_SMOKE_PROMPT=<文本> 时，窗口出现后自动填入
            # 该文本并走一次 _submit_prompt()，用来在没有人工按键的情况下验证
            # 「回车 → emit_reply("prompt")」这条链路。不设该变量时完全惰性。
            smoke_prompt = os.environ.get("DSH_DAFEIYU_SMOKE_PROMPT")
            if smoke_prompt:
                def _run_smoke_prompt() -> None:
                    self.prompt_input.setText(smoke_prompt)
                    self._submit_prompt()
                QTimer.singleShot(300, _run_smoke_prompt)
            self._setup_tray()
            QTimer.singleShot(0, self._restore_visible_position)

        def apply_message(self, message: dict[str, Any]) -> None:
            recorder.record(message)
            kind = message.get("kind")
            if kind == "shutdown":
                self.hardware_sampler.stop()
                if self.hardware_plate is not None:
                    self.hardware_plate.hide()
                QApplication.quit()
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if kind == "task":
                self.task = str(message.get("task", ""))
                self._show_status(
                    str(message.get("message", self.task)),
                    str(message.get("detail", "")),
                    self.model.base_state,
                    None if self.model.base_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else 6000,
                )
            elif kind == "tasks":
                raw_tasks = message.get("tasks")
                self.tasks = raw_tasks if isinstance(raw_tasks, list) else []
                self._sync_bubble_size()
            elif kind == "config":
                self._apply_config(message)
            elif kind == "balance":
                self.balance_summary = str(message.get("summary", ""))[:200]
                self._sync_bubble_size()
            elif kind in {"state", "pulse"}:
                previous_base_state = self.model.base_state
                state = str(message.get("state", "IDLE"))
                self.display_state = state
                if kind == "pulse":
                    ttl_ms = max(250, int(message.get("ttlMs", 1800)))
                    resume_state = str(message.get("resumeState", self.model.base_state))
                    self.model.apply_pulse(
                        state,
                        ttl_ms,
                        self._now_ms(),
                        resume_state,
                        message.get("resumeActivity"),
                        complete_clip=not self.reduced_motion,
                    )
                    ttl_ms = self.model.pulse_deadline_ms - self._now_ms()
                    self._show_status(
                        str(message.get("resumeMessage", self.LABELS.get(resume_state, resume_state))),
                        str(message.get("resumeDetail", "")),
                        resume_state,
                        None if resume_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else ttl_ms + 2200,
                    )
                    self._show_overlay(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        ttl_ms,
                    )
                    if state in {"SUCCESS", "ERROR"}:
                        self._notify_alert(state)
                else:
                    activity = None if self.reduced_motion else message.get("activity")
                    self.model.apply_state(state, activity)
                    self.display_state = self.model.pulse_state or state
                    if self.model.pulse_state is None:
                        self._clear_overlay()
                    persistent = state in {"THINKING", "WORKING", "WAITING", "ERROR"}
                    self._show_status(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        None if persistent else 4200,
                    )
                if previous_base_state != self.model.base_state and not self.reduced_motion:
                    self._schedule_micro()
            self._sync_frame_transition(previous_frame, previous_clip)
            self._sync_bubble_size()
            self.update()
            if snapshot_path is not None and not self.snapshot_saved:
                QTimer.singleShot(180, self._save_snapshot)

        def _set_reduced_motion(self, enabled: bool) -> None:
            self.reduced_motion = enabled
            self.animation_timer.setInterval(self._animation_interval_ms())
            if enabled:
                self.micro_timer.stop()
                if not self.dragging:
                    self.model.clear_overlay()
            else:
                self._schedule_micro()

        def _apply_config(self, message: dict[str, Any]) -> None:
            """Apply a live CONFIG message without restarting the window."""
            if isinstance(message.get("openUrl"), str):
                self.webui_url = message["openUrl"]
            if isinstance(message.get("openLabel"), str):
                self.open_label = message["openLabel"]
            scale = message.get("scale")
            if isinstance(scale, (int, float)) and not isinstance(scale, bool):
                self.scale = min(1.4, max(0.1, float(scale)))
            bubble_scale = message.get("bubbleScale")
            if isinstance(bubble_scale, (int, float)) and not isinstance(bubble_scale, bool):
                self.bubble_scale = min(1.2, max(0.8, float(bubble_scale)))
            reduced_motion = message.get("reducedMotion")
            if isinstance(reduced_motion, bool) and reduced_motion != self.reduced_motion:
                self._set_reduced_motion(reduced_motion)
            sound_enabled = message.get("soundEnabled")
            if isinstance(sound_enabled, bool):
                self.sound_enabled = sound_enabled
            activity_level = message.get("activityLevel")
            if activity_level in {"quiet", "normal", "lively"}:
                self.activity_level = activity_level
                if not self.reduced_motion:
                    self._schedule_micro()
            bubble_mode = message.get("bubbleMode")
            if bubble_mode in {"always", "hidden", "custom"}:
                self.bubble_mode = bubble_mode
            bubble_states = message.get("bubbleStates")
            if isinstance(bubble_states, list):
                self.bubble_states = [str(state) for state in bubble_states if isinstance(state, str)]
            self._sync_bubble_size()
            self._save_layout()

        def _apply_glove(self, closed: bool) -> None:
            """Closed fist while the button is held, open hand otherwise.

            Sets the cursor directly so feedback is immediate instead of
            waiting for the next WM_SETCURSOR pass.
            """
            self.glove.pressed = closed
            handle = self.glove.handle_for(closed)
            if handle:
                set_native_cursor(handle)

        def enterEvent(self, event: Any) -> None:
            self._apply_glove(False)
            super().enterEvent(event)

        def leaveEvent(self, event: Any) -> None:
            self.glove.pressed = False
            reset_native_cursor()
            super().leaveEvent(event)

        def _animation_interval_ms(self) -> int:
            if self.reduced_motion:
                return 40
            # Sub-frame poll: a once-per-frame timer turns one early delivery into a whole-frame hitch.
            return max(8, min(20, round(self.model.active_clip.frame_ms / 3)))

        def _rearm_animation_interval(self) -> None:
            wanted = self._animation_interval_ms()
            if self.animation_timer.interval() != wanted:
                self.animation_timer.setInterval(wanted)

        def _pixmap(self, frame: str) -> QPixmap:
            cached = self.decoded_frames.get(frame)
            if cached is not None:
                self.decoded_frames.move_to_end(frame)
                return cached
            pixmap = QPixmap()
            if not pixmap.loadFromData(self.frame_sources[frame], "WEBP"):
                raise RuntimeError(f"Unable to load BigFish frame: {frame}")
            self.decoded_frames[frame] = pixmap
            while len(self.decoded_frames) > DECODED_FRAME_CACHE:
                self.decoded_frames.popitem(last=False)
            return pixmap

        def _tick(self) -> None:
            now_ms = self._now_ms()
            elapsed_ms = max(0, now_ms - self.last_tick_ms)
            self.last_tick_ms = now_ms
            had_pulse = self.model.pulse_state is not None
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            model_elapsed = 0 if self.reduced_motion else elapsed_ms
            self.model.advance(model_elapsed, now_ms)
            self._sync_frame_transition(previous_frame, previous_clip)
            if had_pulse and self.model.pulse_state is None:
                self.display_state = self.model.base_state
            if self.overlay_deadline_ms is not None and now_ms >= self.overlay_deadline_ms:
                self._clear_overlay()
            self._rearm_animation_interval()
            self.update()

        def _play_idle_micro(self) -> None:
            if self.reduced_motion:
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            self.model.play_idle_micro(random.randrange(max(1, len(self.model.idle_micro_clips))))
            self._sync_frame_transition(previous_frame, previous_clip)
            self.update()
            self._schedule_micro()

        def _sync_frame_transition(
            self,
            previous_frame: str,
            previous_clip: str,
            *,
            allow_fade: bool = True,
        ) -> None:
            current_frame = self.model.frame
            if current_frame == previous_frame:
                return
            # Preserve an in-progress clip fade while its new video advances.
            if allow_fade and previous_clip == self.model.active_clip_name:
                return
            duration = crossfade_duration(previous_clip, self.model.active_clip_name) if allow_fade else None
            if duration is None:
                self.fade_from_pixmap = None
                return
            self.fade_from_pixmap = (
                self._pixmap(previous_frame) if previous_frame in self.frame_sources else None
            )
            self.fade_started = time.monotonic()
            self.fade_duration = duration

        def _play_model_overlay(
            self,
            clip_name: str,
            *,
            allow_fade: bool = True,
            repaint: bool = True,
        ) -> bool:
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if not self.model.play_overlay(clip_name):
                return False
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=allow_fade)
            if repaint:
                self.update()
            return True

        def _begin_drag(self) -> None:
            if self.dragging:
                return
            self.dragging = True
            self.micro_timer.stop()
            played = self._play_model_overlay("dragging", allow_fade=False, repaint=False)
            if not played:
                self.animation_timer.stop()
                return
            clip = self.model.active_clip
            if self.reduced_motion or not clip.loop:
                self.animation_timer.stop()
            else:
                self.last_tick_ms = self._now_ms()
                self.animation_timer.start(self._animation_interval_ms())

        def _finish_drag(self) -> None:
            if not self.dragging:
                return
            now_ms = self._now_ms()
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            # Expire an underlying pulse before revealing it after a long drag.
            self.model.advance(0, now_ms)
            if self.reduced_motion or not self.model.play_overlay("dragging_release"):
                self.model.clear_overlay()
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            self.dragging = False
            self.last_tick_ms = now_ms
            self.animation_timer.start(self._animation_interval_ms())
            if not self.reduced_motion:
                self._schedule_micro()

        def _schedule_micro(self) -> None:
            if self.reduced_motion:
                self.micro_timer.stop()
                return
            lower, upper = self.model.idle_micro_interval(self.activity_level)
            self.micro_timer.start(self.model.overlay_remaining_ms + random.randint(lower, upper))

        def _prompt_row_height(self) -> int:
            """固定一行输入的高度（不随 bubbleScale 缩放，保证可读可点）。"""
            return 34

        def _submit_prompt(self) -> None:
            text = self.prompt_input.text().strip()
            if not text:
                return
            self.prompt_input.clear()
            emit_reply("prompt", text=text)

        def _position_prompt_input(self) -> None:
            row = self._prompt_row_height()
            if self._bubble_visible():
                card_x, _, card_width, _ = self._bubble_rect()
                x = card_x + 10
                width = max(120, card_width - 20)
            else:
                x = 14
                width = max(120, self.width() - 28)
            self.prompt_input.setGeometry(x, 7, width, row - 8)

        def _bubble_visible(self) -> bool:
            if self.bubble_mode == "hidden":
                return False
            if self.bubble_mode == "always":
                return True
            if len(self.tasks) >= 2:
                return any(task.get("state") in self.bubble_states for task in self.tasks)
            state = self.overlay_state or self.status_state or self.model.base_state or "IDLE"
            return state in self.bubble_states

        def _sync_bubble_size(self) -> None:
            old_size = (self.width(), self.height())
            self._apply_window_size()
            if (self.width(), self.height()) != old_size:
                self._move_to_pet(self.pet_x, self.pet_y)

        def _apply_window_size(self) -> None:
            pet_width = round(int(manifest["maxFrameWidth"]) * self.scale)
            pet_height = round(int(manifest["maxFrameHeight"]) * self.scale)
            row = self._prompt_row_height()
            if self._bubble_visible():
                bubble_width = round(420 * self.bubble_scale)
                bubble_height = self._card_height()
                # 多出来的 row 用来放输入框；宠物锚在窗口底部，所以宠物屏幕位置不变，
                # 卡片会被 bubble_top() 自动下移 row 像素，正好让出顶部这一条。
                self.setFixedSize(
                    max(pet_width + 50, bubble_width + 28),
                    pet_height + bubble_height + 34 + row,
                )
            else:
                self.setFixedSize(max(pet_width + 50, 288), pet_height + 26 + row)
            self._position_prompt_input()

        def _screen_geometry_at(self, x: int, y: int):
            screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
            if screen is None:
                return None
            return screen.availableGeometry()

        def _pet_size(self) -> tuple[int, int]:
            return (
                round(int(manifest["maxFrameWidth"]) * self.scale),
                round(int(manifest["maxFrameHeight"]) * self.scale),
            )

        def _move_to_pet(self, pet_x: int, pet_y: int) -> None:
            """Resize or move the container around the character's anchor."""
            geometry = self._screen_geometry_at(pet_x, pet_y)
            screen = (geometry.x(), geometry.y(), geometry.width(), geometry.height()) if geometry is not None else None
            window_x, window_y, self.pet_x, self.pet_y = position_window(
                (pet_x, pet_y), self._pet_size(), (self.width(), self.height()), screen,
                (self._card_height() + self._prompt_row_height()) if self._bubble_visible() else 0,
            )
            self.move(window_x, window_y)
            self.update()
            self._sync_hardware_plate()

        def _pet_offset_x(self, pet_width: int) -> int:
            return min(max(self.pet_x - self.x(), 0), self.width() - pet_width)

        def _pet_rect(self) -> tuple[int, int, int, int]:
            pet_width, pet_height = self._pet_size()
            offset_y = min(max(self.pet_y - self.y(), 0), self.height() - pet_height)
            return self._pet_offset_x(pet_width), offset_y, pet_width, pet_height

        def _bubble_rect(self) -> tuple[int, int, int, int]:
            card_width = round(420 * self.bubble_scale)
            card_height = self._card_height()
            pet_width, _ = self._pet_size()
            pet_center_x = self._pet_offset_x(pet_width) + pet_width // 2
            margin = 14
            card_x = pet_center_x - card_width // 2
            min_x = margin
            max_x = self.width() - card_width - margin
            if max_x < min_x:
                max_x = min_x
            card_x = min(max(card_x, min_x), max_x)
            _, pet_y, _, pet_height = self._pet_rect()
            card_y = bubble_top(pet_y, pet_height, card_height, self.height())
            return card_x, card_y, card_width, card_height

        def _refresh_hardware(self) -> None:
            self.hardware_stats = self.hardware_sampler.snapshot()
            if self.hardware_plate is not None:
                self.hardware_plate.set_stats(self.hardware_stats)
            self._sync_hardware_plate()

        def _sync_hardware_plate(self) -> None:
            """Keep the plate centered above the prompt bubble after every move/resize."""
            plate = self.hardware_plate
            if plate is None or not self.show_hardware:
                return
            prompt_top_left = self.mapToGlobal(self.prompt_input.geometry().topLeft())
            anchor = QRect(prompt_top_left, self.prompt_input.size())
            screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            plate.follow(anchor, screen.availableGeometry() if screen is not None else None)

        @staticmethod
        def _clamp_plate_scale(value: Any) -> float:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 1.0
            return min(1.7, max(0.7, number))

        def _on_plate_scale_slider_change(self, scale: float) -> None:
            self.plate_scale = self._clamp_plate_scale(scale)
            if self.hardware_plate is not None:
                self.hardware_plate.set_scale(self.plate_scale)
            self._sync_hardware_plate()

        def _on_plate_scale_slider_commit(self, scale: float) -> None:
            self._on_plate_scale_slider_change(scale)
            self._save_layout()

        def _show_hardware_plate(self) -> None:
            self.hardware_ready = True
            if not self.show_hardware or self.hardware_plate is None:
                return
            self._refresh_hardware()
            self.hardware_plate.show()

        def _set_show_hardware(self, enabled: bool) -> None:
            self.show_hardware = bool(enabled)
            plate = self.hardware_plate
            if not self.show_hardware:
                self.hardware_timer.stop()
                # 关掉挂牌就没必要继续 spawn nvidia-smi：整条采样链一起停。
                self.hardware_sampler.stop()
                if plate is not None:
                    plate.hide()
            elif plate is not None:
                self.hardware_sampler = HardwareSampler()
                self.hardware_sampler.start()
                self.hardware_timer.start()
                self._show_hardware_plate()
            self._save_layout()

        def moveEvent(self, event: Any) -> None:
            super().moveEvent(event)
            self._sync_hardware_plate()

        def showEvent(self, event: Any) -> None:
            super().showEvent(event)
            if self.hardware_ready:
                self._show_hardware_plate()

        def hideEvent(self, event: Any) -> None:
            super().hideEvent(event)
            if self.hardware_plate is not None:
                self.hardware_plate.hide()

        def closeEvent(self, event: Any) -> None:
            self.hardware_sampler.stop()
            if self.hardware_plate is not None:
                self.hardware_plate.hide()
                self.hardware_plate.close()
            super().closeEvent(event)

        def _restore_visible_position(self) -> None:
            pet_width, pet_height = self._pet_size()
            top_offset = self.height() - pet_height - 8
            center_offset = (self.width() - pet_width) // 2
            saved_pet_x = self.layout.get("petX")
            saved_pet_y = self.layout.get("petY")
            if isinstance(saved_pet_x, int) and isinstance(saved_pet_y, int):
                pet_x, pet_y = saved_pet_x, saved_pet_y
            else:
                saved_x = self.layout.get("x")
                saved_y = self.layout.get("y")
                if isinstance(saved_x, int) and isinstance(saved_y, int):
                    # Legacy layouts stored the window position.  Recreate the
                    # pet position that the old centered layout would have had.
                    pet_x = saved_x + center_offset
                    pet_y = saved_y + top_offset
                else:
                    geometry = self._screen_geometry_at(self.x() + self.width() // 2, self.y() + self.height() // 2)
                    if geometry is None:
                        return
                    pet_x = geometry.right() - pet_width - 24
                    pet_y = geometry.bottom() - pet_height - 24
            self._move_to_pet(pet_x, pet_y)
            self._show_hardware_plate()

        def _save_layout(self) -> None:
            self.layout = {
                "version": 1,
                "x": self.x(),
                "y": self.y(),
                "petX": self.pet_x,
                "petY": self.pet_y,
                "scale": self.scale,
                "bubbleScale": self.bubble_scale,
                "reducedMotion": self.reduced_motion,
                "bubbleMode": self.bubble_mode,
                "bubbleStates": self.bubble_states,
                "showHardware": self.show_hardware,
                "plateScale": self.plate_scale,
            }
            try:
                save_layout(self.layout_path, self.layout)
            except OSError as error:
                print(f"Unable to save BigFish layout: {error}", file=sys.stderr)

        def _save_snapshot(self) -> None:
            if snapshot_path is None or self.snapshot_saved:
                return
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.snapshot_saved = self.grab().save(str(snapshot_path), "PNG")

        def _show_status(self, message: str, detail: str, state: str, ttl_ms: int | None) -> None:
            self.status_message = message
            self.status_detail = detail
            self.status_state = state
            self.status_deadline_ms = None if ttl_ms is None else self._now_ms() + ttl_ms

        def _show_overlay(self, message: str, detail: str, state: str, ttl_ms: int) -> None:
            self.overlay_message = message
            self.overlay_detail = detail or self.status_detail
            self.overlay_state = state
            self.overlay_deadline_ms = self._now_ms() + ttl_ms

        def _clear_overlay(self) -> None:
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_state = None
            self.overlay_deadline_ms = None

        @staticmethod
        def _now_ms() -> int:
            return int(time.monotonic() * 1000)

        def _current_card(self) -> tuple[str, str, str] | None:
            now_ms = self._now_ms()
            if self.overlay_message and (
                self.overlay_deadline_ms is None or now_ms < self.overlay_deadline_ms
            ):
                return self.overlay_message, self.overlay_detail, self.overlay_state or self.status_state
            if self.status_message and (
                self.status_deadline_ms is None or now_ms < self.status_deadline_ms
            ):
                return self.status_message, self.status_detail, self.status_state
            if self.balance_summary:
                return "大肥鱼陪你待命", "DSH · 等待下一次任务", "IDLE"
            return None

        @staticmethod
        def _status_colors(state: str) -> tuple[QColor, QColor]:
            return {
                "SUCCESS": (QColor("#D9F7E4"), QColor("#12B85A")),
                "ERROR": (QColor("#FDE3E3"), QColor("#E5484D")),
                "WAITING": (QColor("#FFF0CE"), QColor("#D88A00")),
                "THINKING": (QColor("#E2ECFF"), QColor("#4C78E8")),
                "WORKING": (QColor("#DDEBFF"), QColor("#3478F6")),
                "DISCONNECTED": (QColor("#ECEEF1"), QColor("#7B818A")),
            }.get(state, (QColor("#ECEEF1"), QColor("#747A84")))

        def _draw_status_icon(self, painter: QPainter, state: str, center_x: int, center_y: int) -> None:
            background, foreground = self._status_colors(state)
            radius = 23
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
            pen = QPen(foreground, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if state == "SUCCESS":
                painter.drawLine(center_x - 10, center_y, center_x - 3, center_y + 8)
                painter.drawLine(center_x - 3, center_y + 8, center_x + 12, center_y - 10)
            elif state == "ERROR":
                painter.drawLine(center_x - 8, center_y - 8, center_x + 8, center_y + 8)
                painter.drawLine(center_x + 8, center_y - 8, center_x - 8, center_y + 8)
            elif state == "WAITING":
                painter.drawLine(center_x, center_y - 10, center_x, center_y + 3)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 2, center_y + 9, 4, 4)
            elif state in {"THINKING", "WORKING"}:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                for offset in (-9, 0, 9):
                    painter.drawEllipse(center_x + offset - 3, center_y - 3, 6, 6)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)

        def _card_height(self) -> int:
            footer = 28 if self.balance_summary else 0
            if len(self.tasks) >= 2:
                rows = min(len(self.tasks), 3)
                return round((58 + rows * 26 + footer) * self.bubble_scale)
            return round((84 + footer) * self.bubble_scale)

        def _draw_card_background(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            corner_radius: int,
            s: float,
        ) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(17, 24, 39, 13))
            painter.drawRoundedRect(
                card_x + 1, card_y + round(13 * s), card_width - 2, card_height,
                corner_radius, corner_radius,
            )
            painter.setBrush(QColor(17, 24, 39, 18))
            painter.drawRoundedRect(
                card_x, card_y + round(7 * s), card_width, card_height,
                corner_radius, corner_radius,
            )
            painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
            painter.setBrush(QColor(252, 252, 253, 248))
            painter.drawRoundedRect(
                card_x, card_y, card_width, card_height,
                corner_radius, corner_radius,
            )

        def _draw_multi_task_card(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            s: float,
        ) -> None:
            title_font = QFont("Microsoft YaHei UI")
            title_font.setPointSizeF(11.0 * max(1.0, s))
            title_font.setWeight(QFont.Weight.DemiBold)
            detail_font = QFont("Microsoft YaHei UI")
            detail_font.setPointSizeF(9.0 * max(1.0, s))
            text_x = card_x + round(16 * s)
            text_width = max(40, card_width - round(32 * s))
            painter.setFont(title_font)
            painter.setPen(QColor("#25282D"))
            title = f"{len(self.tasks)} 个任务进行中"
            painter.drawText(
                text_x,
                card_y + round(10 * s),
                text_width,
                max(12, round(22 * s)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, text_width),
            )
            painter.setFont(detail_font)
            for index, task in enumerate(self.tasks[:3]):
                row_y = card_y + round((36 + index * 24) * s)
                state = str(task.get("state", "IDLE"))
                state_label = self.LABELS.get(state, state)
                label = task.get("project") or task.get("task") or task.get("message") or state_label
                line = f"{state_label} · {label}"
                _, foreground = self._status_colors(state)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(text_x, row_y + round(4 * s), round(8 * s), round(8 * s))
                painter.setPen(QColor("#747981"))
                painter.drawText(
                    text_x + round(14 * s),
                    row_y,
                    text_width - round(14 * s),
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    QFontMetrics(detail_font).elidedText(line, Qt.TextElideMode.ElideRight, text_width - round(14 * s)),
                )
            if len(self.tasks) > 3:
                more = f"还有 {len(self.tasks) - 3} 个任务…"
                painter.setPen(QColor("#9AA0A6"))
                painter.drawText(
                    text_x + round(14 * s),
                    card_y + round((36 + 3 * 24) * s),
                    text_width,
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    more,
                )

        def _notify_alert(self, state: str) -> None:
            if self.sound_enabled:
                played = False
                if sys.platform == "win32":
                    try:
                        import winsound

                        sound_name = "success.wav" if state == "SUCCESS" else "error.wav"
                        sound_path = bundle_root() / "assets" / "sounds" / sound_name
                        winsound.PlaySound(
                            str(sound_path),
                            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                        )
                        played = True
                    except (ImportError, OSError, RuntimeError):
                        pass
                if not played:
                    try:
                        QApplication.beep()
                    except Exception:
                        pass

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # 平滑缩放：放大/缩小时插值，避免锯齿和模糊
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            card = self._current_card() if self._bubble_visible() else None
            card_x, card_y, card_width, card_height = self._bubble_rect()
            s = self.bubble_scale
            corner_radius = round(30 * s)

            if len(self.tasks) >= 2 and self._bubble_visible():
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                self._draw_multi_task_card(painter, card_x, card_y, card_width, card_height, s)
            elif card:
                title, detail, card_state = card
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                icon_center_x = card_x + card_width - round(39 * s)
                icon_center_y = card_y + round(42 * s)
                painter.save()
                painter.translate(icon_center_x, icon_center_y)
                painter.scale(s, s)
                painter.translate(-icon_center_x, -icon_center_y)
                self._draw_status_icon(painter, card_state, icon_center_x, icon_center_y)
                painter.restore()

                text_x = card_x + round(24 * s)
                text_width = max(40, card_width - round(102 * s))
                title_font = QFont("Microsoft YaHei UI")
                title_font.setPointSizeF(11.0 * max(1.0, s))
                title_font.setWeight(QFont.Weight.DemiBold)
                detail_font = QFont("Microsoft YaHei UI")
                detail_font.setPointSizeF(9.0 * max(1.0, s))
                painter.setFont(title_font)
                painter.setPen(QColor("#25282D"))
                title_text = QFontMetrics(title_font).elidedText(
                    title,
                    Qt.TextElideMode.ElideRight,
                    text_width,
                )
                painter.drawText(
                    text_x,
                    card_y + round(15 * s),
                    text_width,
                    max(12, round(27 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    title_text,
                )
                painter.setFont(detail_font)
                painter.setPen(QColor("#747981"))
                detail_text = QFontMetrics(detail_font).elidedText(
                    detail,
                    Qt.TextElideMode.ElideRight,
                    text_width,
                )
                painter.drawText(
                    text_x,
                    card_y + round(43 * s),
                    text_width,
                    max(12, round(24 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    detail_text,
                )

            if self.balance_summary and self._bubble_visible():
                balance_font = QFont("Microsoft YaHei UI")
                balance_font.setPointSizeF(9.0 * max(1.0, s))
                painter.setFont(balance_font)
                painter.setPen(QColor("#53616F"))
                text_width = card_width - round(32 * s)
                text = QFontMetrics(balance_font).elidedText(self.balance_summary, Qt.TextElideMode.ElideRight, text_width)
                painter.drawText(card_x + round(16 * s), card_y + card_height - round(31 * s),
                                 text_width, round(23 * s), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

            pixmap = self._pixmap(self.model.frame)

            fade_alpha = 1.0
            if self.fade_from_pixmap is not None and not self.fade_from_pixmap.isNull():
                fade_elapsed = time.monotonic() - self.fade_started
                if fade_elapsed < self.fade_duration:
                    fade_alpha = min(1.0, (fade_elapsed / self.fade_duration) ** 0.7)
                else:
                    self.fade_from_pixmap = None

            def draw_pet(pix: QPixmap, alpha: float) -> None:
                pw = pix.width() * self.scale
                ph = pix.height() * self.scale
                x, y, _, _ = self._pet_rect()
                painter.save()
                painter.setOpacity(alpha)
                painter.drawPixmap(QRectF(x, y, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
                painter.restore()

            if fade_alpha < 1.0 and self.fade_from_pixmap is not None:
                # Keep the old frame opaque underneath so the pet never flashes transparent.
                draw_pet(self.fade_from_pixmap, 1.0)
            draw_pet(pixmap, fade_alpha)

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._apply_glove(True)
                self.drag_origin = event.globalPosition().toPoint()
                self.pet_origin = QPoint(self.pet_x, self.pet_y)
                self.dragging = False

        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            if self.drag_origin is not None and self.pet_origin is not None:
                if not self.dragging and (event.globalPosition().toPoint() - self.drag_origin).manhattanLength() > 5:
                    self._begin_drag()
                delta = event.globalPosition().toPoint() - self.drag_origin
                self._move_to_pet(self.pet_origin.x() + delta.x(), self.pet_origin.y() + delta.y())

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.dragging:
                    self._finish_drag()
                    self._move_to_pet(self.pet_x, self.pet_y)
                    self._save_layout()
                else:
                    self._play_click_interaction(event.position().x(), event.position().y())
            self.drag_origin = None
            self.pet_origin = None
            self.dragging = False
            # The button state is authoritative: restore the open hand if the
            # pointer is still over the pet, or the default arrow otherwise.
            self.glove.pressed = False
            if self.rect().contains(event.position().toPoint()):
                self._apply_glove(False)
            else:
                reset_native_cursor()

        def _play_click_interaction(self, x: float, y: float) -> None:
            pet_x, pet_y, pet_width, pet_height = self._pet_rect()
            relative_x = max(0.0, x - pet_x)
            relative_y = max(0.0, y - pet_y)
            if relative_y < pet_height * 0.45:
                self._play_interaction("head_pat", "摸摸也不能让我少干活哦~")
            elif relative_x > pet_width * 0.72:
                self._play_interaction("tail", "尾巴不是进度条啦！")
            else:
                self._play_interaction("poke", "戳我干嘛，任务还在跑呢")

        def _play_interaction(self, clip_name: str, message: str) -> None:
            previous_frame, previous_clip = self.model.frame, self.model.active_clip_name
            if not self.reduced_motion and not self.model.play_interaction(clip_name, self._now_ms()):
                return
            self._sync_frame_transition(previous_frame, previous_clip)
            self._show_overlay(message, self.status_detail, self.status_state, 1800)
            self._schedule_micro()
            self.update()

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._play_interaction("head_pat", "好啦好啦，知道你喜欢我~")

        def contextMenuEvent(self, event: Any) -> None:
            menu = QMenu(self)
            size_menu = menu.addMenu("大小")
            # 用滑块代替固定预设（迷你/小/标准/大）：拖动即改，松手写回配置。
            size_menu.addAction(SliderMenuAction(
                size_menu,
                20,
                140,
                int(round(self.scale * 100)),
                self._on_scale_slider_change,
                self._on_scale_slider_commit,
            ))
            bubble_size_menu = menu.addMenu("气泡大小")
            # 气泡尺寸同样改为滑块（原预设：小 0.8 / 标准 1.0 / 大 1.2）。
            # 范围刻意限制在 0.80–1.20：卡片字号有 max(1.0, s) 下限，再小会文字溢出。
            bubble_size_menu.addAction(SliderMenuAction(
                bubble_size_menu,
                80,
                120,
                int(round(self.bubble_scale * 100)),
                self._on_bubble_scale_slider_change,
                self._on_bubble_scale_slider_commit,
                label_text="气泡",
            ))
            plate_size_menu = menu.addMenu("硬件气泡大小")
            # 与「大小 / 气泡大小」同款滑块：0.70–1.70，默认 1.00。
            plate_size_menu.addAction(SliderMenuAction(
                plate_size_menu,
                70,
                170,
                int(round(self.plate_scale * 100)),
                self._on_plate_scale_slider_change,
                self._on_plate_scale_slider_commit,
                label_text="硬件",
            ))
            reduced_action = menu.addAction("减少动态")
            reduced_action.setCheckable(True)
            reduced_action.setChecked(self.reduced_motion)
            hardware_action = menu.addAction("硬件状态")
            hardware_action.setCheckable(True)
            hardware_action.setChecked(self.show_hardware)
            open_webui_action = menu.addAction(self.open_label)
            menu.addSeparator()
            hide_action = menu.addAction("本次隐藏")
            exit_action = menu.addAction("本次关闭")
            selected = menu.exec(event.globalPos())
            if selected == reduced_action:
                self._set_reduced_motion(reduced_action.isChecked())
                self._save_layout()
                emit_reply("settings", reducedMotion=self.reduced_motion)
                self.update()
            elif selected == hardware_action:
                self._set_show_hardware(hardware_action.isChecked())
            elif selected == open_webui_action:
                self._open_client()
            elif selected == hide_action:
                self.hide()
                # 隐藏是单向的（没有 self.show() 路径），所以必须告诉用户从哪找回
                if getattr(self, "tray", None) is not None:
                    try:
                        self.tray.showMessage(
                            "大肥鱼已隐藏",
                            "右键托盘里的鲸鱼图标 → 显示大肥鱼，即可让它回来",
                            QSystemTrayIcon.MessageIcon.Information,
                            5000,
                        )
                    except Exception:
                        pass
            elif selected == exit_action:
                self._save_layout()
                emit_reply("closed", reason="user")
                QApplication.quit()

        def _on_scale_slider_change(self, scale: float) -> None:
            """拖动过程中实时改尺寸。

            这里只重排窗口大小、不重新定位：弹出菜单是窗口的子级，拖动中频繁 move()
            会让菜单跟着抖。松手时再完整定位。
            """
            if abs(self.scale - scale) < 0.001:
                return
            self.scale = scale
            self._apply_window_size()
            self.update()

        def _on_scale_slider_commit(self, scale: float) -> None:
            self._on_scale_slider_change(scale)
            self._move_to_pet(self.pet_x, self.pet_y)
            self._save_layout()
            emit_reply("settings", scale=self.scale)

        def _on_bubble_scale_slider_change(self, bubble_scale: float) -> None:
            """拖动中实时改气泡尺寸（同 scale：只重排、不重新定位）。"""
            if abs(self.bubble_scale - bubble_scale) < 0.001:
                return
            self.bubble_scale = bubble_scale
            self._apply_window_size()
            self.update()

        def _on_bubble_scale_slider_commit(self, bubble_scale: float) -> None:
            self._on_bubble_scale_slider_change(bubble_scale)
            self._sync_bubble_size()
            self._save_layout()
            emit_reply("settings", bubbleScale=self.bubble_scale)

        def _setup_tray(self) -> None:
            """托盘图标：窗口被「本次隐藏」藏起来之后，还能从这里把它叫回来。

            原版没有任何 self.show() 路径——一旦隐藏就只能重启进程，
            所以这里补一个常驻托盘入口，右键即「显示大肥鱼 / 打开 DSH / 退出桌宠」。
            """
            self.tray = None
            self.tray_menu = None
            try:
                if not QSystemTrayIcon.isSystemTrayAvailable():
                    return
                tray = QSystemTrayIcon(QIcon(_fish_icon(32)), self)
                tray.setToolTip("DSH 大肥鱼")
                menu = QMenu()
                menu.addAction("显示大肥鱼").triggered.connect(self._restore_from_tray)
                menu.addAction(self.open_label).triggered.connect(self._open_client)
                menu.addSeparator()
                menu.addAction("退出桌宠").triggered.connect(self._quit_from_tray)
                tray.setContextMenu(menu)
                tray.activated.connect(self._on_tray_activated)
                tray.show()
                self.tray = tray
                self.tray_menu = menu
            except Exception as error:
                # 托盘不是核心功能：拿不到就安静跳过，别影响桌宠本体
                print(f"Unable to create the tray icon: {error}", file=sys.stderr)

        def _restore_from_tray(self) -> None:
            self.show()
            self.raise_()
            self._apply_window_size()
            self._move_to_pet(self.pet_x, self.pet_y)
            self.update()

        def _on_tray_activated(self, reason: Any) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self._restore_from_tray()

        def _quit_from_tray(self) -> None:
            self._save_layout()
            emit_reply("closed", reason="user")
            QApplication.quit()

        def _open_client(self) -> None:
            if not QDesktopServices.openUrl(QUrl(self.webui_url)):
                print("Unable to open the configured DSH client", file=sys.stderr)
                self._show_overlay("无法打开 DSH", "请确认 DSH 已安装、打开地址设置正确", "ERROR", 4000)
                self._sync_bubble_size()
                self.update()

    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    inbox = Inbox()
    window = CompanionWindow()
    glove_filter = GloveCursorFilter(window, window.glove_open_h, window.glove_closed_h)
    application.installNativeEventFilter(glove_filter)
    inbox.message.connect(window.apply_message)
    inbox.closed.connect(application.quit)

    def read_stdin() -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
                if message.get("kind") == "ping":
                    emit_reply("pong")
                inbox.message.emit(message)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
        inbox.closed.emit()

    reader = threading.Thread(target=read_stdin, name="dsh-bigfish-stdin", daemon=True)
    reader.start()
    window.show()
    emit_reply("ready")
    code = application.exec()
    recorder.close()
    return code


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="DSH BigFish native helper")
    parser.add_argument("--headless", action="store_true", help="validate the protocol without opening a window")
    parser.add_argument("--event-log", type=Path, help="append received protocol messages to a JSONL file")
    parser.add_argument("--snapshot", type=Path, help="save one diagnostic visual frame after the first message")
    args = parser.parse_args()
    recorder = EventRecorder(args.event_log)
    return run_headless(recorder) if args.headless else run_visual(recorder, args.snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
