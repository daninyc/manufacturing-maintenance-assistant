# Windows 客户端

当前交付目标为 Flutter Windows 客户端。Android 平台源码保留，不再列入当前验收范围；暂不拆分仓库。

## 源码现状与待实现能力

- 已有登录、问答、设备及记录查询、诊断证据与引用重查页面，以及管理员文档策略页面。
- `lib/main.dart` 的问答与诊断请求目前固定 `mode: local`。
- 必须补充 local／真实模型选择、当前模式显示及受控失败提示；真实模型由服务端调用 DeepSeek。失败不得悄悄回退到 local。
- `lib/api_client.dart` 使用 HTTPS、禁用重定向、校验会话、限制响应大小并清理旧账号响应；凭证只在内存保存。
- 多轮对话、任务历史、追问继续、执行轨迹页面尚未实现。
- 上传网络方法已存在，文件选择与上传页面尚未形成完整操作流程。
- 模式切换、真实接口联调、证书信任、弱网与 Windows 打包运行需在升级后重新验收。源码存在不等于实际运行通过。

## 开发与检查

在项目根目录双击 `打开App开发终端.cmd`，或加载 `scripts/app_env.ps1` 后进入此目录。既有英文入口 `D:\CodexWorkspace\maintenance-client-dev` 是指向本目录的 Junction，使用前检查它仍指向本项目。

```powershell
flutter analyze
flutter test
dart run test/api_client_check.dart
flutter build windows --release
```

以上是执行命令，不是本次已运行的结果。现有历史构建记录仅证明当时版本能编译；当前版本以重新运行结果为准。

## 连接与数据边界

输入受信任的 HTTPS 服务根地址。浏览器能打开网页不代表 Dart 的证书信任已配置完成；不得禁用证书校验。

客户端不持有 DeepSeek Key、数据库或向量索引。退出、切换账号/服务器应清理会话和旧正文；后台返回后重新确认身份。已被用户复制的内容无法通过撤权远程收回。

项目当前事实见 [根目录说明](../../README.md)。
