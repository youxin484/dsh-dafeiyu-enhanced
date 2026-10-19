/**
 * dsh-pet-open — Host 半边。
 *
 * 「打开桌宠」是一个纯浏览器侧按钮：它直接调用 dsh-dafeiyu 自己暴露的本地配置
 * 接口（/plugins/dsh-dafeiyu/config）把 enabled 关掉再打开，从而让那个插件重启
 * helper 进程、把原生窗口重新拉起来。
 *
 * 之所以不在 Host 侧另做一个「显示」通道：dsh-dafeiyu 的 helper 只有 self.hide()，
 * 没有任何 self.show() 路径，能复用的现成手段就是 enabled 开关触发 startRuntime。
 *
 * 这个空 apply 只为让本包出现在 Loader 组合里，dsh-client-modules 才会扫描
 * package.json 的 dsh.client 声明。
 */
function apply() {}

export { apply }
