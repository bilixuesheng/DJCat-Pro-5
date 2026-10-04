# Window Transition 用快照形变，不逐帧改窗口尺寸

Display Window 在全屏、窗口化和 Floating Button 之间切换原本是一步跳到位。现在加上 Window Transition：起步时给切换前后的样子各截一张快照，真窗口先切到终态但暂不显示；一个临时的置顶透明层把一块圆角矩形从起点几何插值到终点几何，圆角和阴影一起插值，两张快照在里面交叉淡入淡出，都按比例裁切铺满，不拉伸；结束后撤掉透明层、显示真窗口。四种切换（缩小、放大、Collapse、从 Floating Button 恢复）都是 250 ms `OutCubic`。

## Considered Options

**逐帧改真窗口的 geometry**：最"真实"，但每帧都会让 Projection 的 Markdown 正文重新换行、倒计时和时钟按新高度重算字号、背景图片按新尺寸重新缩放、Silhouette Shadow 按新尺寸重新模糊。三个窗口都是透明表面，Windows 上每次提交都是整窗交给系统合成。在教室的老电脑上这是逐帧掉帧和闪烁，文字一路抖动也难看。

**系统自带的最小化／最大化动画**：DWM 只给有标题栏样式的普通窗口播放，而且只在最小化、最大化和还原时播放。Display Window 是透明、无边框的 Tool 窗口；全屏也不是最大化，Floating Button 更不是任务栏。这条路走不通。

## Consequences

- 过渡期间画面是静止的：倒计时和时钟的数字定格 250 ms，恰好跨过一秒时，结束后跳到最新值；计时本身不受影响。
- 倒计时从全屏（约 16:9）到 600 × 190，长宽比差得很远，只缩放一张图一定会变形，所以必须交叉淡入淡出两张快照。
- 过渡期间透明层吞掉全部输入，不支持中途反向；0.25 秒内的第二次点按直接丢弃。
- 全屏大小的透明层如果每个 Animation Tick 都重绘，就是每毫秒把整屏位图交给系统一次，所以重绘按所在屏幕的刷新率自限，读不到时按 60 Hz。
- Collapse 时圆角矩形飞向 Floating Button 的位置并收成 60 px 正圆，内容淡出、主题色和图标淡入，停在 Floating Button 平时的半透明状态；恢复是倒放，从 Floating Button 当前的位置展开。
- 「个性化 → 外观」有一个总开关，同时控制三个 Display Window，默认开启；关掉后行为与以前完全一样，直接跳到位。开始和关闭 Display Window 不播放 Window Transition。
