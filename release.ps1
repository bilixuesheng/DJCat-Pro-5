<#
.SYNOPSIS
    交互式生成 git-cliff 日志，打标签，并推送到远程。
.DESCRIPTION
    1. 询问新版本号（如 v5.0.0-pre.10）
    2. 自动获取上一个 Git 标签（获取不到则手动输入）
    3. 使用 git cliff 生成两个版本间的 CHANGELOG 并插入到文件顶部
    4. 打上新标签，提交 CHANGELOG.md 变更
    5. 推送标签和当前分支到远程 origin
#>

# ------------------------------ 前置检查 ------------------------------
# 1. git-cliff 可用
if (-not (Get-Command "git-cliff" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 未找到 git-cliff，请先安装：cargo install git-cliff 或 scoop install git-cliff" -ForegroundColor Red
    exit 1
}

# 2. 在 Git 仓库内
if (-not (git rev-parse --show-toplevel 2>$null)) {
    Write-Host "❌ 当前目录不是 Git 仓库，请 cd 到项目根目录再执行。" -ForegroundColor Red
    exit 1
}

# 3. 检查 cliff.toml
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

# 自动获取上一个版本标签（按版本排序取第一个）
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
Write-Host "  新版本    : $newVersion" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Magenta
$confirm = Read-Host "确认开始生成并推送？(Y/n)"
if ($confirm -ne "" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "已取消。" -ForegroundColor Gray
    exit 0
}

# ------------------------------ 检查工作区 ------------------------------
$status = git status --porcelain
if ($status) {
    Write-Host "⚠ 工作目录有未提交的更改：" -ForegroundColor Yellow
    git status --short
    $stash = Read-Host "是否自动 stash 后再继续？(y/N)"
    if ($stash -eq "y" -or $stash -eq "Y") {
        git stash push -m "auto-stash before release $newVersion"
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
    # 如果有 stash，恢复
    if ($stash -eq "y" -or $stash -eq "Y") { git stash pop }
    exit 1
}

# 将新生成的日志插入到现有 CHANGELOG.md 顶部（如果文件不存在则创建）
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
    # 手动恢复 stash
    if ($stash -eq "y" -or $stash -eq "Y") { git stash pop }
    exit 1
}

Write-Host "🏷 正在创建标签 $newVersion ..." -ForegroundColor Cyan
git tag $newVersion
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

# ------------------------------ 恢复 stash ------------------------------
if ($stash -eq "y" -or $stash -eq "Y") {
    Write-Host "🔄 正在恢复之前 stash 的更改..." -ForegroundColor Cyan
    git stash pop
}

Write-Host ""
Write-Host "✅ 发布流程完成！" -ForegroundColor Green
Write-Host "  - 新标签: $newVersion" -ForegroundColor Green
Write-Host "  - CHANGELOG 已更新并推送" -ForegroundColor Green