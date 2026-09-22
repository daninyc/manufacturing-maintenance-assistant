# Manufacturing Maintenance Assistant

制造设备运维知识助手，基于公开规格和模拟资产，提供可追溯文档问答、受权限约束的业务查询与多源证据汇总。当前不接入真实产线、不控制设备，也不确认故障根因。

## 当前状态

以当前源码为准：后端已实现受控 RAG 与固定多源诊断工作流；Windows 客户端已有页面和平台工程。客户端本轮未重新构建，已有测试记录不代表当前版本通过全部验收。

| 能力 | 当前实现 |
| --- | --- |
| 文档处理 | PDF/TXT、清洗分块、BGE 向量化、Chroma 持久化、文档与设备标签 |
| 问答 | 授权检索、距离门控、证据编号选择、原文引用与返回前权限复核 |
| 模型模式 | 后端支持 local 与 deepseek；local 是规则与证据摘录，并非本地大模型 |
| 业务查询 | SQLite 设备、报警、维修记录；参数化只读查询与资源权限过滤 |
| 辅助诊断 | 固定汇总知识、报警、维修证据；校验建议依赖及疑似冲突 |
| 身份与权限 | 登录、退出、会话撤销、账号管理、角色/部门/密级、独立外发许可 |
| 文档管理 | 策略版本、草稿、受控上传发布、下线、审计 |
| 使用入口 | FastAPI、Streamlit 验收页、Flutter Windows 客户端 |
| Windows 模式选择 | 当前页面固定 local；local／真实模型切换待实现 |
| 自主 Agent | 工具自主选择、多轮追问、持久任务、完整执行追踪和系统化 Agent 评测待实现 |

诊断的 `human_review` 是结果状态，尚无人工确认后恢复执行的任务机制。登录会话不等于对话记忆。现有 request_id、部分问答 trace 和测试脚本不等于完整 Agent 追踪与效果评测。

## 当前交付范围

- 保留 Windows 客户端；Android 不再作为当前开发、打包或验收目标，现有平台源码暂留。
- 保留当前单仓库布局。旧拆仓、手机局域网及云端迁移安排不再作为当前实施前置条件。
- 后端和管理/验收网页继续使用现有 Python、FastAPI 与 Streamlit。
- Windows 目标支持 local 和真实模型两种模式，真实模型由后端调用 DeepSeek。密钥不下发客户端，失败不静默切换模式。
- 多 Agent 协同、OCR、MCP 和云端部署后续按需求评估，当前先完善单 Agent 核心流程。

## 本机运行

项目使用 Python 3.12。以下命令从项目根目录 PowerShell 执行；首次安装、资料下载和模型下载需要网络。

```powershell
# 已有虚拟环境时不要重复创建。
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-api.txt
& '.\.venv\Scripts\python.exe' -m scripts.fetch_sources
& '.\.venv\Scripts\python.exe' -m scripts.prepare_model
```

已有环境可双击 `启动网页版验收.cmd`。默认页面为 `http://127.0.0.1:18501`；启动器建立隔离模拟数据，账号保存在本机 `data/acceptance-web/验收账号（勿上传）.txt`。按 Ctrl+C 停止本次启动的服务。此入口是网页验收，不证明 Windows App 的证书和业务联调已通过。

Windows 开发、分析和构建入口见 [客户端说明](clients/flutter_app/README.md)。服务配置见 [服务启动](docs/server-startup.md)，接口见 [认证与 API](docs/auth-api.md)。

## 模型配置与资料版本

在本机 `.env` 配置 `DEEPSEEK_API_KEY` 与 `DEEPSEEK_MODEL`；参考不含真实密钥的 `.env.example`。local 不需要模型密钥，deepseek 会真实外发获准上下文并产生调用费用。

本次模拟资料统一使用中性名称，内容和版本已变化。旧本地索引不会自动更新：基础问答使用 `scripts.ingest` 重建对应资料；受保护问答须按 [受控发布流程](docs/document-upload.md) 重新发布，并重新生成内容版本。不要通过放宽校验来继续使用旧索引。

## 验证

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.customer_acceptance_checks --suite offline
& '.\.venv\Scripts\ruff.exe' check app scripts tests ui --no-cache
& '.\.venv\Scripts\python.exe' -m pip check
```

offline 结果会写入本机独立时间戳目录。查看 passed、failed、skipped 和 warnings，不将跳过记为通过。model/web 套件会真实调用 DeepSeek，需单独选择运行。

## 源码导航

| 目录 | 职责 |
| --- | --- |
| app/api、app/auth、app/security | HTTP、会话、授权与策略 |
| app/ingestion、app/retrieval | 资料发布、向量与检索 |
| app/services | 受控问答、业务查询、诊断和证据校验 |
| app/db、app/schemas | SQLite 与数据契约 |
| clients/flutter_app | Windows 客户端与保留的平台工程 |
| scripts、ui、tests | 运行命令、管理/验收网页、回归检查 |
| data/raw_docs、data/seed、data/eval | 可公开的资料摘要、模拟种子和评测样例 |

参阅 [当前架构](docs/architecture.md)、[Agent 核心能力升级计划](docs/Agent核心能力升级计划.md)、[核心功能](docs/Agent核心功能与实现原理.md)、[授权规范](docs/authz-spec.md) 和 [来源与许可](LICENSE-NOTICES.md)。

## 数据与发布边界

资产、报警和维修记录是模拟数据；SIM-* 不是厂商报警代码。规格摘要引用厂商资料，但不替代原版手册。厂商 PDF 未确认再分发许可，不纳入仓库。

不提交模型密钥、账号凭证、会话库、业务数据库、向量索引、证书私钥、SDK 和构建缓存。公开结果仅使用脱敏模拟数据。性能、准确率和生产可用性须由对应版本的实测支持。
