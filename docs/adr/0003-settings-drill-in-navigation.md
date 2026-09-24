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
- 交叉淡入淡出用 `QGraphicsOpacityEffect` 驱动，这看起来与"graphics effect 会让整棵子树重新栅格化"的顾虑冲突，但已经量过，不要为省这点开销改掉观感：整段 300 ms 推移多花约 6.6 ms CPU，单次重绘从 2.8–8.0 ms 涨到 3.0–8.6 ms（1.08–1.10x）。`dialog_animation.py` 之所以必须暂停阴影，差别在两处：那里是 `QGraphicsDropShadowEffect`，模糊远贵于一次不透明度相乘；而且它挂在卡片上、要陪着 Busy Glow 这种不定时长的子动画逐帧重算，不是推移这样 300 ms 就结束的一次性动作。下钻式拆分之后每个 Section 只有一屏卡片，这也是它便宜的前提——若某个 Section 重新长回整页，需要重新量。
- 每次推移新建的 `QParallelAnimationGroup` 挂在 `SettingSectionStack` 名下，必须在 `_Transition.settle()` 里 `deleteLater()`。Qt 不会自己回收它们，漏掉就是每次下钻和返回各留一组动画对象，一次会话里线性增长。
