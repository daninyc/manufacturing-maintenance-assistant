# 后端启动与网络边界

从项目根目录执行。首次使用须先完成账号库初始化、策略表升级和模拟资料发布；启动命令不创建默认密码，不自动给资料授权。

本机调试：

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_api
```

仅监听 127.0.0.1:8000。本机 HTTP 用于调试，Flutter 客户端要求 HTTPS，不能因此添加忽略 TLS 的开关。

局域网部署命令示例：

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_api --host 0.0.0.0 --port 8443 --certfile D:\secure-config\server.pem --keyfile D:\secure-config\server-key.pem
```

证书路径是示例，不代表文件已创建。必须使用客户端信任、名称/IP 与实际服务器地址匹配的证书；仅能加载证书不代表其有效期、信任链和终端信任均通过。私钥仅授予服务账号读取，禁止提交 Git。加密私钥暂不支持无人值守启动，不在命令行传私钥密码。

入口固定单 worker、关闭自动重载和 URL 访问日志、不信任转发头。并发连接上限 32 是初始配置，非实测容量承诺。只暴露 API，不映射 data、数据库、文档或模型目录为静态资源。不要把旧 Streamlit 当作公开服务；旧入口收敛尚未全部完成。

验收记录：入口配置测试 8 passed（0.15 秒），Ruff 通过。临时监听本机 18765 端口时，GET /health/live 返回 status=ok，未登录 GET /api/v1/me 返回 401。未做 HTTPS 握手、跨设备连接或正式服务安装，不能视为部署完成。

GET /health/ready 要求管理员有效会话；检查权限库必需表、业务库身份/版本和三张业务表。缺失策略表或业务库返回 503，检查不会创建业务库，不返回本地路径。成功响应的 scope 明确为 authentication-policy-business-databases，not_checked 明确列出向量索引、嵌入模型、云模型和客户端连通性，不能当作全系统健康承诺。相关 API 测试 7 passed（5.33 秒，2 条已有警告），Ruff 通过。

还需完成：可信证书部署、防火墙审批、服务自动启动/停止、模型及索引就绪验证、数据备份恢复演练、日志脱敏审计、干净 Windows 联调。
