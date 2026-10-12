# MyClaw：组内 AI 新闻与专题论文自动推送

把一个正在运行的 OpenClaw 推送系统整理成可复用、脱敏的部署仓库。
包含 3 个 Skills、7 个定时任务和自动安装脚本。

OpenClaw 负责调度与飞书投递；Python 负责抓取、调用 Codex 和校验；
Codex 原生搜索负责专题论文检索与来源核验。输出为中文 Markdown。

## 默认推送安排

全部使用 `Asia/Shanghai` 时区。

| 时间 | 内容 |
| --- | --- |
| 周一 11:40 | Model Reuse / Model Routing / Model Selection |
| 周二 11:40 | Tabular / Time Series / Structured Data Foundation Models |
| 周三 11:40 | Continual Learning / Test-Time Adaptation / Meta-Learning / Few-shot & Efficient Adaptation |
| 周四 11:40 | LLM Post-training / RLVR / Reward-Value Model / Verifier / Test-time Scaling |
| 周五 11:40 | Multimodal LLM / VLM / MLLM Evaluation & Adaptation |
| 每天 14:00 | Juya AI Daily 新闻概览 |
| 每天 14:05 | Hugging Face Daily Papers Top 10 |

周报统计上一完整自然周（周一至周日），保留六节结构、原始来源链接、
精选论文、3 篇精读推荐、关键词和讨论问题。优先高质量论文，不凑数。
每个周报任务总超时 40 分钟；格式错误自动返修最多两次，仍需通过校验后才投递。
HF 中文摘要不可用时退回带明确说明的官方英文摘要，不发送空白截图。

## 快速部署

目标环境：Linux 服务器、可用的 systemd 用户服务、Python 3.11+、
Node.js 22.22.3+ 或 24.15+、npm 和 Git。运行用户需要能安装 npm 全局包。
Mac/Windows 上的脚本可能可用，但本仓库的安装流程未在这些平台验证。

```bash
git clone https://github.com/Hunter-Wrynn/MyClaw.git
cd MyClaw
cp .env.example .env
chmod 600 .env
# 用编辑器填写 .env 中的四个 FEISHU_* 参数。
bash install.sh --install-deps
```

这条命令安装 `versions.json` 锁定的 OpenClaw/Codex，检测 Codex 登录，
生成当前用户的本地配置，复制 Skills，安装并启动网关，注册 7 个定时任务。
已经登录时直接沿用本机登录；没有登录时会提示使用自己的账号完成设备码授权。
账号授权和飞书应用审批需要使用者亲自完成，不能由公开仓库预先提供。
Codex 安装与授权方式见 [官方 CLI 文档](https://developers.openai.com/codex/cli) 和
[官方认证文档](https://developers.openai.com/codex/auth)。

依赖已安装时使用 `bash install.sh`。若不创建 `.env`，安装器会以隐藏输入
方式询问四个参数；环境变量也可提供参数，且优先于 `.env`。
环境文件按数据解析，内容不会作为 shell 命令执行。

```bash
bash install.sh --dry-run                  # 只校验参数并查看计划
bash install.sh --non-interactive          # 已配好参数且 Codex 已登录
git config core.hooksPath .githooks         # 启用提交前隐私检查
```

重复执行安装会按任务名称更新已有任务，不会重复注册。
安装仅注册任务，不会当场触发一次日报。

## 需要自己提供的参数

| 参数 | 含义 |
| --- | --- |
| `FEISHU_APP_ID` | 自建飞书机器人应用的 App ID |
| `FEISHU_APP_SECRET` | 应用 App Secret |
| `FEISHU_CHAT_ID` | 要接收推送的群聊 ID |
| `FEISHU_OWNER_OPEN_ID` | 允许在群里触发机器人的用户 Open ID；必须属于同一机器人应用 |
| `MYCLAW_CODEX_MODEL` | 默认 `gpt-5.6-sol`；可改为自己的 Codex 账号有权调用的模型 |
| `MYCLAW_TIMEZONE` | 默认 `Asia/Shanghai` |
| `MYCLAW_GATEWAY_PORT` | 默认 `15110` |

飞书后台需要创建自建应用、启用机器人、授权消息接收/发送权限，选择
WebSocket 长连接事件订阅并订阅 `im.message.receive_v1`，发布应用并把机器人加入目标群。
具体权限随应用场景配置，参见 [OpenClaw 飞书配置文档](https://docs.openclaw.ai/channels/feishu)。

群聊中只有配置的用户 @ 机器人时可以触发回复，其他成员保持静默。
定时任务主动推送照常进行。私聊使用 pairing，需要单独配对授权。

## 本地文件与已有实例

默认配置写入安装用户的 `~/.openclaw/openclaw.json`，权限 `600`；
Skills 写入 `~/.openclaw/workspace/skills/`。运行文件都在 Git 仓库之外。
备份位于状态目录的 `myclaw/backups/`，被拒绝的周报草稿位于工作区的 `.artifacts/`。

如果机器已经有另一套 OpenClaw，安装器会拒绝直接覆盖。
确认要替换时使用 `bash install.sh --update`，原配置和改变的工作区文件会先备份。
这会替换配置模板涉及的整个 OpenClaw 配置；不保留原实例额外插件/API 提供方设置。
升级 MyClaw 自己管理的安装时可直接再次运行安装命令。

默认网关只监听本机，且生成独立随机令牌。这里没有复制原部署的公网管理页面、
不安全认证开关或机器专属路径。服务器关机、用户服务停止或账户授权失效会影响推送。
需要退出登录后仍持续运行的 Linux 服务器可由管理员为运行用户启用 systemd linger。

可在 `.env` 中使用绝对路径设置 `MYCLAW_STATE_DIR`、`MYCLAW_WORKSPACE`、
`MYCLAW_CODEX_BIN`、`MYCLAW_PYTHON_BIN`。换状态目录的服务仍使用同一用户的默认网关
服务名；在同一用户下并行运行多实例，请自行使用 OpenClaw 的命名 profile/服务。

## 本地测试与补发

以下是默认安装目录的示例，只在终端输出 Markdown，不发送到飞书：

```bash
python3 ~/.openclaw/workspace/skills/ai-daily/scripts/fetch_ai_daily.py
python3 ~/.openclaw/workspace/skills/hf-daily/scripts/fetch_hf_daily.py --force-fallback
python3 ~/.openclaw/workspace/skills/weekly-domain-paper-review/scripts/run_codex_weekly.py \
  --preset monday-routing --print-prompt
python3 ~/.openclaw/workspace/skills/weekly-domain-paper-review/scripts/run_codex_weekly.py \
  --preset monday-routing --start YYYY-MM-DD --end YYYY-MM-DD --diagnostics
```

```bash
openclaw cron list
openclaw channels status --channel feishu
openclaw cron runs --id YOUR_JOB_ID --limit 5
# 注意：下一条会立刻执行，并向配置的群发送结果。
openclaw cron run YOUR_JOB_ID
```

自定义状态目录时，为 OpenClaw 命令设置对应的 `OPENCLAW_STATE_DIR` 和
`OPENCLAW_CONFIG_PATH`；模型及脚本路径在注册任务时已写入任务的环境变量。

## 隐私与维护

本仓库使用人工选择的导出文件清单，没有上传整个运行目录。
以下内容没有进入仓库：Codex 登录 JSON/TOML、API key、飞书 App Secret、
真实群 ID/用户 ID、网关令牌、个人记忆、聊天会话、运行日志、数据库和原始失败草稿。

提交前运行：

```bash
python3 scripts/check_privacy.py
python3 -m unittest discover -s tests -v
bash -n install.sh .githooks/pre-commit
```

维护者还可用 `check_privacy.py --compare-local /path/to/private-config.json`
对照本机凭证进行内存比较；检查只输出文件位置和问题类型，不打印私密值。
`.gitignore`、提交钩子和 GitHub Actions 一起检查隐私与离线测试。
检测器用于阻止常见误提交，不能代替对新增文件的审查。

模板位于 `templates/`，专题关键词与完整提示词在周报 runner 的 `PRESETS` 和
`build_prompt()` 中。版本升级请先在独立环境检查 CLI 参数、插件配置和任务投递，
再更新 `versions.json`。本仓库复制的是推送功能与研究模板，每次实时生成的论文内容会变化。
