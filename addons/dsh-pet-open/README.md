# dsh-pet-open 🐋

给 [dsh-dafeiyu](../)（大肥鱼桌宠）配的**一个小附加插件**：在 composer 工具行里加一个「打开桌宠」按钮，
位置在模型强度变阻器的**左侧**，一键把被隐藏的桌宠叫回来。

## 为什么需要它

桌宠原生窗口的代码里**只有 `self.hide()`，没有任何 `self.show()` 路径**。
所以「右键 → 本次隐藏」是一次单向操作：窗口一藏，连右键入口都没有了，
运行期间无法靠桌宠自己恢复。

官方手段只有在设置页把「启用大肥鱼」关掉再打开（触发 helper 重启）。
这个按钮把这套操作做成一次点击。

## 布局

```
conversation.input.right（composer 工具行，发送按钮之前）
├─ dsh-pet-open     order 5    [🐋 打开桌宠]   ← 本插件
└─ model-rheostat   order 10   [强度 ▬▬▬ High]  ← 模型强度变阻器
```

两者在同一个列表槽位里按 `order` 排序，5 < 10，所以按钮渲染在变阻器左边。

### 变阻器缺席时按钮自动靠右

变阻器没装、被停用，或它自身条件不满足而渲染 `null` 时，整组变窄，
按钮会留在左边、和模型选择器之间空出一截。所以按钮会自己处理：

- 全局探测 `document` 里的 `[data-mrh]`（变阻器的根节点标记）
- 缺失时给按钮（以及它「单子节点的包层」）加 `margin-left: auto`，把按钮推到最右
- 用 `MutationObserver` 跟随变阻器的挂载/卸载动态切换，不需要刷新页面

两个实现细节踩过坑：**不能靠 `parentElement` 找变阻器**（槽位可能给每个条目各包一层，
两者不是同一个父节点的子元素）；也**不能只给按钮本身加 auto margin**（若存在包层，
那个包层才是 flex item）。两处都加，两种 DOM 形状都能覆盖。

回归测试见 `dev/preview/harness.html`（8 项断言，含变阻器动态消失/回来）。
运行前先从 `<dafeiyu 仓库>/dev/preview` 复制 React UMD 到 `dev/preview/vendor`（该目录不入库）。

## 实现

点击后调用 dsh-dafeiyu 自己暴露的本地配置接口
（`PATCH /plugins/dsh-dafeiyu/config`）：

```js
先 GET 配置
├─ enabled 已经是 false → 只做「启用」（不会反着来）
└─ enabled 是 true     → false → 等 1.5s → true（失败重试 3 次）
```

`enabled` 关→开会触发 dafeiyu 的 `stopRuntime → startRuntime`，重启 helper 进程、
重新拉起原生窗口。

**失败保护**：无论中间哪一步出错，都会保证 `enabled` 最终回到 `true`，
不会把用户留在「桌宠被停用」的状态；真失败时按钮变红并提示去设置页手动开。

按钮四态：`打开桌宠` → `启动中…` → `已打开` / `失败了`。
composer 空间紧张时（`--dsh-composer-model-text-display: none`）自动只留图标。

## 安装

```powershell
dsh plugin --profile desktop add <本仓库地址>/tree/main/addons/dsh-pet-open
```

或本地路径：`dsh plugin --profile desktop add <本目录绝对路径>`

装完刷新页面（F5），composer 右下角变阻器左边就会出现按钮。

## 依赖

需要 **dsh-dafeiyu 已安装并启用**（本仓库根目录就是这个插件）。
按钮只是去调用它的配置接口，两个插件互相独立。

## 授权

MIT。与 DeepSeek 官方无关联。
