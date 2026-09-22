# DJCat Pro 5

面向 Windows 教室场景的桌面助手，提供全屏信息投送、考试倒计时、定时音频播报、按时间或软件行为触发的自动任务、定时关机和可编排的主页入口。配套服务为桌面端提供 AI Markdown 转换和应用市场目录。

## Language

### 主页

**Home Card**:
主页"常用功能"区域中一个用户可见的入口。按来源分为 Default Home Card、Custom Home Card 和 Application Home Card，三者共享排序，但来源和执行规则不同。
_Avoid_: shortcut、tile；不加限定地称 card

**Default Home Card**:
DJCat 自带的 Home Card，目前固定为"全屏投送""考试倒计时""全屏时钟""定时播报""自动任务"和"定时关机"。用户可以移除、恢复和排序，但不能改写它代表的功能。
_Avoid_: built-in app、system card

**Custom Home Card**:
用户在本机创建的 Home Card，包含标题、说明、图标和一个有序 Action Sequence。它不归属于 Application Store 中的 Application。
_Avoid_: Application Home Card、Application Preset

**Home Action**:
Custom Home Card 中的一个本地动作，类型为启动程序、执行 Shell、打开网页、打开本地路径或延时。程序和 Shell 动作可选择是否等待进程结束。
_Avoid_: Application Action、step、command（仅 Shell 类型是命令）

**Action Sequence**:
一次点击 Custom Home Card 后按当前顺序处理的 Home Action 集合。
_Avoid_: workflow、macro

### 系统托盘

**Application Icon**:
DJCat 主窗口、启动页和系统托盘共享的软件图标。默认模式保留原有主 Logo，Tray Menu 的"主页"入口继续使用独立的猫图标；自定义模式使用同一张本地图片替换这些位置。
_Avoid_: Home Card 图标、Application Store 中 Application 的图标

**Tray Menu**:
DJCat 系统托盘图标提供的快捷操作集合。右键始终打开它；左键可配置为打开 Tray Menu 或显示主窗口。Tray Menu 不拥有 Home Card，只根据主页快照重建菜单。
_Avoid_: context menu、右键菜单（它不只可由右键打开）

**Tray Click Action**:
用户左键单击系统托盘图标时的行为，取值为显示主窗口或打开 Tray Menu；右键不受它影响。
_Avoid_: left-click preference、mouse mode

**Tray Card Shortcut**:
Tray Menu 中对现存 Home Card 的引用，复用源卡片的标题、图标和点击行为。源 Home Card 被移除、删除或取消固定后，对应 Tray Card Shortcut 同步消失。
_Avoid_: Tray Home Card、复制卡片、独立托盘动作

### 课堂展示

**Projection**:
"全屏投送"产生的一次文字展示，由标题和正文组成，正文可使用纯文本或 Markdown。Projection 可全屏或窗口化显示，也可收起为恢复入口。启用启动恢复后，程序退出时仍未关闭的 Projection 会在下一次启动时自动恢复。
_Avoid_: Broadcast（项目中 Broadcast Task 指音频定时播报，不是文字展示）、投屏（不传输屏幕或视频）、presentation

**Projection Snapshot**:
最近一次已经开始的 Projection 的本地快照，保存标题、正文、Markdown 模式和是否仍在投送。关闭投送后保留内容用于手动导入，但不再参与下次启动恢复。
_Avoid_: Projection、editor draft、template

**Exam Countdown**:
"考试倒计时"产生的一次临时计时，具有初始时长、剩余时长、倒计时标题、结束时标题和语音提醒开关。关闭后不保存进度。
_Avoid_: timer、Scheduled Task

**Fullscreen Clock**:
"全屏时钟"显示当前系统时间，默认全屏展示，也可配置为固定大小的窗口。关闭后不保存状态。
_Avoid_: Exam Countdown、timer、Scheduled Task

### 定时与自动任务

**Scheduled Task**:
按对应 Task Master Switch、独立启用状态、星期和精确时间反复匹配的本地规则。Broadcast Task、使用固定时间的 Home Card Task 和 Shutdown Task 属于 Scheduled Task；软件行为触发的 Home Card Task 不参与定时匹配。
_Avoid_: alarm、job；不加限定地称 task

**Task Master Switch**:
Broadcast Task、Home Card Task 和 Shutdown Task 各自独立的持久化总开关。关闭时保留每条任务原有的启用状态；重新开启后不补执行关闭期间错过的任务。
_Avoid_: 批量启用、批量关闭、改写每条任务的 enabled 状态

**Broadcast Task**:
"定时播报"中的 Scheduled Task，在匹配时播放指定 Audio Source，并带有独立的重复次数和音量。它是音频播放，不是 Projection。
_Avoid_: Projection、全屏投送、Broadcast Window

**Audio Source**:
Broadcast Task 要播放的内容来源，分为内置报时或铃声、系统 TTS、在线 Edge TTS 和本地音频。
_Avoid_: Broadcast Type、media type

**Home Card Task**:
"自动任务"中的本地自动化规则，可按固定时间或 Application Lifecycle Event 触发。它可以引用现存 Home Card、关闭正在运行的 Default Home Card，或直接拥有一个 Action Sequence。UI 名称"自动任务"不等同于所有 Scheduled Task。
_Avoid_: Broadcast Task、Custom Home Card、复制卡片

**Application Lifecycle Event**:
Home Card Task 可选择的软件行为，当前包括每次启动、开机静默启动和从 Tray Menu 退出。关闭主窗口、更新安装退出或其他非 Tray Menu 退出不触发退出事件。
_Avoid_: Scheduled Task、操作系统关机、主窗口关闭

**Shutdown Task**:
"定时关机"中的 Scheduled Task，在匹配时直接关闭计算机或先进入 Shutdown Prompt。"本次不关机"只跳过当前触发，不会禁用或删除任务。
_Avoid_: shutdown timer、power plan

**Shutdown Prompt**:
Shutdown Task 可选的全屏确认过程，提供立即关机、延后 1 分钟再次提醒，以及可选的跳过本次。若用户在等待时间内没有操作，则自动关机。
_Avoid_: notification、dialog（它覆盖所有屏幕并参与关机决策）

### 应用市场

**Application Store**:
DJCat 内用于发现、安装、更新、打开和卸载 Application 的用户功能。它消费 Application Catalog，但不负责 DJCat 自身的 Client Update。
_Avoid_: Application Catalog、应用下载页（仅是界面名称）

**Application Catalog**:
服务端发布给桌面端的有序目录快照，包含 Application、可用架构和 Advertisement。它描述远端可获得的内容，不代表本机已经安装的内容。
_Avoid_: Application Store、Installed Application、manifest

**Application**:
Application Catalog 中一个可下载产品，拥有稳定 ID、名称、版本、安装目录、按架构区分的 Package，以及可选的 Application Action 和 Application Preset。
_Avoid_: 软件、程序（仅保留在既有 UI 文案中）、package

**Package**:
一个 Application 面向某一客户端架构发布的 ZIP 安装包；当前架构为 x86_64 或 arm64。Package 带有 SHA-256 完整性校验值。
_Avoid_: Application、Client Installer、binary

**Installed Application**:
已由 Application Store 安装并可被 DJCat 识别的 Application。版本落后于 Application Catalog 中同 ID 的 Application 时形成 Application Update。
_Avoid_: downloaded application、Package

**Application Action**:
由 Application Catalog 提供、在 Application 边界内执行的受限动作。作为应用默认入口时称 Open Action；由 Application Preset 引用时称 Preset Action。
_Avoid_: Home Action、Shell action

**Application Launch**:
从 Application Store 打开一个 Installed Application 时，对其 Open Action 的一次后台执行。启动新程序只确认进程已创建，不要求出现可见窗口；再次打开仍在运行的同一程序时才尝试唤起已有窗口。
_Avoid_: Application Update、install、等待程序窗口

**Application Preset**:
归属于一个 Application 的命名 Preset Action，由服务端维护标题、说明和顺序。用户将它固定到主页后才产生 Application Home Card。
_Avoid_: Custom Home Card、template、default setting

**Application Home Card**:
从 Application Store 固定到主页、并归属于一个 Installed Application 的 Home Card。它执行该 Application 的 Open Action 或某个 Preset Action，所属应用未安装时不可用。
_Avoid_: Custom Home Card；不加限定地称 Preset Card

**Recommendation**:
Application Catalog 中对现有 Application 的推荐标记和独立排序。它不是 Application 的副本。
_Avoid_: featured copy、Advertisement

**Advertisement**:
Application Catalog 中独立排序的推广位，展示标题、说明和图片，并可指向一个 Application、外部 HTTPS 网页或不提供按钮。
_Avoid_: Recommendation、Application

### 管理后台

**Admin Console**:
服务端的浏览器管理界面，负责 AI Markdown 配置、Machine Identity 查询和 Application Catalog 维护。
_Avoid_: Application Store、桌面设置页

**Catalog Order**:
Admin Console 中按稳定 ID 持久化的目录顺序。Application、Recommendation、Advertisement 各有独立顺序；Application Preset 的顺序只在所属 Application 内有效。它不改变用户本机的 Home Card 排序。
_Avoid_: Home Card order、全局应用排序

### AI Markdown

**AI Markdown Conversion**:
将作业清单或其他纯文本整理成适合 Projection 展示的 Markdown 的一次请求。
_Avoid_: chat、generation、Projection

**Machine Identity**:
用于把 AI Markdown 使用量稳定归到同一台设备的匿名身份。它只服务于额度统计，不是账号或许可证。
_Avoid_: account、license、raw hardware ID

**Machine Code**:
服务器为 Machine Identity 分配的用户可见别名，格式为 `DJ-` 加六位起的数字。便于用户和管理员识别额度记录，不具备认证或授权能力。
_Avoid_: Machine Identity、activation code、license key

**Daily Quota**:
每个 Machine Identity 每个北京时间自然日可用于 AI Markdown Conversion 的额度点数，于 0 点刷新。失败请求不最终占用额度。
_Avoid_: request count（高峰时一次请求可能消耗两点）、token quota

**Peak Hours**:
可由管理员启用的双倍额度时段，当前为北京时间 9:00–12:00 和 14:00–18:00。启用时每次转换扣 2 点，其余时段扣 1 点。
_Avoid_: rate limit window、busy status

**Busy Glow（忙碌光晕）**:
一次 AI Markdown Conversion 进行期间，环绕输入框边缘的彩色光带。它只表示"正在进行且尚未出结果"，不表示完成度——转换耗时无法预估。AI Markdown 对话框和 Projection 编辑器的内联整理共用同一个 Busy Glow。
_Avoid_: 进度条／progress bar（它不表达百分比）、loading spinner、忙碌边框（它不是边框，会渗到框内外两侧）

**Custom Markdown Style**:
桌面端用户可选的本机偏好，用来微调 AI Markdown Conversion 的输出格式；与服务端基础规则冲突时以它为准。
_Avoid_: theme、CSS、System Prompt

**Conversion Log（整理记录）**:
一次成功的 AI Markdown Conversion 的完整输入、输出和元数据快照，存储在服务端供管理员审阅。审批后可提升为 Prompt Example。
_Avoid_: request log（那是额度和计费的元数据记录）、history、转化记录

**Prompt Example**:
已审批并纳入系统提示词的 few-shot 输入输出对。管理员从 Conversion Log 中选取并编辑后加入；运行时按顺序动态拼接到提示词模板中。
_Avoid_: sample、template、system prompt（Prompt Example 是提示词的一部分，不是提示词本身）

### 更新

**Client Update**:
DJCat Pro 5 自身的新版本，通过专用更新信息和 Windows 安装程序交付。它独立于 Application Store，不使用 Application Catalog 或 Package。
_Avoid_: Application Update；不加限定地称 update

**Client Version**:
用户可见的 DJCat 版本号，唯一来源是 `app/common/config.py`。
_Avoid_: Python Distribution Version、把构建元数据中的 `+` 版本展示给用户

**Application Update**:
同一 Application 在 Application Catalog 中的版本高于 Installed Application 时形成的更新。Application Store 的"全部"分类保持发现和打开语义，Application Update 只在"已安装"和详情页提供。
_Avoid_: Client Update；不加限定地称 update

**Application Download Count**:
服务端记录的 Application 下载请求累计值。不证明 Package 已完整下载或安装；数值来自 Application Catalog，不由客户端本地推算。
_Avoid_: 本机安装次数、当前用户下载次数、完成安装次数

### 配置存储

**App Data Directory**:
DJCat 所有可迁移数据的根目录。进程启动时只确定一次，运行期间不切换。
_Avoid_: APP_DIR（程序文件所在目录）、只把它称为配置目录

**Installed Mode**:
App Data Directory 位于系统用户数据目录的存储模式。这里的 Installed 指 DJCat 自身的存储模式，不是 Installed Application。
_Avoid_: Application 安装状态、用户模式

**Portable Mode**:
App Data Directory 位于程序旁 `DJCatPro/` 的存储模式。全新安装默认选择此模式；已有 User Data Directory 时保持 Installed Mode。
_Avoid_: 便携 ZIP 的文件格式、Application 的安装目录

**Storage Migration**:
切换 Installed Mode 与 Portable Mode 时，复制整个 App Data Directory 并改写配置中的绝对路径。迁移发生在进程退出阶段，运行中不切换路径。
_Avoid_: 只复制 `UserConfig.json`、运行中热切换路径

### 设置

**Setting Section**:
设置页层级中的一个节点，由稳定 key、标题、图标和可选说明构成，含若干 Setting Card、纯文字小节和可选 Setting Preview。顶层的"设置"是根 Section。
_Avoid_: group（可折叠分组已退役）、页面（它不是导航页面，MainWindow 不感知它）

**Setting Route**:
从根到某个 Setting Section 的稳定 key 序列，如 `broadcast.background`。面包屑显示它，Setting Suggestion 指向它。
_Avoid_: path（与文件路径混淆）、breadcrumb（那是控件不是数据）

**Setting Card**:
Setting Section 中的一行设置项，通常绑定一个 `cfg` 配置项或一个动作按钮。部分 Setting Card 只在前置配置取特定值时可见。
_Avoid_: 设置项（泛指值本身）、Home Card

**Setting Preview**:
Setting Section 中按当前配置实时渲染的示意图，随所在 Section 的配置项变化立即重绘。它复刻目标界面的真实排布，而不是孤立地摆一张图片或一段文字。只显示状态，不接受输入。
_Avoid_: 缩略图、示意图（静态图片）、截图

**Setting Suggestion**:
搜索框输入时弹出的一条建议，指向某个 Setting Card 及其所属 Setting Route。只在有输入时存在，不持久化，也不改变页面内容。
_Avoid_: 搜索结果（设置页不再有结果列表）、筛选项

## Example dialogue

> **Dev:** "定时播报是不是把全屏投送安排到某个时间？"
> **Domain expert:** "不是。Projection 显示文字；Broadcast Task 到点播放 Audio Source。"

> **Dev:** "关闭主窗口时，会不会触发'电教猫关闭时'的自动任务？"
> **Domain expert:** "不会。关闭主窗口只是隐藏；该 Application Lifecycle Event 只由 Tray Menu 的退出程序触发。"

> **Dev:** "发现新版本后直接走应用市场更新就行吗？"
> **Domain expert:** "先说清是哪一种版本。Client Update 更新 DJCat；Application Update 更新市场里的某个 Application。"

> **Dev:** "在设置里搜'背景颜色'，页面会只留下匹配的卡片吗？"
> **Domain expert:** "不会。设置搜索只弹 Setting Suggestion，点一条才跳到对应的 Setting Route，页面本身从不筛选。"
