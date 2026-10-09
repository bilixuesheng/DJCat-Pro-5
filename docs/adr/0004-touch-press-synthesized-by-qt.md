---
status: superseded by ADR-0008
---

# 触控按下改由 Qt 合成鼠标事件

Windows 上 Qt 6 默认把触控的 `WM_POINTER` 消息交回 `DefWindowProc`，由系统生成对应的鼠标消息。系统要先分辨轻点、拖动和长按（右键），所以轻点在抬手时才一起发按下和松开，拖动在手指开始移动时才发按下。结果是所有控件用手指按住时都没有按下态，要等松开或挪动一点才出现。现在启动时给 QApplication 传入 `-platform windows:nomousefromtouch`：Qt 丢弃系统从触控生成的鼠标消息，在 `TouchBegin` 没有被控件接受时，于落指瞬间自己合成左键按下。

## Considered Options

**逐个控件接管 `TouchBegin`**：应用市场横幅和主页编辑态已经这样做，自己 `setDown(True)`。推广到全部控件时，QFluentWidgets 的下拉框、输入框和菜单项很难覆盖全，以后新加的控件还得再补。

**对每个顶层窗口设 `TABLET_DISABLE_PRESSANDHOLD`**，继续用系统的鼠标消息：要给包括弹出菜单在内的所有顶层窗口挂钩，而且文档没有说明关掉长按后按下消息就不再延迟。

**滚动区内延迟约 100 ms 再显示按下**（Android 的做法）：与鼠标的手感不一致。最终选了立即按下、起滑后撤销，这是 Windows 原生控件的做法。

## Consequences

- 显式指定了平台（命令行 `-platform` 或 `QT_QPA_PLATFORM`，如 offscreen 测试）时不附加这个参数。也不能改用环境变量设置，否则 DJCat 启动的 Application 会继承它。
- 按下在落指瞬间到达，所以从控件上起滑时一定会先出现按下态。`ScrollArea` 的起滑取消因此必须覆盖所有可按控件：按钮、`CardWidget` 的 `isPressed` 和登记过的自绘目标。起滑后的松开由触控仲裁吞掉，控件自己不会复位。
- 长按不再有系统的右键菜单。真机验证推翻了当初的推断：即使系统仍发来 `WM_CONTEXTMENU`，Qt 也会丢弃所有由鼠标触发的这类消息（`QGuiApplicationPrivate::processContextMenuEvent`：Widgets do not care about mouse triggered context menu events）。所以 `app/platform/touch_input.py` 自己补上长按：Qt 合成的左键按下后，手指在 `mousePressAndHoldInterval` 内没挪出触控容差，就向指下控件发一个 `QContextMenuEvent`，与鼠标右键走同一条路径。菜单弹出后抬手的松开落在菜单上，菜单不会把没见过按下的松开当成点击；没有控件弹菜单时，抬手照常算一次点击，与鼠标按住再松开一致。
- 长按的"没挪动"最初借用了 `startDragDistance`，真机上仍然弹不出菜单：Windows 上它取自鼠标的 `SM_CXDRAG`，只有 4 px，而且按横纵位移之和计算，按住不动的手指抖两三个像素就把长按取消了。现在按微软触控规范的 2.7 mm（目标分辨率下约 10 px）取直线距离，与系统拖动阈值取较大者。
- 标题栏拖动也失效了：qframelesswindow 把拖动交给系统的移动循环（`SC_MOVE | HTCAPTION`），这个循环跟着系统的左键走，而手指的左键按下是 Qt 自己合成的，系统那边还没按下，循环立刻结束；只有手指先挪够距离、系统已经补发按下时才偶尔能拖动。`touch_input.py` 让手指在标题栏上的拖动改由 Qt 直接 `move()` 窗口，最大化时先还原；鼠标拖动仍交给系统，保留贴边吸附。
- 真机上还有一处原因没查明：已有任务卡片展开后，手指点时间选择器弹出面板里的勾和叉，按着有高亮、松手没反应，鼠标正常，改动前也正常。offscreen 下把滚动区、展开卡片、先滚动时间列、模态对话框都凑齐也复现不出来，触屏又在学校、拿不到事件日志。`touch_input.py` 因此只做兜底：手指在弹出窗口里的按钮上按下、又在它上面抬起，事件循环处理完抬手后按钮仍没发 `clicked`，就补一次 `click()`；已经点过的不会再点。只限弹出窗口，因为滚动区里手指随内容滚动后抬起时往往还停在原按钮上，那次松开是故意吞掉的。
- 自己接管 `TouchBegin` 的控件（横幅、主页编辑态卡片、动作排序把手）不再额外收到系统合成的鼠标事件。
- 回退只需去掉这个启动参数。长按和标题栏的补丁只认 Qt 合成的鼠标事件，参数去掉后自然不再生效。
