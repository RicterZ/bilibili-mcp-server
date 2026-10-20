# 第三方代码与署名说明

本插件（`dsh-bili-scroll` / 刷B站）本体以 **MIT** 协议发布，正文见仓库根目录的 `LICENSE`。

## 内含第三方代码

- 目录：`vendor/bilibili-mcp/`
- 项目：**bilibili-mcp**
- 许可证：**MIT**，Copyright (c) 2026 AGI_Ananas
- 完整许可见该目录下的 `LICENSE`

## 关于版权署名

`LICENSE` 第一行写的是 `Copyright (c) 2026 c1overzz`。
如果你要基于本仓库做二次分发，保留这一行和 MIT 正文即可，不必另行取得授权（MIT 本身就允许改、再发、商用）。

---
*本文件只是说明，不构成额外限制。*
## 独立服务改造

本仓库现为独立 Python MCP Server，不再是 DSH 插件。`src/bilibili_mcp/`
的 B 站 API、扫码持久化及转写流程参考上述 AGI_Ananas vendor 与
c1overzz/dsh-bili-scroll 的 `lib/asr.py`（MIT）重新组织；保留双方许可证与 Git 历史。
未将 DSH 的调度、设置页或账号公开写入工具移入新服务。
