# Bilibili MCP Server

让 AI 搜索 B 站、读懂视频内容、查看讨论并发表评论。
独立部署，通过标准 MCP Streamable HTTP 接入 Momoi 或其他 MCP 客户端。

## 功能

- **搜索视频**：按关键词搜索，支持综合、播放量和最新排序。
- **阅读视频**：优先读取字幕；没有字幕时自动使用 Whisper 转写音频，支持分 P 和时间分段。
- **评论互动**：读取视频评论，使用已登录账号发布顶层评论。
- **扫码登录**：通过 MCP 返回二维码，手机确认后保存登录状态，重启无需重复扫码。

所有功能开箱可用，无需额外开启 ASR 或评论。视频阅读仅基于字幕和语音，不分析画面。

## 快速启动

需要 Docker Compose。在仓库目录执行：

```sh
cp .env.example .env
# 生成访问令牌，将结果填入 .env 的 BILI_MCP_TOKEN
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up -d --build
```

服务地址为 `http://127.0.0.1:8000/mcp`。登录凭证和模型保存在 Docker 命名卷中。
默认限制为 2 CPU、4 GB 内存；首次转写会下载 Whisper 模型，需要访问 Hugging Face。

## 接入 MCP 客户端

在客户端的远程 MCP 配置中填写：

```json
{
  "url": "http://127.0.0.1:8000/mcp",
  "headers": {
    "Authorization": "Bearer <你的 BILI_MCP_TOKEN>"
  },
  "description": "搜索 B 站视频、阅读字幕或语音转写、查看和发表评论"
}
```

客户端需支持 Streamable HTTP；显示登录二维码还需支持 MCP 图片内容。
同一 Docker 网络中的客户端可使用 `http://bilibili-mcp:8000/mcp`。

接入后，让 AI 调用 `login_start` 展示二维码，用 B 站 App 扫码确认，再调用 `login_poll` 完成登录。
Momoi 的频道二维码投递尚未端到端验证。

## 配置

在 `.env` 中配置，修改后执行 `docker compose up -d`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `BILI_MCP_TOKEN` | 必填 | MCP 访问令牌，至少 32 字符 |
| `BILI_ASR_MODEL` | `small` | Whisper 模型，如 `tiny`、`base`、`small`、`medium` |
| `BILI_ALLOWED_HOSTS` | 本机与服务名 | 允许的请求 Host，逗号分隔；远程部署时填写实际域名和端口 |
| `BILI_ALLOWED_ORIGINS` | 本机 HTTP 地址 | 允许的浏览器 Origin，逗号分隔；浏览器跨域接入时配置 |

默认仅监听宿主机回环端口。远程访问请配置 TLS 反向代理和对应 Host/Origin；不要公开令牌或数据卷。
所有客户端共享同一个 B 站账号，仅适合受信任的个人使用。

## 工具

| 工具 | 用途 |
| --- | --- |
| `search_videos` | 搜索视频 |
| `video_info` | 获取详情和分 P 信息 |
| `read_video` | 读取字幕，无字幕时返回 ASR 任务 ID |
| `transcription_status` | 查询转写进度与结果 |
| `get_comments` | 分页读取评论 |
| `post_comment` | 发布顶层评论 |
| `login_start` / `login_poll` | 创建二维码、完成扫码登录 |
| `login_status` / `logout` | 检查登录、清除本地登录状态 |

ASR 支持最长 30 分钟视频，单任务限时 15 分钟，单并发处理；任务与转写结果不跨重启保留。
评论会以你的账号公开发出，请确认内容；发送超时可能已经成功，不要盲目重试。

## 开发

```sh
uv sync --frozen
uv run pytest
```

本地运行需设置 `BILI_MCP_TOKEN` 和可写的 `BILI_DATA_DIR`，然后执行 `uv run bilibili-mcp`。

## 来源与许可

Fork 自 [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)，
保留上游 Git 历史、MIT 许可证与版权署名，并改造为不依赖 DSH 的独立服务。
上游内置的 `AGI_Ananas/bilibili-mcp` 源码及许可证保留在 `vendor/bilibili-mcp/`。
详见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。
