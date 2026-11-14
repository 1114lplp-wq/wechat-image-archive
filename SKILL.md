---
name: wechat-image-archive
description: Configure, start, stop, or troubleshoot a local Windows workflow that saves images actively copied from desktop WeChat and gives them conservative OCR-based filenames. Use for 微信图片复制自动保存、截图归档、自动初步命名, or packaging this workflow for another computer. Also supports explicitly requested manual verification of its saved images. It does not collect incoming chat messages or run recurring AI review.
---

# 微信图片复制归档

Use the bundled local collector for continuous clipboard work. A Skill supplies instructions and scripts; the collector is the process that stays running. Saving and Windows OCR make no model/API/network calls. Model usage applies when the user invokes an AI conversation or explicitly asks for visual review.

## Preserve the existing setup

- Inspect the user's known configuration and collector status before changing anything. Reuse a working existing collector; do not start this collector alongside an older collector for the same WeChat source and destination. Installing this Skill does not migrate or restart an older installation.
- A legacy installation may be named `微信截图整理助手` in the user's supplied workspace, with `config.json`, `image_assistant.py`, `background.py`, `start.ps1`, and `stop.ps1`. Inspect and use that installation's own lifecycle scripts when maintaining it. Its configuration schema differs; never point this Skill's new manager at a legacy runtime.
- Preserve the user's stopped/paused state. Never create or resume an AI automation, schedule, startup task, cloud upload, or recurring review as part of this workflow.
- Do not read chat databases, encryption keys, process memory, other chat contents, or encrypted cache files. Do not operate the WeChat UI or send messages.
- Only consume file paths supplied by an active native clipboard copy and located beneath the configured plaintext `temp/RWTemp/YYYY-MM/` directory. Do not scan WeChat folders for incoming files. The collector requests CF_HDROP; WeChat may export the copied image on demand. Unsupported clipboard formats require troubleshooting, never expanded collection.

## Configure and operate

Read [README.md](README.md) for user-facing commands and GitHub packaging instructions. Requirements: Windows 10/11, Python 3.11+ with `pythonw.exe`, desktop WeChat exposing copied images as CF_HDROP files, and a Windows OCR language. OCR failure still saves the image.

Use the absolute path to `scripts/manage.ps1` for these commands:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-folder>\scripts\manage.ps1" -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-folder>\scripts\manage.ps1" -Action Configure -SourceRoot "<wechat-account>\temp\RWTemp" -TargetFolder "<destination-folder>"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-folder>\scripts\manage.ps1" -Action Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-folder>\scripts\manage.ps1" -Action Stop
```

Runtime defaults to `%LOCALAPPDATA%\WeChatImageArchiveSkill`. `-RuntimeDir` selects another isolated runtime; use the same value for all actions. `-PythonPath` selects a Python executable. Configure creates a stopped config and refuses to overwrite an existing config. Stop before editing config. Start only when requested and only after checking for a conflicting older collector.

The user right-clicks an image in any desktop WeChat chat and chooses **复制**. No further copying, opening, or saving is needed. The current copied image may be consumed when the collector starts. Single-instance locking prevents duplicate processes within one runtime. There is no login startup registration; restarting Windows requires Start again.

## Naming and data integrity

- Save original bytes and original extension before OCR. Use SHA256 deduplication, verify copied bytes, and never overwrite existing names. Do not delete source or destination images.
- Automatic names are **待核对_[labelled date]_平台订单或内容类型_商品或标题_[订单尾号或摘要]**. All OCR-derived fields are provisional. Unclear values are omitted or marked pending. Never place a guessed amount in an automatic filename; especially do not treat discounts as payments.
- A date needs a relevant label such as 下单时间/付款时间/签订日期. Do not use an expiry or delivery date. Do not infer people's identities in photographs.
- Runtime `records/*.json` stores SHA256, current filename, status, and unverified OCR hints. `ocr-cache` and records are local private data. They are not a queue for a scheduled AI process.
- Never rename pre-existing destination images automatically. If the user renames or edits a newly saved file while OCR is running, preserve the change and record `skipped_user_changed`. Persisted SHA256 deduplication does not recreate files the user later moves or deletes.

## Optional manual visual review

Only when explicitly requested, inspect up to 20 records with `local_ocr_unverified`, `ocr_failed`, or `saved_review_deferred` status. Restrict reads to that runtime's records and their referenced images inside its configured destination. Verify SHA256 before opening each image with a local image viewing tool. Do not rely on OCR alone for digits.

Verify visible order date, platform, product/contract subject, actual amount paid, and order number. Name as `日期_平台订单或内容类型_商品或主体_实付金额_订单号尾号` using only clearly visible fields; omit uncertain fields or mark 待确认. Keep bytes and extension, avoid collisions, and recheck SHA256 afterward. Update the record to `verified` or `reviewed_with_uncertainty`, including final filename, checked fields, uncertainty, and time. If missing, edited, or user-renamed, record a skip and preserve the user's version. Never search other folders to recover it. Do not upload images.

## Troubleshoot and test

Run Status first; inspect only this runtime's `watcher.log` if needed. Confirm a background process exists, config is enabled, source root belongs to the right account, and the active copy yields CF_HDROP. Unsupported clipboard formats, changed WeChat versions, or missing exported files may prevent capture; report that limitation without collecting more broadly. OCR failure is separate from saving failure.

Run `python -X utf8 "<skill-folder>\scripts\test_archive.py"` for isolated checks. Tests never read the real clipboard or chat data. Runtime data must stay outside the Skill/repository. See `.gitignore`; package only code and documentation.
