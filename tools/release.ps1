<#
.SYNOPSIS
  Aurascope 一键发版：改版本号 -> 跑测试 -> 打包 -> 打 zip -> 建 Gitee 发行版 -> 传附件 -> 推代码与更新源。

.DESCRIPTION
  凭证只从环境变量 GITEE_TOKEN 读取（Gitee 私人令牌，需勾 projects 权限），脚本内不保存任何密钥。
  发布前需先在 CHANGELOG.md 里写好 ## <版本> — 日期 段落，脚本直接用它作为更新说明。

.EXAMPLE
  $env:GITEE_TOKEN = '你的令牌'
  .\tools\release.ps1 -Version 6.3.12

.EXAMPLE
  # 只打包和改文件，不建发行版、不推送（用于本地验证）
  .\tools\release.ps1 -Version 6.3.12 -SkipPush
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$SkipTests,
    [switch]$SkipPush,
    [string]$Token = $env:GITEE_TOKEN
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$srcOwner = 'lingyue001';  $srcRepo = 'aurascope'
$relOwner = 'lingyue001';  $relRepo = 'aurascope-repo'
$tag = "v$Version"
$zipName = "Aurascope-$Version.zip"
$zipPath = Join-Path $root "dist\$zipName"
$feedFile = Join-Path $root 'release\latest.json'
$releaseFiles = @('app_version.py', 'version_info.txt', 'CHANGELOG.md', 'release\latest.json')

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n[x] $text" -ForegroundColor Red; exit 1 }
function Ok($text)   { Write-Host "[v] $text" -ForegroundColor Green }

# ---------- 0. 前置检查 ----------
Step "前置检查"
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "版本号格式应为 x.y.z，例如 6.3.12" }
if (-not $SkipPush -and -not $Token) {
    Fail "缺少 GITEE_TOKEN。先在 Gitee 生成私人令牌（勾 projects），然后 `$env:GITEE_TOKEN = '...'"
}
$sevenZip = @('C:\Program Files\7-Zip\7z.exe', 'C:\Program Files (x86)\7-Zip\7z.exe') |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenZip) { $sevenZip = (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source }
if (-not $sevenZip) { Fail "找不到 7z.exe（请安装 7-Zip 或把 7z 加入 PATH）" }

$changelog = Get-Content 'CHANGELOG.md' -Encoding UTF8
$startIdx = ($changelog | Select-String -Pattern "^## $([regex]::Escape($Version))\b" | Select-Object -First 1).LineNumber
if (-not $startIdx) { Fail "CHANGELOG.md 里没有 '## $Version' 段落，请先补上更新说明" }
$notes = @()
for ($i = $startIdx; $i -lt $changelog.Count; $i++) {
    if ($changelog[$i] -match '^## ') { break }
    $notes += $changelog[$i]
}
$notes = (($notes -join "`n").Trim() -replace '^- ', '- ');
if (-not $notes) { Fail "CHANGELOG.md 的 '## $Version' 段落是空的" }
Ok "版本 $Version，更新说明 $($notes.Length) 字符"

$running = Get-Process | Where-Object { $_.ProcessName -like 'Aurascope*' }
if ($running) {
    Write-Host "检测到正在运行的 Aurascope，正在关闭..." -ForegroundColor Yellow
    $running | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 2
    Get-Process | Where-Object { $_.ProcessName -like 'Aurascope*' } |
        ForEach-Object { Stop-Process -Id $_.Id -Force }
    Ok "已关闭运行中的实例"
}

# ---------- 1. 改版本号 ----------
Step "写入版本号 $Version"
$appVersionPath = Join-Path $root 'app_version.py'
$appVersionText = [System.IO.File]::ReadAllText($appVersionPath)
$appVersionText = [regex]::Replace($appVersionText, "APP_VERSION = '[^']*'", "APP_VERSION = '$Version'")
[System.IO.File]::WriteAllText($appVersionPath, $appVersionText, (New-Object System.Text.UTF8Encoding($false)))

$viPath = Join-Path $root 'version_info.txt'
$viText = [System.IO.File]::ReadAllText($viPath)
$parts = $Version.Split('.')
$quad = "$($parts[0]), $($parts[1]), $($parts[2]), 0"
$viText = [regex]::Replace($viText, 'filevers=\([^)]*\)', "filevers=($quad)")
$viText = [regex]::Replace($viText, 'prodvers=\([^)]*\)', "prodvers=($quad)")
$viText = [regex]::Replace($viText, "StringStruct\('FileVersion', '[^']*'\)", "StringStruct('FileVersion', '$Version')")
$viText = [regex]::Replace($viText, "StringStruct\('ProductVersion', '[^']*'\)", "StringStruct('ProductVersion', '$Version')")
[System.IO.File]::WriteAllText($viPath, $viText, (New-Object System.Text.UTF8Encoding($false)))
Ok "app_version.py / version_info.txt 已更新"

# ---------- 2. 回归测试 ----------
if (-not $SkipTests) {
    Step "运行单元测试"
    $env:PYTHONIOENCODING = 'utf-8'
    $env:QT_QPA_PLATFORM = 'offscreen'
    & (Join-Path $root 'venv\Scripts\python.exe') -B -m unittest `
        test_area_tab test_teach_batch_logic test_update_check test_updater test_shear 2>&1 |
        Select-Object -Last 3
    if ($LASTEXITCODE -ne 0) { Fail "单元测试未通过，已中止发版" }
    Ok "测试通过"
}

# ---------- 3. 打包与压缩 ----------
Step "PyInstaller 打包"
& (Join-Path $root 'venv\Scripts\pyinstaller.exe') --clean --noconfirm AurascopeV6.spec |
    Out-Null
if ($LASTEXITCODE -ne 0) { Fail "打包失败（先看 build 日志，常见原因是 exe 还在运行）" }
$exe = Get-Item 'dist\Aurascope\Aurascope.exe'
if ($exe.VersionInfo.FileVersion -ne $Version) {
    Fail "打包产物版本是 $($exe.VersionInfo.FileVersion)，与目标 $Version 不一致"
}
Ok "产物版本 $Version"

Step "压缩发布包"
if (Test-Path $zipPath) { [System.IO.File]::Delete($zipPath) }
Push-Location 'dist'
& $sevenZip a -tzip -mx=7 -xr!recipes $zipName 'Aurascope' | Out-Null
Pop-Location
if (-not (Test-Path $zipPath)) { Fail "压缩失败" }
$size = (Get-Item $zipPath).Length
$sizeMB = [math]::Round($size / 1MB, 1)
if ($size -gt 100MB) { Fail "zip 超过 Gitee 附件 100MB 上限（当前 $sizeMB MB），需要改用对象存储" }
Ok "$zipName  $sizeMB MB"

# ---------- 4. 写更新源 ----------
Step "更新 release\latest.json"
$feed = [ordered]@{
    version = $Version
    url     = "https://gitee.com/$relOwner/$relRepo/releases/download/$tag/$zipName"
    page    = "https://gitee.com/$relOwner/$relRepo/releases/tag/$tag"
    notes   = ($notes -replace "`r?`n", ' ' -replace '^-\s*', '' -replace '\s*-\s*', '；')
    size    = $size
}
$feedJson = $feed | ConvertTo-Json
[System.IO.File]::WriteAllText($feedFile, $feedJson, (New-Object System.Text.UTF8Encoding($false)))
Ok "已写入（url 指向 $tag）"

if ($SkipPush) {
    Write-Host "`n-SkipPush：已停在「本地准备完成」，没有提交、建发行版或上传。" -ForegroundColor Yellow
    Write-Host "产物：$zipPath"
    exit 0
}

# ---------- 5. 提交并推送代码 ----------
Step "提交并推送源码"
& git add -- app_version.py version_info.txt CHANGELOG.md release/latest.json
& git commit -m "发布 $Version" -m $notes
if ($LASTEXITCODE -ne 0) { Write-Host "（没有新改动可提交，继续）" -ForegroundColor Yellow }
& git tag $tag
& git push origin main; if ($LASTEXITCODE -ne 0) { Fail "推送 origin/main 失败" }
& git push origin $tag;  if ($LASTEXITCODE -ne 0) { Fail "推送 origin tag 失败" }
$env:GIT_TERMINAL_PROMPT = '0'
& git push gitee main;   if ($LASTEXITCODE -ne 0) { Fail "推送 gitee/main 失败（凭据失效？）" }
& git push gitee $tag
Ok "GitHub + Gitee 已同步"

# ---------- 6. 建发行版并上传附件 ----------
Step "Gitee 建发行版 $tag"
$apiBase = "https://gitee.com/api/v5/repos/$relOwner/$relRepo"
try {
    $existing = Invoke-RestMethod -Uri "$apiBase/releases" -TimeoutSec 30
    if ($existing | Where-Object { $_.tag_name -eq $tag }) { Fail "发行版 $tag 已存在，请换版本号或先去网页删除" }
    $release = Invoke-RestMethod -Method Post -Uri "$apiBase/releases" -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 60 -Body @{
        access_token    = $Token
        tag_name        = $tag
        name            = $tag
        body            = $notes
        target_commitish = 'main'
        prerelease      = 'false'
    }
} catch { Fail "建发行版失败：$($_.Exception.Message)" }
Ok "发行版 id=$($release.id)"

Step "上传附件（约 $sizeMB MB，可能要 1~2 分钟）"
$upload = & curl.exe -s -S -X POST "$apiBase/releases/$($release.id)/attach_files" `
    -F "access_token=$Token" -F "file=@$zipPath" -w "`nHTTP=%{http_code}"
if ($upload -notmatch 'browser_download_url') { Fail "上传失败：$upload" }
$httpCode = ([regex]::Match($upload, 'HTTP=(\d+)')).Groups[1].Value
if ($httpCode -ne '201') { Fail "上传返回 HTTP $httpCode" }
Ok "附件已上传"

# ---------- 7. 推更新源到发布仓 ----------
Step "推送 latest.json 到发布仓"
$pub = Join-Path $env:TEMP 'aurascope_repo_pub'
if (Test-Path $pub) {
    & git -C $pub pull --ff-only 2>&1 | Out-Null
} else {
    & git clone "https://gitee.com/$relOwner/$relRepo.git" $pub 2>&1 | Out-Null
}
Copy-Item $feedFile (Join-Path $pub 'latest.json') -Force
& git -C $pub add latest.json
& git -C $pub commit -m "发布 $Version" | Out-Null
& git -C $pub push origin main 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "推送发布仓失败" }
Ok "更新源已发布"

# ---------- 8. 线上校验 ----------
Step "线上校验"
$feedUrl = "https://gitee.com/$relOwner/$relRepo/raw/main/latest.json"
$ok = $false
for ($i = 1; $i -le 6; $i++) {
    Start-Sleep -Seconds 5
    try {
        $live = (Invoke-WebRequest -Uri $feedUrl -UseBasicParsing -TimeoutSec 20).Content | ConvertFrom-Json
        if ($live.version -eq $Version) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { Fail "更新源还没生效（可能需要等 CDN 缓存），稍后重试或手动检查 $feedUrl" }
try {
    $head = Invoke-WebRequest -Uri $feed.url -Method Head -UseBasicParsing -TimeoutSec 30
    Ok "更新源 version=$($live.version) size=$($live.size)"
    Ok "附件可下载 HTTP $($head.StatusCode)  $([math]::Round([int]$head.Headers['Content-Length']/1MB,2)) MB"
} catch { Fail "附件地址不可下载：$($_.Exception.Message)" }

Write-Host "`n发布完成：$Version" -ForegroundColor Green
Write-Host "  页面  $($feed.page)"
Write-Host "  更新源 $feedUrl"
