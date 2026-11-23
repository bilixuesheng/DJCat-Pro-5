<#
.SYNOPSIS
    ClassIsland 一键修复工具 v2.0（绕过希沃窗口拦截）
.DESCRIPTION
    做两件事：
      1) 安装 ClassIslandHide 插件（随机进程名/窗口标题，避免被弹窗拦截工具识别）
      2) 修改 ClassIsland.Desktop.exe 的「产品名」（ClassIsland -> Classlsland），
         让希沃的窗口拦截规则（按产品名匹配）不再命中

    v2.0 相比旧版：
      - 自动搜索安装位置（运行中的进程 / 注册表 / 常见目录），搜不到才让你输入
      - 全程大白话提示，直接回车就是默认选项
      - 自动申请管理员权限（弹窗点「是」即可）
      - 适配 Windows 10 / 11（Windows PowerShell 5.1）

    用法：
      - 直接双击 修复ClassIsland.cmd（推荐，全自动）
      - 也可以把 ClassIsland 文件夹拖到 cmd 上
      - 运行 还原ClassIsland.cmd 可恢复原 exe 并卸载插件
.PARAMETER Path
    ClassIsland 安装路径（文件夹或 exe 均可）。留空则自动搜索，搜不到再交互输入。
.PARAMETER Restore
    还原模式：恢复备份的 exe，并卸载 ClassIslandHide 插件。
.PARAMETER Replacement
    新的产品名（默认 Classlsland，必须与原产品名 ClassIsland 等长）。
.PARAMETER SkipPlugin
    不安装插件，只改产品名。
.PARAMETER SkipKill
    如果 ClassIsland 正在运行，不自动结束（可能因文件占用而失败）。
.PARAMETER SkipVerify
    改完后不自动启动应用做验证。
.PARAMETER Elevated
    内部使用：标记本进程是「提权后重新启动」的实例，不要再次提权，并在结束时暂停。
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Path,
    [switch]$Restore,
    [string]$Replacement = 'Classlsland',
    [switch]$SkipPlugin,
    [switch]$SkipKill,
    [switch]$SkipVerify,
    [switch]$Elevated,
    [string]$PluginPackage = ''
)

$ToolVersion = '2.0'

$ErrorActionPreference = 'Stop'
# 统一成 UTF-8，避免中文乱码（提权后的新窗口不是经 cmd 启动的，必须自己设一遍）
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$OldProductName = 'ClassIsland'
$PluginId       = 'dev.hellowrc.classIslandHide'
$PluginMd5      = 'B86B7D47B6DD9FD00E260EBE5AFEDA66'
$PluginAssetId  = 399703343   # HelloWRC/ClassIslandHide release 2.0.0.1

function Write-Section([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Write-Ok([string]$Text)      { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text)   { Write-Host "  [!!] $Text" -ForegroundColor Yellow }
function Write-Err2([string]$Text)    { Write-Host "  [XX] $Text" -ForegroundColor Red }

# 出了意外错误时也别让窗口一闪而过（尤其是提权后的新窗口）
trap {
    try { Write-Err2 $_.Exception.Message } catch { Write-Host $_ }
    if ($Elevated) { Write-Host ""; Read-Host "出错了，按一下回车键关闭这个窗口" | Out-Null }
    exit 1
}

# 结束脚本：提权后的窗口会自己暂停，避免一闪而过
function Done([int]$Code = 0) {
    if ($Elevated) {
        Write-Host ""
        Read-Host "全部结束啦，按一下回车键就可以关掉这个窗口" | Out-Null
    }
    exit $Code
}

# ---------------------------------------------------------------- 傻瓜式问答
function Ask-YesNo([string]$Question, [bool]$DefaultYes = $true) {
    if ($DefaultYes) { $hint = '（想好了直接按回车=好；不想就输入 n 再按回车）' }
    else             { $hint = '（想好了直接按回车=不要；要的话输入 y 再按回车）' }
    while ($true) {
        $a = (Read-Host "$Question $hint").Trim()
        if ($a -eq '') { return $DefaultYes }
        if ($a -match '^(y|yes|是|1|好|要|行|对|可以|继续)$') { return $true }
        if ($a -match '^(n|no|否|0|不|别|取消)$')            { return $false }
        Write-Host '  没看懂你输入的内容～ 想选「好」就直接按回车，想选「不要」就输入 n 再按回车。' -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- 工具函数
function Get-HuorongBlockCount {
    $ini = Join-Path $env:APPDATA 'Seewo\SeewoAbility\window_block\window_block.ini'
    if (Test-Path -LiteralPath $ini) {
        $t = Get-Content -LiteralPath $ini -Raw -ErrorAction SilentlyContinue
        if ($t -match 'blockcount\s*=\s*(\d+)') { return [int]$Matches[1] }
    }
    return $null
}

function Get-RunningFromDir([string]$Dir) {
    $list = @()
    foreach ($p in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ($p.ExecutablePath -and $p.ExecutablePath.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase)) {
            $list += $p
        }
    }
    return $list
}

function Stop-RunningFromDir([string]$Dir) {
    $procs = Get-RunningFromDir -Dir $Dir
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Ok "已关闭进程 $($p.ProcessId) $($p.Name)" }
        catch { Write-Warn2 "没能关闭进程 $($p.ProcessId)：$($_.Exception.Message)" }
    }
    Start-Sleep -Milliseconds 1200
}

function Set-ProductNameInExe([string]$ExePath, [string]$Old, [string]$New) {
    if ($Old.Length -ne $New.Length) { throw "替换字符串长度必须与原名相同（$Old=$($Old.Length) 字符，$New=$($New.Length) 字符）" }
    $bytes = [IO.File]::ReadAllBytes($ExePath)
    # 整个文件按 UTF-16 解码后查找（Unicode 是定长编码，字符位置 * 2 = 字节偏移）
    $text  = [Text.Encoding]::Unicode.GetString($bytes)
    $newB  = [Text.Encoding]::Unicode.GetBytes($New)

    # 先收集所有出现位置，并区分「版本资源里的字段值」和其它位置
    $versionFields = New-Object System.Collections.Generic.List[int]
    $others        = New-Object System.Collections.Generic.List[int]
    $start = 0
    while ($true) {
        $idx = $text.IndexOf($Old, $start, [StringComparison]::Ordinal)
        if ($idx -lt 0) { break }
        $start = $idx + 1
        $preStart = [Math]::Max(0, $idx - 40)
        $pre = $text.Substring($preStart, $idx - $preStart)
        $next = ''
        if ($idx + $Old.Length + 1 -lt $text.Length) { $next = $text.Substring($idx + $Old.Length, 2) }

        if ($pre.IndexOf('ProductName', [StringComparison]::Ordinal) -ge 0 -or
            $pre.IndexOf('FileDescription', [StringComparison]::Ordinal) -ge 0) {
            $versionFields.Add($idx)
        }
        elseif ($next -eq '.D') {
            # ClassIsland.Desktop.dll 之类的内部文件名，跳过
        }
        elseif ($pre -match 'github\.com/|\.exe by |by github') {
            # 数字签名区里的字符串，跳过
        }
        else {
            $others.Add($idx)
        }
    }

    $targets = if ($versionFields.Count -gt 0) { $versionFields } else { $others }
    if ($targets.Count -eq 0) {
        throw "在 exe 中找不到可替换的产品名字段（可能与工具适配的版本结构不同）"
    }
    foreach ($idx in $targets) {
        [Array]::Copy($newB, 0, $bytes, $idx * 2, $newB.Length)
    }
    [IO.File]::WriteAllBytes($ExePath, $bytes)
    return $targets.Count
}

function Get-ExeWindows([string[]]$Dirs) {
    if (-not ('CiWinScan' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class CiWinScan
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] static extern int GetWindowThreadProcessId(IntPtr hWnd, out int pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int n);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static string Scan()
    {
        var sb = new StringBuilder();
        EnumWindows((h, l) =>
        {
            int pid; GetWindowThreadProcessId(h, out pid);
            var tt = new StringBuilder(512); GetWindowText(h, tt, 512);
            RECT r; GetWindowRect(h, out r);
            sb.Append(h.ToInt64()).Append('\t').Append(pid).Append('\t')
              .Append(IsWindowVisible(h) ? 1 : 0).Append('\t')
              .Append(r.R - r.L).Append('x').Append(r.B - r.T).Append('\t')
              .Append(tt).Append('\n');
            return true;
        }, IntPtr.Zero);
        return sb.ToString();
    }
}
'@
    }
    $rows = @()
    foreach ($line in ([CiWinScan]::Scan() -split "`n")) {
        if (-not $line.Trim()) { continue }
        $p = $line -split "`t"
        $procId = [int]$p[1]
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc -or -not $proc.Path) { continue }
        foreach ($d in $Dirs) {
            if ($proc.Path.StartsWith($d, [StringComparison]::OrdinalIgnoreCase)) {
                $rows += [pscustomobject]@{ Pid = $procId; Visible = ($p[2] -eq '1'); Size = $p[3]; Title = $p[4]; Path = $proc.Path }
                break
            }
        }
    }
    return $rows
}

function Resolve-ClassIslandPaths([string]$InputPath) {
    $item = Get-Item -LiteralPath $InputPath
    $pkgRoot = $null
    $appDirs = @()

    if ($item.PSIsContainer) {
        if ($item.Name -like 'app-*') {
            $appDirs = @($item.FullName); $pkgRoot = $item.Parent.FullName
        }
        elseif (Test-Path -LiteralPath (Join-Path $item.FullName 'ClassIsland.Desktop.exe')) {
            $appDirs = @($item.FullName); $pkgRoot = Split-Path $item.FullName -Parent
        }
        else {
            $sub = @(Get-ChildItem -LiteralPath $item.FullName -Directory -Filter 'app-*' -ErrorAction SilentlyContinue |
                     Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'ClassIsland.Desktop.exe') })
            if ($sub.Count -gt 0) {
                $pkgRoot = $item.FullName
                $appDirs = @($sub | ForEach-Object { $_.FullName })
            }
        }
    }
    else {
        if ($item.Name -eq 'ClassIsland.Desktop.exe') {
            $appDirs = @($item.DirectoryName); $pkgRoot = Split-Path $item.DirectoryName -Parent
        }
        elseif ($item.Name -eq 'ClassIsland.exe') {
            $pkgRoot = $item.DirectoryName
        }
    }

    if (-not $pkgRoot) {
        # 最后尝试：在输入目录往下找 「ClassIsland 2」 之类的目录
        if ($item.PSIsContainer) {
            $cand = @(Get-ChildItem -LiteralPath $item.FullName -Directory -Recurse -Depth 3 -ErrorAction SilentlyContinue |
                      Where-Object { $_.Name -like 'ClassIsland*' })
            foreach ($c in $cand) {
                $apps = @(Get-ChildItem -LiteralPath $c.FullName -Directory -Filter 'app-*' -ErrorAction SilentlyContinue |
                          Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'ClassIsland.Desktop.exe') })
                if ($apps.Count -gt 0) { $pkgRoot = $c.FullName; $appDirs = @($apps | ForEach-Object { $_.FullName }); break }
            }
        }
    }

    if ($pkgRoot -and $appDirs.Count -eq 0) {
        $apps = @(Get-ChildItem -LiteralPath $pkgRoot -Directory -Filter 'app-*' -ErrorAction SilentlyContinue |
                  Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'ClassIsland.Desktop.exe') })
        $appDirs = @($apps | ForEach-Object { $_.FullName })
    }

    if (-not $pkgRoot -or $appDirs.Count -eq 0) {
        throw "无法识别 ClassIsland 安装目录。请把 「ClassIsland 2」 文件夹（或 ClassIsland.Desktop.exe / ClassIsland.exe）拖进来。"
    }

    return [pscustomobject]@{ PackageRoot = $pkgRoot; AppDirs = $appDirs; DataDir = (Join-Path $pkgRoot 'data') }
}

# ---------------------------------------------------------------- 自动搜索
function Find-ClassIslandInstalls {
    $hits = New-Object System.Collections.Generic.List[string]
    # 把一个路径加进命中列表（去重）。列表作为参数显式传入，避免依赖闭包作用域。
    $addHit = {
        param([System.Collections.Generic.List[string]]$list, [string]$p)
        if ($p) {
            try { $rp = (Resolve-Path -LiteralPath $p -ErrorAction Stop).Path } catch { $rp = $p }
            if ($rp -and (-not $list.Contains($rp))) { $list.Add($rp) }
        }
    }

    # 1) 正在运行的 ClassIsland 进程（最快最准）
    try {
        foreach ($pr in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $ep = $pr.ExecutablePath
            if (-not $ep) { continue }
            if ($ep -match '\\ClassIsland\.Desktop\.exe$') { & $addHit $hits (Split-Path $ep -Parent) }
            elseif ($ep -match '\\ClassIsland[^\\]*\\.*\\app-[^\\]+\\[^\\]+\.exe$') { & $addHit $hits (Split-Path $ep -Parent) }
        }
    } catch { }

    # 2) 注册表卸载信息里的安装位置
    $regRoots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($r in $regRoots) {
        try {
            Get-ItemProperty -Path $r -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -like '*ClassIsland*' -and $_.InstallLocation } |
                ForEach-Object { if (Test-Path -LiteralPath $_.InstallLocation) { & $addHit $hits $_.InstallLocation } }
        } catch { }
    }

    # 收集所有磁盘上的用户 AppData\Local
    $drives = @()
    try { $drives = @((Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction SilentlyContinue).DeviceID) } catch { }
    if (-not $drives -or $drives.Count -eq 0) { $drives = @('C:') }

    $localDirs = New-Object System.Collections.Generic.List[string]
    foreach ($d in $drives) {
        $u = "$d\Users"
        if (Test-Path -LiteralPath $u) {
            foreach ($prof in (Get-ChildItem -LiteralPath $u -Directory -ErrorAction SilentlyContinue)) {
                $localDirs.Add((Join-Path $prof.FullName 'AppData\Local'))
            }
        }
    }
    if ($env:LOCALAPPDATA -and ($localDirs -notcontains $env:LOCALAPPDATA)) { $localDirs.Add($env:LOCALAPPDATA) }

    # 3) 常见位置直接命中
    foreach ($lp in $localDirs) {
        # velopack 默认：<Local>\ClassIsland
        $g = Join-Path $lp 'ClassIsland'
        if (Test-Path -LiteralPath $g) { & $addHit $hits $g }
        # 希沃电教猫（DJCat）常见：<Local>\Programs\...\ClassIsland*
        $prog = Join-Path $lp 'Programs'
        if (Test-Path -LiteralPath $prog) {
            try {
                Get-ChildItem -LiteralPath $prog -Directory -Recurse -Depth 4 -Filter 'ClassIsland*' -ErrorAction SilentlyContinue |
                    ForEach-Object { & $addHit $hits $_.FullName }
            } catch { }
        }
    }

    # 4) 还没找到就做一次有范围、有时限的递归搜索（兜底）
    if ($hits.Count -eq 0) {
        $roots = New-Object System.Collections.Generic.List[object]
        foreach ($lp in $localDirs) {
            $roots.Add([pscustomobject]@{ Path = (Join-Path $lp 'Programs'); Depth = 6 })
            $roots.Add([pscustomobject]@{ Path = $lp;                        Depth = 3 })
        }
        foreach ($b in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)) {
            if ($b) { $roots.Add([pscustomobject]@{ Path = $b; Depth = 4 }) }
        }
        $seenRoot = New-Object System.Collections.Generic.HashSet[string]
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        foreach ($r in $roots) {
            if ($sw.Elapsed.TotalSeconds -gt 45) { break }
            if (-not $r.Path -or -not (Test-Path -LiteralPath $r.Path)) { continue }
            if (-not $seenRoot.Add($r.Path.ToLowerInvariant())) { continue }
            try {
                Get-ChildItem -LiteralPath $r.Path -Recurse -Depth $r.Depth -Filter 'ClassIsland.Desktop.exe' -ErrorAction SilentlyContinue |
                    ForEach-Object { & $addHit $hits (Split-Path $_.FullName -Parent) }
            } catch { }
        }
    }

    # 把命中路径解析成安装对象，并按安装根目录去重
    $results = New-Object System.Collections.Generic.List[object]
    $seen    = New-Object System.Collections.Generic.HashSet[string]
    foreach ($h in $hits) {
        try {
            $resolved = Resolve-ClassIslandPaths -InputPath $h
            if ($seen.Add($resolved.PackageRoot.ToLowerInvariant())) { $results.Add($resolved) }
        } catch { }
    }
    return $results.ToArray()
}

function Choose-InstallTarget([object[]]$Found) {
    if ($Found.Count -eq 1) {
        Write-Host ""
        Write-Host "我帮你找到了 ClassIsland，就在这里：" -ForegroundColor Green
        Write-Host "   $($Found[0].PackageRoot)" -ForegroundColor White
        if (Ask-YesNo "是这个吗？" $true) { return $Found[0] }
        return $null
    }
    Write-Host ""
    Write-Host "我找到了下面这几个 ClassIsland，你要修哪一个？" -ForegroundColor Green
    for ($i = 0; $i -lt $Found.Count; $i++) {
        $tag = ''
        if ($i -eq 0) { $tag = '   ← 一般选这个' }
        Write-Host ("   [{0}] {1}{2}" -f ($i + 1), $Found[$i].PackageRoot, $tag) -ForegroundColor White
    }
    Write-Host "   [0] 都不对，我自己输入路径" -ForegroundColor DarkGray
    while ($true) {
        $a = (Read-Host "输入前面的数字再按回车（直接按回车=选 1）").Trim()
        if ($a -eq '') { return $Found[0] }
        if ($a -eq '0') { return $null }
        $n = 0
        if ([int]::TryParse($a, [ref]$n) -and $n -ge 1 -and $n -le $Found.Count) { return $Found[$n - 1] }
        Write-Host "  请输入列表里有的数字哦～" -ForegroundColor Yellow
    }
}

function Read-ManualTarget {
    Write-Host ""
    Write-Host "没关系，手动指一下就行：" -ForegroundColor Yellow
    Write-Host "  把 ClassIsland 的文件夹用鼠标拖到这个黑窗口里，然后按回车；" -ForegroundColor White
    Write-Host "  （或者把路径复制进来再按回车也行）" -ForegroundColor DarkGray
    Write-Host "  实在不知道在哪，路径一般长这样：" -ForegroundColor DarkGray
    Write-Host "    D:\Users\seewo\AppData\Local\Programs\DJCat Pro\DJCatPro\Program\ClassIsland 2" -ForegroundColor DarkGray
    while ($true) {
        $m = (Read-Host "路径").Trim().Trim('"').Trim("'")
        if (-not $m) { Write-Warn2 "你还没输入路径，再试一次（或直接关掉窗口放弃）。"; continue }
        if (-not (Test-Path -LiteralPath $m)) { Write-Err2 "这个路径找不到，检查一下再试：$m"; continue }
        try { return (Resolve-ClassIslandPaths -InputPath $m) }
        catch { Write-Err2 $_.Exception.Message }
    }
}

function Install-PluginPackage([string]$DataDir, [string]$PackagePath) {
    $installedDir = Join-Path $DataDir "Plugins\$PluginId"
    if (Test-Path -LiteralPath $installedDir) { Write-Ok "ClassIslandHide 插件已经装过了，跳过"; return }

    $pkg = $null
    if ($PackagePath -and (Test-Path -LiteralPath $PackagePath)) { $pkg = (Resolve-Path -LiteralPath $PackagePath).Path }
    if (-not $pkg) {
        $local = Join-Path $PSScriptRoot 'ClassIslandHide.cipx'
        if (Test-Path -LiteralPath $local) { $pkg = $local }
    }
    if (-not $pkg) {
        Write-Warn2 "本地没有 ClassIslandHide.cipx，尝试从网上下载……"
        $tmp = Join-Path $env:TEMP 'ClassIslandHide.cipx'
        $ua = 'Mozilla/5.0'
        $urls = @(
            @{ U = "https://api.github.com/repos/HelloWRC/ClassIslandHide/releases/assets/$PluginAssetId"; H = @{ 'User-Agent' = $ua; 'Accept' = 'application/octet-stream' } },
            @{ U = 'https://ghfast.top/https://github.com/HelloWRC/ClassIslandHide/releases/download/2.0.0.1/ClassIslandHide.cipx'; H = @{ 'User-Agent' = $ua } }
        )
        foreach ($u in $urls) {
            try {
                Invoke-WebRequest -Uri $u.U -Headers $u.H -OutFile $tmp -TimeoutSec 40 -MaximumRedirection 10 -UseBasicParsing
                $pkg = $tmp; break
            } catch { }
        }
    }
    if (-not $pkg) { throw "下载 ClassIslandHide 插件失败（网络问题）。可手动下载后放到脚本同目录：https://github.com/HelloWRC/ClassIslandHide/releases" }

    $md5 = (Get-FileHash -LiteralPath $pkg -Algorithm MD5).Hash
    if ($md5 -ne $PluginMd5) {
        throw "插件 MD5 校验失败（得到 $md5，期望 $PluginMd5），已中止安装，避免装入被篡改的包。"
    }
    Write-Ok "插件包校验通过"

    $pkgDir = Join-Path $DataDir 'Cache\PluginPackages'
    New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null
    Copy-Item -LiteralPath $pkg -Destination (Join-Path $pkgDir 'ClassIslandHide.cipx') -Force
    Write-Ok "插件已放入安装队列（下次打开 ClassIsland 时会自动装好）"
}

function Uninstall-Plugin([string]$DataDir) {
    $removed = $false
    $p = Join-Path $DataDir "Plugins\$PluginId"
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force; Write-Ok "已删除插件目录"; $removed = $true }
    $c = Join-Path $DataDir "Config\Plugins"
    if (Test-Path -LiteralPath $c) {
        Get-ChildItem -LiteralPath $c -Filter "$PluginId*" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force; Write-Ok "已删除插件配置 $($_.Name)"
        }
    }
    if (-not $removed) { Write-Warn2 "没有发现已安装的 ClassIslandHide 插件" }

    # 同时清掉“已放入安装队列但还没装”的插件包，避免下次启动又被装上
    $queued = Join-Path $DataDir 'Cache\PluginPackages\ClassIslandHide.cipx'
    if (Test-Path -LiteralPath $queued) {
        Remove-Item -LiteralPath $queued -Force
        Write-Ok "已删除待安装的插件包"
    }
}

# ---------------------------------------------------------------- 管理员权限
function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

# ---------------------------------------------------------------- 主流程
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " ClassIsland 一键修复工具 v$ToolVersion" -ForegroundColor Cyan
Write-Host " （让希沃别再把 ClassIsland 当弹窗关掉）" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 如果不是管理员，先自动提权（弹窗点「是」即可）
if (-not $Elevated -and -not (Test-Admin)) {
    Write-Host ""
    Write-Host "这一步需要「管理员权限」才能改程序文件。" -ForegroundColor Yellow
    Write-Host "马上会弹出一个确认窗口，请点【是】就可以了。" -ForegroundColor Yellow
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Elevated')
    if ($Restore)              { $argList += '-Restore' }
    if ($SkipPlugin)           { $argList += '-SkipPlugin' }
    if ($SkipKill)             { $argList += '-SkipKill' }
    if ($SkipVerify)           { $argList += '-SkipVerify' }
    if ($Path)                 { $argList += @('-Path', "`"$Path`"") }
    if ($Replacement -ne 'Classlsland') { $argList += @('-Replacement', "`"$Replacement`"") }
    if ($PluginPackage)        { $argList += @('-PluginPackage', "`"$PluginPackage`"") }
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList -ErrorAction Stop | Out-Null
        exit 10   # 通知 cmd：已开新窗口，这个窗口不用再暂停
    } catch {
        Write-Warn2 "你取消了授权，或者这台电脑没有管理员权限，将按普通权限继续试试。"
        Write-Warn2 "如果等下改文件失败，请右键点「修复ClassIsland.cmd」→「以管理员身份运行」再来一次。"
    }
}

# 确定要操作哪个 ClassIsland
$paths = $null
if ($Path) {
    $Path = $Path.Trim().Trim('"').Trim("'")
    if (-not (Test-Path -LiteralPath $Path)) { Write-Err2 "路径不存在：$Path"; Done 1 }
    try { $paths = Resolve-ClassIslandPaths -InputPath $Path }
    catch { Write-Err2 $_.Exception.Message; $paths = Read-ManualTarget }
} else {
    Write-Host ""
    Write-Host "正在自动查找 ClassIsland 的安装位置，请稍等几秒……" -ForegroundColor Yellow
    $found = @(Find-ClassIslandInstalls)
    if ($found.Count -gt 0) {
        $paths = Choose-InstallTarget -Found $found
    } else {
        Write-Warn2 "没能自动找到 ClassIsland。"
    }
    if (-not $paths) { $paths = Read-ManualTarget }
}

Write-Ok "安装根目录：$($paths.PackageRoot)"
foreach ($d in $paths.AppDirs) { Write-Ok "程序目录：$d" }
if (-not (Test-Path -LiteralPath $paths.DataDir)) { Write-Warn2 "没找到 data 目录：$($paths.DataDir)" }

if ($Restore) {
    Write-Section "还原模式"
    foreach ($appDir in $paths.AppDirs) {
        $running = Get-RunningFromDir -Dir $appDir
        if ($running.Count -gt 0 -and -not $SkipKill) {
            if (Ask-YesNo "  ClassIsland 正在运行，需要先关掉它才能还原。现在关掉它吗？" $true) { Stop-RunningFromDir -Dir $appDir }
            else { Write-Warn2 "没关它，等下可能因为文件被占用而还原失败" }
        }
        $exe = Join-Path $appDir 'ClassIsland.Desktop.exe'
        $bak = "$exe.bak_dsh"
        if (Test-Path -LiteralPath $bak) {
            Copy-Item -LiteralPath $bak -Destination $exe -Force
            Write-Ok "已还原：$exe"
        } else { Write-Warn2 "没有备份文件，没法还原：$exe" }

        # 清理插件生成的「幽灵副本」
        Get-ChildItem -LiteralPath $appDir -Filter '*.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'ClassIsland.Desktop.exe' } | ForEach-Object {
                try { Remove-Item -LiteralPath $_.FullName -Force; Write-Ok "已删除伪装副本：$($_.Name)" } catch { }
            }
    }
    if (-not $SkipPlugin) { Uninstall-Plugin -DataDir $paths.DataDir }
    Write-Section "搞定"
    Write-Host "  已经还原回去啦。重新打开 ClassIsland 就会回到原来（会被希沃拦截）的状态。" -ForegroundColor Yellow
    Done 0
}

# 1) 插件
if (-not $SkipPlugin) {
    Write-Section "第 1 步：安装 ClassIslandHide 插件"
    try {
        Install-PluginPackage -DataDir $paths.DataDir -PackagePath $PluginPackage
    } catch {
        Write-Err2 "插件这步没成功：$($_.Exception.Message)"
        Write-Warn2 "没关系，继续做更关键的第 2 步（改产品名）；插件可以之后再补。"
    }
}

# 2) 产品名补丁
Write-Section "第 2 步：修改 ClassIsland.Desktop.exe 的产品名"
$blockBefore = Get-HuorongBlockCount
if ($null -ne $blockBefore) { Write-Host "  当前希沃拦截计数 blockcount = $blockBefore" -ForegroundColor DarkGray }

foreach ($appDir in $paths.AppDirs) {
    $running = Get-RunningFromDir -Dir $appDir
    if ($running.Count -gt 0 -and -not $SkipKill) {
        if (Ask-YesNo "  ClassIsland 正在运行，需要先关掉它才能修改。现在关掉它吗？" $true) { Stop-RunningFromDir -Dir $appDir }
        else { Write-Warn2 "没关它，若文件被占用会修改失败" }
    } elseif ($running.Count -gt 0) {
        Write-Warn2 "ClassIsland 正在运行（$($running.Count) 个进程），可能没法写入 exe"
    }

    $exe = Join-Path $appDir 'ClassIsland.Desktop.exe'
    $bak = "$exe.bak_dsh"
    $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe)

    if ($vi.ProductName -eq $Replacement) {
        Write-Ok "这个已经修过了（产品名 = $($vi.ProductName)），跳过"
        continue
    }
    if ($vi.ProductName -ne $OldProductName) {
        Write-Warn2 "当前产品名是「$($vi.ProductName)」，不是 $OldProductName，跳过（不认识的版本）"
        continue
    }

    if (-not (Test-Path -LiteralPath $bak)) {
        Copy-Item -LiteralPath $exe -Destination $bak -Force
        Write-Ok "已备份原文件：ClassIsland.Desktop.exe.bak_dsh"
    } else {
        Write-Ok "备份已存在，保留原备份"
    }

    try {
        $n = Set-ProductNameInExe -ExePath $exe -Old $OldProductName -New $Replacement
        $vi2 = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
        if ($vi2.ProductName -eq $Replacement) {
            Write-Ok "修改成功：$OldProductName -> $Replacement（替换 $n 处）"
        } else {
            throw "写入后校验失败（当前产品名：$($vi2.ProductName)）"
        }
    } catch {
        Write-Err2 "修改失败：$($_.Exception.Message)"
        if (Test-Path -LiteralPath $bak) {
            Copy-Item -LiteralPath $bak -Destination $exe -Force
            Write-Warn2 "已自动恢复到备份，没有改坏"
        }
        Done 1
    }
}

# 3) 验证
if (-not $SkipVerify) {
    Write-Section "第 3 步：验证一下"
    if (Ask-YesNo "  要不要现在打开 ClassIsland，看 12 秒它还会不会被关掉？" $true) {
      try {
        $mainAppDir = $paths.AppDirs[0]
        $launcher = Join-Path $paths.PackageRoot 'ClassIsland.exe'
        $desktop = Join-Path $mainAppDir 'ClassIsland.Desktop.exe'
        $startExe = if (Test-Path -LiteralPath $launcher) { $launcher } else { $desktop }
        Write-Host "  正在打开：$startExe" -ForegroundColor DarkGray
        Start-Process -FilePath $startExe | Out-Null
        Start-Sleep -Seconds 12
        $wins = @(Get-ExeWindows -Dirs $paths.AppDirs | Where-Object { $_.Visible -and $_.Size -ne '0x0' })
        $blockAfter = Get-HuorongBlockCount
        if ($wins.Count -gt 0) {
            Write-Ok "看到 $($wins.Count) 个窗口还开着，没有被关掉，成功！"
            foreach ($w in $wins) { Write-Host "     - pid=$($w.Pid) 大小=$($w.Size) 标题=「$($w.Title)」" -ForegroundColor DarkGray }
        } else {
            Write-Warn2 "没看到可见窗口（可能被拦了，或者应用还没完全打开）"
        }
        if ($null -ne $blockBefore -and $null -ne $blockAfter) {
            if ($blockAfter -gt $blockBefore) { Write-Warn2 "希沃拦截计数增加了：$blockBefore -> $blockAfter（说明还在被拦）" }
            else { Write-Ok "希沃拦截计数：$blockBefore -> $blockAfter（没有新增拦截）" }
        }
      } catch {
        Write-Warn2 "验证这步出了点小问题（不影响已经改好的补丁）：$($_.Exception.Message)"
      }
    }
}

Write-Section "全部搞定"
Write-Host "  这次做了什么：" -ForegroundColor Yellow
Write-Host "   - 装好了 ClassIslandHide 插件 + 把 exe 产品名改成 $Replacement（原文件已备份）"
Write-Host "   - 以后「重装 / 更新 ClassIsland」或者「电教猫修复文件」之后，补丁会失效，重新双击本工具再跑一次就行"
Write-Host "   - 想撤销/还原：双击「还原ClassIsland.cmd」"
Write-Host "   - 最彻底的办法，还是让学校希沃集控管理员把 ClassIsland 从拦截名单里去掉"
Done 0
