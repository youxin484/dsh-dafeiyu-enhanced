window.__ModuleLoader__.load({
	id: "dsh-pet-open",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		"use strict";

		/**
		 * dsh-pet-open — 浏览器半边。
		 *
		 * 在 composer 工具行里加一个「打开桌宠」按钮，位置在模型强度变阻器**左侧**：
		 * 两者都在 conversation.input.right 这个列表槽位里，靠 order 排序
		 * （变阻器 order 10，本按钮 order 5 → 渲染在它前面，也就是更靠左）。
		 *
		 * 点击后调用 dsh-dafeiyu 的本地配置接口，把 enabled 关掉再打开，
		 * 触发它 stopRuntime → startRuntime，从而重启 helper、把原生窗口重新拉起来。
		 * 先读一次配置：如果用户本来就把插件停用了，就只做「启用」，不会反着来。
		 */

		var React = require("react");

		var CONFIG_ENDPOINT = "/plugins/dsh-dafeiyu/config";
		var STYLE_MARKER = "style[data-dsh-pet-open-style]";

		var CSS = `
[data-pet-open] { display:flex; align-items:center; gap:4px; height:28px; padding:0 8px; flex:none;
  border:1px solid var(--dsw-alias-border-l1,#e2e5ea); border-radius:14px; cursor:pointer;
  background:transparent; color:var(--dsw-alias-label-secondary,#5b6270);
  font-family:inherit; font-size:12px; line-height:20px; white-space:nowrap; }
[data-pet-open]:hover:not(:disabled) { background:var(--dsw-alias-interactive-bg-hover,#eef1f5);
  color:var(--dsw-alias-label-primary,#16181d); }
[data-pet-open]:disabled { cursor:default; opacity:.55; }
[data-pet-open][data-state="busy"] { border-color:var(--dsw-alias-brand-primary,#4176e6);
  color:var(--dsw-alias-brand-primary,#4176e6); }
[data-pet-open][data-state="error"] { border-color:var(--dsw-alias-state-error-primary,#d94c4c);
  color:var(--dsw-alias-state-error-primary,#d94c4c); }
/* 槽位里没有变阻器时，把按钮推到这一组的最右侧（紧贴模型选择器） */
[data-pet-open][data-alone] { margin-left:auto; }
[data-pet-open-icon] { font-size:13px; line-height:1; }
[data-pet-open-text] { display:var(--dsh-composer-model-text-display,inline); }
`;

		function ensureStyle() {
			if (typeof document === "undefined") return null;
			if (document.querySelector(STYLE_MARKER) !== null) return null;
			var element = document.createElement("style");
			element.setAttribute("data-dsh-pet-open-style", "");
			element.setAttribute("data-plugin", "dsh-pet-open");
			element.textContent = CSS;
			document.head.append(element);
			return element;
		}

		function sleep(ms) {
			return new Promise(function (resolve) { setTimeout(resolve, ms); });
		}

		async function readConfig() {
			var response = await fetch(CONFIG_ENDPOINT, { cache: "no-store" });
			if (!response.ok) throw new Error("HTTP " + response.status);
			return response.json();
		}

		async function patchConfig(patch) {
			var response = await fetch(CONFIG_ENDPOINT, {
				method: "PATCH",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(patch),
			});
			if (!response.ok) throw new Error("HTTP " + response.status);
			return response.json();
		}

		/**
		 * 把桌宠叫回来的完整流程。
		 * 关键点：无论中间哪一步失败，都必须保证 enabled 最终是 true，
		 * 否则用户会被留在一个「桌宠被停用」的状态里。
		 */
		async function openPet() {
			var config = null;
			try {
				config = await readConfig();
			} catch (error) {
				// 读不到就按「当前是启用」处理，仍然尝试一轮重启
			}

			if (config !== null && config.enabled === false) {
				await patchConfig({ enabled: true });
				return;
			}

			await patchConfig({ enabled: false });
			await sleep(1500);

			var lastError = null;
			for (var attempt = 0; attempt < 3; attempt++) {
				try {
					await patchConfig({ enabled: true });
					return;
				} catch (error) {
					lastError = error;
					await sleep(600);
				}
			}
			throw lastError !== null ? lastError : new Error("恢复启用失败");
		}

		function PetOpenButton() {
			var pair = React.useState("idle");
			var state = pair[0];
			var setState = pair[1];
			var timerRef = React.useRef(null);
			var buttonRef = React.useRef(null);

			// 变阻器（model-rheostat）与本按钮在同一个列表槽位里（它 order 10，本按钮 order 5）。
			// 它不在的时候（没装 / 被停用 / 自身条件不满足而渲染 null），把按钮推到最右侧，
			// 否则会留一段空隙，看着像和模型选择器脱节。
			var alonePair = React.useState(false);
			var alone = alonePair[0];
			var setAlone = alonePair[1];

			React.useEffect(function () {
				return function () {
					if (timerRef.current !== null) clearTimeout(timerRef.current);
				};
			}, []);

			React.useEffect(function () {
				var node = buttonRef.current;
				if (!node) return undefined;

				var last = null;

				var apply = function () {
					// 全局找变阻器的标记节点：不能靠 parentElement，槽位可能给每个条目
					// 各包一层，那样按钮和变阻器并不是同一个父节点的子元素。
					var alone = document.querySelector("[data-mrh]") === null;
					if (alone === last) return;
					last = alone;
					setAlone(alone);

					// 直接给按钮加 auto margin；同时给「只有一个子节点的包层」也加上，
					// 因为那个包层才是 flex 布局里的 item。两种 DOM 形状都能覆盖。
					node.style.marginLeft = alone ? "auto" : "";
					var parent = node.parentElement;
					if (parent !== null && parent !== document.body && parent.childElementCount === 1) {
						parent.style.marginLeft = alone ? "auto" : "";
					}
				};

				apply();
				if (typeof MutationObserver !== "function") return undefined;
				var observer = new MutationObserver(apply);
				observer.observe(document.body, { childList: true, subtree: true });
				return function () {
					observer.disconnect();
					node.style.marginLeft = "";
					var parent = node.parentElement;
					if (parent !== null) parent.style.marginLeft = "";
				};
			}, []);

			function settle(next, ms) {
				setState(next);
				if (timerRef.current !== null) clearTimeout(timerRef.current);
				timerRef.current = setTimeout(function () {
					timerRef.current = null;
					setState("idle");
				}, ms);
			}

			function handleClick() {
				if (state === "busy") return;
				setState("busy");
				Promise.resolve()
					.then(openPet)
					.then(function () { settle("done", 1200); })
					.catch(function () { settle("error", 4000); });
			}

			var label = state === "busy" ? "启动中…" : state === "done" ? "已打开" : state === "error" ? "失败了" : "打开桌宠";
			var title = state === "error"
				? "启动桌宠失败：请到 设置 → 插件 → dsh-dafeiyu 手动把「启用大肥鱼」打开"
				: "打开/显示桌面大肥鱼（会重启它的原生窗口）";

			return React.createElement("button", {
				ref: buttonRef,
				type: "button",
				"data-pet-open": "",
				"data-state": state,
				"data-alone": alone ? "" : undefined,
				disabled: state === "busy",
				title: title,
				"aria-label": title,
				onClick: handleClick,
			},
				React.createElement("span", { "data-pet-open-icon": "", "aria-hidden": "true" }, "🐋"),
				React.createElement("span", { "data-pet-open-text": "" }, label)
			);
		}

		function apply(ctx) {
			var styleElement = ensureStyle();
			if (styleElement !== null) {
				ctx.effect(function () {
					return function () { styleElement.remove(); };
				}, "dsh-pet-open: styles");
			}

			try {
				ctx.slots.inject("conversation.input.right", function () {
					try {
						// order 5 < 变阻器的 10 → 渲染在它左边
						return ctx.slots.register({
							name: "conversation.input.right",
							id: "pet-open",
							order: 5,
							label: function () { return "打开桌宠"; },
						}, PetOpenButton);
					} catch (error) {
						console.warn("[dsh-pet-open] 注册失败：", error);
						return undefined;
					}
				});
			} catch (error) {
				console.warn("[dsh-pet-open] 注入失败：", error);
			}
		}

		exports.name = "dsh-pet-open";
		exports.inject = ["slots"];
		exports.apply = apply;

		return module.exports;
	}
});
