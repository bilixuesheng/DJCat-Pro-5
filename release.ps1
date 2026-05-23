<#
.SYNOPSIS
    交互式生成 git-cliff 日志，打标签，推送，并自动创建 GitHub Release。
.DESCRIPTION
    1. 询问新版本号（如 v5.0.0-pre.10）
    2. 询问是否为预发布版本
    3. 自动获取上一个 Git 标签（获取不到则手动输入）
    4. 使用 git cliff 生成两个版本间的 CHANGELOG 并插入到文件顶部
    5. 打上新标签，提交 CHANGELOG.md 变更
    6. 推送标签和当前分支到远程 origin
    7. 使用 gh CLI 创建 GitHub Release（如果可用）
#>

# ------------------------------ 前置检查 ------------------------------
if (-not (Get-Command "git-cliff" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 未找到 git-cliff，请先安装：cargo install git-cliff 或 scoop install git-cliff" -ForegroundColor Red
    exit 1
}
if (-not (git rev-parse --show-toplevel 2>$null)) {
    Write-Host "❌ 当前目录不是 Git 仓库，请 cd 到项目根目录再执行。" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "cliff.toml")) {
    Write-Host "📄 未找到 cliff.toml，正在生成默认配置..." -ForegroundColor Yellow
    git cliff --init
    Write-Host "✔ 已生成 cliff.toml，请检查并修改配置后重新运行脚本。" -ForegroundColor Green
    exit 0
}

# ------------------------------ 收集信息 ------------------------------
$newVersion = Read-Host "请输入新版本号（例如 v5.0.0-pre.10）"
if ([string]::IsNullOrWhiteSpace($newVersion)) {
    Write-Host "❌ 版本号不能为空" -ForegroundColor Red
    exit 1
}

$isPreReleaseInput = Read-Host "这是预发布版本吗？(y/N)"
$isPreRelease = ($isPreReleaseInput -eq 'y' -or $isPreReleaseInput -eq 'Y')
$preReleaseLabel = if ($isPreRelease) { "🔶 预发布" } else { "🔷 正式发布" }

# 自动获取上一个版本标签
$latestTag = (git tag --sort=-version:refname | Select-Object -First 1) -as [string]

if ([string]::IsNullOrWhiteSpace($latestTag)) {
    $prevVersion = Read-Host "仓库中未找到任何标签，请手动输入上一个版本号（例如 v5.0.0-pre.9）"
    if ([string]::IsNullOrWhiteSpace($prevVersion)) {
        Write-Host "❌ 上一个版本号不能为空" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "检测到上一个标签：$latestTag" -ForegroundColor Cyan
    $useAuto = Read-Host "按 Enter 使用此标签，或输入其他版本号来覆盖"
    if ([string]::IsNullOrWhiteSpace($useAuto)) {
        $prevVersion = $latestTag
    } else {
        $prevVersion = $useAuto
    }
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Magenta
Write-Host "  上一个版本: $prevVersion" -ForegroundColor Yellow
Write-Host "  新版本    : $newVersion  $preReleaseLabel" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Magenta
$confirm = Read-Host "确认开始生成并推送？(Y/n)"
if ($confirm -ne "" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "已取消。" -ForegroundColor Gray
    exit 0
}

# ------------------------------ 检查工作区 ------------------------------
$status = git status --porcelain
$stash = $false
if ($status) {
    Write-Host "⚠ 工作目录有未提交的更改：" -ForegroundColor Yellow
    git status --short
    $stashInput = Read-Host "是否自动 stash 后再继续？(y/N)"
    if ($stashInput -eq "y" -or $stashInput -eq "Y") {
        git stash push -m "auto-stash before release $newVersion"
        $stash = $true
        Write-Host "✔ 已暂存更改。" -ForegroundColor Green
    } else {
        Write-Host "❌ 请先提交或暂存更改后再运行脚本。" -ForegroundColor Red
        exit 1
    }
}

# ------------------------------ 生成日志 ------------------------------
Write-Host ""
Write-Host "🚀 正在生成 CHANGELOG（$prevVersion..HEAD）..." -ForegroundColor Cyan
$output = git cliff $prevVersion..HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ git cliff 执行失败：$output" -ForegroundColor Red
    if ($stash) { git stash pop }
    exit 1
}

# 插入到现有文件顶部
if (Test-Path "CHANGELOG.md") {
    $existing = Get-Content "CHANGELOG.md" -Raw
    $newContent = $output + "`n" + $existing
    Set-Content "CHANGELOG.md" -Value $newContent -NoNewline
    Write-Host "✔ 已将新日志插入到 CHANGELOG.md 顶部。" -ForegroundColor Green
} else {
    $output | Out-File "CHANGELOG.md" -Encoding utf8
    Write-Host "✔ 已创建 CHANGELOG.md。" -ForegroundColor Green
}

# ------------------------------ 提交变更并打标签 ------------------------------
Write-Host "📌 正在提交 CHANGELOG.md 变更..." -ForegroundColor Cyan
git add CHANGELOG.md
git commit -m "chore(release): update CHANGELOG for $newVersion" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ git commit 失败，请检查日志。" -ForegroundColor Red
    if ($stash) { git stash pop }
    exit 1
}

Write-Host "🏷 正在创建标签 $newVersion ..." -ForegroundColor Cyan
$tagMsg = if ($isPreRelease) { "Prerelease: $newVersion" } else { "Release: $newVersion" }
git tag -a $newVersion -m $tagMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 标签创建失败。" -ForegroundColor Red
    exit 1
}

# ------------------------------ 推送 ------------------------------
$remote = "origin"
Write-Host "🚀 正在推送标签和当前分支到 $remote ..." -ForegroundColor Cyan
git push $remote $newVersion
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 推送标签失败，请检查网络或权限。" -ForegroundColor Red
    exit 1
}
git push $remote HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠ 推送分支失败，但标签已推送。" -ForegroundColor Yellow
}

# ------------------------------ GitHub Release ------------------------------
Write-Host ""
Write-Host "🐙 准备创建 GitHub Release..." -ForegroundColor Cyan

# 检查 gh 是否可用
$ghAvailable = Get-Command "gh" -ErrorAction SilentlyContinue
if (-not $ghAvailable) {
    Write-Host "⚠ 未找到 GitHub CLI (gh)，跳过创建 Release。" -ForegroundColor Yellow
    Write-Host "  安装方法：winget install --id GitHub.cli  或  scoop install gh" -ForegroundColor Yellow
} else {
    # 检查 gh 登录状态
    $ghAuth = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "⚠ gh 未登录，跳过创建 Release。请先运行 'gh auth login'。" -ForegroundColor Yellow
    } else {
        # 使用刚生成的日志作为 Release Notes（仅截取新版本的区块）
        # 直接使用 $output 作为 body
        $releaseName = Read-Host "请输入 Release 标题（留空则使用版本号 $newVersion）"
        if ([string]::IsNullOrWhiteSpace($releaseName)) {
            $releaseName = $newVersion
        }

        # 将 CHANGELOG 内容写入临时文件，避免命令行转义问题
        $tempNotes = [System.IO.Path]::GetTempFileName()
        $output | Out-File $tempNotes -Encoding utf8

        $ghArgs = @(
            "release", "create", $newVersion,
            "--title", $releaseName,
            "--notes-file", $tempNotes
        )
        if ($isPreRelease) {
            $ghArgs += "--prerelease"
        }

        Write-Host "📝 正在创建 Release..." -ForegroundColor Cyan
        & gh $ghArgs
        $ghExit = $LASTEXITCODE

        # 清理临时文件
        Remove-Item $tempNotes -Force

        if ($ghExit -eq 0) {
            Write-Host "✔ GitHub Release 创建成功！" -ForegroundColor Green
        } else {
            Write-Host "❌ GitHub Release 创建失败，请检查输出。" -ForegroundColor Red
        }
    }
}

# ------------------------------ 恢复 stash ------------------------------
if ($stash) {
    Write-Host "🔄 正在恢复之前 stash 的更改..." -ForegroundColor Cyan
    git stash pop
}

Write-Host ""
Write-Host "✅ 发布流程完成！" -ForegroundColor Green
Write-Host "  - 新标签: $newVersion ($preReleaseLabel)" -ForegroundColor Green
Write-Host "  - CHANGELOG 已更新并推送" -ForegroundColor Green