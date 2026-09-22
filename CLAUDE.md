# CLAUDE.md

DJCat Pro 5 的实现规则和架构约束。领域术语见 `CONTEXT.md`。

## Relationships

- 一个 **Home Card** 只能属于 Default、Custom 或 Application 三种来源之一；排序列表可以混排，但执行规则不合并。
- **Application Home Card** 引用一个 Installed Application 的 Open Action 或 Application Preset；Application 被卸载或固定关系被移除后，相应主页和托盘入口同步失效。
- **Application Catalog** 与本机安装清单按稳定 Application ID 合并，形成界面使用的 `installed`、`update_available`、`installed_version` 和架构支持状态。
- **Admin Console** 维护四种互不替代的 Catalog Order；Application Preset 还按所属 Application 分组，任何服务端顺序都不直接覆盖本机 Home Card 排序。
- **Application Update** 与首次安装使用同一 Package 下载和安装链路；差别只在目标目录已有受 DJCat 管理的 Installed Application。
- **Application Launch** 执行 Installed Application 的 Open Action；Application Store 的卡片和详情页共享同一后台运行状态，不创建第二个并发启动。
- **Projection** 的纯文本正文由 `QTextEdit` 渲染，Markdown 正文由 `MarkdownView(largeText=True)` 渲染；两者是同一 Projection 的互斥显示方式。
- Projection 编辑器的标题保存在 `cfg.broadcastTitle`，离开编辑器后仍保留；正文不作为编辑草稿持久化。
- **Projection Snapshot** 保存在 `cfg.lastBroadcast`；开始 Projection 时立即写入，关闭或返回编辑只清除活动状态，不删除可再次导入的内容。
- **Installed Mode** 与 **Portable Mode** 共享相同的目录结构，Storage Migration 移动的是整个 App Data Directory，不是单独的设置文件。
- **Application Icon** 由个性化设置统一控制；主窗口、启动页、系统托盘和 Tray Menu 的"主页"入口共享自定义图片，但默认模式保留各位置原有资源。
- **Tray Card Shortcut**、主页固定项和 Application Store 共享 `cfg.pinnedHomeCards` 中的稳定引用；图片缓存路径只是可更新的派生元数据。
- **Custom Home Card** 包含一个 Action Sequence；`ActionSequenceWorker` 每次执行前读取最新动作列表，同一动作 ID 在一次运行中至多执行一次。
- Custom Home Card 与 Custom 模式的 **Home Card Task** 共享 `ActionSequenceEditor` 和 Home Action 校验规则；两者只共享编辑与执行能力，不共享标题、图标或持久化对象。
- Broadcast Task、Home Card Task 与 Shutdown Task 持久化在 `cfg`；对应设置页只编辑规则，MainWindow 负责按时间匹配或分发 Application Lifecycle Event。
- Existing-card 模式的 **Home Card Task** 只保存稳定 Home Card key、用于失效提示的标题快照和打开／关闭动作；关闭只适用于 Default Home Card。Custom 模式直接拥有 Action Sequence，但不会创建 Custom Home Card。
- AI Markdown Conversion 使用 Machine Identity 领取和结算 Daily Quota；Machine Code 只是定位该身份的可见别名。
- Projection 编辑器中的"整理并投送"只在 Markdown 模式显示并独立记忆；它复用 AI Markdown Conversion，但启动恢复必须绕过整理流程并原样恢复 Projection Snapshot。
- **Setting Section** 按 Setting Route 组成一棵树；顶层只有导航行，叶子才持有 Setting Card。Setting Suggestion 指向卡片及其 Route，不改变任何页面内容。
- Animation Tick 推进动画属性；Qt/Windows 的绘制与合成链路再决定 Presented Frame。两者不能互换描述。
- Menu Reveal 由 Animation Tick 推进，但菜单 viewport 刷新次数不是动画帧数；合并冗余刷新不能改变用户看到的展开效果。

## Ownership rules

**`cfg` 是客户端持久化设置的唯一来源。** 设置页、主页和托盘通过 `cfg.set(...)` 修改值；运行时对象不另建一份需要双向同步的配置副本。

Application Icon 的来源和本地路径由 `cfg.applicationIconSource` 与 `cfg.applicationIconPath` 持久化。MainWindow 同步更新 QApplication 和主窗口图标，启动页直接复用主窗口图标；SystemTrayIcon 同步更新系统托盘及已存在的"主页"菜单项，不重建菜单，也不要求重新启动。

**`app/platform/animation_timer.py` 独占 Qt 全局 Animation Tick 间隔。** View 和业务模块不直接调用 Qt 私有动画 API；私有符号不可用时保留 Qt 默认行为。

**`app/platform/menu_animation.py` 独占 QFluentWidgets 的 Menu Reveal 适配。** 它只替换 `DROP_DOWN` 和 `PULL_UP` 两种动画管理器；其他动画类型及页面组件不再分别接管菜单动画。

**`app/platform/dialog_animation.py` 独占 QFluentWidgets 蒙层弹窗的公共适配。** 它复用阴影效果并接管 `showEvent` 和 `done`，在淡入淡出期间暂停阴影以避免 1 ms Animation Tick 下的逐帧模糊重算；淡入结束后用 `color` 属性动画将阴影 alpha 从 0 渐变到目标值，此时无外层不透明度效果只剩一层阴影，不掉帧。弹窗中的下拉框仍属于 Menu Reveal；页面不得重复修补组件库或改变原有动画曲线。

**`app/view/components/setting_section.py` 独占设置页的层级导航。** Setting Section 的下钻、返回、面包屑对应的 Setting Route，以及层级之间的推移动画都由它提供；页面只负责装配内容。推移沿用 `SlideNavigationTransitionInfo`：进入下一级时旧页左移出场、新页自右入场，返回时反向，两页共用同一条 `cubic-bezier(0,0,0,1)` 曲线和 300 ms 时长并交叉淡入淡出。"旧页原地淡出"是 `FromBottom`（顶层切换）的特征，横向照搬会让两页脱节。位移 150 px 是设备无关像素，不得再乘 `devicePixelRatio`——Qt 的部件坐标本就是设备无关像素，乘了等于缩放两次；`main_window.py` 的 `BORDER_WIDTH` 要乘是因为它喂给原生命中测试，吃的是物理像素。动画期间只改 `pos` 和不透明度，不碰布局。

**设置页搜索只产出 Setting Suggestion。** 页面本身不筛选、不折叠、不重排；建议只按 Setting Card 的标题匹配，条件隐藏的卡片不参与，跨 Section 重名的标题才补完整 Route 前缀。`SettingPage` 提供 `searchSuggestions()` 和 `navigateToRoute()`，弹窗由 MainWindow 拥有——搜索框属于标题栏，设置页不得反向持有它。选中建议后清空搜索框、跳到目标 Route、滚动到卡片并描一圈主题色边框，绝不改写用户的前置设置来让隐藏卡片现身。

**每个 Setting Section 各自是一个 `ScrollArea`，各自记住滚动位置。** 返回上一级时停在离开时的位置，触控仲裁沿用 `ScrollArea` 既有实现，页面不另写一套。

`ScrollArea` 的触控手势抓取只做一次，不能反复抓了又放：Qt 不会在目标销毁时清掉手势管理器里的记录，抓放循环留下的残留会在之后创建任意窗口时崩在 `QWindowPrivate::connectToScreen`。一次会话里大多数 Setting Section 从不打开，因此它们用 `ScrollArea(parent, grabTouch=False)` 构造，首次显示时才 `grabTouchGesture()`。是否已抓由实例自己记账——`QScroller.grabbedGesture()` 返回的是全局注册的识别器类型（任何 viewport 都非零），拿它判断会让除第一个以外的所有 `ScrollArea` 都不再抓手势，等于全局关掉触控滚动。

**`ScrollArea` 统一仲裁单指触控滚动与子控件点击。** 从按钮、下拉框或卡片上起滑时，移动达到系统拖动阈值后必须取消该触控序列的按压和释放，不能在滚动结束时触发原控件；未达到阈值的短按仍按正常点击处理。页面不得各自复制这套判定。HomePage 进入卡片编辑态时由排序手势独占触控，并依靠卡片拖动的边缘自动滚动跨越视口；退出编辑态后恢复页面触控滚动。

**Tray Menu 不拥有 Home Card。** 它只根据 HomePage 提供的入口快照重建菜单，并把稳定 key 交回 MainWindow/HomePage 执行。

Tray Menu 的外观和弹出方式固定恢复为 v5.1.2：右键由注册的 context menu 打开，左键按配置调用菜单；位置调整保留在 `showEvent()`，不再叠加新的展开或定位方案。自定义 AcrylicMenu 在 Windows 10 上统一使用方角窗口和方角边框，一级菜单和主页卡片二级菜单保持一致；Windows 11 继续使用原有系统圆角、亚克力和阴影。该平台差异只属于 Tray Menu，不修改下拉框、输入框右键等 QFluentWidgets 菜单。

**HomePage 按稳定 key 复用 Application Home Card。** 不变快照不得重建卡片或重复发布主页变化；标题、图标和动作更新原有卡片，移除时才释放对应 QWidget。

TrayControlPage 只渲染 Tray Card Shortcut 开关，不得在刷新控件时清理 `cfg.trayHomeCardKeys`。MainWindow 必须先恢复 Application Home Card，再用完整的 HomePage 快照移除已经失效的引用，避免启动阶段的临时不完整快照覆盖已保存选择。

### 主窗口与页面

**MainWindow** 是桌面端组合根和长生命周期运行时所有者。它负责：

- 导航、搜索框和系统托盘的页面级绑定；
- Scheduled Task 的定时匹配、Application Lifecycle Event 分发、音频播放、Home Card/Action Sequence 执行和 Client Update 流程；
- Projection、Exam Countdown 与 Shutdown Prompt 的窗口创建和回收；
- 应用退出时停止页面工作线程、音频、下载和待保存编辑。

MainWindow 的缩放命中宽度使用统一 DPI 比例计算，以 300% 缩放下 35 个物理像素为基准，即 `round(35 × devicePixelRatio / 3)`；窗口切换屏幕时重新计算，因此所有缩放比例都按同一规则变化。调整该基准时必须同时确认顶部和右侧命中带不会覆盖标题栏最小化、最大化与关闭按钮。

**HomePage** 是唯一随 MainWindow 立即创建的导航页面。Application Store、Credits、Tray Control 和 Setting 使用 Lazy Page；Projection 编辑、Exam Countdown、Broadcast Task、Home Card Task 和 Shutdown Task 页面通过 `_getTaskPage()` 系列方法首次打开时创建。

只有启用了启动恢复且最近一次 Projection 仍处于活动状态，或启动时触发的 Home Card Task 明确打开 Projection 时，MainWindow 才在启动阶段创建 Projection 编辑页面；仅关闭尚未打开的 Projection 不会破坏懒加载。

Exam Countdown 编辑页的返回栏和"开始倒计时"按钮固定在页面两端，四张配置卡片统一放在中间的 `ScrollArea`；窗口高度不足时只滚动配置区，不得压缩卡片造成内容重叠。

Lazy Page 必须保留外部调用需要的最小接口：

| Lazy Page | 加载前可暂存或转发的状态 |
|---|---|
| `LazyAppStorePage` | 搜索文字、固定卡片信号；清缓存和关闭在未加载时为空操作 |
| `LazySettingPage` | 缓存清理信号；搜索建议和 Setting Route 导航一律转发给真实页面（导航到设置页必然已 `ensureLoaded()`，搜索框只在该页可见） |
| `LazyTrayControlPage` | 最新 Home Card 列表 |
| `LazyCreditsPage` | 无业务状态 |

调用方不得直接依赖 `lazyPage.page` 的存在；需要真实页面时调用 `ensureLoaded()`，只做关闭或缓存失效时应保持未加载状态。

### Scheduled Task 调度

Broadcast Task、Home Card Task 和 Shutdown Task 都按各自 `cfg` 列表的顺序显示；新任务插入列表开头，并连同原有任务顺序一起持久化。页面不得仅反转显示顺序，也不得按触发时间重新排序。

三类 Scheduled Task 共用表单和 `TaskFormSettingCard`，但展示材质取决于表单宿主：新建对话框中的每个配置项保留独立圆角卡片；已有任务的展开区域只绘制分割线并透出外层材质，避免卡片嵌套。表单交给 ScrollArea 后会被 Qt 重新设置父对象，因此材质模式必须在构造时依据原始宿主确定，不能在绘制阶段沿当前父链判断。修改共享表单时应同时验证三类任务的新建和已有任务两种场景。

MainWindow 的单一调度循环在对应管理页面从未打开时也必须执行 Scheduled Task。Broadcast Task 和固定时间 Home Card Task 最多补偿最近 60 秒内被模态窗口或主线程阻塞错过的触发；Shutdown Task 只补偿最近 5 秒，避免恢复运行后执行过期关机。软件行为 Home Card Task 完全不参与时间匹配。一次定时触发由任务种类、计划时刻和稳定任务 ID 去重。

Custom 模式的 Home Card Task 以稳定任务 ID 读取最新 Action Sequence；任务被删除或切换模式后，尚未开始的动作停止。同一任务仍在运行时跳过新触发，不弹出并发确认框。Existing-card 模式在触发时解析当前 Home Card 快照，不复制源卡片数据；关闭 Projection 时同时识别正常窗口和悬浮恢复入口，关闭未打开的功能不创建页面、不报错。

### 应用市场

**server/app_store.py** 拥有 Application Catalog、Package 配置、Application Download Count 和管理后台写入。桌面端只消费目录和下载重定向，不能自行增加下载次数。

AI Markdown 数据库的 schema 初始化缓存同时使用文件身份和 SQLite schema version；同一路径下的数据库文件被替换后必须重新初始化，普通额度和请求记录写入不能反复触发 schema 初始化。

**ApplicationStore** 拥有本机 Application 规则：目录扫描、安装清单、版本合并、ZIP 安全校验、原子覆盖、卸载和 Application Action 执行。它不拥有界面按钮或 InfoBar。

**AppStorePage** 拥有一次 UI 会话中的异步状态：

| State | Meaning |
|---|---|
| `_downloadJobs` | 正在传输 Package 的 worker 与线程 |
| `_downloadProgress` | 0–100 的确定下载百分比 |
| `_launching` | 正在后台执行 Open Action 的 Application ID |
| `_installing` | 正在解压并原子替换的 Application ID |
| `_uninstalling` | 正在移除的 Application ID |
| `_downloadStates` | 卡片和详情按钮共享的用户可见状态文字 |

下载刚建立或尚未得到有效传输进度时，即使按钮文字为"下载中 0%"，仍显示不确定进度线；出现有效百分比后切换为确定进度线。确定进度使用与 Fluent ProgressBar 一致的 150 ms 属性动画；连续更新必须从当前显示值追到最新目标值，不能瞬间跳变或排队播放过时进度。打开、安装和卸载无法可靠计算百分比，始终显示不确定进度线。进度线贴住按钮底边，只铺满两侧 5 px 圆角之间的直线区域；自身两端保持抗锯齿圆角，按钮禁用时仍使用当前主题色。卡片和详情页必须从同一组状态读取，不能各自维护进度。首次启动 Application 不等待或检查可见窗口；只有重新打开仍在运行的进程时才尝试唤起已有窗口，无窗口的进程不能因此被判定为启动失败。

Application Launch 在后台线程读取本机安装状态并执行 Open Action，完成或失败后通过 Qt Signal 在 GUI 线程恢复卡片和详情按钮；线程创建、启动失败和页面关闭也必须清理 `_launching`，不得留下永久禁用的按钮。

Application Store 首次显示前同步计算"已安装"和"全部应用"两个网格的最终列数，避免先按旧宽度单列绘制再重新排列。后续尺寸变化仍由现有布局定时器合并，不为修复首帧闪动持续同步重排。

Client Update 与 Application Store 的 Package 下载共用 `app/common/update_download.py` 中的 `UpdateDownloadWorker`。支持分段的下载默认以 8 个工作线程开始；后续智能扩容和全局并发限制仍由共享下载器统一控制，不能按界面各自复制线程配置。

Client Update 下载完成后，MainWindow 使用后台 `UpdateApplyWorker` 解压更新 ZIP 到暂存目录并启动 `updater.exe`，期间显示不可取消且只含不确定进度环的蒙层弹窗。确认更新器进程创建成功后才关闭 DJCat；启动失败时关闭蒙层并保留当前进程显示错误，不能在 GUI 线程等待更新器启动。

广告触控的 QApplication 全局事件过滤器只在 Application Store 可见时安装；页面隐藏或关闭时移除，避免其他页面的全部输入事件继续经过广告层。

`ApplicationStore.installZip()` 是安装与更新的共同提交点：先校验并解压到 `.staging-*`，已有版本先改名为 `.backup-*`，再原子替换目标；失败时恢复备份。启动扫描会恢复未完成替换留下的备份并清理残留操作目录。

### 管理后台

`server/templates/admin_base.html` 拥有 Admin Console 的共享导航布局；`server/static/admin.css` 和 `server/static/admin.js` 拥有后台共用的导航、表格拖拽和异步交互，不在各页面模板复制相同逻辑。移动端打开侧边栏时锁定页面滚动，但导航列表本身必须保留独立的纵向触控滚动。

Catalog Order 由 `server/app_store.py` 按稳定 ID 写入数据库。拖拽和键盘排序提交完整新顺序及原始顺序快照；服务端在事务内核对原始顺序，过期快照返回 HTTP 409。保存失败或拖拽取消时，浏览器恢复原顺序；拖拽浮影只是临时视觉状态，不参与命中测试或持久化。Application Preset 排序必须限定在所属 Application 内。

### 配置和文件

`app/config/paths.py` 是 App Data Directory 及其所有派生目录的唯一来源。其他模块使用 `CONFIG_PATH`、`PROGRAM_DIR`、`APP_STORE_CACHE_DIR` 和 `HOME_CARD_ICON_DIR`，不得自行重新拼接另一套根目录。

Storage Migration 的安全约束：

- 迁移必须发生在 `qconfig.load` 之后、进程退出阶段；运行中的模块仍使用启动时的路径常量。
- Installed → Portable 先写入 `.migrating`，成功后再提交为 Portable 目录；失败时清理临时目录，原数据和当前模式不变。
- Portable → Installed 复制并改写目标配置成功后，才把 Portable 源目录改名为唯一 `.bak` 目录；源目录仍存在时下一次启动仍保持 Portable Mode。
- 只改写配置值中位于旧 App Data Directory 下的绝对路径，不改写普通文案或外部路径。
- 每次启动只读取当前 App Data Directory 的 `UserConfig.json`；迁移后的 Installed Application 连同清单和安装目录继续支持打开、更新及卸载，不回退读取旧模式目录。

**ImageCache** 拥有应用图片和临时 Package 所在缓存根目录的清理互斥。存在下载或安装操作时拒绝清缓存；设置页只发出用户意图并显示 `ImageCache.size()`。

Application 图标允许使用 PNG、JPEG、WebP、GIF、BMP、SVG 和 ICO。`ImageCache` 保留普通图片已识别的 URL 文件后缀；ICO 在临时文件中由 Pillow 读取最大尺寸帧并规范化为 PNG，再原子替换到 `.png` 缓存路径。Application Store、主页和 Tray Menu 只复用规范化后的路径，不应各自承担 ICO 解码兼容。

### Projection 渲染

Projection Snapshot 的内容和活动状态必须作为同一份配置立即落盘，不能等到程序退出时保存，否则无法恢复意外退出。只有 `cfg.restoreBroadcastAtStartup` 已启用且快照内容合法、仍处于活动状态时才自动恢复；恢复关闭或快照损坏时只清除活动标记，不创建 Projection 编辑页面。没有合法快照时，手动导入入口保持禁用。

Projection 的两种正文渲染器必须保持这些共同约束：

- 左侧和顶部正文起点一致。大字号 `MarkdownView` 的内容边距固定为 4 px，与 `QTextDocument.documentMargin()` 默认值一致；普通更新日志的 MarkdownView 保留渲染器默认边距。
- 纯文本和 Markdown 正文控件都延伸到 Projection 窗口底边；外层布局不保留底部空隙，内容自身的 4 px 边距不受影响。
- 纯文本与大字号 Markdown 正文共享 96% 行高；Markdown 顶层块之间不额外留白，普通更新日志保留默认块间距。
- 全屏时纯文本和 Markdown 都使用 QFluentWidgets `SmoothScrollDelegate`，并在 viewport 上注册 `QScroller.TouchGesture`，支持鼠标滚轮和平滑单指触控；窗口化时正文不响应滚轮或拖动滚动，只能操作垂直滚动条，正文区域的鼠标或触控拖动用于移动 Projection 窗口。
- Projection 关闭文本选择，手指拖动用于滚动而不是选择文字。
- Projection 切换正文类型或关闭时释放旧正文控件，并立即取消其远程 Markdown 图片下载；返回编辑时仍从独立的 Projection 内容快照恢复。
- 全屏时 Markdown 正文未处理的鼠标按压和拖动必须在 `MarkdownView` 边界停止，不能冒泡到外层无边框 Projection 窗口；窗口化时由 Projection 统一接管正文拖动，但短按链接和操作按钮仍需保持可用。

Projection、Exam Countdown 和 Fullscreen Clock 共用的 `WindowBackground` 会覆盖整个窗口背景。窗口化时的 `1 px #808080` 边界线必须由该组件在主题色、纯色或图片绘制完成后最后绘制；全屏时不绘制。不得恢复为父窗口 QSS 边框，否则背景子控件会再次把它盖住。

Projection、Exam Countdown 与 Fullscreen Clock 的窗口化背景、图片裁剪和边框共用 8 px 圆角；首次显示前启用透明窗口表面，不依赖 Win11 系统圆角。Qt 阴影只附着在背景组件上，四周各留 12 px 透明空间，Exam Countdown 与 Fullscreen Clock 的可见内容仍为 600 × 190，Projection 初始可见尺寸仍为可用屏幕的一半；字体、布局与角落按钮按 `contentsRect()` 定位，不能把阴影空间算进正文尺寸。切回全屏（含保留任务栏模式）时清除透明边距、圆角、边框和阴影，背景重新铺满窗口。Projection 保留窗口化缩放：Windows 命中测试使用消息中的坐标，按 DPI 转为背景局部坐标，在可见圆角边界内侧 12 px、外侧 2 px 的圆角区域判断四边及四角，不将透明阴影外沿作为边框。圆角外的空白和角落按钮不触发缩放；全屏禁用缩放。

**`app/view/components/busy_glow.py` 独占 Busy Glow。** AI Markdown 对话框和 Projection 编辑器内联整理的输入框共用同一个 `BusyGlowOverlay`；它是输入框的兄弟层而不是子控件，因此光带能同时向框内和框外渗开，并且不碰输入框的样式表——QFluentWidgets 的 TextEdit 外观正是靠 widget 级 `setStyleSheet` 装上去的，改写它会连滚动条一起换成 Qt 原生外观。不要回到 QSS 渐变边框：样式表分别绘制边框各边，粗渐变在圆角处必然斜向拼接。

Busy Glow 的四条约束在 `docs/adr/0002-busy-glow-custom-paint.md` 里有完整理由，改动前先读：重绘自限 60 Hz（全局 1 ms Animation Tick 下这是必需的自我限流，不是疏忽）；已长出的部分是以底边中点为中心的一段连续圆弧，不是两条对称的臂（两条臂会在起笔点和会合点叠出亮疙瘩，调笔帽解决不了）；锥形渐变按周长弧长而非原始角度参数化，几何变化时在 `resizeEvent` 重建，动画期间只转相位；深浅主题是两套配方而不是同一套调亮度。

Busy Glow 只表示"正在进行"，不表示完成度。对话框那张卡上挂着 `QGraphicsDropShadowEffect`，而 graphics effect 会因任意子控件重绘而整棵子树重新栅格化，所以光晕启动时用 `dialog_animation.fadeDialogShadow()` 把卡片阴影渐隐、结束时渐回。

内联整理必须保存开始时的标题和正文快照；完成后投送完整结果，用户取消时先停止接收迟到信号，再立即投送快照正文。

## Module topology

### Desktop

| Module | Responsibility |
|---|---|
| `djcat.py` | 进程入口、工作目录、单实例应用、日志、配置加载和 MainWindow 创建 |
| `app/platform/` | Windows 单实例/IPC、唤起窗口、开机启动及 Qt 运行时适配 |
| `app/platform/animation_timer.py` | Qt 全局 Animation Tick 间隔的私有 API 适配和安全回退 |
| `app/platform/dialog_animation.py` | QFluentWidgets 蒙层弹窗的阴影复用和淡入淡出阴影暂停 |
| `app/platform/menu_animation.py` | QFluentWidgets 全局 Menu Reveal 管理器适配，不改变原版展开视觉 |
| `app/config/` | 配置 schema、常量和 App Data Directory |
| `app/common/` | 不依赖具体页面的 AI、更新下载、应用市场、主页动作和进程环境规则 |
| `app/common/home_card_tasks.py` | Home Card Task schema 归一化、稳定 ID、触发事件和动作常量；不负责计时或 QWidget |
| `app/view/windows/main_window.py` | 桌面组合根、导航、长期运行任务和 Client Update UI |
| `app/view/pages/` | 页面、临时展示窗口和页面级 worker 编排 |
| `app/view/pages/home_card_task_page.py` | Home Card Task 的懒加载编辑页面；不拥有调度计时器 |
| `app/view/components/` | 多页面复用的 Markdown、背景、滚动和设置卡片组件 |
| `app/view/components/busy_glow.py` | Busy Glow 的几何、配色和绘制；不知道 AI Markdown 的业务规则 |
| `app/view/components/setting_section.py` | Setting Section 的下钻容器、导航行、推移动画和命中高亮 |
| `app/view/components/setting_preview.py` | Setting Preview：按真实排布复刻整个主窗口（标题栏／导航栏／横幅／卡片）、投送与倒计时窗口（标题／正文或大时间／角落按钮，按钮位置跟随对应配置）、软件图标四处用法、主题小窗和标题栏＋Windows 通知区域 |
| `app/view/components/setting_suggestion_menu.py` | Setting Suggestion 弹窗；选中后交回 Route，不把文本写回搜索框 |
| `app/common/application_icon.py` | Application Icon 的解析：主窗口、启动页、托盘与 Tray Menu“主页”共用一处 |
| `pyqt_github_markdown/` | 项目内置 Markdown 渲染器；不承载 DJCat 业务规则 |

`app/common/application_version.py` 只包含架构和版本比较等纯函数，允许 MainWindow 在启动阶段导入。重量较大的 `app/common/application_store.py`、Custom Home Card 编辑器和 Markdown 渲染器分别在对应页面、编辑操作或更新日志首次需要时导入；`edge_tts` 依赖只在实际查询音色或合成语音时导入。

### Server

| Module | Responsibility |
|---|---|
| `server/ai_markdown.py` | Machine Identity、Daily Quota、AI Markdown Conversion 和管理接口 |
| `server/app_store.py` | Application Catalog、下载重定向/计数和应用市场管理页面 |
| `server/templates/admin_base.html` | Admin Console 的共享页面结构、侧边栏和导航入口 |
| `server/static/admin.css`、`server/static/admin.js` | Admin Console 的共享样式、移动端导航、目录排序和异步表单 |

服务端模块不能导入桌面 View；桌面端通过 HTTPS API 消费服务端结果。桌面配置中的 `DJCATAI_API_BASE_URL` 环境变量只改变 API 根地址，不改变业务所有权。

## App lifecycle

### Startup (`djcat.py`)

```text
set working directory
  → SingletonApplication (Windows single instance + IPC)
  → unlockQtAnimations (before any QWidget animation is created)
  → optimizeFluentDialogs + optimizeFluentMenus (before MainWindow or its popups are created)
  → configure logging and clear stale Client Update files
  → qconfig.load(CONFIG_PATH, cfg)
  → MainWindow(isSilent)
      → HomePage eagerly
      → register Lazy Pages without constructing their real pages
      → restore Application Home Card from cfg.pinnedHomeCards
      → publish the complete Home Card snapshot to Tray Control and Tray Menu
      → create tray and long-lived timers/workers
      → restore valid active Projection Snapshot only when recovery is enabled
      → dispatch startup event and, when applicable, silent-startup event
  → bind activation request and aboutToQuit
  → Qt event loop
```

App Data Directory 必须在导入 `cfg` 和调用 `qconfig.load` 前由 `app/config/paths.py` 确定。第二个 Windows 实例只通知现有实例显示窗口，然后退出；它不创建 MainWindow。

`unlockQtAnimations()` 必须在 QApplication 创建之后、任何动画启动之前、GUI 主线程上调用。它只针对项目锁定的 Qt 运行时查找私有符号；找不到符号或动态库时记录警告并保留 Qt 默认 16 ms 间隔，不允许加载系统中另一份 Qt 来凑合。

`optimizeFluentDialogs()` 和 `optimizeFluentMenus()` 在 MainWindow 创建之前分别注册蒙层弹窗阴影复用和 Menu Reveal 管理器，重复调用保持幂等。菜单适配覆盖所有使用 QFluentWidgets 下拉或上拉管理器的菜单，包括对话框内部的下拉框和输入框右键菜单；其他 Popup 和 Flyout 不会自动继承蒙层弹窗优化。

### Navigation loading

```text
switchTo(target)
  → if another snapshot transition is active, keep only latest target
  → ensureLoaded(target) when it is first requested
  → run stacked-widget transition
  → after currentChanged, navigate to the one queued target
```

排队目标在首个过渡期间可以提前构造，以免页面构造时间叠加到第二段动画；重复目标只执行一次。

### Shutdown

```text
Tray Menu quit → MainWindow.requestQuit()
  → dispatch application-quit Home Card Tasks
  → wait asynchronously for newly started custom Action Sequences
  → MainWindow._shutdownResources()
  → stop navigation animation and timers
  → cancel Edge TTS and stop audio players
  → flush loaded Setting / Scheduled Task editors
  → shutdown HomePage, loaded Application Store page and loaded Projection editor workers
  → cancel running custom Home Card Task workers
  → cancel Client Update download and close InfoBars
  → optional Storage Migration connected after normal shutdown
  → QApplication exits and releases the single-instance lock
```

`_shutdownResources()` 必须幂等。Application Lifecycle Event 的退出触发只归属于 Tray Menu 请求，不应接到 `aboutToQuit` 或其他关闭路径；自定义退出动作完成前不能提前取消对应 worker。Lazy Page 未加载时，关闭流程不能为了清理而创建它。正常退出期间未被主动关闭的 Projection 必须保留 Projection Snapshot 的活动状态；用户主动关闭、自动任务明确关闭投送或返回编辑才结束下次启动恢复。

## Animation scheduling

PySide6 6.10 没有绑定 `QAnimationDriver`，DJCat 因此把 Qt 私有 `QUnifiedTimer::setTimingInterval()` 封装在 `app/platform/animation_timer.py`，将默认 16 ms Animation Tick 间隔改为 1 ms。1 ms 是避免零间隔忙循环的最小非零调度间隔；事件循环繁忙时，逾期 tick 会在 GUI 线程恢复后推进，不再额外固定等待 16 ms。

该适配有四条边界：

- 动画 duration 仍按真实经过时间计算，不能按 tick 次数累计时间。
- 不读取显示器刷新率，也不按 60/120/160 Hz 切换间隔；机器负载决定实际可处理的 tick 数。
- 不承诺 Presented Frame 数；DWM、VSync 和绘制耗时仍可限制屏幕实际帧率。
- Qt 版本或打包布局变化导致私有符号不可用时必须安全退回默认动画驱动；升级 PySide6 时需要在 Windows x64 重新验证导出符号和端到端动画时长。

1 ms 间隔只对改位置和透明度的动画是净收益。凡是每帧要调操作系统或强制同步布局的回调，都必须自己限流，否则 tick 变密等于把这类开销放大十几倍：`setMask` 在顶层菜单上落到 `SetWindowRgn`，`QLayout.activate()` 是不受 `LayoutRequest` 事件压缩保护的同步重排。只打脏标记的调用（`setFixedHeight`、`update()`）由 Qt 自行合并，不要给它们加限流——那只会让控件几何落后于动画值。

Menu Reveal 是另一层独立优化：保留 QFluentWidgets 原始的 250 ms 时长、`OutQuad` 缓动、窗口位移、逐帧遮罩和阴影，只把每次属性变化触发的 viewport 强制刷新合并为动画结束时的一次。上游同一个方法里还负责同步 `WA_UnderMouse` 和 `HoverEnter`，这部分必须留在逐帧执行，否则展开途中光标下的菜单项不会高亮。逐帧遮罩按位移去重：位移不足一像素时遮罩完全相同，跳过不改变展开轨迹，但不能改成按时间采样遮罩——遮罩滞后于窗口位置会让内容错位。不能改成只淡入、删除遮罩或阴影，也不能把 `NONE`、`FADE_IN_DROP_DOWN` 等其他管理器替换成下拉实现。

带蒙层的 `MaskDialogBase` 的 200 ms 淡入和 100 ms 淡出由 `QGraphicsOpacityEffect` 驱动；`app/platform/dialog_animation.py` 接管 `showEvent` 和 `done`，在不透明度动画期间暂停 `QGraphicsDropShadowEffect`（`setEnabled(False)`）。淡入结束后移除 `QGraphicsOpacityEffect`，将阴影 `color` alpha 从 0 渐变到目标值（150 ms / `OutCubic`）；此阶段只有一层阴影效果，即使 1 ms tick 也不掉帧。淡出直接禁用阴影后开始不透明度动画。不能改用 `setWindowOpacity`：`MaskDialogBase` 调用 `setWindowFlags(Qt.FramelessWindowHint)` 后窗口类型退回 `Qt::Widget`，带父窗口时 `isWindow()` 为假，`QWidget::setWindowOpacity()` 直接返回，动画会静默失效。也不能通过缩短动画、改变蒙层透明度或永久删除阴影换取性能。

## Code shape

### Naming

项目自有 Python 名称沿用现有风格：类使用 `PascalCase`，函数、方法和局部变量使用 `camelCase`，常量使用 `UPPER_SNAKE_CASE`，内部实现加 `_` 前缀。Qt 事件重载保留 Qt 名称，如 `showEvent`、`resizeEvent`。

业务名称优先使用本文件 Language 中定义的词。特别注意：

- Projection 与 Broadcast Task 不能共用无修饰的 `broadcast` 业务含义；
- Client Update 与 Application Update 必须写明种类；
- Home Action 与 Application Action 不能互换；
- `APP_DIR` 是程序目录，`APP_DATA_DIR` 是可迁移数据目录。

### QWidget initialization

新增的复杂 QWidget/SettingCard 优先按四阶段组织：

```python
def __init__(self, parent=None):
    super().__init__(parent)
    self._initWidget()
    self._initLayout()
    self._bind()
```

`_initWidget()` 创建并设置子控件，`_initLayout()` 只组装布局，`_bind()` 最后连接信号。小型且只含少量控件的类可以保持内联，不为形式增加一次性包装函数。

### Threads and Qt

- 网络、文件复制、ZIP 解压、卸载和 Application Launch 不得阻塞 Qt 主线程。
- worker 在线程中工作，通过 Qt Signal 把结果送回页面；只有主线程更新 QWidget。
- 页面关闭时先设置 shutdown/cancel 状态，再等待有文件提交风险的线程；超时后也不能让回调访问已销毁控件。
- 可计算总字节数的下载使用确定进度；无法可靠估计的文件操作使用不确定进度，不伪造百分比。
- 新的私有 Qt/Windows API 必须封装、可失败、可回退，并有锁定版本的真实二进制验证。

### Comments

代码默认依靠清晰命名表达行为。注释只解释隐藏约束、平台差异或看似多余但不能删除的顺序，例如原子替换、触控手势和 Qt 动画时序；不写逐行复述代码的注释。

## Flagged ambiguities

- "全屏投送"过去容易被称为 Broadcast，但项目中的 Broadcast Task 是音频定时播报。已统一用 **Projection** 表示文字展示。
- UI 名称"自动任务"不等同于所有 Scheduled Task。领域语义中用 **Home Card Task** 专指按固定时间或 Application Lifecycle Event 执行 Home Card、自定义 Action Sequence，或关闭 Default Home Card 的规则。
- "电教猫关闭时"指 Tray Menu 的退出程序，不是关闭主窗口、系统关机、更新重启或任意 `aboutToQuit` 信号。
- "更新"可能指 DJCat 自身或市场 Application。已拆为 **Client Update** 与 **Application Update**。
- "安装版"可能被误解为 Installed Application。已定义 **Installed Mode** 专指 DJCat 的 App Data Directory 位置。
- "下载次数"并不证明 Package 已完整下载或安装。它是服务端去重后的下载重定向请求累计值。
- "懒加载页面"不等于只隐藏 QWidget。真实页面及其重量级依赖必须尚未构造；纯版本比较被拆到轻量模块，避免 MainWindow 提前初始化应用市场缓存。
- Application Store 的"全部"与"已安装"是两个操作上下文：即使存在 Application Update，"全部"卡片仍显示"打开"；"已安装"和详情页才显示"更新"。
- 主窗口右上角关闭曾被理解为退出。已消歧：**close** 只隐藏主窗口；**quit** 才清理资源并结束进程。
- "解除 Qt 60 帧限制"容易被理解为绕过 VSync 或保证某个 FPS。已消歧：本实现只把 **Animation Tick** 的默认 16 ms 间隔改为 1 ms，不控制 **Presented Frame**。
- "菜单动画优化"不等于修改动画样式或缩短时长。**Menu Reveal** 保留原版展开轨迹、遮罩和阴影，只消除重复刷新。
- "应用打开成功"不要求检测到窗口。**Application Launch** 创建进程即可；无窗口或仅托盘运行的 Application 仍属于正常启动。
- "低配置机器按自身能力运行"不表示创建自适应刷新率策略。已消歧：所有机器使用同一最小非零 tick 间隔；事件循环繁忙时自然只能处理较少更新，不额外补跑积压帧。
- Application Store 的"全部应用 → 全部"分类固定每页最多展示 6 个 Application；"推荐"分类展示全部推荐项，不参与分页。
