# SpeedAI 降AI率与AIGC检测：技能与 MCP（speedai-jiangai）

[SpeedAI](https://speedai.com) 的官方技能（Skill）和 MCP 连接器：在 AI 助手里给论文**降 AIGC 率、降重、润色、做 AIGC 检测**，支持整篇 Word 文档和 AIGC 检测报告（PDF），检测口径覆盖知网、维普、万方、格子达、大雅、Turnitin、GPTZero。

和 speedai.com 网页同一套模型与检测，扣费规则一致，积分通用。积分不足时可以在对话里创建充值订单，由你本人扫码支付。

- 技能：[`skills/speedai-jiangai`](skills/speedai-jiangai)（教 AI 先检测、只改高风险段落，长文自动切分，改完核对数据和引用）
- MCP 地址：`https://api.speedai.com/mcp`（Streamable HTTP，支持 OAuth 一键连接或 API Key）
- 本地 MCP：`npx -y speedai-cn-mcp`
- 文档：<https://speedai.com/open/docs>

## 一句话安装（推荐）

把这句话发给你的 AI 助手，它会自己装好：

```text
帮我安装 SpeedAI 降AI率与AIGC检测技能，按 https://speedai.com/skill/install.txt 的步骤操作
```

适用于能运行命令的助手。安装文件从 speedai.com 下载，国内网络也能顺利安装。

### 国内

| 应用 | 安装技能 | 连接 MCP |
|---|---|---|
| [科搭 Codar](https://speedai.com/codar) | 开箱即用：已内置，登录科搭即可用 | 已内置，不用填 Key |
| WorkBuddy | 一句话安装；或放到 `~/.workbuddy/skills` | 「连接器 → + 自定义连接器」会打开 `~/.workbuddy/mcp.json`，加入下方配置 |
| 豆包工作 | 下载 [技能包](https://speedai.com/downloads/speedai-jiangai-skill.zip) 发给豆包，说「帮我安装这个技能」；或「插件·技能·伙伴 → 技能 → + 添加 → 上传技能」 | 「插件·技能·伙伴 → 新建 → 新建自定义连接器」 |

### 海外

| 应用 | 安装技能 | 连接 MCP |
|---|---|---|
| Codex | 一句话安装，或 `npx skills add SpeedAI-team/speedai-skills` | `~/.codex/config.toml` 加 `[mcp_servers.speedai]` |
| Claude Code | 一句话安装，或 `/plugin marketplace add SpeedAI-team/speedai-skills` 后 `/plugin install speedai-jiangai@speedai`（技能 + 连接器一起装） | `claude mcp add --transport http speedai https://api.speedai.com/mcp` |
| pi | 一句话安装，或 `npx skills add SpeedAI-team/speedai-skills` | — |
| Cursor | 一句话安装，或 `npx skills add SpeedAI-team/speedai-skills` | 「Settings → MCP」添加 `https://api.speedai.com/mcp` |

每个客户端的完整 MCP 配置见 [MCP 接入文档](https://speedai.com/open/docs/mcp)。

### 通过 GitHub 链接安装

```text
# Claude Code（技能 + 连接器）
/plugin marketplace add https://github.com/SpeedAI-team/speedai-skills
/plugin install speedai-jiangai@speedai
```

Claude 桌面版：「插件（Plugins）→ 添加（Add）→ 添加插件市场」，粘贴本仓库链接，再搜索 `speedai-jiangai` 安装。

```bash
# Codex、Cursor、pi 等
npx skills add https://github.com/SpeedAI-team/speedai-skills
```

也可以对 AI 助手说：「从 https://github.com/SpeedAI-team/speedai-skills 安装 SpeedAI 降AI率与AIGC检测技能」。

### WorkBuddy 连接器配置

WorkBuddy 的自定义连接器是配置文件，没有填地址的输入框。在「连接器」点「+ 自定义连接器」，在打开的 `~/.workbuddy/mcp.json` 的 `mcpServers` 里加入：

```json
"speedai": {
  "type": "streamableHttp",
  "url": "https://api.speedai.com/mcp",
  "headers": { "Authorization": "Bearer <你的 API Key>" },
  "timeout": 600000
}
```

保存后回到连接器列表确认已启用。

## 连接账号

技能脚本需要 API Key：在 <https://speedai.com/open/console/keys> 创建，然后在终端运行并粘贴（输入不显示）：

```bash
python3 ~/.agents/skills/speedai-jiangai/scripts/speedai.py set-key
```

Key 保存在 `~/.speedai/credentials.json`（仅本人可读），也可以用环境变量 `SPEEDAI_API_KEY`。通过 MCP 连接器使用时，支持 OAuth 的应用（Claude、Claude Code 等）用 speedai.com 账号授权即可，不需要 Key。

## 用法示例

- 「把这段降一下知网 AIGC 率：……」
- 「检测这段的 AI 率，按维普的标准」
- 「把这篇 Word 论文按知网降 AIGC，做完保存到桌面」
- 「给这篇论文出一份 AIGC 检测报告」

## 仓库内容

| 路径 | 说明 |
|---|---|
| `skills/speedai-jiangai/` | 技能：`SKILL.md`、`scripts/speedai.py`（只用 Python 标准库）、`references/platforms.md` |
| `.claude-plugin/` | Claude Code 插件与插件市场定义 |
| `.mcp.json` | 插件自带的远程 MCP 连接器 |
| `server.json` | [MCP Registry](https://registry.modelcontextprotocol.io) 登记信息 |

---

## English

Official SpeedAI skill and MCP server for lowering AIGC (AI-generated content) scores, reducing similarity, polishing and checking the AI rate of Chinese academic writing, including whole Word documents and AIGC detection reports. Same models, pricing and credits as speedai.com.

- Install the skill: `npx skills add SpeedAI-team/speedai-skills`, or tell your agent: *"Install the SpeedAI AI Rate Reducer & AIGC Detector skill by following https://speedai.com/skill/install.txt"*
- Claude Code plugin (skill + MCP): `/plugin marketplace add SpeedAI-team/speedai-skills`, then `/plugin install speedai-jiangai@speedai`
- Remote MCP: `https://api.speedai.com/mcp` (OAuth or `Authorization: Bearer <API key>`); local: `npx -y speedai-cn-mcp`
- API keys: <https://speedai.com/open/console/keys> · Docs: <https://speedai.com/open/docs>

## License

MIT
