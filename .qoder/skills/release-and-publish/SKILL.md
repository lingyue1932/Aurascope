---
name: release-and-publish
description: Aurascope 的发版与推送流程。用户要求「发版/打包/推到 Gitee」时使用；包含一键脚本用法、令牌存放位置与使用授权规则、线上校验方法。
---

# Aurascope 发版与推送

## 何时使用

- 用户说「发版」「打包发布」「推个新版本」「上传到 Gitee」→ 用本流程。
- 用户说「只打包不发布」→ `.\tools\release.ps1 -Version x.y.z -SkipPush`。
- 用户**没有**明确要求推送/发布时，**不要**读取或使用令牌，也不要执行 `git push` 与 Gitee API 调用。

## 令牌（重要）

令牌**不在仓库里**，存放在：

```
%LOCALAPPDATA%\Aurascope\gitee_token.txt
```

读取方式（PowerShell）：

```powershell
$token = (Get-Content "$env:LOCALAPPDATA\Aurascope\gitee_token.txt" -Raw).Trim()
$env:GITEE_TOKEN = $token
```

规则（必须遵守）：

1. **仅在用户明确要求推送/发版时**才读取并使用；平时不读、不打印、不写日志。
2. **绝不**把令牌写入仓库内任何文件（含 `.qoder/`、`docs/`、脚本、注释），仓库是公开的（GitHub + Gitee 双远端）。
3. 命令里用到令牌时不要 `Write-Host` 回显；`curl`/`Invoke-RestMethod` 的 URL 参数里若带 token，不要把完整命令贴进对话。
4. 怀疑泄露（例如贴进了公开渠道）→ 立刻提示用户去 <https://gitee.com/profile/personal_access_tokens> 撤销并换新。

## 一键发版

前置：`CHANGELOG.md` 已有 `## x.y.z — 日期` 段落（脚本会校验，缺失直接拒绝）。

```powershell
$env:GITEE_TOKEN = (Get-Content "$env:LOCALAPPDATA\Aurascope\gitee_token.txt" -Raw).Trim()
.\tools\release.ps1 -Version 6.3.13
```

脚本依次做：改 `app_version.py` / `version_info.txt` → 跑 5 个测试套件 → PyInstaller 打包并核对 FileVersion → 7z 打 `dist/Aurascope-x.y.z.zip`（排除 recipes，>100MB 报错）→ 写 `release/latest.json` → commit + tag + 推 GitHub 与 Gitee 源码仓 → Gitee API 建发行版并 curl 上传附件 → 把 `latest.json` 推到发布仓 `aurascope-repo` → 轮询线上校验。

开关：`-SkipTests` 跳过测试；`-SkipPush` 只做到本地 zip 与 `latest.json`。

## 手工发版（脚本不可用时）

1. 改版本号三处：`app_version.py`、`version_info.txt`（filevers/prodvers/FileVersion/ProductVersion）、`CHANGELOG.md`
2. 跑测试：`venv\Scripts\python.exe -B -m unittest test_area_tab test_teach_batch_logic test_update_check test_updater test_shear`
3. 打包：`venv\Scripts\pyinstaller.exe --clean --noconfirm AurascopeV6.spec`（先确认没有 Aurascope.exe 在运行，否则 `cv2.pyd` 被锁导致构建失败）
4. 压缩：`7z a -tzip -mx=7 -xr!recipes dist\Aurascope-x.y.z.zip dist\Aurascope`
5. 建发行版：`POST https://gitee.com/api/v5/repos/lingyue001/aurascope-repo/releases`（`tag_name` **必须带 `v` 前缀**）
6. 传附件：`curl -F "access_token=$token" -F "file=@dist/Aurascope-x.y.z.zip" .../releases/<id>/attach_files`（成功返回 HTTP 201）
7. 写 `release/latest.json`（version/url/page/notes/size，size 用 zip 实际字节数）→ 推源码仓 → 复制到发布仓根目录并推送

## 线上校验（发完必做）

```powershell
Invoke-WebRequest 'https://gitee.com/lingyue001/aurascope-repo/raw/main/latest.json' -UseBasicParsing
Invoke-WebRequest 'https://gitee.com/lingyue001/aurascope-repo/releases/download/vX.Y.Z/Aurascope-X.Y.Z.zip' -Method Head -UseBasicParsing
```

两者都返回 200、`version` 与 `size` 对得上，才算发布完成。

## 注意

- 客户端读的是发布仓**根目录**的 `latest.json`（`update_check.FEED_URL`），源码仓的 `release/latest.json` 只是底稿，两边都要更新。
- 发行版标签若漏写 `v` 前缀，`latest.json` 里的 url 会 404，客户端更新会失败。
- Gitee 发行版单附件上限 100MB，当前 zip 约 91.4MB，余量有限。
