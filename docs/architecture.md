# 当前架构

依据当前源码整理。当前实现是受控 RAG 与固定多源诊断工作流，尚未实现自主工具调用循环或多轮任务状态机。

## 请求路径

Windows / Streamlit → FastAPI → 服务端认证 → 资源授权 → 文档或业务查询 → 证据校验 → 返回前复核 → 客户端。

| 路径 | 实现与边界 |
| --- | --- |
| 问答 | protected_qa.authorized_answer：授权范围检索、权威后过滤、距离门控、证据选择、原文引用、最终复核 |
| 业务查询 | protected_data.ProtectedMaintenance：设备、报警、维修记录的参数化只读查询，权限先于分页 |
| 诊断 | diagnosis_service.diagnose：固定查询设备、报警、维修与知识；受控选择证据和 SOP 建议 |
| 模型输出 | evidence / diagnosis_selection：本次请求编号、结构校验、建议依赖与疑似冲突校验 |
| 发布 | ingestion.publication：内容快照、版本、发布状态与失败关闭；SQLite 与 Chroma 非跨库原子事务 |
| 客户端 | Windows 页面目前固定 local；后端支持 local/deepseek，页面模式切换待实现 |

## 已有模块

- app/api/server.py：鉴权 API、输入限制、错误码与引用重查。
- app/auth/sessions.py：身份、会话、到期和撤销。
- app/security：读取/管理/外发许可、资源策略、版本和审计。
- app/retrieval：BGE/Chroma 检索及设备范围；旧 hash 基线不代表当前语义能力。
- app/services：证据与业务流程；不执行模型生成 SQL 或设备动作。
- app/db：模拟业务 SQLite，使用受限只读查询。
- ui：API 网页工作台；clients/flutter_app：Windows 主展示客户端。

## 待补能力

模型选择受控工具 → 参数校验与授权执行 → 观察结果并选择下一步 → 缺信息追问或有证据结束。该循环、多轮上下文、任务持久化、完整事件记录与 Agent 评测尚未落地。

local 是确定性规则与摘录，不能称为本地大模型 Agent。human_review 是诊断输出状态，不是可恢复的人工审批节点。登录会话与任务状态应分别管理。

## 当前部署范围

优先本机 Windows、单实例后端和现有 SQLite/Chroma；保留网页用于管理与回归。当前不要求拆仓、Android 发布或云端迁移。服务启动不自动初始化/清空既有数据，非回环监听继续遵守 TLS 要求。

[项目说明](../README.md) · [现有流程](system-flows.md) · [服务入口](server-startup.md)
