# DJCat Pro 5

面向 Windows 教室场景的桌面助手，提供全屏信息投送、考试倒计时、定时音频播报、定时关机和可编排的主页入口。配套服务为桌面端提供 AI Markdown 转换和应用市场目录。

## Language

### 主页

**Home Card**:
主页“常用功能”区域中一个用户可见的入口。按来源分为 Default Home Card、Custom Home Card 和 Application Home Card，三者共享排序，但来源和执行规则不同。
_Avoid_: shortcut、tile；不加限定地称 card

**Default Home Card**:
DJCat 自带的 Home Card，目前固定为“全屏投送”“考试倒计时”“全屏时钟”“定时播报”和“定时关机”。用户可以移除、恢复和排序，但不能改写它代表的功能。
_Avoid_: built-in app、system card

**Custom Home Card**:
用户在本机创建的 Home Card，包含标题、说明、图标和一个有序 Action Sequence。它不归属于 Application Store 中的 Application。
_Avoid_: Application Home Card、Application Preset

**Home Action**:
Custom Home Card 中的一个本地动作，类型为启动程序、执行 Shell、打开网页、打开本地路径或延时。程序和 Shell 动作可选择是否等待进程结束。
_Avoid_: Application Action、step、command（仅 Shell 类型是命令）

**Action Sequence**:
一次点击 Custom Home Card 后按当前顺序处理的 Home Action 集合。运行期间会读取最新动作列表，但同一动作 ID 至多执行一次；等待型动作和延时会阻塞后续动作，取消则停止尚未执行的动作。
_Avoid_: workflow、macro

### 系统托盘

**Tray Menu**:
DJCat 系统托盘图标提供的快捷操作集合。右键始终打开它；左键可配置为打开 Tray Menu 或显示主窗口。打开主窗口和退出程序始终可用，Broadcast Task 与 Shutdown Task 的总开关可分别隐藏；选中的 Tray Card Shortcut 位于任务总开关之后，按主页顺序显示或统一放入“主页卡片”二级菜单。菜单使用原生行高，不提供滚动；“主页卡片”二级菜单既可由鼠标悬停，也可由触控点击展开。
_Avoid_: context menu、右键菜单（它不只可由右键打开）

**Tray Click Action**:
用户左键单击系统托盘图标时的行为，取值为显示主窗口或打开 Tray Menu；右键不受它影响。
_Avoid_: left-click preference、mouse mode

**Tray Card Shortcut**:
Tray Menu 中对现存 Home Card 的引用，可指向 Default Home Card、Custom Home Card 或 Application Home Card，并复用源卡片的标题、图标和点击行为。触发 Default Home Card 时先显示主窗口并导航；Custom/Application Home Card 成功执行时保持当前窗口状态，失败时显示主窗口并保留现有错误提示。源 Home Card 被移除、删除或取消固定后，对应 Tray Card Shortcut 同步消失。
_Avoid_: Tray Home Card、复制卡片、独立托盘动作

### 课堂展示

**Projection**:
“全屏投送”产生的一次临时文字展示，由标题和正文组成，正文可使用纯文本或 Markdown。Projection 可全屏或窗口化显示，也可收起为恢复入口；关闭后不保存内容。
_Avoid_: Broadcast、投屏（不传输屏幕或视频）、presentation

**Exam Countdown**:
“考试倒计时”产生的一次临时计时，具有初始时长、剩余时长、标题和语音提醒开关。它可运行、暂停、调整、重置或结束；关闭后不保存进度，从更长时间跨过 15 分钟及归零时可播放提醒音。
_Avoid_: timer、Scheduled Task

**Fullscreen Clock**:
“全屏时钟”显示当前系统时间，进入后直接全屏展示，也可切换为固定大小的窗口。它没有计时控制或编辑页面，关闭后不保存状态。
_Avoid_: Exam Countdown、timer、Scheduled Task

### 定时任务

**Scheduled Task**:
按启用状态、星期和精确时间反复匹配的本地规则。当前只有 Broadcast Task 和 Shutdown Task 两种；提到 Task 时应始终写明种类。
_Avoid_: alarm、job；不加限定地称 task

**Broadcast Task**:
“定时播报”中的 Scheduled Task，在匹配时播放指定 Audio Source，并带有独立的重复次数和音量。它是音频播放，不是 Projection。
_Avoid_: Projection、全屏投送、Broadcast Window

**Audio Source**:
Broadcast Task 要播放的内容来源，分为内置报时或铃声、系统 TTS、在线 Edge TTS 和本地音频。TTS 使用文本，Edge TTS 还选择中文音色，本地音频使用文件。
_Avoid_: Broadcast Type、media type

**Shutdown Task**:
“定时关机”中的 Scheduled Task，在匹配时直接关闭计算机或先进入 Shutdown Prompt。它的“本次不关机”只跳过当前触发，不会禁用或删除任务。
_Avoid_: shutdown timer、power plan

**Shutdown Prompt**:
Shutdown Task 可选的全屏确认过程，提供立即关机、延后 1 分钟再次提醒，以及可选的跳过本次。若用户在任务设定的等待时间内没有操作，则自动关机。
_Avoid_: notification、dialog（它覆盖所有屏幕并参与关机决策）

### 应用市场

**Application Store**:
DJCat 内用于发现、安装、更新、打开和卸载 Application Catalog 中 Application 的用户功能。它消费 Application Catalog，但不负责 DJCat 自身的 Client Update。
_Avoid_: Application Catalog、应用下载页（仅是界面名称）

**Application Catalog**:
服务端发布给桌面端的有序目录快照，包含 Application、可用架构和 Advertisement。它描述远端可获得的内容，不代表本机已经安装的内容。
_Avoid_: Application Store、Installed Application、manifest

**Application**:
Application Catalog 中一个可下载产品，拥有稳定 ID、名称、版本、安装目录、按架构区分的 Package，以及可选的 Application Action 和 Application Preset。
_Avoid_: 软件、程序（仅保留在既有 UI 文案中）、package

**Package**:
一个 Application 面向某一客户端架构发布的 ZIP 安装包；当前架构为 x86_64 或 arm64。Package 带有 SHA-256 完整性校验值；只有启用且校验值有效时，该架构才能下载该 Application。
_Avoid_: Application、Client Installer、binary

**Installed Application**:
已由 Application Store 安装并可被 DJCat 识别的 Application。它与 Application Catalog 中同 ID 的 Application 是同一产品的本地状态，版本落后时形成 Application Update。
_Avoid_: downloaded application、Package

**Application Action**:
由 Application Catalog 提供、在 Application 边界内执行的受限动作，类型为启动安装目录内的程序、打开 HTTPS 网页或调用允许的系统 URI。启动程序时以该 Application 的安装目录为工作目录，并清理 DJCat 自身的运行时路径，以兼容 Python/Nuitka 打包的 Application。作为应用默认入口时称 Open Action；由 Application Preset 引用时称 Preset Action。
_Avoid_: Home Action、Shell action

**Application Preset**:
归属于一个 Application 的命名 Preset Action，由服务端维护标题、说明和顺序。Application Preset 本身不是 Home Card；用户将它固定到主页后才产生 Application Home Card。
_Avoid_: Custom Home Card、template、default setting

**Application Home Card**:
从 Application Store 固定到主页、并归属于一个 Installed Application 的 Home Card。它执行该 Application 的 Open Action 或某个 Application Preset 的 Preset Action，所属应用未安装时不可用。
_Avoid_: Custom Home Card；不加限定地称 Preset Card

**Recommendation**:
Application Catalog 中对现有 Application 的推荐标记和独立排序。它不是 Application 的副本，也不改变安装、版本或 Package 规则。
_Avoid_: featured copy、Advertisement

**Advertisement**:
Application Catalog 中独立排序的推广位，展示标题、说明和图片，并可指向一个 Application、外部 HTTPS 网页或不提供按钮。Advertisement 是否启用只影响目录展示。
_Avoid_: Recommendation、Application

### AI Markdown

**AI Markdown Conversion**:
将作业清单或其他纯文本整理成适合 Projection 展示的 Markdown 的一次请求。转换结果只有在用户确认采用后才替换原文；取消对话保留原文，它也不等同于 Projection 本身。
_Avoid_: chat、generation、Projection

**Machine Identity**:
用于把 AI Markdown 使用量稳定归到同一台设备的匿名身份。它只服务于额度统计，不是账号、许可证或可见的 Machine Code。
_Avoid_: account、license、raw hardware ID

**Machine Code**:
服务器为 Machine Identity 分配的用户可见别名，格式为 `DJ-` 加六位起的数字。它便于用户和管理员识别额度记录，不具备认证或授权能力。
_Avoid_: Machine Identity、activation code、license key

**Daily Quota**:
每个 Machine Identity 每个北京时间自然日可用于 AI Markdown Conversion 的额度点数，于 0 点刷新。一次成功请求按当前时段的扣费点数消耗额度，失败请求不最终占用额度。
_Avoid_: request count（高峰时一次请求可能消耗两点）、token quota

**Peak Hours**:
可由管理员启用的双倍额度时段，当前为北京时间 9:00–12:00 和 14:00–18:00。启用时这些时段每次转换扣 2 点，其余时段扣 1 点。
_Avoid_: rate limit window、busy status

**Custom Markdown Style**:
桌面端用户可选的本机偏好，用来微调 AI Markdown Conversion 的输出格式；与服务端基础规则冲突时以它为准。它不直接改变 Projection 的渲染样式。
_Avoid_: theme、CSS、System Prompt

### 更新

**Client Update**:
DJCat Pro 5 自身的新版本，通过专用更新信息和 Windows 安装程序交付。安装程序固定从 `DOWNLOAD_URL` 指向的雨云对象存储下载，不根据版本号或架构拼接 GitHub Release 地址。它独立于 Application Store，不使用 Application Catalog 或 Package。
_Avoid_: Application Update；不加限定地称 update

**Application Update**:
同一 Application 在 Application Catalog 中的版本高于 Installed Application，或本地执行清单修订落后时形成的更新，用新 Package 替换该应用的本地安装。它不会升级 DJCat 客户端。
_Avoid_: Client Update；不加限定地称 update

**Application Download Count**:
服务端记录的 Application 下载请求累计值。桌面端只在 Application Store 的“全部”卡片展示它；数值来自 Application Catalog，不由客户端本地推算。服务端用每次下载生成的随机 token 去重，同一 token 重试不会重复计数。
_Avoid_: 本机安装次数、当前用户下载次数、完成安装次数

### 配置存储

**App Data Directory**:
DJCat 所有可迁移数据的根目录，包含 `UserConfig.json`、`Program/`、`AppStoreCache/` 和 `HomeCardIcons/`。进程启动时只确定一次，运行期间不切换。
_Avoid_: APP_DIR（程序文件所在目录）、只把它称为配置目录

**Installed Mode**:
App Data Directory 位于 `QStandardPaths.GenericDataLocation/DJCatPro` 的存储模式。它适合正常安装；这里的 Installed 指 DJCat 自身的存储模式，不是 Installed Application。
_Avoid_: Application 安装状态、用户模式

**Portable Mode**:
App Data Directory 位于程序旁 `DJCatPro/` 的存储模式。启动时只要该目录存在就选择 Portable Mode，适用于系统盘有还原或需要随程序携带数据的场景。
_Avoid_: 便携 ZIP 的文件格式、Application 的安装目录

**Storage Migration**:
切换 Installed Mode 与 Portable Mode 时，在应用完成正常关闭后复制整个 App Data Directory、改写配置中位于旧根目录下的绝对路径，并通过下一次启动重新选择模式。切到 Portable Mode 时保留原用户数据；切回 Installed Mode 时把原 Portable 目录改名为 `.bak` 备份，避免它继续被启动检测选中。
_Avoid_: 只复制 `UserConfig.json`、运行中热切换路径

### 页面加载

**Lazy Page**:
已注册导航身份但尚未创建真实页面 QWidget 的占位页。`LazyPage.ensureLoaded()` 在首次导航或确实需要页面能力时创建真实页面，并转发必要的信号和暂存输入。
_Avoid_: 隐藏页面（隐藏的真实页面已经构造）、后台预加载

### 动画

**Animation Tick**:
Qt 统一动画计时器推进 `QPropertyAnimation`、动画组和 QFluentWidgets 动画当前时间的一次更新。它决定属性更新的细密程度，不等同于一次窗口绘制，也不保证屏幕实际呈现一帧。
_Avoid_: Render Frame、刷新率、渲染线程 sleep

**Presented Frame**:
Windows 合成器和显示设备最终呈现的一帧。它会受绘制耗时、DWM、VSync、显示器刷新率和机器负载约束，DJCat 的 Animation Tick 间隔不能解除这些约束。
_Avoid_: Animation Tick；用 1 ms 调度间隔推断 1000 FPS

### 动词词汇

这些动词在项目内有固定含义；新的名称优先沿用它们，不用近义词制造第二套概念。

**load**: 从本地配置、清单或资源读取数据。
_Not_: fetch（网络请求）

**save**: 把用户配置或本地状态持久化。

**fetch**: 发起网络请求取得目录、额度、语音或更新信息。
_Not_: load（本地读取）

**normalize**: 在持久化或服务端数据进入业务逻辑前，将兼容旧格式、缺失字段和非法值收敛为可用结构。
_Not_: validate（只判断能否接受）

**validate**: 检查输入、下载包或完整性约束；失败时拒绝继续，不负责修正数据。

**execute**: 执行已经验证的 Home Action 或 Application Action。

**activate**: 唤起已经运行的窗口或进程，不创建第二份运行实例。

**install / uninstall**: 将 Application 原子地放入安装目录，或从安装目录移除。

**remove**: 从主页、菜单、内存集合或配置中移除引用。
_Not_: uninstall、delete files

**clear**: 清空缓存、输入或集合；不用于卸载 Application。

**close**: 关闭一次 Projection、Exam Countdown 或对话框；主窗口的关闭按钮只隐藏窗口。
_Not_: quit（结束 DJCat 进程）

**quit**: 经统一资源清理流程退出 DJCat 进程。

**on\***: Qt 信号、事件或异步结果的响应函数。

## Relationships

- 一个 **Home Card** 只能属于 Default、Custom 或 Application 三种来源之一；排序列表可以混排，但执行规则不合并。
- **Application Home Card** 引用一个 Installed Application 的 Open Action 或 Application Preset；Application 被卸载或固定关系被移除后，相应主页和托盘入口同步失效。
- **Application Catalog** 与本机安装清单按稳定 Application ID 合并，形成界面使用的 `installed`、`update_available`、`installed_version` 和架构支持状态。
- **Application Update** 与首次安装使用同一 Package 下载和安装链路；差别只在目标目录已有受 DJCat 管理的 Installed Application。
- **Projection** 的纯文本正文由 `QTextEdit` 渲染，Markdown 正文由 `MarkdownView(largeText=True)` 渲染；两者是同一 Projection 的互斥显示方式。
- **Installed Mode** 与 **Portable Mode** 共享相同的目录结构，Storage Migration 移动的是整个 App Data Directory，不是单独的设置文件。
- **Tray Card Shortcut**、主页固定项和 Application Store 共享 `cfg.pinnedHomeCards` 中的稳定引用；图片缓存路径只是可更新的派生元数据。
- **Custom Home Card** 包含一个 Action Sequence；`ActionSequenceWorker` 每次执行前读取最新动作列表，同一动作 ID 在一次运行中至多执行一次。
- Broadcast Task 与 Shutdown Task 持久化在 `cfg`；对应设置页只编辑规则，MainWindow 的调度循环负责匹配时间并触发执行。
- AI Markdown Conversion 使用 Machine Identity 领取和结算 Daily Quota；Machine Code 只是定位该身份的可见别名。
- Animation Tick 推进动画属性；Qt/Windows 的绘制与合成链路再决定 Presented Frame。两者不能互换描述。

## Ownership rules

**`cfg` 是客户端持久化设置的唯一来源。** 设置页、主页和托盘通过 `cfg.set(...)` 修改值；运行时对象不另建一份需要双向同步的配置副本。

**`app/platform/animation_timer.py` 独占 Qt 全局 Animation Tick 间隔。** View 和业务模块不直接调用 Qt 私有动画 API；私有符号不可用时保留 Qt 默认行为。

**Tray Menu 不拥有 Home Card。** 它只根据 HomePage 提供的入口快照重建菜单，并把稳定 key 交回 MainWindow/HomePage 执行。

### 主窗口与页面

**MainWindow** 是桌面端组合根和长生命周期运行时所有者。它负责：

- 导航、搜索框和系统托盘的页面级绑定；
- Scheduled Task 的定时匹配、音频播放和 Client Update 流程；
- Projection、Exam Countdown 与 Shutdown Prompt 的窗口创建和回收；
- 应用退出时停止页面工作线程、音频、下载和待保存编辑。

**HomePage** 是唯一随 MainWindow 立即创建的导航页面。Application Store、Credits、Tray Control 和 Setting 使用 Lazy Page；Projection 编辑、Exam Countdown、Broadcast Task 和 Shutdown Task 页面通过 `_getTaskPage()` 系列方法首次打开时创建。

Lazy Page 必须保留外部调用需要的最小接口：

| Lazy Page | 加载前可暂存或转发的状态 |
|---|---|
| `LazyAppStorePage` | 搜索文字、固定卡片信号；清缓存和关闭在未加载时为空操作 |
| `LazySettingPage` | 搜索文字、缓存清理信号；未加载时无需刷新 AI 风格草稿 |
| `LazyTrayControlPage` | 最新 Home Card 列表 |
| `LazyCreditsPage` | 无业务状态 |

调用方不得直接依赖 `lazyPage.page` 的存在；需要真实页面时调用 `ensureLoaded()`，只做关闭或缓存失效时应保持未加载状态。

### 应用市场

**server/app_store.py** 拥有 Application Catalog、Package 配置、Application Download Count 和管理后台写入。桌面端只消费目录和下载重定向，不能自行增加下载次数。

**ApplicationStore** 拥有本机 Application 规则：目录扫描、安装清单、版本合并、ZIP 安全校验、原子覆盖、卸载和 Application Action 执行。它不拥有界面按钮或 InfoBar。

**AppStorePage** 拥有一次 UI 会话中的异步状态：

| State | Meaning |
|---|---|
| `_downloadJobs` | 正在传输 Package 的 worker 与线程 |
| `_downloadProgress` | 0–100 的确定下载百分比 |
| `_installing` | 正在解压并原子替换的 Application ID |
| `_uninstalling` | 正在移除的 Application ID |
| `_downloadStates` | 卡片和详情按钮共享的用户可见状态文字 |

下载阶段显示确定进度线；安装和卸载无法可靠计算百分比，显示不确定进度线。卡片和详情页必须从同一组状态读取，不能各自维护进度。

`ApplicationStore.installZip()` 是安装与更新的共同提交点：先校验并解压到 `.staging-*`，已有版本先改名为 `.backup-*`，再原子替换目标；失败时恢复备份。启动扫描会恢复未完成替换留下的备份并清理残留操作目录。

### 配置和文件

`app/config/paths.py` 是 App Data Directory 及其所有派生目录的唯一来源。其他模块使用 `CONFIG_PATH`、`PROGRAM_DIR`、`APP_STORE_CACHE_DIR` 和 `HOME_CARD_ICON_DIR`，不得自行重新拼接另一套根目录。

Storage Migration 的安全约束：

- 迁移必须发生在 `qconfig.load` 之后、进程退出阶段；运行中的模块仍使用启动时的路径常量。
- Installed → Portable 先写入 `.migrating`，成功后再提交为 Portable 目录；失败时清理临时目录，原数据和当前模式不变。
- Portable → Installed 复制并改写目标配置成功后，才把 Portable 源目录改名为唯一 `.bak` 目录；源目录仍存在时下一次启动仍保持 Portable Mode。
- 只改写配置值中位于旧 App Data Directory 下的绝对路径，不改写普通文案或外部路径。

**ImageCache** 拥有应用图片和临时 Package 所在缓存根目录的清理互斥。存在下载或安装操作时拒绝清缓存；设置页只发出用户意图并显示 `ImageCache.size()`。

Application 图标允许使用 PNG、JPEG、WebP、GIF、BMP、SVG 和 ICO。`ImageCache` 必须保留这些已识别的 URL 文件后缀；下载临时文件以 `.part` 结尾，校验 ICO 时显式指定 `ico` 格式，再原子替换到最终缓存路径。不得把 ICO 退化为通用 `.img`，因为 Application Store、主页和 Tray Menu 都直接复用该缓存路径加载图标。

### Projection 渲染

Projection 的两种正文渲染器必须保持这些共同约束：

- 左侧和顶部正文起点一致。大字号 `MarkdownView` 的内容边距固定为 4 px，与 `QTextDocument.documentMargin()` 默认值一致；普通更新日志的 MarkdownView 保留渲染器默认边距。
- 纯文本和 Markdown 都使用 QFluentWidgets `SmoothScrollDelegate`，并在 viewport 上注册 `QScroller.TouchGesture`，支持鼠标滚轮和平滑单指触控。
- Projection 关闭文本选择，手指拖动用于滚动而不是选择文字。

AI Markdown 输入框的忙碌边框使用 2 px 渐变 QSS 边框。Qt 样式表会分别绘制边框各边，粗渐变边框在圆角处会出现斜向拼接；除非改为一次性自定义绘制完整圆角路径，否则不要再次只靠增加 QSS `border-width` 加粗。

## Module topology

### Desktop

| Module | Responsibility |
|---|---|
| `djcat.py` | 进程入口、工作目录、单实例应用、日志、配置加载和 MainWindow 创建 |
| `app/platform/` | Windows 单实例/IPC、唤起窗口、开机启动及 Qt 运行时适配 |
| `app/config/` | 配置 schema、常量和 App Data Directory |
| `app/common/` | 不依赖具体页面的 AI、更新下载、应用市场、主页动作和进程环境规则 |
| `app/view/windows/main_window.py` | 桌面组合根、导航、长期运行任务和 Client Update UI |
| `app/view/pages/` | 页面、临时展示窗口和页面级 worker 编排 |
| `app/view/components/` | 多页面复用的 Markdown、背景、滚动和设置卡片组件 |
| `pyqt_github_markdown/` | 项目内置 Markdown 渲染器；不承载 DJCat 业务规则 |

`app/common/application_version.py` 只包含架构和版本比较等纯函数，允许 MainWindow 在启动阶段导入。重量较大的 `app/common/application_store.py` 由 Setting 或 Application Store 页面首次加载时导入，避免图片缓存扫描破坏页面懒加载的启动收益。

### Server

| Module | Responsibility |
|---|---|
| `server/ai_markdown.py` | Machine Identity、Daily Quota、AI Markdown Conversion 和管理接口 |
| `server/app_store.py` | Application Catalog、下载重定向/计数和应用市场管理页面 |

服务端模块不能导入桌面 View；桌面端通过 HTTPS API 消费服务端结果。桌面配置中的 `DJCATAI_API_BASE_URL` 环境变量只改变 API 根地址，不改变业务所有权。

## App lifecycle

### Startup (`djcat.py`)

```text
set working directory
  → SingletonApplication (Windows single instance + IPC)
  → unlockQtAnimations (before any QWidget animation is created)
  → configure logging and clear stale Client Update files
  → qconfig.load(CONFIG_PATH, cfg)
  → MainWindow(isSilent)
      → HomePage eagerly
      → register Lazy Pages without constructing their real pages
      → create tray and long-lived timers/workers
  → bind activation request and aboutToQuit
  → Qt event loop
```

App Data Directory 必须在导入 `cfg` 和调用 `qconfig.load` 前由 `app/config/paths.py` 确定。第二个 Windows 实例只通知现有实例显示窗口，然后退出；它不创建 MainWindow。

`unlockQtAnimations()` 必须在 QApplication 创建之后、任何动画启动之前、GUI 主线程上调用。它只针对项目锁定的 Qt 运行时查找私有符号；找不到符号或动态库时记录警告并保留 Qt 默认 16 ms 间隔，不允许加载系统中另一份 Qt 来凑合。

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
MainWindow._shutdownResources()
  → stop navigation animation and timers
  → cancel Edge TTS and stop audio players
  → flush loaded Setting / Scheduled Task editors
  → shutdown HomePage and loaded Application Store page
  → cancel Client Update download and close InfoBars
  → optional Storage Migration connected after normal shutdown
  → QApplication exits and releases the single-instance lock
```

`_shutdownResources()` 必须幂等。Lazy Page 未加载时，关闭流程不能为了清理而创建它。

## Animation scheduling

PySide6 6.10 没有绑定 `QAnimationDriver`，DJCat 因此把 Qt 私有 `QUnifiedTimer::setTimingInterval()` 封装在 `app/platform/animation_timer.py`，将默认 16 ms Animation Tick 间隔改为 1 ms。1 ms 是避免零间隔忙循环的最小非零调度间隔；事件循环繁忙时，逾期 tick 会在 GUI 线程恢复后推进，不再额外固定等待 16 ms。

该适配有四条边界：

- 动画 duration 仍按真实经过时间计算，不能按 tick 次数累计时间。
- 不读取显示器刷新率，也不按 60/120/160 Hz 切换间隔；机器负载决定实际可处理的 tick 数。
- 不承诺 Presented Frame 数；DWM、VSync 和绘制耗时仍可限制屏幕实际帧率。
- Qt 版本或打包布局变化导致私有符号不可用时必须安全退回默认动画驱动；升级 PySide6 时需要在 Windows x64 与 ARM64 重新验证导出符号和端到端动画时长。

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

- 网络、文件复制、ZIP 解压和卸载不得阻塞 Qt 主线程。
- worker 在线程中工作，通过 Qt Signal 把结果送回页面；只有主线程更新 QWidget。
- 页面关闭时先设置 shutdown/cancel 状态，再等待有文件提交风险的线程；超时后也不能让回调访问已销毁控件。
- 可计算总字节数的下载使用确定进度；无法可靠估计的文件操作使用不确定进度，不伪造百分比。
- 新的私有 Qt/Windows API 必须封装、可失败、可回退，并有锁定版本的真实二进制验证。

### Comments

代码默认依靠清晰命名表达行为。注释只解释隐藏约束、平台差异或看似多余但不能删除的顺序，例如原子替换、触控手势和 Qt 动画时序；不写逐行复述代码的注释。

## Flagged ambiguities

- “全屏投送”过去容易被称为 Broadcast，但项目中的 Broadcast Task 是音频定时播报。已统一用 **Projection** 表示文字展示。
- “更新”可能指 DJCat 自身或市场 Application。已拆为 **Client Update** 与 **Application Update**。
- “安装版”可能被误解为 Installed Application。已定义 **Installed Mode** 专指 DJCat 的 App Data Directory 位置。
- “下载次数”并不证明 Package 已完整下载或安装。它是服务端去重后的下载重定向请求累计值。
- “懒加载页面”不等于只隐藏 QWidget。真实页面及其重量级依赖必须尚未构造；纯版本比较被拆到轻量模块，避免 MainWindow 提前初始化应用市场缓存。
- Application Store 的“全部”与“已安装”是两个操作上下文：即使存在 Application Update，“全部”卡片仍显示“打开”；“已安装”和详情页才显示“更新”。
- 主窗口右上角关闭曾被理解为退出。已消歧：**close** 只隐藏主窗口；**quit** 才清理资源并结束进程。
- “解除 Qt 60 帧限制”容易被理解为绕过 VSync 或保证某个 FPS。已消歧：本实现只把 **Animation Tick** 的默认 16 ms 间隔改为 1 ms，不控制 **Presented Frame**。
- “低配置机器按自身能力运行”不表示创建自适应刷新率策略。已消歧：所有机器使用同一最小非零 tick 间隔；事件循环繁忙时自然只能处理较少更新，不额外补跑积压帧。
- Application Store 的“全部应用 → 全部”分类固定每页最多展示 6 个 Application；“推荐”分类展示全部推荐项，不参与分页。

## Example dialogue

> **Dev:** “定时播报是不是把全屏投送安排到某个时间？”
> **Domain expert:** “不是。Projection 显示文字；Broadcast Task 到点播放 Audio Source。”

> **Dev:** “应用预设卡片和用户自定义卡片都可以执行动作，是同一种卡片吗？”
> **Domain expert:** “不是。Application Home Card 执行 Application Catalog 提供的受限 Application Action；Custom Home Card 执行用户在本机编排的 Action Sequence。”

> **Dev:** “托盘里的卡片是不是主页卡片的另一份副本？”
> **Domain expert:** “不是。Tray Card Shortcut 只引用现存 Home Card，沿用主页的顺序、标题、图标和点击行为。”

> **Dev:** “左键点托盘图标是不是总会打开主页？”
> **Domain expert:** “不一定。Tray Click Action 可将左键配置为打开 Tray Menu；右键始终打开 Tray Menu。”

> **Dev:** “把卡片放进托盘二级菜单后，它的排序是不是独立的？”
> **Domain expert:** “不是。Tray Menu 始终沿用主页排序；二级菜单只改变显示层级。”

> **Dev:** “机器码能不能当授权码，阻止别人调用 AI 接口？”
> **Domain expert:** “不能。Machine Code 只是匿名设备的可见别名，用于查找 Daily Quota，不承担认证。”

> **Dev:** “发现新版本后直接走应用市场更新就行吗？”
> **Domain expert:** “先说清是哪一种版本。Client Update 更新 DJCat；Application Update 更新市场里的某个 Application。”

> **Dev:** “应用有更新，‘全部’卡片也应该显示更新吗？”
> **Domain expert:** “不应该。‘全部’保持发现和打开语义；Application Update 只在‘已安装’和详情页提供。”

> **Dev:** “切换到 Portable Mode 后能不能马上让当前进程改用新目录？”
> **Domain expert:** “不能。当前进程的 App Data Directory 在启动时已经确定；正常关闭后迁移，下一次启动再选择新模式。”

> **Dev:** “设置页没打开，退出时要不要先创建它再保存？”
> **Domain expert:** “不要。未加载的 Lazy Page 没有待保存的页面草稿，关闭流程也不能因此破坏懒加载。”

> **Dev:** “动画间隔改成 1 ms，是不是软件就能显示 1000 FPS？”
> **Domain expert:** “不是。1 ms 只提高 Animation Tick 的调度密度；Presented Frame 仍由绘制耗时、DWM、VSync 和显示器决定。”
