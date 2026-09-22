# 权限规格（实现基准）

## 身份与动作

会话验证后由服务端构造 UserContext；该对象不能由客户端 JSON 直接作为可信输入。
用户启用、资源 active、密级足够、部门匹配或组织共享四项必须同时满足。
employee、engineer、admin 都有读取动作；admin 的管理动作不等于跨部门读取正文。

密级：0 公开、1 内部、2 受限。每个用户首版一个角色和部门。
缺少标签、未知角色、非法类型、非 active 文档默认拒绝。

## 权威数据与版本

documents 权限数据库是权威来源，Chroma metadata 仅供预过滤。
检索后根据 document_id 批量获取当前 ResourcePolicy，校验 policy_version 和 content_version。
即使索引宣称公开，也不放行数据库中不可读的文档。
外发同时要求 can_read 和 external_processing_allowed；后者默认 false。

## 状态

draft → indexing → active；失败进入 failed；下线进入 disabled。
入库和资源管理仍待接入；本文件不将策略函数描述为完整鉴权系统。

## 已实现

app/security/authorization.py：严格用户/资源模型、读取与管理判断、外发判断、候选后过滤。
tests/unit/test_authorization.py：权限矩阵、缺标签、错误类型、元数据伪造、旧版本与下线。

## 待实现

登录与会话数据库、FastAPI 身份依赖、文档发布、受保护检索接入、业务记录权限、
模型前与返回前复核、客户端、部署与真机验收。
旧问答入口尚未接入本策略，不可对外部署并声称已有访问控制。

