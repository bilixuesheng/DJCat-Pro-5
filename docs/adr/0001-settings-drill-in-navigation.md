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
- 层级切换动画沿用 Fluent 运动基准（进入 150 px 滑入 + 300 ms 淡入 `cubic-bezier(0,0,0,1)`，退出 150 ms 淡出 `cubic-bezier(1,0,1,1)`）。150 px 是设备无关像素，Qt 的部件坐标同样是设备无关像素，因此不得再乘 `devicePixelRatio`——那会缩放两次。`main_window.py` 的 `BORDER_WIDTH` 之所以要乘，是因为它喂给原生命中测试，吃的是物理像素。
