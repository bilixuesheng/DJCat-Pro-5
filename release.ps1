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
    Write-Host "[ERROR] git-cliff not found. Install: cargo install git-cliff or scoop install git-cliff" -ForegroundColor Red
    exit 1
}
if (-not (git rev-parse --show-toplevel 2>$null)) {
    Write-Host "[ERROR] Not in a Git repository." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "cliff.toml")) {
    Write-Host "[INFO] cliff.toml not found, generating default config..." -ForegroundColor Yellow
    git cliff --init
    Write-Host "[OK] cliff.toml generated. Please review and modify if needed." -ForegroundColor Green
    exit 0
}

# ------------------------------ 收集信息 ------------------------------
$newVersion = Read-Host "Enter new version (e.g. v5.0.0-pre.10)"
if ([string]::IsNullOrWhiteSpace($newVersion)) {
    Write-Host "[ERROR] Version cannot be empty." -ForegroundColor Red
    exit 1
}

$isPreReleaseInput = Read-Host "Is this a pre-release? (y/N)"
$isPreRelease = ($isPreReleaseInput -eq 'y' -or $isPreReleaseInput -eq 'Y')
$preReleaseLabel = if ($isPreRelease) { "[Pre-release]" } else { "[Release]" }

# 自动获取上一个版本标签
$latestTag = (git tag --sort=-version:refname | Select-Object -First 1) -as [string]

if ([string]::IsNullOrWhiteSpace($latestTag)) {
    $prevVersion = Read-Host "No tags found. Enter previous version (e.g. v5.0.0-pre.9)"
    if ([string]::IsNullOrWhiteSpace($prevVersion)) {
        Write-Host "[ERROR] Previous version cannot be empty." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Detected previous tag: $latestTag" -ForegroundColor Cyan
    $useAuto = Read-Host "Press Enter to use this tag, or type another version to override"
    if ([string]::IsNullOrWhiteSpace($useAuto)) {
        $prevVersion = $latestTag
    } else {
        $prevVersion = $useAuto
    }
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Magenta
Write-Host "  Previous version: $prevVersion" -ForegroundColor Yellow
Write-Host "  New version     : $newVersion $preReleaseLabel" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Magenta
$confirm = Read-Host "Confirm to proceed? (Y/n)"
if ($confirm -ne "" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Cancelled." -ForegroundColor Gray
    exit 0
}

# ------------------------------ 检查工作区 ------------------------------
$status = git status --porcelain
$stash = $false
if ($status) {
    Write-Host "[WARN] Uncommitted changes:" -ForegroundColor Yellow
    git status --short
    $stashInput = Read-Host "Automatically stash changes? (y/N)"
    if ($stashInput -eq "y" -or $stashInput -eq "Y") {
        git stash push -m "auto-stash before release $newVersion"
        $stash = $true
        Write-Host "[OK] Changes stashed." -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Please commit or stash changes manually." -ForegroundColor Red
        exit 1
    }
}

# ------------------------------ 生成日志 ------------------------------
Write-Host ""
Write-Host "[STEP] Generating CHANGELOG ($prevVersion..HEAD)..." -ForegroundColor Cyan
$output = git cliff $prevVersion..HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git cliff failed: $output" -ForegroundColor Red
    if ($stash) { git stash pop }
    exit 1
}

# 插入到现有文件顶部
if (Test-Path "CHANGELOG.md") {
    $existing = Get-Content "CHANGELOG.md" -Raw
    $newContent = $output + "`n" + $existing
    Set-Content "CHANGELOG.md" -Value $newContent -NoNewline
    Write-Host "[OK] CHANGELOG.md updated (prepended)." -ForegroundColor Green
} else {
    $output | Out-File "CHANGELOG.md" -Encoding utf8
    Write-Host "[OK] CHANGELOG.md created." -ForegroundColor Green
}

# ------------------------------ 提交变更并打标签 ------------------------------
Write-Host "[STEP] Committing CHANGELOG.md..." -ForegroundColor Cyan
git add CHANGELOG.md
git commit -m "chore(release): update CHANGELOG for $newVersion" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git commit failed." -ForegroundColor Red
    if ($stash) { git stash pop }
    exit 1
}

Write-Host "[STEP] Creating tag $newVersion ..." -ForegroundColor Cyan
$tagMsg = if ($isPreRelease) { "Prerelease: $newVersion" } else { "Release: $newVersion" }
git tag -a $newVersion -m $tagMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Tag creation failed." -ForegroundColor Red
    exit 1
}

# ------------------------------ 推送 ------------------------------
$remote = "origin"
Write-Host "[STEP] Pushing tag and branch to $remote ..." -ForegroundColor Cyan
git push $remote $newVersion
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to push tag." -ForegroundColor Red
    exit 1
}
git push $remote HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Branch push failed, but tag was pushed." -ForegroundColor Yellow
}

# ------------------------------ GitHub Release ------------------------------
Write-Host ""
Write-Host "[STEP] Creating GitHub Release..." -ForegroundColor Cyan

$ghAvailable = Get-Command "gh" -ErrorAction SilentlyContinue
if (-not $ghAvailable) {
    Write-Host "[WARN] GitHub CLI (gh) not found. Skipping Release creation." -ForegroundColor Yellow
    Write-Host "       Install: winget install --id GitHub.cli  or  scoop install gh" -ForegroundColor Yellow
} else {
    $ghAuth = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] gh not authenticated. Run 'gh auth login' first." -ForegroundColor Yellow
    } else {
        $releaseName = Read-Host "Enter Release title (leave empty to use version $newVersion)"
        if ([string]::IsNullOrWhiteSpace($releaseName)) {
            $releaseName = $newVersion
        }

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

        Write-Host "[INFO] Creating release..." -ForegroundColor Cyan
        & gh $ghArgs
        $ghExit = $LASTEXITCODE

        Remove-Item $tempNotes -Force

        if ($ghExit -eq 0) {
            Write-Host "[OK] GitHub Release created." -ForegroundColor Green
        } else {
            Write-Host "[ERROR] GitHub Release creation failed." -ForegroundColor Red
        }
    }
}

# ------------------------------ 恢复 stash ------------------------------
if ($stash) {
    Write-Host "[STEP] Restoring stashed changes..." -ForegroundColor Cyan
    git stash pop
}

Write-Host ""
Write-Host "[DONE] Release process completed!" -ForegroundColor Green
Write-Host "  - New tag: $newVersion $preReleaseLabel" -ForegroundColor Green
Write-Host "  - CHANGELOG updated and pushed" -ForegroundColor Green