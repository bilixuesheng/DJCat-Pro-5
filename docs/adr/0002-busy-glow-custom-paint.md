# Paint the Busy Glow instead of animating a QSS border

Busy Glow 原本由一个 60 ms 的 `QTimer` 驱动，每一帧用 `setStyleSheet()` 重写一条 `qlineargradient` 边框。这条实现同时踩了五个问题：`setStyleSheet()` 是 widget 级替换，忙碌期间 QFluentWidgets 给 TextEdit 装的整张样式表被顶掉，滚动条和选中色退回 Qt 原生外观；60 ms 只有 16.7 fps，且定时器不按真实经过时间补偿，主线程一忙就丢帧；每帧重解析样式表并 repolish；边框宽度从 1 px 变 2 px，开始和结束各挤动一次内容区；QSS 分四边绘制边框，粗渐变在圆角处留下斜向拼接。

改为在一个覆盖输入框的透明 overlay 上自绘：`QPainterPath` 圆角路径 + `QConicalGradient` 笔刷，多遍递减 alpha 描边伪造 bloom。

## Considered Options

- **继续用 QSS，只降低刷新频率**：改动最小，但解决不了圆角拼接、样式表被顶掉和 1 px 跳动，而且降频会让抖动更明显。
- **给输入框套 `QGraphicsBlurEffect` 做光晕**：能得到真模糊，但 graphics effect 会让整棵子树每帧重新栅格化，开销远高于多遍描边，且与下面阴影那条冲突。
- **在 overlay 上自绘多遍描边（已选择）**：一次描完整圆角路径，没有边的概念因而没有拼接；不触碰样式表因而不顶掉 Fluent 外观；不改变输入框几何因而没有跳动。

## Consequences

- **自限 60 Hz 是刻意的，不是疏忽。** 项目把全局 Animation Tick 调到 1 ms（见 `app/platform/animation_timer.py`），但 Busy Glow 每帧要做多遍抗锯齿描边，属于 CLAUDE.md 点名"必须自己限流"的那类回调。相位按真实经过时间计算，重绘按最小 16 ms 间隔合并。删掉这个限流会让 1 ms tick 把开销放大十几倍。
- **已长出的部分是一段连续圆弧，不是两条对称的臂。** 进场时光带从底边中点向两侧爬升，直觉上是两条臂，但两条臂会在起笔点和会合点重叠，alpha 叠加成两个亮疙瘩。表述成以底边中点为中心的单段圆弧后，底边接缝不存在；长满时换成闭合路径，顶边接缝也不存在。不要为了"两条臂"再去调笔帽。
- **锥形渐变按周长弧长参数化，不按原始角度。** `QConicalGradient` 按角度分配颜色，在扁矩形上会让颜色沿短边飞掠、沿长边爬行。色标位置按各边弧长占比重排后颜色才匀速绕圈。渐变在 `resizeEvent` 重建，动画期间只旋转相位。
- **深浅主题是两套配方，不是同一套调亮度。** 光感来自"比背景亮"，浅色主题下没有比接近白更亮的余地，因此浅色配方改为提饱和（×1.30）、降明度（×0.68），靠"比背景暗"显形。这是观感上的妥协，不是参数微调。
- **`app/view/components/busy_glow.py` 依赖 `app/platform/dialog_animation.py`。** AI Markdown 对话框的卡片上挂着 `blurRadius=60` 的 `QGraphicsDropShadowEffect`，而带 graphics effect 的控件只要有子控件重绘就会整棵子树重新栅格化并重跑模糊。Busy Glow 把重绘频率从 16.7 Hz 提到 60 Hz，等于把这项开销放大 3.6 倍，因此光晕启动时复用 `dialog_animation` 的阴影 alpha 渐变把卡片阴影渐隐、结束时渐回。view 组件依赖 platform 适配层是这条约束的直接结果。内联整理所在的 `BroadcastEditPage` 是普通 QWidget，没有这个问题。
- Busy Glow 不表达完成度。转换耗时无法预估，任何百分比都是伪造的。
