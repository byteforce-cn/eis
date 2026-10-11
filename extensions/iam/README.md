# IAM 域扩展（v1.0.0）

IAM 定义账户、凭证、角色、角色绑定与认证会话的管理面契约。授权解析结构及判定语义仍由核心 04 契约负责；IAM 仅负责管理这些对象的生命周期。

命令使用 `iam.*` 命名空间，领域错误使用 `IAM-` 前缀。`Credential.secret_hash` 是写入专用字段，不得出现在对象查询、事件或日志中。用户禁用会在同一命令中吊销其全部活动会话，角色绑定授予在写入前执行核心 SoD 检查。

运行完整参考验收：

```bash
python3 tools/e2e-runner extensions/iam/tests/iam.test.yaml
python3 tools/contract-checker
python3 tools/schema-compiler compile iam
```

