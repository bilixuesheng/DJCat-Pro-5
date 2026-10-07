---
name: release
description: 发布 DJCat 客户端新版本。用户只给出版本号（「发布 5.2.1」「发版 5.2.0-kb261020」）时使用。
---

用户给出版本号，就直接把这一版发出去：不提问，不让用户确认草稿，合并也由你来做。版本号**原样使用**，不补位、不改写（`kb261007` 就是 `kb261007`）。只有版本号缺失、tag 已存在，或者上一个 tag 之后没有一个提交时才停下来问。

过了第 1 步就一路做到 Release 发出来，中途不提问、不请求确认，也不等用户回复：用户不会再回复。拿不准的地方一律按本 skill 的默认做法处理，只在最后的汇报里提一句。几个常见的拿不准：
- 分类：按第 4 步自己判断。
- 服务端改动有没有在线上点过 Server Update：查不到，照写摘要里那句。
- CI 红了：自己修复后重推；修不好就在 PR 上写明原因，不合并，在最后的汇报里说清楚。

## 步骤

1. **定版本。** `VERSION=<用户给的>`，`TAG=v$VERSION`。`git fetch --tags origin`，确认 `refs/tags/$TAG` 和 `.github/release-notes/$TAG.md` 都还不存在。上一版是 `git tag --sort=-creatordate | head -1`。
   完成标准：新 tag 空闲，上一版 tag 已确定。

2. **准备分支。** 在会话指定的开发分支上工作；该分支的 PR 已合并时，从 `origin/main` 重建它（`git checkout -B <branch> origin/main`）。

3. **读提交。** `git log --no-merges --format='%h %an | %s%n%b' <上一版>..origin/main`，逐条读标题和正文，判断每条用户能不能感知到：
   - 写：新功能、看得见的优化、用户碰到过的 bug 修复，包括已经随 Server Update 上线的管理后台和 AI 整理改动。
   - 并入相关条目或不写：`docs:`、`test:`、`chore:`、按评审意见整理之类的提交。
   完成标准：每个提交都已归入某一条，或明确判定不写。

4. **定分类。** 选一个 Release Category（见 `CONTEXT.md`）。用户点名了分类就照用；没点名时只看客户端用户能感知到的变化，只随 Server Update 上线的管理后台和 AI 整理改动照写进说明，但不参与判断：
   - `功能更新`：客户端多了新的功能或入口（新页面、新设置项、新任务类型、新的窗口模式）；
   - `体验更新`：以交互、动画、外观、文案打磨为主，也包括已有功能在某种情况下改成更合理的行为（如额度不足时「整理并投送」改为直接投送）；
   - `稳定更新`：以修复为主；`性能更新`：以速度、内存为主；
   - 两类势均力敌时可以写 `体验与稳定更新`。分类只写这种大类，不写「定时任务更新」这类具体名目。

5. **改版本号。** 改三处：
   - `app/common/config.py`：`VERSION = "$VERSION"`
   - `pyproject.toml` 的 `version`，以及 `uv.lock` 里 `name = "djcat-pro-5"` 下面那行 `version`：都写构建版本，即把第一个 `-` 换成 `+`（`5.2.0-kb261007` 写 `5.2.0+kb261007`；没有后缀时与 `VERSION` 相同）

6. **写发版说明** `.github/release-notes/$TAG.md`，严格套用下面的模板。格式照 Ghost Downloader 的 GitHub 发版日志，只写中文：
   - 条目写用户看得见的效果，不写实现细节；
   - 每条末尾按提交作者署名：`Claude` 署 `By @claude`，`XUESHENG` 署 `By @bilixuesheng`，两人都有就两个都写；
   - 某一节没有内容就整节删掉；
   - 有服务端改动时，摘要里加一句「管理后台与 AI 整理的改动已随服务端更新上线，无需更新客户端。」，没有就删掉这句。

   ```markdown
   ## [$VERSION] - YYYY-MM-DD - <分类>

   > [!IMPORTANT]
   > <一两句话概括本次更新>
   > 管理后台与 AI 整理的改动已随服务端更新上线，无需更新客户端。
   > 本版本仅提供 Windows x86_64 的安装程序和免安装压缩包。

   ### 功能更新 ✨

   - <条目> By @claude

   ### 功能优化 🔧

   - <条目> By @claude

   ### 问题修复 🐛

   - 修复<问题> By @claude

   ---

   ### 下载

   | 平台 | 格式 | 链接 |
   |------|------|------|
   | 🪟 Windows x86_64 | 安装程序（Setup.exe） | [下载](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/$TAG/DJCat-Pro-$TAG-Windows-x86_64-Setup.exe) · [SHA-256](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/$TAG/DJCat-Pro-$TAG-Windows-x86_64-Setup.exe.sha256) |
   | 🪟 Windows x86_64 | 免安装压缩包（ZIP） | [下载](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/$TAG/DJCat-Pro-$TAG-Windows-x86_64.zip) |

   ---

   **Full Changelog**: [<上一版>...$TAG](https://github.com/bilixuesheng/DJCat-Pro-5/compare/<上一版>...$TAG)

   ### Contributors

   - @bilixuesheng
   - @claude
   ```

   日期用今天（北京时间）；KB Release 用后缀里的日期（`kb261008` 写 `2026-10-08`），与版本号保持一致。`$TAG`、`$VERSION` 和 `<上一版>` 都写成实际值。

7. **本地验证。** 下面三项都要通过：
   - 按 `.github/workflows/main.yml` 的「Resolve release metadata」步骤，用同样的正则从 `config.py` 取出版本号，从发版说明取出第一个 H2，确认版本一致，并打印出 Release 标题 `$TAG · <分类>`。
   - `isUpdateAvailable(<上一版>, VERSION)` 为真。函数在 `app/common/application_version.py`。
   - `PYTHONPATH=. uv run --frozen pytest -q --noconftest tests/test_release_packaging.py` 和 `uv lock --check` 都通过。

8. **提交并开 PR。** 提交信息写 `release: 发布 $TAG <分类>`，推送后照 `.github/PULL_REQUEST_TEMPLATE.md` 开 PR，类型勾「文档」和「Build 或 CI 更新」。

9. **等 CI 绿了再合并。** 用 `subscribe_pr_activity` 订阅 PR，等 `test-windows` 和 `build-updater` 都成功，然后用 merge commit 合并。CI 红了就按 PR 的处理规则修复后重推，绝不在红的时候合并。

10. **跟到 Release 发出来。** 合并后 `main.yml` 的「Build and Release DJCat Pro」会自动运行，大约 50 分钟。用 `send_later` 约一次检查，跑完后确认三件事：Release `$TAG` 已发布、标题是 `$TAG · <分类>`、三个附件（Setup.exe、.sha256、.zip）都在。最后向用户简短汇报 Release 链接。
    完成标准：Release 已发布并核对过上面三项；流水线失败时找到原因并修复或汇报。
