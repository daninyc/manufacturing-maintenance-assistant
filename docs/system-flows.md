# 系统流程示意图

当前实现说明，不是完整交付证明。依据 app/api/server.py、protected_qa.py、diagnosis_service.py、publication.py 的执行链路。Mermaid 源码可在支持 Mermaid 的 Markdown 查看器中显示；本次尚未执行图形渲染验收。

当前范围：后端与 Windows 客户端，网页保留作管理和回归入口。Android 不列入当前交付。下图只说明已有固定流程。

## 授权问答

```mermaid
flowchart TD
    askInput["问答请求"] --> askSession{"会话有效"}
    askSession -->|"否"| askUnauthorized["401 拒绝"]
    askSession -->|"是"| allowList["从权威策略生成可读文档集合"]
    allowList --> retrieve["全部检索分支应用预过滤"]
    retrieve --> postFilter["后校验权限、状态、内容及策略版本"]
    postFilter --> distance["距离门控、去重、有界补齐"]
    distance --> enough{"存在可用候选"}
    enough -->|"否"| askRefusal["无证据拒答"]
    enough -->|"是"| askMode{"处理模式"}
    askMode -->|"本地"| localSelect["有限规格原文选择"]
    askMode -->|"DeepSeek"| external{"再次授权且允许外发"}
    external -->|"否"| askRefusal
    external -->|"是"| cloudSelect["随机编号与隔离 Prompt"]
    cloudSelect --> validate["严格输出结构、编号、原文及比较完整性"]
    localSelect --> validate
    validate --> finalCheck{"最终权限与版本仍有效"}
    finalCheck -->|"否"| askRefusal
    finalCheck -->|"是"| askResult["原文答案及鉴权引用信息"]
```

会话在途失效可直接返回 401；模型/数据库故障经 API 返回受控错误，不把失败正文拼成答案。未授权候选在模型、客户端响应及普通正文日志之前被过滤。图中“无证据拒答”与“系统错误”不是同一种内部原因。

## 三源辅助诊断

```mermaid
flowchart TD
    diagnoseInput["设备、现象、时间范围"] --> deviceCheck{"会话及设备可读"}
    deviceCheck -->|"否"| diagnoseDeny["拒绝请求"]
    deviceCheck -->|"是"| recordQuery["SQL 中同时过滤记录、关联文档及时间"]
    recordQuery --> recordLimit["过滤后排序与数量限制"]
    recordLimit --> knowledge["调用授权问答取得知识证据"]
    knowledge --> assemble["汇总知识、报警、历史维修及版本"]
    assemble --> sop["核验模拟 SOP 条件、原文、安全说明及版本"]
    sop --> diagnoseMode{"处理模式"}
    diagnoseMode -->|"本地"| overallCheck["整体复核会话及全部策略"]
    diagnoseMode -->|"DeepSeek"| allExternal{"全部参与资源允许外发"}
    allExternal -->|"否"| diagnoseDeny
    allExternal -->|"是"| threeSelect["模型仅选择本次证据和建议编号"]
    threeSelect --> structureCheck{"编号及建议依赖有效"}
    structureCheck -->|"否"| invalidOutput["受控错误，不发布部分结果"]
    structureCheck -->|"是"| conflict{"模型标记疑似冲突"}
    conflict -->|"是"| suppress["移除建议，标记人工核查"]
    conflict -->|"否"| overallCheck
    suppress --> overallCheck
    overallCheck --> unchanged{"授权未发生变化"}
    unchanged -->|"否"| diagnoseDeny
    unchanged -->|"是"| diagnoseResult["证据、受限建议、风险与来源"]
```

知识选择与三源选择可能分别调用模型。读取许可不等于外发许可。历史维修只作历史证据；目前建议仅支持现有模拟 SOP 的信息登记、补充手册和人工升级，不提供设备操作授权。疑似冲突是模型标记，不是服务端证明的事实；grounded=false 不宣称根因已经确认。

## 文档上传与发布

```mermaid
flowchart TD
    localFile["CLI 指定 PDF 或 TXT"] --> manageCheck{"有效管理员会话"}
    httpFile["HTTP 上传 PDF 或 TXT"] --> draftCheck{"管理员且草稿版本匹配"}
    draftCheck -->|"否"| uploadDeny["受控拒绝"]
    draftCheck -->|"是"| boundedUpload["类型、实际体积、读取时限校验"]
    boundedUpload --> persist["复核身份并以随机文件名保存"]
    persist --> manageCheck
    manageCheck -->|"否"| publishDeny["拒绝发布"]
    manageCheck -->|"是"| parse["同一字节快照解析及散列"]
    parse --> indexing["事务内复核身份并写 indexing"]
    indexing --> chunks["逐页分块并继承权限及版本标签"]
    chunks --> indexWrite["写入权限版向量集合"]
    indexWrite --> publishCheck{"管理员及期望版本仍有效"}
    publishCheck -->|"是"| activate["版本递增并标记 active"]
    publishCheck -->|"否"| failed["失败状态或保留更新的策略"]
    indexWrite -->|"异常"| failed
    activate --> available["通过查询端权威复核后才可见"]
```

发布失败不放开读取；不能依赖旧向量已删除来保证下线。HTTP 失败时清理该请求创建的原件；成功原件仅留在服务端，无静态下载接口。HTTP 上传已通过模拟文件接口测试，真实 HTTPS、解析器进程级资源限制仍未验收。图中上传校验、文件保存或解析失败也会提前退出，不进入 active。

## 客户端与部署状态

以下为延后范围及运行环境说明，不把未完成客户端作为 Agent 已完成的依据，也不再把安装包作为本次完成条件。

| 部分 | 当前状态 |
| --- | --- |
| Flutter 登录、问答、设备、诊断、引用页面 | 源码已写，未编译和运行 |
| HTTPS、退出清理、旧响应隔离、回前台复核 | 源码已写，端到端未验证 |
| 平台安全存储、管理员页、完整筛选分页 | 未完成 |
| 后端启动入口 | 本机存活与未登录拒绝已实测 |
| 可信 HTTPS、Windows 安装包、签名 APK | 未完成 |
| 干净 Windows 环境 | 未验收 |

以上流程图不会证明所有安全输入均被覆盖。模型输出格式、授权语义、并发撤权、日志、部署和客户端需要分别验收。
