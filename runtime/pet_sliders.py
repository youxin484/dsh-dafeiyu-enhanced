"""桌宠右键菜单里两条滑块的外观：绕线轨道 + DeepSeek 鲸鱼手柄。

QSS 的 ``QSlider::handle`` 只能设背景/渐变，没法直接塞矢量图标，所以这里先用
QtSvg 把官方鲸鱼标渲染成一张「白底圆片 + 品牌色鲸鱼」的 PNG，再让 QSS 用
``image: url(...)`` 引用它。

鲸鱼路径与 viewBox 来自 DSH 自带的官方品牌包
``@deepseek-ai/dsh-client-ui-primitives``（FISH_LOGO_PATH / FISH_LOGO_VIEWBOX），
由 scripts/extract-fish-logo.mjs 从 app.asar 原样注入，请勿手改。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

# 官方鲸鱼标的原生 viewBox（宽, 高），与 dsh-client-ui-primitives 一致。
FISH_LOGO_VIEWBOX = (23.16, 17.04)

# 官方鲸鱼标的路径数据（SVG path d）。
FISH_LOGO_PATH = "M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z"

BRAND = "#4D6BFE"
DEEP = "#2B57C4"

_handle_cache: dict[str, str] = {}


def _handle_png(color: str, size: int) -> str:
    """渲染一次手柄并返回 PNG 路径（QSS 的 image 只接受 URL）。

    圆片白底 + 品牌色鲸鱼：只画纯色鲸鱼时，在蓝色填充段和灰色轨道段上无法同时
    保证对比度，加一层白底圆片就两种背景下都清晰（与网页版变阻器的处理一致）。
    """
    key = f"{color}-{size}"
    cached = _handle_cache.get(key)
    if cached and os.path.exists(cached):
        return cached

    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    scale = 3  # 高分屏下保持锐利
    pixels = size * scale
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 白底圆片 + 品牌色描边
    painter.setPen(QPen(QColor(color), max(1, pixels // 16)))
    painter.setBrush(QColor("#FFFFFF"))
    inset = pixels * 0.06
    painter.drawEllipse(QRectF(inset, inset, pixels - inset * 2, pixels - inset * 2))

    # 鲸鱼本体（居中，左右留一点边）
    view_w, view_h = FISH_LOGO_VIEWBOX
    inner_w = pixels * 0.58
    inner_h = inner_w * view_h / view_w
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '
        f'{view_w} {view_h}"><path d="{FISH_LOGO_PATH}" fill="{color}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    box = QRectF((pixels - inner_w) / 2, (pixels - inner_h) / 2, inner_w, inner_h)
    renderer.render(painter, box)
    painter.end()

    path = os.path.join(tempfile.gettempdir(), f"dsh-dafeiyu-handle-{color.lstrip('#')}-{size}.png")
    pixmap.save(path, "PNG")
    _handle_cache[key] = path
    return path


def rheostat_style(color: str = BRAND, handle_size: int = 16) -> str:
    """两条滑块共用的 QSS：绕线轨道 + 渐变填充 + 鲸鱼手柄。"""
    handle = _handle_png(color, handle_size).replace("\\", "/")
    return (
        "QSlider::groove:horizontal {"
        " height: 6px; border-radius: 3px;"
        " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        "  stop:0 #E9ECF1, stop:1 #D3D8E0);"
        "}"
        "QSlider::sub-page:horizontal {"
        " height: 6px; border-radius: 3px;"
        " background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
        "  stop:0 " + DEEP + ", stop:1 " + color + ");"
        "}"
        "QSlider::handle:horizontal {"
        f" width: {handle_size}px; height: {handle_size}px; margin: -5px 0;"
        " border: 0; background: transparent;"
        f" image: url({handle});"
        "}"
    )


def render_preview(path: str, width: int = 220, height: int = 44) -> bool:
    """把一条滑块单独渲染成 PNG。

    给 smoke 测试用：手柄画在 QMenu 弹出层里，窗口截图抓不到，
    所以单独渲染一条滑块来验证外观。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QSlider

    app = QApplication.instance() or QApplication([])
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimum(0)
    slider.setMaximum(100)
    slider.setValue(55)
    slider.setStyleSheet(rheostat_style())
    slider.resize(width, height)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.white)
    slider.render(pixmap)
    del app
    return pixmap.save(path, "PNG")


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "slider-preview.png"
    print("saved" if render_preview(target) else "failed", target)
