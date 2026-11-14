# 微信图片复制归档 Skill

在 Windows 电脑微信中右键图片 → **复制**，本地后台保存原图，用 Windows 自带 OCR 提取文字并初步命名。

**保存和 OCR 不调用 ChatGPT、不使用 AI API、不消耗模型 token。** 与 AI 对话、请 AI 人工复核图片时仍会使用模型额度。Skill 本身不会常驻监听；持续保存由附带的本地后台程序完成，后台启动后无需保持 ChatGPT 打开。电脑需开机并保持用户会话可用。

## 做什么

- 只处理你主动复制的微信图片，不自动收集新收到的图片，不读聊天记录。
- 保存原图字节与扩展名，SHA256 去重；重名时加编号，不覆盖已有图片。
- 先保存再 OCR；识别失败仍保留图片。
- 自动名称示例：`待核对_2026-01-02_天猫订单_纯棉长袖衬衫_尾号123456.PNG`。
- OCR 数字可能出错，所有初步名称带“待核对”，自动名称不写金额。需要实付金额等精确信息时，可自行检查，或主动要求 AI 进行一次人工复核。
- 不会创建 AI 定时任务、设置开机启动或上传图片。

## 运行条件和限制

- Windows 10/11；Python 3.11+（含 `pythonw.exe`）；Windows PowerShell 5.1。
- Windows 已有 OCR 识别语言，中文截图建议具备中文识别语言；缺失时仍能保存。
- 桌面微信复制图片时，需提供 CF_HDROP 文件路径，且导出文件位于所配置账户的 `temp\RWTemp\YYYY-MM\...` 下。微信版本或复制方式变化可能使此方式不适用。
- 支持 JPEG、PNG、BMP、WEBP 的文件导出。只有位图、链接、文本或加密缓存的剪贴板内容不处理。
- 图片去重按文件内容；同一张图片再次复制通常不会重复保存。改过压缩或分辨率的图片属于不同内容。
- 运行后当前剪贴板上已复制的微信图片也可能被保存。程序仅保存，不修改剪贴板。

## 安装 Skill

将本仓库整个文件夹放入 `%USERPROFILE%\.codex\skills\wechat-image-archive`，其中 `SKILL.md` 应位于该文件夹根目录。若当前 Codex 会话尚未列出它，重开会话或重启应用后再使用。

可以对 Codex 说：

> 使用 $wechat-image-archive 检查本地图片归档状态。

**如果电脑已运行旧版图片整理助手，继续使用原程序即可。安装本 Skill 不会迁移旧程序；不要为同一个来源和目标再启动一份。** 下面的首次配置步骤面向新电脑或明确迁移后的安装。

## 首次配置本地后台

打开 PowerShell，设置 Skill 路径：

```powershell
$skillFolder = Join-Path $env:USERPROFILE '.codex\skills\wechat-image-archive'
```

找到你自己的微信文件存储位置、账户目录下的 `temp\RWTemp`。以下两个路径需要替换，不要原样执行示例路径：

```powershell
& "$skillFolder\scripts\manage.ps1" -Action Configure `
  -SourceRoot 'D:\微信文件\你的账户\temp\RWTemp' `
  -TargetFolder 'D:\图片归档'
& "$skillFolder\scripts\manage.ps1" -Action Start
```

如当前 PowerShell 执行策略阻止 `.ps1`，可用单次进程参数运行，不必修改系统执行策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$skillFolder\scripts\manage.ps1" -Action Status
```

脚本会优先检测本机 Codex 附带的 Python，然后检测 `PATH` 中的 Python。找不到时为各操作添加 `-PythonPath 'C:\你的Python目录\python.exe'`。

配置、状态、日志、OCR 结果放在 `%LOCALAPPDATA%\WeChatImageArchiveSkill`，不写入仓库。配置初始为停止状态；需执行 Start。也可以为每个命令添加同一个 `-RuntimeDir 'D:\本地运行数据'`，使用自选运行目录。Configure 不覆盖已有配置；更改路径前 Stop，再编辑运行目录中的 `config.json`。

## 日常使用

1. 电脑微信中，右键要保存的图片，选择“复制”。
2. 图片先保存到目标文件夹；几秒至约一分钟后完成本地 OCR 初步命名。
3. 需要准确订单金额等信息时，再人工核对；自动名称中的字段都是 OCR 提示。

```powershell
& "$skillFolder\scripts\manage.ps1" -Action Status
& "$skillFolder\scripts\manage.ps1" -Action Stop
& "$skillFolder\scripts\manage.ps1" -Action Start
```

Stop 后不再接收新图片；正在执行的 OCR 最多等待 75 秒结束，已保存的图片保留。重启 Windows 后需要重新 Start。不同运行目录之间没有共享锁，所以不要同时启动两套处理同一来源的程序。

## 保存到 GitHub：网页操作

1. 登录 GitHub，打开 <https://github.com/new>，仓库名填 `wechat-image-archive`，选择 Public（公开分享）或 Private（个人备份）。不勾选初始化 README、.gitignore、License，创建仓库。
2. 空仓库页面选择 **uploading an existing file**；已有文件的仓库选择 **Add file → Upload files**。
3. 打开准备好的源码文件夹，将**里面的全部文件和子文件夹**拖进上传区。上传后，根目录应直接显示 `SKILL.md`、`README.md`，另有 `agents/`、`scripts/`。不要多套一层 `wechat-image-archive/`。
4. 提交说明填 `Add local WeChat image archive skill`，按页面提示提交保存。

只上传此源码文件夹。不要上传图片归档目录、旧助手目录、运行配置、日志、OCR 缓存、微信账户目录或私人截图。网页上传不执行 `.gitignore` 过滤，上传前仍要确认清单。ZIP 便于备份和传输；GitHub 不会自动把上传的 ZIP 展开为仓库文件，请先解压再上传里面的源码。

官方操作说明：[上传文件到 GitHub 仓库](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)。

## 文件结构

```text
SKILL.md                 Codex 操作与边界说明
agents/openai.yaml       Skill 展示信息
scripts/manage.ps1       配置、启动、停止、状态入口
scripts/archive.py       本地后台、复制保存、去重和记录
scripts/naming.py        保守的 OCR 初步命名
scripts/ocr-image.ps1    Windows 本地 OCR
scripts/test_archive.py  隔离测试，不读取真实剪贴板
README.md                使用及 GitHub 上传指南
.gitignore               避免运行数据被 Git 跟踪
```

开发验证：`python -X utf8 scripts/test_archive.py`。不需要第三方 Python 包、付费服务或 API 密钥。
