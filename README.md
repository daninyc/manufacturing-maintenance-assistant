# Manufacturing Maintenance Assistant

一个可本地运行的检索增强问答基线，当前支持 TXT 文档读取、文本清洗、固定长度分块、本地向量化、Chroma 持久化检索、来源引用和 Streamlit 页面。

## 当前实现

- 读取 UTF-8 TXT 文档，拒绝错误文件类型和空文档。
- 规范空白字符，保留数字、单位和代码等原始内容。
- 按字符长度分块，支持 overlap，并生成稳定的 chunk ID。
- 使用确定性 hash embedding 完成本地向量化，不需要外部模型或 API Key。
- 使用 Chroma 持久化向量数据，通过 `upsert` 避免同一文档重复入库。
- 检索 top-k 文本块并返回余弦距离。
- 引用信息直接取自入库 metadata，包括来源文件、chunk ID 和原文片段。
- 使用 Pydantic 校验问答和诊断数据结构。
- 提供命令行入口、Streamlit 页面和 pytest 测试。

## 技术栈

- Python 3.12
- ChromaDB
- Pydantic
- Streamlit
- pytest
- Ruff

## 数据流

```text
TXT 文档
  -> 文档校验与读取
  -> 文本清洗
  -> 固定长度分块
  -> hash embedding
  -> Chroma 持久化
  -> top-k 检索
  -> 测试替身回答
  -> 引用组装
  -> CLI / Streamlit
```

详细模块映射见 [`docs/architecture.md`](docs/architecture.md)。

## 项目结构

```text
.
├─ app/
│  ├─ core/config.py           # 路径、集合名和 top-k 配置
│  ├─ ingestion/               # TXT 读取、清洗、分块和入库
│  ├─ retrieval/               # hash embedding、Chroma 和检索
│  ├─ schemas/                 # 问答与诊断数据结构
│  ├─ services/qa_service.py   # 检索、拒答、引用和基线回答
│  └─ main.py                  # 命令行入口
├─ data/
│  ├─ raw_docs/                # 输入文档
│  └─ results/                 # 已保存的运行结果
├─ docs/                       # 架构、决策和验证记录
├─ tests/test_baseline.py      # 单元与端到端基线测试
├─ ui/streamlit_app.py         # Web 页面
├─ .env.example                # 可选配置示例
├─ LICENSE-NOTICES.md
└─ requirements.lock.txt       # 锁定依赖
```

## 环境要求

- Windows PowerShell
- Python 3.12

## 安装

```powershell
git clone https://github.com/daninyc/manufacturing-maintenance-assistant.git
cd manufacturing-maintenance-assistant

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

## 配置

当前基线不需要 API Key。默认配置如下：

```dotenv
CHROMA_PATH=data/chroma
CHROMA_COLLECTION=day1_baseline
TOP_K=3
```

如需临时覆盖配置，可在当前 PowerShell 会话中设置环境变量：

```powershell
$env:CHROMA_PATH = "data/chroma"
$env:CHROMA_COLLECTION = "day1_baseline"
$env:TOP_K = "3"
```

## 命令行运行

使用默认文档和默认问题运行，并重建 Chroma collection：

```powershell
.\.venv\Scripts\python.exe -m app.main --reset
```

指定文档和问题：

```powershell
.\.venv\Scripts\python.exe -m app.main `
  --document data\raw_docs\baseline_demo.txt `
  --question "维护窗口是什么时间？" `
  --reset
```

将结果保存为 JSON：

```powershell
.\.venv\Scripts\python.exe -m app.main `
  --reset `
  --output data\results\day1-baseline.json
```

响应包含 `indexed_chunks`、`answer`、`citations`、`grounded` 和 `request_id`。引用中包含来源文件、chunk ID、原文片段和向量距离。

## Streamlit 运行

```powershell
.\.venv\Scripts\streamlit.exe run ui\streamlit_app.py
```

浏览器访问 `http://localhost:8501`。页面会自动导入 `data/raw_docs/baseline_demo.txt`，展示回答、引用、`grounded` 状态、请求 ID 和向量距离。

## 测试与静态检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app ui tests
.\.venv\Scripts\python.exe -m pip check
```

当前测试覆盖：

- 分块 overlap 与稳定 chunk ID。
- 非法分块参数。
- `top_k` 请求范围校验。
- 空知识库拒答。
- TXT 入库、检索、回答和来源引用的端到端链路。

## 核心实现

### 稳定分块

`split_text` 使用 `document_id::chunk-NNNN` 生成稳定 ID。相同文档使用相同参数重复入库时，Chroma `upsert` 更新对应记录，不创建重复记录。

### 本地向量化

`hash_embedding` 将中文字符和英文词元稳定映射到 256 维向量，并进行归一化。它只用于验证数据链路，不具备语义模型的同义表达理解能力。

### 可追溯引用

入库时保存 `source_file`、`document_id`、`chunk_id`、`start` 和 `end`。返回引用由检索结果的 metadata 组装，不由回答文本生成来源。

### 拒答边界

当前仅在 Chroma 没有返回任何结果时设置 `grounded=false` 并拒答。相关性阈值尚未实现，因此一次检索命中不等于答案已通过质量验证。

## 当前限制

- 仅支持 TXT，尚未实现 PDF 解析。
- hash embedding 只匹配表面词元，不提供真实语义检索。
- 回答由测试替身拼接首条检索结果，尚未接入生成模型。
- 尚未实现相关性阈值、正式评测集、FastAPI、SQLite 和多源诊断。
- `data/chroma/` 是本地运行产物，不提交到 Git。

## 许可证与依赖

项目代码和数据声明见 [`LICENSE-NOTICES.md`](LICENSE-NOTICES.md)，第三方依赖及固定版本见 [`requirements.lock.txt`](requirements.lock.txt)。
