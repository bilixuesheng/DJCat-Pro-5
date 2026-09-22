# Default to Portable Mode for new installations

DJCat Pro 5 的目标用户环境（学校电教室）普遍使用冰点还原等系统还原软件，C 盘数据在每次重启后被恢复。旧版默认 Installed Mode 将配置存储在 C 盘用户目录，导致设置反复丢失。从此版本起，全新安装默认选择 Portable Mode，将数据保存在程序旁，配合非 C 盘安装即可保护用户数据。已有 User Data Directory 的升级用户自动保持 Installed Mode，无需迁移。

## Considered Options

- **保持 Installed Mode 为默认值**：符合 Windows 惯例，但在冰点还原环境下配置每次重启被清除，是用户投诉的主要来源。
- **自动将升级用户迁移到 Portable Mode**：统一所有用户的行为，但有数据丢失风险且强制改变用户已有的存储位置。
- **默认 Portable Mode，升级用户保持原模式（已选择）**：全新安装受益于便携存储，既有用户不受影响，可随时在设置中手动切换。

## Consequences

- 安装器默认安装路径从 `{autopf}` 改为 `D:\Users\<user>\AppData\Local\Programs\DJCat Pro`（D 盘不存在时回退），并在选路径页面提示冰点还原相关建议。
- 程序旁目录无写权限时（如 Program Files），静默回退到 Installed Mode 并显示一条 InfoBar 通知。
- `CONTEXT.md` 中 Portable Mode 的定义更新为"全新安装默认选择此模式"。
