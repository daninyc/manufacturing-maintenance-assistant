# 管理员上传与发布

## 接口顺序

管理员可先调用 `GET /api/v1/admin/documents?limit=20&offset=0` 查询包含草稿、失败和下线项的策略列表。返回 items、total、limit、offset；limit 范围 1–50，offset 范围 0–100000。排序、计数和分页在同一数据库读事务完成，响应前复核管理员会话。管理列表仅包含 ResourcePolicy 标签字段，不含正文或服务器路径；它与普通用户的可读文档列表分离，不授予正文读取权限。

1. 管理员登录，取得 Bearer token。
2. 使用已有 `PATCH /api/v1/admin/documents/{id}/policy` 创建或更新草稿，明确部门、密级、可见范围与外发许可。新增时 expected_version=0、policy_version=1、status=draft。
3. `POST /api/v1/admin/documents/{id}/content?expected_version=1&format=txt`，请求体为原始文件字节，不是 multipart 或 JSON。TXT 使用 `Content-Type: text/plain`，PDF 使用 `application/pdf` 和 format=pdf。可选 equipment_id 用于检索型号范围，不是授权依据。
4. 服务端要求草稿版本匹配；正常返回 201，包含 document_id、status、policy_version、content_version，不含文件路径。新增草稿版本 1 发布后版本为 3。
5. 用户仅通过已鉴权引用接口查看片段，没有原始文件静态下载入口。

## 安全与失败行为

- 上传者必须是当前有效管理员；上传完成后再次校验身份，发布写事务再校验会话。
- 请求头和实际流量均检查 10 MiB 限制；读取上传流最长 60 秒。超限返回 413，超时返回 408。
- 仅允许 PDF/TXT；PDF 检查文件头并由解析器验证，TXT 要求 UTF-8。解析失败返回受控错误，不回显正文。
- 文件保存在权限数据库同级 uploads 目录，名称由服务端随机生成。原始文件名和 document_id 不拼入路径。
- 文件用排他创建；发布成功保留原件，失败清理该请求创建的文件。默认 data/uploads 已加入 Git 忽略规则；自定义数据目录也必须放在仓库外或另行忽略。
- 更新需先将策略改为 draft；旧块因此不可读。发布过程沿用 indexing → active / failed 和版本冲突保护。
- 409 表示草稿不存在于预期版本或已非草稿，不可无条件重试覆盖；应重新检查标签和当前版本。

## 验证边界

接口测试使用真实临时 SQLite、测试向量库与模拟 TXT，验证正常上传、授权引用、不可静态下载、重复发布冲突及多种输入拒绝。另覆盖无 Content-Length 的超限输入、接收期间撤权、索引失败文件清理和异常信息隐藏。2026-09-15 后端全量回归 221 passed（46.86 秒，2 条第三方弃用警告），上传模块及其测试 Ruff 通过。

尚未完成真实 HTTPS 大文件上传、恶意 PDF 解析资源隔离、客户端上传页面及断网恢复验收。TestClient 不证明真实网络分段或上传超时行为。服务端仍应限制并发和磁盘配额；输入体积限制不能保证 PDF 解压后的内存上限。
