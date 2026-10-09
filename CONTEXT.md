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

**Application Icon（软件图标）**:
DJCat 主窗口和启动页共用的软件图标。默认模式使用原有主 Logo，自定义模式使用一张本地图片替换。Tray Icon 默认跟随它。
_Avoid_: Tray Icon（只在跟随时才相同）、Home Card 图标、Application Store 中 Application 的图标

**Tray Icon（托盘图标）**:
系统托盘里代表 DJCat 的图标，取值只有两种："跟随软件图标"（默认）或"自定义"，自定义时换成另一张本地图片，不影响主窗口和启动页。Tray Menu 的"主页"入口跟着 Tray Icon 变：跟随时和 Application Icon 的规则一样（默认模式显示独立的猫图标，自定义模式显示那张图），Tray Icon 自定义时换成 Tray Icon 那张图。
_Avoid_: Application Icon、托盘图片

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
"全屏投送"产生的一次文字展示，由标题和正文组成，正文可使用纯文本或 Markdown。Projection 可全屏或窗口化显示，也可 Collapse 为 Floating Button。启用启动恢复后，程序退出时仍未关闭的 Projection 会在下一次启动时自动恢复。
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

**Display Window（展示窗口）**:
Projection、Exam Countdown 或 Fullscreen Clock 显示在屏幕上的那个窗口，可在全屏和窗口化之间切换；窗口化时是带阴影的圆角卡片。
_Avoid_: 全屏窗口（它也可以窗口化）、主窗口

**Collapse（收起）**:
Projection 的 Display Window 暂时让出屏幕、变成 Floating Button 的操作；按钮文字是"最小化"，但窗口不进任务栏。只有 Projection 能 Collapse。
_Avoid_: minimize、最小化（仅保留在按钮文字中）、隐藏

**Floating Button（悬浮按钮）**:
Projection Collapse 后浮在屏幕角落的主题色圆形按钮，可拖动；点按后 Display Window 回到 Collapse 前的全屏或窗口化。
_Avoid_: 恢复入口、恢复圆钮、悬浮球、mini window

**Window Transition（窗口过渡动画）**:
Display Window 在全屏、窗口化和 Floating Button 之间切换时，外形从起点连续变到终点的过渡；过渡期间画面是静止的。可在设置里整体关闭，关闭后直接跳到终点。
_Avoid_: 最大化动画（没有最大化）、缩放动画（圆角和内容也在变）、切页过渡（那是主窗口里的页面切换）

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
已由 Application Store 安装并可被 DJCat 识别的 Application。版本落后于 Application Catalog 中同 ID 的 Application 时形成 Application Update。只有版本变化才形成 Application Update；同一版本下名称、简介、图标、公告、Open Action 或 Application Preset 的变化只同步到本机记录，不重新下载 Package。
_Avoid_: downloaded application、Package

**Application Action**:
由 Application Catalog 提供、在 Application 边界内执行的受限动作。作为应用默认入口时称 Open Action；由 Application Preset 引用时称 Preset Action。
_Avoid_: Home Action、Shell action

**Application Launch**:
从 Application Store、Application Home Card 或对应的 Tray Card Shortcut 打开一个 Installed Application 或它的 Application Preset 时，对其 Open Action 或 Preset Action 的一次后台执行。同一 Application 同时至多有一次 Application Launch。启动新程序只确认进程已创建，不要求出现可见窗口；再次打开仍在运行的同一程序时才尝试唤起已有窗口。
_Avoid_: Application Update、install、等待程序窗口

**Application Preset**:
归属于一个 Application 的命名 Preset Action，由服务端维护标题、说明和顺序。用户将它固定到主页后才产生 Application Home Card。从详情页和从 Application Home Card 打开遵循同一规则：Application Catalog 已加载时，Catalog 不再列出的 Preset 失效，可直接执行的网址或协议以 Catalog 为准，程序及其他协议以本机 Installed Application 记录为准；Catalog 尚未加载时先用本机记录，其次用固定时保存的网址或协议。
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
每个 Machine Identity 每个北京时间自然日可用于 AI Markdown Conversion 的额度点数，于 0 点刷新。失败请求不最终占用额度。有 Quota Override 时取它，否则取 Default Daily Quota。
_Avoid_: request count（高峰时一次请求可能消耗两点）、token quota

**Default Daily Quota（默认额度）**:
管理员设定的、所有没有 Quota Override 的 Machine Identity 共用的 Daily Quota。改它不影响已有 Quota Override 的机器。
_Avoid_: 单机额度（旧的后台叫法，容易和 Quota Override 混淆）、全局额度

**Quota Override（专属额度）**:
管理员给单个 Machine Identity 长期指定的 Daily Quota，取值 0–10000，0 表示这台机器停用 AI Markdown Conversion。填多少就是多少，即使和 Default Daily Quota 相等也不跟着它变；只有"恢复默认"才删掉它。修改立即生效，只改上限，不动当天已用的点数；扣点规则（Peak Hours 双倍、节假日豁免）照旧。它跟着 Machine Identity 走：重装 Windows 后得到的新 Machine Identity 没有它。
_Avoid_: 自定义额度（Custom 指桌面用户自建的东西）、单机额度、额度总量

**Peak Hours**:
可由管理员启用的双倍额度时段，当前为北京时间 9:00–12:00 和 14:00–18:00。启用时每次转换扣 2 点，其余时段扣 1 点。管理员另开"节假日豁免"时，只有 **Working Day** 的这两个时段才加倍。
_Avoid_: rate limit window、busy status

**Working Day（工作日）**:
按国务院当年放假安排认定的上班日，与 DeepSeek 空闲时段的定义一致：法定节假日整段放假（含借来的工作日）不是工作日，调休补班的周末是工作日；安排没提到的日子才按周一至周五算。
_Avoid_: weekday（周几不等于是否上班）、holiday（只说了放假，漏了补班）

**Busy Glow（忙碌光晕）**:
一次 AI Markdown Conversion 进行期间，环绕输入框边缘的彩色光带。它只表示"正在进行且尚未出结果"，不表示完成度——转换耗时无法预估。AI Markdown 对话框和 Projection 编辑器的内联整理共用同一个 Busy Glow。
_Avoid_: 进度条／progress bar（它不表达百分比）、loading spinner、忙碌边框（它不是边框，会渗到框内外两侧）

**Custom Markdown Style**:
桌面端用户可选的本机偏好，用来微调 AI Markdown Conversion 的输出格式；与服务端基础规则冲突时以它为准。
_Avoid_: theme、CSS、System Prompt

**Conversion Log（整理记录）**:
一次成功的 AI Markdown Conversion 的完整输入、输出和元数据快照，存储在服务端供管理员审阅。审批后可提升为 Prompt Example。
_Avoid_: request log（那是额度和计费的元数据记录）、history、转化记录

**Prompt Template（提示词模板）**:
管理员在后台编辑的 AI Markdown Conversion 全局规则文字，服务端自带一份可随时恢复的默认值。发给模型的系统提示词依次由它、Prompt Example 和 Custom Markdown Style 拼成，它只是其中第一段。
_Avoid_: 全局系统提示词（容易误解成整份系统提示词）、提示词上半部分

**Prompt Example**:
纳入系统提示词的 few-shot 输入输出对。来源有两种：管理员从 Conversion Log 中选取并编辑后加入，或在后台直接编写；两者加入后没有区别。运行时按顺序动态拼接到 Prompt Template 之后，Prompt Template 本身不应再写示例。
_Avoid_: sample、template、system prompt（Prompt Example 是提示词的一部分，不是提示词本身）

### 更新

**Client Update**:
DJCat Pro 5 自身的新版本，通过专用更新信息和更新 ZIP 交付，DJCat 退出后由独立的更新器整目录替换程序目录。它独立于 Application Store，不使用 Application Catalog 或 Package。
_Avoid_: Application Update；不加限定地称 update

**Update Toast（更新通知卡）**:
一次 Client Update 下载从开始到完成或失败，主窗口右下角始终是同一张卡片：下载中显示进度且不可关闭，完成时提供立即更新或稍后，失败时提供重试。它只属于 Client Update；Application Update 的进度显示在 Application Store 的按钮上。
_Avoid_: 进度条（那只是卡片底边的一条线）、StateToolTip、ProgressToast（QFluentWidgets Pro 的组件名）

**Client Version**:
用户可见的 DJCat 版本号，唯一来源是 `app/common/config.py`。
_Avoid_: Python Distribution Version、把构建元数据中的 `+` 版本展示给用户

**KB Release**:
同一 Client Version 正式发布之后的修订发布，在版本号后加 `-kb` 和发布日期（如 `5.2.0-kb261007`）。它排在同号正式版之后、下一个版本号之前，Client Update 照常提示。
_Avoid_: 补丁版、预发布（kb 不是 pre，排序在正式版之后而不是之前）

**Release Category（发版分类）**:
一次 Client Version 发布在标题上的唯一笼统分类：功能更新、体验更新、稳定更新或性能更新，两类势均力敌时可写「体验与稳定更新」。它按 DJCat 用户在客户端里能感知到的变化来定；只随 Server Update 上线的管理后台和 AI 整理改动写进发版说明，但不决定分类。
_Avoid_: 具体名目（如"定时任务更新"）、按提交数量或服务端改动定分类

**Client Distribution**:
用户首次获取 DJCat 时下载的发布文件，分为安装程序（`Setup.exe`）和免安装压缩包（`.zip`）两种。它只描述文件形态，与存储模式无关：两种形态全新使用时都默认 Portable Mode。
_Avoid_: 安装版、便携版（与 Installed Mode、Portable Mode 混淆）；安装包（那是 Application 的 Package）

**Application Update**:
同一 Application 在 Application Catalog 中的版本高于 Installed Application 时形成的更新。Application Store 的"全部"分类保持发现和打开语义，Application Update 只在"已安装"和详情页提供。
_Avoid_: Client Update；不加限定地称 update

**Server Version（服务端版本）**:
整个服务端的版本号，与 Client Version 各自独立编号（例如客户端 5.2.0 时服务端为 1.4.8）。AI Markdown 接口、Application Catalog 接口和 Admin Console 同属一个服务端，共用这一个版本号。
_Avoid_: 后台版本号（不只是后台页面）、Client Version

**Server Update（服务端更新）**:
管理员在 Admin Console 中把服务端换成更新的 Server Version 的一次操作。换的是整个服务端，不影响任何已安装的 DJCat 或 Application。
_Avoid_: 后台更新、部署（部署指首次安装和 Nginx 配置）；Client Update、Application Update；不加限定地称 update

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

**Cache（缓存）**:
DJCat 在本机留下、清理后不影响任何设置或已安装内容的数据：Application Store 的图片和临时 Package，以及除正在写入那一份之外的日志。图片和 Package 清理后会在需要时重新下载，日志删掉就没有了。它属于整个 DJCat，不只属于 Application Store。
_Avoid_: 应用市场缓存（它不再只装 Application Store 的东西）；把 Custom Home Card 的图标当缓存（那是用户数据）

**Log（日志）**:
DJCat 运行时按天写下的诊断记录，以及更新器在程序目录留下的那份更新记录，都只保留最近 14 天。按天的日志属于 App Data Directory，Client Update 和 Storage Migration 之后仍在。用户可以随 Cache 一起清理，正在写入的那一份除外。
_Avoid_: 错误日志（设置里的入口叫法，它记录的不只是错误）

### 窗口

**Resize Band（缩放命中带）**:
可缩放窗口沿边缘的一圈区域，在其中按下并拖动会改变窗口大小。主窗口和窗口化的 Projection 各有一条；主窗口右上角的最小化、最大化、关闭三个按钮上没有 Resize Band，按下去一律是点按钮。
_Avoid_: 边框（窗口化时那条 1 px 灰线才是边框）、缩放像素、拖拽边

**Background Effect（窗口背景透明材质）**:
由 Windows 在主窗口背后合成的透明材质，可选 Acrylic、Mica、MicaAlt、Aero 或 None，切换后立即生效；未设置时 Win11 为 Mica、Win10 为 None。只作用于主窗口和画在主窗口上的蒙层弹窗；投送、考试倒计时和全屏时钟各自的背景设置以及 Tray Menu 的亚克力都不受它影响。
_Avoid_: 背景（投送、倒计时和时钟的背景设置）、卡片材质、透明度

### 设置

**Setting Section**:
设置页层级中的一个节点，由稳定 key、标题、图标和可选说明构成。顶层的"设置"是根 Section，只放通往子 Section 的导航行。其他有子 Section 的节点可以在导航行之外再放 Setting Card 和纯文字小节（如全屏投送设置的「背景」入口和下面的窗口、关闭行为卡片），但不放 Setting Preview。
_Avoid_: group（可折叠分组已退役）、页面（它不是导航页面，MainWindow 不感知它）

**Setting Route**:
从根到某个 Setting Section 的稳定 key 序列，如 `broadcast.background`。面包屑显示它，Setting Suggestion 指向它。
_Avoid_: path（与文件路径混淆）、breadcrumb（那是控件不是数据）

**Setting Card**:
Setting Section 中的一行设置项，通常绑定一个 `cfg` 配置项或一个动作按钮。部分 Setting Card 只在前置配置取特定值时可见。
_Avoid_: 设置项（泛指值本身）、Home Card

**Setting Preview**:
Setting Section 中目标界面按当前配置等比缩小后的样子，随所在 Section 的配置项变化立即重绘。它照真实的排布、尺寸和用户自己的数据（例如主页上实际存在的 Home Card）来画，而不是孤立地摆一张图片或一段文字。目标是主窗口时，宽高比跟着主窗口当前的宽高比实时变化。只显示状态，不接受输入。只放在叶子 Section 上，每个至多一个；不同叶子可以画同一个目标界面（横幅设置和外观都画主窗口），但同一条 Setting Route 上不重复。
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

> **Dev:** "后台点了更新，学生机上的 DJCat 也会跟着升级吗？"
> **Domain expert:** "不会。那是 Server Update，只换服务端，Server Version 从 1.4.8 往上走；DJCat 5.2.0 要等 Client Update。"

> **Dev:** "在设置里搜'背景颜色'，页面会只留下匹配的卡片吗？"
> **Domain expert:** "不会。设置搜索只弹 Setting Suggestion，点一条才跳到对应的 Setting Route，页面本身从不筛选。"

> **Dev:** "把主窗口的边框再调宽一点，手指好拖。"
> **Domain expert:** "你说的是 Resize Band，不是边框。可以加宽，但它在右上角三个按钮上始终让位，按钮上一律是点击。"
