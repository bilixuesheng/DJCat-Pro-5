# 设置页改为多级下钻导航，搜索只提供建议

设置页原本是单页八个可折叠分组，搜索时就地筛选卡片并强制展开命中的分组。随着设置项增长，单页折叠既放不下分类，也没有位置承载背景、图标这类需要实时预览的内容。现在改为 Windows 设置那样的多级下钻：顶层是纯导航行，点进去是 Setting Section，面包屑固定在顶栏显示 Setting Route；搜索框在任何层级都只弹 Setting Suggestion，点一条跳到对应 Setting Route 并高亮目标 Setting Card，页面本身不再做任何筛选。

## Considered Options

**内联筛选与搜索建议并存**（曾计划采用）：顶层保留"就地筛选 + 展开命中分组"，同时弹建议。放弃的原因是两套搜索反馈同时存在，用户既要看下方重排的列表又要看上方的弹窗；而且多级之后，筛选必须把三级的卡片扁平化挂回顶层，搜索态看到的排布和真实层级不一致。

**分组行同时支持点击进入和原地展开**：同一行两个语义不同的热区，在触控上极易误触，而现有的按压/取消判定已经足够复杂。

## Consequences

- `CollapsibleSettingCardGroup` 的折叠与搜索展开机制（`setSearchExpanded`、`setSettingCardVisible` 及其动画）整体退役，顶层改用纯导航行。
- `cfg.expandedSettingGroups` 不再有任何读写方。配置项定义保留，以免老 `UserConfig.json` 中的键在下次保存时被清掉。
- 条件可见的 Setting Card（如"自定义主页图片"只在图片来源为自定义时出现）原本寄生在 `setSearchText()` 上，必须解耦为由各配置项 `valueChanged` 驱动的独立刷新。
- 隐藏的 Setting Card 不进入 Setting Suggestion：搜索不得为了展示结果而改写用户的前置设置。
- 层级切换是 `SlideNavigationTransitionInfo` 式的推移：进入下一级时旧页左移出场、新页自右入场，返回时反向，两页共用同一条 `cubic-bezier(0,0,0,1)` 曲线和 300 ms 时长并交叉淡入淡出。**不要**改成"旧页原地淡出"——那是 `FromBottom`（顶层切换）的特征，横向用它两页会脱节。
- 位移 150 px 是设备无关像素，Qt 的部件坐标同样是设备无关像素，因此不得再乘 `devicePixelRatio`——那会缩放两次。`main_window.py` 的 `BORDER_WIDTH` 之所以要乘，是因为它喂给原生命中测试，吃的是物理像素。
- 每个 Setting Section 自带 `ScrollArea` 意味着一个页面里有十几个可滚动区域。它们不能在构造时各抓一次触控手势：Qt 的手势管理器不会在目标销毁时清理，抓放循环留下的残留会在之后创建窗口时崩溃（`QWindowPrivate::connectToScreen` 读到已销毁的 `QScreen`）。因此 Section 延迟到首次显示才抓，且只抓一次。
- 交叉淡入淡出最初用 `QGraphicsOpacityEffect` 直接挂在两页真实的 `ScrollArea` 上，当时量得效果本身只让单次重绘贵 1.08–1.10x，结论是"不要为省这点开销改掉观感"。这个结论只比较了"有效果"和"没效果"，漏掉了大头：推移的每个 Animation Tick 都要把两页整棵子树（含 Setting Preview）重新绘制一遍，1 ms tick 下这份开销没有上限。现改为**推移快照**：起步时对两页各 `grab()` 一次，真页面隐藏，逐帧只在 `_SectionSnapshot` 上按 `painter.setOpacity` 贴图，推移结束才显示真页面。观感完全不变——同一条曲线、同样的时长、同样的交叉淡入淡出。offscreen 下 1100×760 实测：起步从 3.8 ms 涨到 32 ms（两次 grab，与旧做法第一帧的开销同量级），之后每帧从 20.4 ms（最大 28 ms）降到 1.7 ms。代价是推移的 300 ms 里页面内容冻结（悬停、预览动画不走），与顶层 `DrillInTransitionStackedWidget` 的快照过渡一致。窗口在推移途中改尺寸时直接落到末态，由真页面按新尺寸排版，不拉伸快照。
- 每次推移新建的 `QParallelAnimationGroup` 挂在 `SettingSectionStack` 名下，必须在 `_Transition.settle()` 里 `deleteLater()`。Qt 不会自己回收它们，漏掉就是每次下钻和返回各留一组动画对象，一次会话里线性增长。
