# Aurascope 启动诊断：放在 Aurascope.exe 同级目录，右键“使用 PowerShell 运行”
# 输出 diagnose.txt，把它发回给开发即可
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSCommandPath
$out = Join-Path $root 'diagnose.txt'

$lines = @()
function W($s) { $script:lines += $s }

W "===== Aurascope 启动诊断 ====="
W ("时间: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
W ""
W "--- 系统 ---"
$os = Get-CimInstance Win32_OperatingSystem
W ("系统: " + $os.Caption)
W ("版本: " + $os.Version + "  Build " + $os.BuildNumber)
W ("位数: " + $os.OSArchitecture)
W ("是否 Win10 及以上: " + ([version]$os.Version -ge [version]'10.0'))
W ""
W "--- 程序目录 ---"
W ("目录: " + $root)
W ("是否在网络盘: " + ($root -match '^\\\\'))
$exe = Join-Path $root 'Aurascope.exe'
W ("Aurascope.exe 存在: " + (Test-Path $exe))
$internal = Join-Path $root '_internal'
W ("_internal 存在: " + (Test-Path $internal))
if (Test-Path $internal) {
    $files = Get-ChildItem $internal -Recurse -File
    W ("_internal 文件数: " + $files.Count + "（正常约 1154）")
    W ("_internal 总大小MB: " + [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 1))
}
$py = Join-Path $internal 'python313.dll'
W ("python313.dll 存在: " + (Test-Path $py))
if (Test-Path $py) { W ("python313.dll 大小: " + (Get-Item $py).Length + "（正常 6123864）") }
$vc = Join-Path $internal 'vcruntime140.dll'
W ("vcruntime140.dll 存在: " + (Test-Path $vc))
$qwindows = Join-Path $internal 'PyQt6\Qt6\plugins\platforms\qwindows.dll'
W ("Qt 平台插件存在: " + (Test-Path $qwindows))
W ""
W "--- 可能冲突的 Python ---"
$sysPy = "$env:SystemRoot\System32\python313.dll"
W ("System32 里有 python313.dll: " + (Test-Path $sysPy))
W ("PATH 里的 python: " + ((Get-Command python -ErrorAction SilentlyContinue).Source))
W ""
W "--- 安全软件 ---"
$av = Get-Process | Where-Object {
    $_.ProcessName -match '360|ZhuDongFangYu|HipsTray|HipsDaemon|wsctrl|QQPCRTP|QMDL|McAfee|Norton|kavfs|avp'
} | Select-Object -ExpandProperty ProcessName -Unique
if ($av) { W ("检测到: " + ($av -join ', ')) } else { W "未检测到常见杀软进程（不代表没有）" }
$defender = Get-Service WinDefend
W ("Windows Defender 服务: " + $(if ($defender -and $defender.Status -eq 'Running') { '运行中' } else { '未运行/未安装' }))
W ""
W "--- 系统 UCRT（Win7 缺它会起不来） ---"
W ("api-ms-win-crt-runtime-l1-1-0.dll 存在: " +
   (Test-Path "$env:SystemRoot\System32\api-ms-win-crt-runtime-l1-1-0.dll"))
W ""
W "--- 应用日志 ---"
$log = Join-Path $env:LOCALAPPDATA 'Aurascope\logs\aurascope.log'
if (Test-Path $log) {
    W ("日志: " + $log)
    W "--- 最后 15 行 ---"
    Get-Content $log -Encoding UTF8 -Tail 15 | ForEach-Object { W ("  " + $_) }
} else {
    W "没有日志文件（说明 Python 根本没起来，问题在引导阶段）"
}

$lines | Set-Content -Path $out -Encoding UTF8
Write-Host "诊断完成，请把这个文件发给开发：$out" -ForegroundColor Green
Write-Host ""
$lines | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "按任意键关闭..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
