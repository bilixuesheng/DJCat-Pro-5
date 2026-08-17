# DJCat Pro 5

面向 Windows 教室场景的桌面助手，提供全屏信息投送、考试倒计时、定时音频播报、定时关机和可编排的主页入口。配套服务为桌面端提供 AI Markdown 转换和应用市场目录。

## Language

### 主页

**Home Card**:
主页“常用功能”区域中一个用户可见的入口。按来源分为 Default Home Card、Custom Home Card 和 Application Home Card，三者共享排序，但来源和执行规则不同。
_Avoid_: shortcut、tile；不加限定地称 card

**Default Home Card**:
DJCat 自带的 Home Card，目前固定为“全屏投送”“考试倒计时”“定时播报”和“定时关机”。用户可以移除、恢复和排序，但不能改写它代表的功能。
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
DJCat 系统托盘图标提供的快捷操作集合。右键始终打开它；左键可配置为打开 Tray Menu 或显示主窗口。打开主窗口和退出程序始终可用，Broadcast Task 与 Shutdown Task 的总开关可分别隐藏；选中的 Tray Card Shortcut 位于任务总开关之后，按主页顺序显示或统一放入“主页卡片”二级菜单。根菜单和二级菜单都支持鼠标悬停、触控点击展开以及触控滚动。
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
DJCat Pro 5 自身的新版本，通过专用更新信息和 Windows 安装程序交付。它独立于 Application Store，不使用 Application Catalog 或 Package。
_Avoid_: Application Update；不加限定地称 update

**Application Update**:
同一 Application 在 Application Catalog 中的版本高于 Installed Application，或本地执行清单修订落后时形成的更新，用新 Package 替换该应用的本地安装。它不会升级 DJCat 客户端。
_Avoid_: Client Update；不加限定地称 update

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
