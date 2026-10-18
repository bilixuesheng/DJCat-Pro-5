# 应用安装位置在运行中迁移，没有权限时用 icacls 给 Users 组授权

Installed Application 原来固定在 App Data Directory 下的 `Program`，路径在启动时就定死了。机房电脑的系统盘常带还原，空间也紧，所以老师需要把应用放到别的盘。现在 Application Install Location 可以在设置里更改，有三处做法和直觉不同：

1. Application Relocation 在 DJCat 运行中进行，进度显示在右下角的 Relocation Toast 上，`ApplicationStore` 在运行中切换根目录。它不像 Storage Migration 那样等到退出时才搬。
2. 迁移是全有或全无的。先把全部应用复制到新位置的临时文件夹（同一个盘直接改名），全部到位后才改配置，最后删旧文件。开始时在 `cfg` 里记一笔迁移记录（旧位置、新位置、是否已提交）：中途退出或断电时，下次启动按记录收尾到其中一边，然后删掉这笔记录。
3. DJCat 对新位置没有写入权限时，以管理员身份运行一次 Windows 自带的 `icacls`，给 Users 组（`S-1-5-32-545`）授"修改"权限并继承到下面所有内容。此后普通权限的 DJCat 就能在那里安装、更新和卸载。

## Considered Options

**退出时迁移，像 Storage Migration 那样**：Storage Migration 要搬的是 DJCat 自己开着的日志和配置，只能等退出。`Program` 里的文件只会被应用自己的进程占用，强制关掉这些进程就能搬，用不着让老师重启 DJCat、对着空白等待。

**一个一个应用迁移，失败的留在原处**：应用会被拆散在两个位置，而 DJCat 同一时间只认一个 Application Install Location。

**让 DJCat 自己以管理员身份再启动一份来授权**：DJCat 没有代码签名，UAC 会显示黄色的"未知发布者"，第二个实例还要绕过单实例检查。`icacls` 有微软签名，等它退出、看它的返回码就够了。

**只授权给当前用户**：标准用户在 UAC 弹窗里输入的是管理员账号，提权出来的进程以管理员身份运行，取到的"当前用户"是那个管理员，不是老师自己。再说机房电脑常有多个账号共用一份便携版配置，只授给一个账号，换个账号登录后应用就装不上、更新不了。

**只对空文件夹提权**：这样最安全，但没有采用，下面"后果"里写了它带来的影响。

## Consequences

- 选中的文件夹如果不是空的，里面已有的文件也会继承这条授权，本机所有普通账号都能修改它们。所以 `Windows`、`Program Files`、`ProgramData`、`Users` 这几个根目录一律不提权，驱动器根目录和网络位置根本不能选。
- 默认位置在配置里存空值，随 App Data Directory 走，也随 Storage Migration 搬动。自定义位置存绝对路径，Storage Migration 不碰它。`APP_DIR` 和 App Data Directory 里面都不能选：Client Update 会整个换掉 `APP_DIR`，清理 Cache 会整个清空 `AppStoreCache`。
- 启动时自定义位置不可用（U 盘拔了、盘符变了），不退回默认位置，也不重建文件夹。退回默认会让新装的应用和原来的应用分在两处。
- 迁移提交时，按 Storage Migration 的规则，把 `cfg` 里落在旧位置下面的绝对路径改写到新位置，比如 Custom Home Card 里"启动程序"的路径。应用自己记下的路径（它自己的配置、注册表、快捷方式），DJCat 改不了。
- 强制关闭的范围是"可执行文件位于该位置下面"的进程，迁移、卸载和 Application Update 用同一套判定。别的程序开着里面的文件（资源管理器开着这个文件夹、Word 打开了里面的文档）时，DJCat 不去关它们，迁移失败并退回，提示文件被占用。
