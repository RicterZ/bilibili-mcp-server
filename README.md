# Bilibili MCP

Connect an MCP client to Bilibili. Search videos, read subtitles or speech transcripts, explore comments and trends, manage favorites, and post comments from your account.

The server uses MCP Streamable HTTP and works with any compatible MCP client. It runs as a standalone Docker service; no companion agent or scheduler is required.

## Features

- Search videos by keyword and inspect video details and parts.
- Read timed subtitles. When subtitles are unavailable, automatically transcribe audio with Whisper and check the result asynchronously.
- Browse and reply to comments, and post top-level comments.
- Explore trending, weekly featured, and ranked videos.
- Browse public user profiles and uploads.
- View favorite folders and videos, and save videos to a favorite folder.
- Log in by scanning a QR code returned through MCP.

Video reading covers subtitle and audio content; it does not interpret video frames. Comment tools post publicly as the logged-in account. Review content before posting.

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

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BILI_MCP_TOKEN` | Required | Bearer token for MCP requests (minimum 32 characters). |
| `BILI_ASR_MODEL` | `small` | Whisper model used when a video has no subtitles. |

## License and Attribution

MIT. This project is forked from [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) and retains its upstream Git history. It also includes code from `AGI_Ananas/bilibili-mcp`; see `vendor/bilibili-mcp/LICENSE` and `NOTICE.md` for attribution and license details.
