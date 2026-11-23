<#
Validation harness for fix-ClassIsland.ps1, run on a real Windows runner.
Modes:
  Parse   - AST parse the script (catches every syntax error on this PS edition)
  Analyze - PSScriptAnalyzer (fails on Error severity; best-effort if module missing)
  Unit    - load the script's functions via AST (without running its main flow)
            and assert the core logic on synthetic inputs
This file is ASCII-only on purpose so it is encoding-proof in CI logs.
#>
[CmdletBinding()]
param(
    [ValidateSet('Parse', 'Analyze', 'Unit')]
    [string]$Mode = 'Parse'
)

$ErrorActionPreference = 'Stop'
$ScriptPath = Join-Path $PSScriptRoot 'fix-ClassIsland.ps1'
Write-Host "PSEdition=$($PSVersionTable.PSEdition)  PSVersion=$($PSVersionTable.PSVersion)"
Write-Host "Target   = $ScriptPath"
if (-not (Test-Path -LiteralPath $ScriptPath)) { throw "script not found: $ScriptPath" }

# ---- parse (shared by all modes) ----
$tokens = $null; $perrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$perrors)
if ($perrors -and $perrors.Count -gt 0) {
    foreach ($e in $perrors) {
        Write-Host ("PARSE ERROR @ line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message) -ForegroundColor Red
    }
    throw "parse failed with $($perrors.Count) error(s)"
}
Write-Host "[PASS] parsed with no syntax errors" -ForegroundColor Green

if ($Mode -eq 'Parse') { exit 0 }

# ---- analyze ----
if ($Mode -eq 'Analyze') {
    $haveModule = [bool](Get-Module -ListAvailable -Name PSScriptAnalyzer)
    if (-not $haveModule) {
        try {
            Write-Host "Installing PSScriptAnalyzer..."
            Install-Module PSScriptAnalyzer -Force -Scope CurrentUser -AllowClobber -ErrorAction Stop
            $haveModule = $true
        } catch {
            Write-Host "[WARN] PSScriptAnalyzer unavailable ($($_.Exception.Message)); skipping analysis (not failing the build)." -ForegroundColor Yellow
            exit 0
        }
    }
    Import-Module PSScriptAnalyzer -ErrorAction Stop
    $findings = Invoke-ScriptAnalyzer -Path $ScriptPath -Severity Error, Warning
    if ($findings) {
        $findings | Sort-Object Severity, Line | Format-Table Severity, Line, RuleName, Message -AutoSize | Out-String -Width 200 | Write-Host
    } else {
        Write-Host "[PASS] PSScriptAnalyzer: no Error/Warning findings" -ForegroundColor Green
    }
    $errors = @($findings | Where-Object { $_.Severity -eq 'Error' })
    if ($errors.Count -gt 0) { Write-Host "[FAIL] $($errors.Count) analyzer error(s)" -ForegroundColor Red; exit 1 }
    exit 0
}

# ---- unit ----
# Load ONLY the top-level function definitions, so the script's main flow never runs.
$fnDefs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
Write-Host "Loaded $($fnDefs.Count) function definition(s)"
$fnText = ($fnDefs | ForEach-Object { $_.Extent.Text }) -join "`n`n"
. ([ScriptBlock]::Create($fnText))

$script:fails = 0
function Check([bool]$Cond, [string]$Msg) {
    if ($Cond) { Write-Host "  [PASS] $Msg" -ForegroundColor Green }
    else       { Write-Host "  [FAIL] $Msg" -ForegroundColor Red; $script:fails++ }
}
function CountSub([string]$Haystack, [string]$Needle) {
    ([regex]::Matches($Haystack, [regex]::Escape($Needle))).Count
}

$U = [System.Text.Encoding]::Unicode

Write-Host "`n== Set-ProductNameInExe (synthetic PE bytes) =="
# Occurrence 1: preceded by ProductName within 40 chars -> version field -> should be patched
# Occurrence 2: 'ClassIsland.Desktop.dll' (next 2 chars '.D') -> should be skipped
# Occurrence 3: bare, far from ProductName -> 'others', ignored because a version field exists
$sep = ('Z' * 60)
$synthetic = ('A' * 20) + 'ProductName' + ('B' * 4) + 'ClassIsland' + $sep + 'ClassIsland.Desktop.dll' + $sep + ('C' * 5) + 'ClassIsland' + ('D' * 20)
$tmpExe = Join-Path ([IO.Path]::GetTempPath()) ("ci_exe_{0}.bin" -f ([guid]::NewGuid().ToString('N')))
[IO.File]::WriteAllBytes($tmpExe, $U.GetBytes($synthetic))
$origLen = (Get-Item -LiteralPath $tmpExe).Length
try {
    $n = Set-ProductNameInExe -ExePath $tmpExe -Old 'ClassIsland' -New 'Classlsland'
    $after = $U.GetString([IO.File]::ReadAllBytes($tmpExe))
    Check ($n -eq 1)                                  "patched exactly 1 occurrence (got $n)"
    Check ((CountSub $after 'Classlsland') -eq 1)     "ProductName value became 'Classlsland'"
    Check ($after -match 'ClassIsland\.Desktop\.dll') "'ClassIsland.Desktop.dll' left untouched"
    Check ((CountSub $after 'ClassIsland') -eq 2)     "2 'ClassIsland' remain (Desktop.dll + bare), got $(CountSub $after 'ClassIsland')"
    Check ((Get-Item -LiteralPath $tmpExe).Length -eq $origLen) "file length unchanged ($origLen bytes)"
} finally {
    Remove-Item -LiteralPath $tmpExe -Force -ErrorAction SilentlyContinue
}

# length-mismatch must throw
$threw = $false
$tmpExe2 = Join-Path ([IO.Path]::GetTempPath()) ("ci_exe2_{0}.bin" -f ([guid]::NewGuid().ToString('N')))
[IO.File]::WriteAllBytes($tmpExe2, $U.GetBytes('ProductName..ClassIsland..'))
try { Set-ProductNameInExe -ExePath $tmpExe2 -Old 'ClassIsland' -New 'TOOLONGNAME' } catch { $threw = $true }
Remove-Item -LiteralPath $tmpExe2 -Force -ErrorAction SilentlyContinue
Check $threw "throws when replacement length differs from original"

Write-Host "`n== Resolve-ClassIslandPaths (fake install tree) =="
$root = Join-Path ([IO.Path]::GetTempPath()) ("ci_tree_{0}" -f ([guid]::NewGuid().ToString('N')))
$pkg  = Join-Path $root 'ClassIsland 2'
$app  = Join-Path $pkg 'app-1.0.0'
New-Item -ItemType Directory -Force -Path $app | Out-Null
Set-Content -LiteralPath (Join-Path $app 'ClassIsland.Desktop.exe') -Value 'x' -Encoding Ascii
try {
    $r1 = Resolve-ClassIslandPaths -InputPath $pkg
    Check ($r1.PackageRoot -ieq $pkg)                          "package folder -> PackageRoot is the folder"
    Check ($r1.AppDirs.Count -eq 1 -and ($r1.AppDirs[0] -ieq $app)) "package folder -> finds the app-* dir"
    Check ($r1.DataDir -ieq (Join-Path $pkg 'data'))           "DataDir = PackageRoot\data"

    $r2 = Resolve-ClassIslandPaths -InputPath (Join-Path $app 'ClassIsland.Desktop.exe')
    Check ($r2.AppDirs[0] -ieq $app -and $r2.PackageRoot -ieq $pkg) "passing the exe resolves app dir + package root"

    $r3 = Resolve-ClassIslandPaths -InputPath $app
    Check ($r3.AppDirs[0] -ieq $app -and $r3.PackageRoot -ieq $pkg) "passing the app-* dir resolves correctly"
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "`n== Find-ClassIslandInstalls (planted install under %LOCALAPPDATA%) =="
$ci    = Join-Path $env:LOCALAPPDATA 'ClassIsland'
$ciApp = Join-Path $ci 'app-9.9.9'
$planted = -not (Test-Path -LiteralPath $ci)
New-Item -ItemType Directory -Force -Path $ciApp | Out-Null
Set-Content -LiteralPath (Join-Path $ciApp 'ClassIsland.Desktop.exe') -Value 'x' -Encoding Ascii
try {
    $found = @(Find-ClassIslandInstalls)
    Write-Host ("  found {0} install(s): {1}" -f $found.Count, (($found | ForEach-Object { $_.PackageRoot }) -join ' ; '))
    $roots = @($found | ForEach-Object { $_.PackageRoot })
    Check ($roots -contains $ci) "auto-search finds the planted %LOCALAPPDATA%\ClassIsland install"
} finally {
    if ($planted) { Remove-Item -LiteralPath $ci -Recurse -Force -ErrorAction SilentlyContinue }
    else { Remove-Item -LiteralPath $ciApp -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host "`n== Ask-YesNo (mocked Read-Host) =="
$script:mockAns = ''
function Read-Host { param([string]$Prompt) return $script:mockAns }
$script:mockAns = 'y'; Check (Ask-YesNo 'q' $true)        "'y' -> yes"
$script:mockAns = 'n'; Check (-not (Ask-YesNo 'q' $true)) "'n' -> no"
$script:mockAns = '1'; Check (Ask-YesNo 'q' $true)        "'1' -> yes"
$script:mockAns = '0'; Check (-not (Ask-YesNo 'q' $true)) "'0' -> no"
$script:mockAns = '';  Check (Ask-YesNo 'q' $true)        "empty -> default yes"
$script:mockAns = '';  Check (-not (Ask-YesNo 'q' $false)) "empty -> default no"

Write-Host ""
if ($script:fails -gt 0) { Write-Host "UNIT RESULT: $($script:fails) failure(s)" -ForegroundColor Red; exit 1 }
Write-Host "UNIT RESULT: all passed" -ForegroundColor Green
exit 0
