# Bilibili MCP

Connect an MCP client to Bilibili. Search videos, read subtitles or speech transcripts, explore comments and trends, manage favorites, and post comments from your account.

The server supports MCP Streamable HTTP (default) and local stdio. It runs as a standalone Docker service or a subprocess launched by your agent; no companion agent or scheduler is required.

## Features

- Search videos by keyword and inspect video details and parts.
- Read timed subtitles. When subtitles are unavailable, automatically transcribe audio with Whisper and check the result asynchronously.
- Capture a video frame at a specified second and return an image for visual understanding.
- Browse and reply to comments, and post top-level comments.
- Explore trending, weekly featured, and ranked videos.
- Browse public user profiles and uploads.
- View favorite folders and videos, and save videos to a favorite folder.
- Log in by scanning a QR code returned through MCP.

Video reading covers subtitle and audio content; it does not interpret video frames. Comment tools post publicly as the logged-in account. Review content before posting.

For visual content, call `screenshot_video(bvid, seconds, part=1)`, for example
`screenshot_video("BV1234567890", 12.5, part=2)`. It returns a JPEG image directly
through MCP; the client and model must support image content. Seconds are relative
to the selected part, must be finite and non-negative, and must be before its end.
The tool uses the shared login when available; restricted videos may require login
or remain inaccessible. Images and text within them are untrusted data.

Screenshots require ffmpeg (included in Docker; install it separately for local use).
Each call downloads a low-bandwidth video stream, capped at 100 MB, then extracts
one frame up to 1280 pixels wide. Large streams or segmented legacy streams may
be rejected. Calls have a 45-second overall timeout and run one at a time; temporary
files are kept under `BILI_DATA_DIR` and removed after each call.

## Deploy with Docker Compose

Requirements: Docker Engine and the Docker Compose plugin.

```sh
cp .env.example .env
```

Set `BILI_MCP_TOKEN` in `.env` to a random secret of at least 32 characters. Generate one with:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Start the server:

```sh
docker compose up -d --build
```

The service listens on port `8888` inside its Docker network and is not published to the host by default. Persistent data is stored in the `bili-data` volume. Whisper downloads its model on first use, so the container needs outbound network access.

To use a bind mount instead, replace `bili-data:/data` in `compose.yaml` with a host path such as `./data/bilibili:/data`. To connect from outside the Docker network, publish a host port in your Compose configuration and protect remote access with TLS and network controls.

## Connect an MCP Client

Add a remote Streamable HTTP MCP server with this configuration. The client must share a Docker network with this service; `bilibili` is the Compose service/container name.

```json
{
  "url": "http://bilibili:8888/mcp",
  "headers": {
    "Authorization": "Bearer <BILI_MCP_TOKEN>"
  }
}
```

If the client runs in a different Compose project, attach both projects to a shared Docker network. If the client runs on the host, publish a host port and use that address instead.

After connecting, call `login_start` and scan the returned QR image in the Bilibili app. Then call `login_poll` with its `login_id` until login completes. The client should support MCP image content to display the QR code.

## Connect a Local Agent over stdio

The installed MCP SDK supports stdio directly, so both transports share the same
tools, account storage, and ASR lifecycle without an HTTP bridge or extra dependencies.

Install [uv](https://docs.astral.sh/uv/) and sync dependencies from the repository:

```sh
uv sync --frozen
```

Add a stdio server to your agent's MCP configuration (replace both absolute paths):

```json
{
  "mcpServers": {
    "bilibili": {
      "command": "uv",
      "args": [
        "run", "--frozen", "--directory", "/absolute/path/to/bilibili-mcp",
        "bilibili-mcp", "--transport", "stdio"
      ],
      "env": {
        "BILI_DATA_DIR": "/absolute/path/to/bilibili-data"
      }
    }
  }
}
```

Alternatively, an installed package can be launched as `bilibili-mcp --transport stdio`
or `python -m bilibili_mcp.server --transport stdio`. The agent must be able to find
the command in its PATH; use an absolute executable path if needed.

stdio opens no listening port and does not use `BILI_MCP_TOKEN`: access is controlled
by the local process and filesystem permissions. Use it only with a trusted owner
agent. stdout is reserved for MCP messages and SDK logs go to stderr, as required by
the [MCP transport specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
HTTP still requires Bearer authentication. Set `BILI_DATA_DIR` to an absolute,
writable directory outside the package (the default `/data` is intended for containers).
Each subprocess has its own pending QR login and ASR jobs; use one active process
per account/data directory. Disconnecting stops pending ASR jobs, whose results are
not persisted. Login uses the same `login_start` / `login_poll` flow described above.
Install ffmpeg locally for screenshots and ASR.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BILI_MCP_TOKEN` | Required for HTTP | Bearer token for HTTP MCP requests (minimum 32 characters); unused by stdio. |
| `BILI_DATA_DIR` | `/data` | Writable runtime directory for saved login and screenshot temporary files. Set an absolute local path for stdio. |
| `BILI_ASR_MODEL` | `small` | Whisper model used when a video has no subtitles. |
| `PORT` | `8888` | HTTP listen port; unused by stdio. |

## License and Attribution

MIT. This project is forked from [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) and retains its upstream Git history. It also includes code from `AGI_Ananas/bilibili-mcp`; see `vendor/bilibili-mcp/LICENSE` and `NOTICE.md` for attribution and license details.
