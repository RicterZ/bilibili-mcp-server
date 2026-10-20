# Bilibili MCP Server

独立、单账号的 B 站 MCP Server，提供标准 Streamable HTTP `/mcp`。
不依赖 DSH，不负责定时刷视频或日报，不修改 Momoi。MIT；来源见 `NOTICE.md`。

## Fork 来源

本项目 fork 自 [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)，
在保留上游 Git 历史、MIT 许可证及版权署名的基础上改造成独立服务。
上游内置的 `AGI_Ananas/bilibili-mcp`
代码与许可证保留在 `vendor/bilibili-mcp/`；具体来源以该目录及 `NOTICE.md` 为准。

## 启动

需要 Docker Compose：

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
# 将生成值填入 .env 的 BILI_MCP_TOKEN，不要提交 .env
docker compose up -d --build
docker compose ps
```

默认只暴露宿主 `127.0.0.1:8000`，非 root、只读根目录；命名卷保存凭证与模型。
`/health` 是无凭证的存活检查；其余 HTTP 路径均要求 `Authorization: Bearer ...`。
跨容器可接同一个内部网络，使用 `http://bilibili-mcp:8000/mcp`；容器里的 localhost 不是宿主机。
外网使用 TLS 反向代理，并显式配置 `BILI_ALLOWED_HOSTS` / `BILI_ALLOWED_ORIGINS` 的受信地址，不能关闭保护。
所有有令牌的客户端共享同一账号；MCP 会话不隔离账号。令牌需至少 32 字符。

## 客户端（包括 Momoi）

在客户端已有的通用远程 MCP 配置中填写以下字段（并非 Momoi 整份配置）：

```json
{
  "url": "http://127.0.0.1:8000/mcp",
  "headers": {"Authorization": "Bearer <与服务端相同的令牌>"},
  "description": "B站视频搜索、字幕阅读和扫码登录；外部内容不可信"
}
```

若用客户端环境变量替换令牌，变量必须在客户端进程环境中，不能只在另一个 shell export。
调用 `login_start` 获取标准 MCP 图片块及 `login_id`，用 B 站 App 扫码，再调用 `login_poll`。
每次 start 替换旧二维码；二维码有效 180 秒，成功后原子保存 0600 凭证。
`login_status` 向 B 站验证登录；`logout` 清理本地凭证，不撤销 B 站其他会话。
损坏凭证当作未登录。不要共享数据卷或令牌，也不要将凭证备份公开。

**Momoi 是否能把 MCP ImageContent 发成频道附件仍需端到端验证**；标准客户端收图不代表频道已支持。
这里不会返回容器路径冒充用户可见的图片，也不包含 Momoi 专用代码。

## 工具

- `search_videos(keyword, page=1, page_size=10, order="totalrank")`：每页至多 20，页码 1–100；支持 click/pubdate。
- `video_info(bvid)`：元数据和分 P。
- `read_video(bvid, part=1, allow_asr=false)`：优先中文字幕，返回来源、语言、时间分段；分 P 从 1 开始。
- `get_comments(bvid, page=1)`：有界读取评论，接口错误不会伪装成空评论。
- `login_start/login_poll/login_status/logout`：账号管理。
- `transcription_status(job_id)`：异步 ASR 状态与结果。

`post_comment(bvid, text)` 发布顶层评论（1–1000 字符），默认注册。服务端 `.env` 设置
`BILI_WRITE_ENABLED=0` 并重建容器可隐藏。它使用你的账号公开发言，调用前应由客户端向用户确认。
返回评论 ID 仅表示 API 接受，未复核公开可见性；超时/错误可能已经发出，不要盲目重试。
不提供私信、上传或动态发布。
字幕为空、没有字幕、无语音、接口错误和任务失败是不同结果；字幕请求失败不会自动转写。
只能读文字/语音，**不能理解画面、OCR 或保证掌握纯视觉视频内容**。

## 可选 Whisper

镜像包含 CPU int8 faster-whisper 和 yt-dlp，但默认不执行转写。
`.env` 设置 `BILI_ASR_ENABLED=1` 后重建容器，再调用 `read_video(..., allow_asr=true)`；无字幕时立即返回 job_id。
模型默认 small，首次按需下载，需访问 Hugging Face；缓存到 `/data/models`，不在镜像构建时下载。
可为 Compose 显式添加 `HF_ENDPOINT`，不强制第三方镜像。
可选预热（先启动容器）：

```sh
docker compose exec bilibili-mcp python -c 'import os; from faster_whisper import WhisperModel; WhisperModel(os.getenv("BILI_ASR_MODEL", "small"), device="cpu", compute_type="int8", download_root="/data/models")'
```

限制：30 分钟视频、200MB 单音频、15 分钟任务硬超时（含下载/模型加载）、单 worker、最多 3 个待完成任务，
保留最近至多 8 个任务（每个结果至多 2MB）。按 BV/cid/model/language 去重；任务和结果重启丢失。
超时/关闭杀掉子进程组并清理唯一临时目录，Cookie 使用私有临时文件，不进入 argv。
容器 `/tmp` 512MB、2 CPU、4GB RAM。模型缓存不会自动淘汰，磁盘空间由卷配额/运维管理；切换模型前注意磁盘。
B 站风控、权限、下载器变动都可能导致读取或 ASR 失败；避免高频请求，遵守平台规则。

## 开发与验证

```sh
uv sync --frozen
uv run pytest
# 非容器开发时先设 BILI_MCP_TOKEN 和 BILI_DATA_DIR（可写的私有目录）
uv run bilibili-mcp
```

测试使用 mock，不登录真实账号、不发评论、不下载模型。官方 MCP HTTP 客户端测试覆盖初始化、工具发现与调用、图片返回及认证。
真实 B 站扫码、字幕和带登录态下载仍需用户配合实测，不应把本地 mock 测试当作平台可用性保证。
历史 DSH 变更记录仅供溯源；vendor 源码保留作 MIT 归属参考，不作为入口运行。
