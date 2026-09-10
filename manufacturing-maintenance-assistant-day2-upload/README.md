# 制造设备运维知识助手

基于公开设备资料与模拟资产的文档问答应用，支持 PDF/TXT 导入、语义检索、原文引用和证据不足拒答。

> 模拟场景原型，不接入真实产线、不控制设备，不提供现场维修授权。设备规格以适用版本的完整厂商手册为准。

## 功能

- 统一加载 UTF-8 TXT 和文本型 PDF，保留文件名、页码、文档编号、版本及设备信息。
- 保守清洗、字符分块、稳定块编号和 Chroma upsert，支持重复导入。
- 本地 BGE 中文语义检索，设备过滤，多设备比较候选分配。
- 无候选或距离不达标时拒答；每条摘录必须属于实际命中块。
- 本地模式支持明确型号的负载、半径、温度问题。
- DeepSeek 模式只选择证据编号，由程序恢复原文与来源。
- 单次问答 CLI、Streamlit 页面、固定问题回归和单元/集成测试。

## 环境与安装

已在 Windows / Python 3.12 环境验证。在 PowerShell 执行：

```powershell
git clone https://github.com/daninyc/manufacturing-maintenance-assistant.git
Set-Location manufacturing-maintenance-assistant
py -3.12 -m venv .venv
& './.venv/Scripts/python.exe' -m pip install -r requirements.lock.txt
& './.venv/Scripts/python.exe' -m scripts.fetch_sources
& './.venv/Scripts/python.exe' -m scripts.prepare_model
& './.venv/Scripts/python.exe' -m scripts.ingest
```

已有虚拟环境时无需重建。首次下载依赖、官方 PDF 和模型需要网络。
直接调用虚拟环境解释器即可，不必激活环境或修改执行策略。

## 启动

本地问答无需 API Key：

```powershell
& './.venv/Scripts/python.exe' -m scripts.day2_qa --question 'UR3e 的最大负载和工作半径是多少？' --mode local
& './.venv/Scripts/streamlit.exe' run ui/streamlit_app.py
```

页面默认本地模式。输入问题后点击“提问”，可展开引用查看文件、页码、块编号、原文和距离。

### DeepSeek 配置

根目录没有 `.env` 时，将无密钥模板 `.env.example` 复制为 `.env`，仅在本机填写：

```dotenv
DEEPSEEK_API_KEY=填写自己的有效密钥
DEEPSEEK_MODEL=deepseek-chat
```

```powershell
& './.venv/Scripts/python.exe' -m scripts.day2_qa --question '比较 UR3e 与 UR5e 的负载和工作半径。' --mode deepseek
```

运行时读取根目录 `.env`，不是 `.env.example`。已有进程环境变量优先。
在线请求向 DeepSeek 发送问题与候选资料，并消耗账户额度。不要上传密钥或未经授权外发的资料。

### CLI 参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| --question | 必填问题 | 无 |
| --mode | local / deepseek | local |
| --top-k | 候选块数量，1–10 | 6 |
| --max-distance | 最大余弦距离 | 0.50 |

## 输出

返回 `answer`、`citations`、`grounded`、`request_id`。
引用包含 `source_file`、`page`、`chunk_id`、`excerpt`、可选来源链接及距离。
无证据时 `grounded=false` 且引用为空；模型请求错误不视为正确拒答。
PDF 页码从 1 开始，TXT 使用逻辑页码 1；摘录按加载器清洗后的页文本核验。
`grounded=true` 不代表通过工业安全审查。

## 数据与索引

| 路径 | 内容 |
| --- | --- |
| data/raw_docs/manifest.json | 文件、设备映射、版本、来源清单 |
| data/raw_docs/manuals/*_summary.txt | 三份真实型号规格摘要与模拟资产 |
| data/raw_docs/manuals/*_official.pdf | 两份官方 PDF 本地快照，不提交 |
| data/raw_docs/sops/ | 自制模拟核对和信息升级流程，不含真实操作许可 |
| data/models/ | embedding 缓存，不提交 |
| data/chroma/ | 持久化索引，不提交 |
| data/eval/ | 固定问题与预期事实 |
| docs/evidence/day2/ | 本地生成入库/回归报告，不提交 |

EQ-ROBOT-001、002、003 为模拟编号，分别对应 UR3e、UR5e、IRB 120-3/0.6。
摘要保留模拟标识与厂商来源，不暗示拥有企业内部数据；未知发布日期保持 unknown。
官方 PDF 未确认再分发许可，由下载脚本复现。

重复导入更新同 ID 块，并删除同文档不再存在的旧块；每轮独立报告记录导入前后块数、失败数、耗时。
从 manifest 移除文件不会自动清除该文档历史索引。导入不是跨文档原子事务。

## 功能链路

```text
PDF/TXT + manifest
  → 加载清洗 → 字符分块与来源绑定 → BGE 文档向量 → Chroma

问题
  → 输入校验 → 设备过滤与语义检索 → 距离门控
  → 本地规则 / DeepSeek 证据编号选择 → 原文与设备来源核验
  → 答案与引用 / 证据不足拒答
```

分块为 500 字符、重叠 80 字符，不是 token 数。语义集合为 `day2_semantic_v1`。
余弦距离越小越接近，0.50 为实验参数，不是概率或通用最优阈值。
UI 直接调用 Python 服务，目前没有 FastAPI 中间层。

## 测试

先下载 PDF 并入库，然后执行：

```powershell
& './.venv/Scripts/python.exe' -m pytest -q
& './.venv/Scripts/ruff.exe' check app scripts tests ui --no-cache
& './.venv/Scripts/python.exe' -m pip check
& './.venv/Scripts/python.exe' -m scripts.run_day2_smoke --extended
```

默认五题覆盖直接问题、比较、无答案和诱导；`--extended` 执行十二题。
自行在线验收可运行 `python -m scripts.run_day2_smoke --mode deepseek`，会产生外部请求与费用。
评测校验来源页摘录、数值设备绑定和拒答行为；条件及否定语义仍需人工复核。

## 目录

| 目录 | 职责 |
| --- | --- |
| app/ingestion | 加载、清洗、分块和入库 |
| app/retrieval | embedding、Chroma 和检索 |
| app/services | 证据选择、拒答与引用组装 |
| app/schemas | 输入输出校验 |
| app/prompts | 在线证据选择规则 |
| scripts | 下载、入库、CLI、回归 |
| ui | Streamlit 页面 |
| tests | 单元/集成测试 |

`app/main.py` 保留为早期 hash 基线入口，不是当前语义问答或 Web API 入口。

## 限制

- 不支持 OCR；复杂表格、跨页条件可能需要人工处理。
- 本地模式、型号识别和字段规则覆盖有限，不是通用工业知识模型。
- 通用 SOP 不会自动并入具体设备过滤结果。
- 原文存在不代表现场条件完整或安全许可。
- 未实现 SQLite 业务查询、多源诊断、FastAPI 正式端点或设备控制。
- 小样本回归不代表生产准确率；尚未完成完整参数对照实验。

来源和权利边界见 [LICENSE-NOTICES.md](LICENSE-NOTICES.md)。
