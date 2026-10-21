# dsh-dafeiyu-enhanced 🐋

**DSH 大肥鱼桌宠 · 增强版** —— 在桌面上陪你工作的 DeepSeek Harness 伴侣。

[▶ 项目介绍视频（B 站）](https://www.bilibili.com/video/BV1JAbC6wEWW/) · [原版仓库（QCYTSN/dsh-dafeiyu）](https://github.com/QCYTSN/dsh-dafeiyu) · [npm](https://www.npmjs.com/package/dsh-dafeiyu)

> 本项目是 [QCYTSN/dsh-dafeiyu](https://github.com/QCYTSN/dsh-dafeiyu) 的**个人修改版（fork）**。
> 原版由 **QCYTSN** 开发并以 MIT 协议发布；本仓库在其基础上增加了下面的改造，代码与素材授权条款保持原样。

## 视频

- **B 站**：[DeepSeek Harness大肥鱼宠物插件](https://www.bilibili.com/video/BV1JAbC6wEWW/)
- **原版仓库**：https://github.com/QCYTSN/dsh-dafeiyu

## 相比原版做了什么

| # | 改造 | 位置 |
|---|---|---|
| 1 | **气泡上方加指令输入框**：直接打字回车，把指令发给 DSH 会话（不用切窗口） | `runtime/helper.py` + `src/plugin.js` |
| 2 | **右键「大小」换成滑动变阻器滑块**（0.20–1.40，原为 迷你/小/标准/大 四档预设） | `runtime/helper.py` |
| 3 | **右键「气泡大小」也换成滑块**（0.80–1.20） | `runtime/helper.py` |
| 4 | **两条滑块的手柄换成官方 DeepSeek 鲸鱼标**（白底圆片 + 品牌色鲸鱼，绕线轨道） | `runtime/pet_sliders.py` |
| 5 | **缩放下限从 0.55 放开到 0.10**，可以调得比原版更小 | `helper.py` / `plugin.js` / `layout_store.py` |
| 6 | Windows helper 已按以上改动**重新打包** | `runtime/bin/win32-x64/` |
| 7 | **附加插件**：页面内「打开桌宠」按钮，桌宠没在跑时一键拉起（见下方「附加插件」） | `addons/dsh-pet-open/` |
| 8 | **桌宠自带托盘图标**（蓝鲸鱼）：右键「显示大肥鱼 / 打开 DSH / 退出桌宠」，左键单击也可显示；点「本次隐藏」时会弹通知告诉你从托盘找回 | `runtime/helper.py` + `runtime/pet_sliders.py` |
| 9 | **脚边硬件状态挂牌**：CPU / 显卡 / 内存占用实时刷新（显卡带温度），拖拽时跟随、鼠标穿透，右键「硬件状态」可开关 | `runtime/helper.py` + `runtime/hardware_stats.py` + `runtime/stats_plate.py` |

硬件挂牌的取数方式：CPU/内存走 `GetSystemTimes` / `GlobalMemoryStatusEx`（单次 <0.2ms，UI 线程按秒读）；
显卡由后台线程每 2 秒 spawn 一次 `nvidia-smi`（单次约 40–60ms，不占 UI）；没有 NVIDIA 卡时显示 `GPU --`。
挂牌是独立的置顶小窗（`Qt.Tool` + `WindowTransparentForInput`），不参与桌宠的拖拽/气泡几何计算。

指令输入框的目标会话按优先级选择：正在执行 turn 的会话 → 最近活动过的会话 → 会话存储里最活跃的（覆盖刚重启还没有任何事件的情况）。

## 安装

```powershell
# WebUI 用户：web profile
dsh plugin --profile web add <本仓库地址>

# 官方桌面端：desktop profile（需用应用自带的 dsh）
dsh plugin --profile desktop add <本仓库地址>
```

装完在 **插件** 里启用，桌面上会出现大肥鱼。右键可以调大小、气泡大小、减少动态等。

> ⚠️ `runtime/bin/` 里**只带 Windows x64** 的预编译 helper，且它是按本仓库改动重新打包的。
> Linux / macOS 的二进制未包含（源码通用，需自行 `scripts/build-helper.ps1` / `build-helper.sh` 构建）。

## 附加插件：打开桌宠按钮

`addons/dsh-pet-open/` 是一个**独立的配套插件**，在 composer 工具行里加一个「🐋 打开桌宠」按钮，
位置在模型强度变阻器**左侧**，用来把被「本次隐藏」藏起来的桌宠叫回来。

为什么要它：桌宠原生窗口的代码里**只有 `self.hide()`，没有任何 `self.show()` 路径** ——
「本次隐藏」是单向操作，窗口一藏连右键入口都没有了。

```powershell
dsh plugin --profile desktop add <本仓库地址>/tree/main/addons/dsh-pet-open
```

它单独成包（没并进主插件），这样改坏也不会影响桌宠本体；装完刷新页面即可。详见 [addons/dsh-pet-open/README.md](addons/dsh-pet-open/README.md)。

## 授权与致谢

- **代码**：MIT，Copyright (c) 2026 **QCYTSN** —— 见 [LICENSE](LICENSE)
- **当前角色素材**（`assets/pet/`）：MIT，来自 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)
- **提示音**：本项目程序化生成，MIT
- **状态光标**：Chromium 原版，BSD 3-Clause

完整说明见 [ASSET_LICENSE.md](ASSET_LICENSE.md)。本项目为粉丝作品，与 DeepSeek 官方无关联。

## 关键词

`#DSH` `#DeepSeekHarness` `#DSH插件` `#桌宠` `#大肥鱼` `#DeepSeek` `#Electron` `#PySide6` `#VibeCoding`
