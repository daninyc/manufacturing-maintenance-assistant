# Agent 验收标准与客户操作手册

状态：验收执行版，尚未最终签收。范围为 Agent 后端及技术文档，Windows 客户端另行验收。

2026-09-17 补充：完整 G0–G8 操作流程见 Agent客户完整验收流程.md（历史记录已移出公开仓库），原计划 P01–P32 逐项要求及证据缺口见 [Agent完整权限验收矩阵.md](Agent完整权限验收矩阵.md)。授权规则层新增 2160 个合法属性组合验证，授权单元文件 41 passed（0.28 秒）；这不等于 P01–P32 全部端到端通过。本文保留为概要入口，最终签收必须依据完整流程及实际执行记录。

## 1. 验收原则

不能仅凭页面启动、测试数量或单次模型回答签收。每项应保留执行日期、代码提交号、环境、命令、实际结果与失败记录。模拟资料测试通过不代表真实企业资料已经获得外发许可，也不保证所有未知攻击均被阻断。

| 验收项 | 通过标准 | 证据入口 | 当前边界 |
| --- | --- | --- | --- |
| Day 3 兼容 | 固定只读查询、输入校验、数据库错误语义回归通过 | test_day3_data.py、test_day3_cli.py | 纳入最终全量复验 |
| 身份 | 未登录/过期/撤销拒绝；客户端不能指定身份 | test_api_auth.py、test_sessions.py | 自动化已覆盖多个场景 |
| 读取授权 | 角色动作、部门、密级、状态共同满足；缺标签拒绝 | test_authorization.py、test_protected_data.py | 完整计划矩阵仍需逐条映射 |
| 文档发布 | 有效标签与版本后才发布；失败不可读；旧向量不绕过下线 | test_document_upload.py、test_protected_qa.py | 真实网络上传另验 |
| 检索隔离 | 未授权证据不得进入模型与响应；预筛选和后校验均有效 | test_protected_qa.py | 已有真实 BGE 冒烟，不等于完整召回评测 |
| 输出约束 | 未知/跨请求编号拒绝，原文匹配，返回前复核授权 | test_evidence_ids.py、test_diagnosis_selection.py | 模型自然语言解释不作为授权依据 |
| 三源诊断 | 知识、报警、维修可合并；历史动作不当作当前许可 | test_diagnosis.py | 真实三源调用已单独通过，仍需整体复验 |
| 管理写入 | 普通用户拒绝，版本冲突拒绝，撤权后写入不成功 | test_api_auth.py | 管理员可管理不等于可读全部正文 |
| 客户部署 | 按文档从干净配置启动，数据与密钥不对外暴露 | server-startup.md | 客户环境尚未验收 |
| 运维恢复 | 备份可恢复且策略、原件、索引版本一致 | 待补可执行演练 | 未完成，不签收此项 |
| 文档交付 | 中文职责、原理、Day 3 对照、操作步骤与渲染图一致 | 本文及后续报告 | 整理中 |

关键安全场景只要发生一次未授权放行、正文外发或凭证泄漏，即阻止签收。性能指标应记录实际机器、样本与模型模式，不能把测试耗时当作生产响应承诺。

## 2. 自动化验收操作

以下在 PowerShell 执行，工作目录必须为项目根目录。不要在真实业务数据目录运行临时造数脚本。

```powershell
Set-Location 'D:\CodexWorkspace\制造设备运维知识助手-7天计划\manufacturing-maintenance-assistant'
git rev-parse HEAD
git status --short
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
Remove-Item Env:RUN_LIVE_DEEPSEEK -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check app scripts tests ui --no-cache
```

判定：pytest 退出码 0、无失败；未启用云端时，明确标注的真实模型测试跳过属于预期，不能将跳过写成通过。Ruff 与 pip check 退出码均为 0。第三方弃用警告单独登记。

### 真实云端测试

先由客户在项目 `.env` 配置 DEEPSEEK_API_KEY；不要把密钥粘贴到报告、截图、命令参数或 Git。网络可达且账号有调用额度后执行。下列测试可能产生模型费用，只使用测试内置模拟资料。

```powershell
$env:RUN_LIVE_DEEPSEEK='1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_protected_qa.py tests/integration/test_diagnosis.py -k 'live_deepseek or live_three_source' -q -p no:cacheprovider
Remove-Item Env:RUN_LIVE_DEEPSEEK
```

预期两项真实模型测试通过。失败必须保留原因；不得改成模拟响应后声称真实模型验收通过。问答验证授权引用与部门隔离；三源测试用真实模型传输，检查模型输入具备三个来源、输出保持人工核查和受限建议规则。

## 3. 本机服务检查

启动命令：`python -m scripts.serve_api --host 127.0.0.1 --port 8000`，应使用项目虚拟环境中的 python。另一终端执行：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health/live'
```

预期仅返回最小存活状态。未携带 token 请求 `/api/v1/me` 应为 401。存活不等于可问答：权限库、业务库、标签和语义索引需按初始化及发布说明准备；`/health/ready` 不检查云端模型及完整向量可用性。

局域网或远程验收必须使用可信 HTTPS，不得通过忽略证书错误测试。证书、服务地址、账号分发以及干净环境初始化仍需补充完整客户演练记录；本节不是已完成的部署证明。

## 4. 签收记录模板

客户环境：______；代码提交号及工作区状态：______；数据来源：模拟/另行获批资料。

执行人：______；复核人：______；日期：______。

每项填写：验收编号、操作、预期、实际、证据文件、通过/失败/未执行、问题编号。最终签收前必须清除所有必需项的“未执行”；不得略过服务端自身权限与运行验证。
