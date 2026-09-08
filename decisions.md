# Day 1 技术决策与风险

## 决策记录

| 决策 | 备选 | 当前取舍 | 风险/后续验证 |
| --- | --- | --- | --- |
| Chroma | FAISS、Milvus、pgvector | 本地持久化、metadata 查询接口适合 7 天原型 | 生产扩展性有限；Day 2 验证幂等与过滤 |
| SQLite | PostgreSQL | 单文件、冷启动简单 | 并发和权限有限；Day 3 明确原型边界 |
| FastAPI + Streamlit | 单体 Streamlit | 服务与演示解耦 | 两进程增加启动成本；Day 5 验证 |
| 固定 Repository | Text-to-SQL | 参数化、可测、范围可控 | 灵活性低；优先守住只读安全边界 |
| 双层拒答 | 只靠 Prompt | 检索门控 + Prompt 约束 | 阈值可能误拒答；Day 6 用固定集测量 |
| Day 1 hash embedding | 在线 embedding、下载本地模型 | 零密钥、零下载也能验证链路 | 不代表语义效果；Day 2 替换并评测 |

## 为什么先冻结响应结构

响应契约是 UI、API、服务和测试的共同边界。先固定 `answer/citations/grounded/request_id` 与诊断结构，可减少后续替换模型、向量库或数据库时的联动修改，也能提前定义拒答和错误路径。

## 风险表

| 风险 | 影响 | 当前处理 | 状态 |
| --- | --- | --- | --- |
| 密钥泄露 | 产生费用或被滥用 | 仓库忽略 `.env*`，截图不含密钥；已建议轮换对话中出现的密钥 | Blocked：需用户轮换 |
| 无参考仓库来源 | 无法证明许可证与复用范围 | 当前不复制参考代码，保留待补字段 | Blocked：需 URL/提交号 |
| 无远程 GitHub 仓库 | 无法完成远程提交和在线看板 | 先完成本地 Git 与 Markdown 看板 | Blocked：需仓库地址/登录授权 |
| Python 3.11 缺失 | 与建议版本不一致 | 使用 3.12 并锁定依赖、记录真实版本 | Accepted |
| 本地 embedding 质量有限 | 不能声称语义检索效果 | 只作为 Day 1 连线替身，Day 2 替换 | Accepted |

## 2026-09-07 代码审计

- 删除 Day 3–6 的空壳模块；需要实现当天再创建。
- 删除未运行的在线模型分支及 OpenAI SDK；Day 1 只保留已经验证的测试替身。
- 删除一次性截图脚本及 Playwright；截图证据保留，项目运行不依赖浏览器自动化。
- 将单实现 `QAService` 类改为 `answer_question` 函数，并将三个测试文件合并为一个。
- 删除 Python 包发布配置；本项目当前按源码运行，不发布 wheel。
