# IM 协作触达层扩展（IM）

> **归属**：领域扩展（ADR-0012 §4.2 → `extensions/im/`），不修改核心六类契约。
> **裁决**：ADR-0023（issue #41 评审结论的落地）；规则：
> `rules/im-message.rules.yaml`、`rules/im-group.rules.yaml`、`rules/im-relationship.rules.yaml`。

## 1. 定位

IM 高频出现在审批催办、告警推送、群组协作与沟通留痕。本扩展只收窄为
**「持久化业务状态的协作触达层」**：

- 纳入契约面：消息与版本历史、会话元数据、已读位点、群组/成员、好友/黑名单、操作审计；
- **不纳入**：网关、长连接、路由、离线推送、typing、无状态类别查询（`/sync/categories/*`）、
  消息位点推进（`/sync/progress/*`）、at-most-once 拉取、0-RTT、实时帧通道；
- 与业务域只用 `external_refs: [{system, id}]` 松耦合引用，不反向依赖 HR / 财务 / 审批。

首期覆盖「通知类消息 + 群组关系 + 审计」；完整实时聊天所需的实时消息流、多端同步、大群扇出
保留在独立 IM 子系统。

## 2. 结构

```
extensions/im/
├── manifest.yaml                       # 7 对象 / 16 命令 / 3 规则 / 19 权限
├── objects/                            # 全部含 id/version/双时间轴
│   ├── message.schema.json             # ImMessage（server_seq 为扩展字段）
│   ├── conversation.schema.json        # ImConversation（置顶/免打扰/隐藏）
│   ├── read-position.schema.json       # ImReadPosition（端维度位点）
│   ├── group.schema.json               # ImGroup（id 即 chat_id）
│   ├── group-member.schema.json        # ImGroupMember（left_at 墓碑）
│   ├── friendship.schema.json          # ImFriendship（有向 + 状态）
│   └── block.schema.json               # ImBlock（revoked_at 失效）
├── operations/                         # 命令 + 只读消息面
├── rules/                              # IM-MSG / IM-GRP / IM-REL
├── migrations/V401__im_initial.sql     # 当前行唯一索引 (+ rollback)
├── README.md
└── tests/im.test.yaml                  # 8 scenario + 4 static
```

## 3. 消息

| 字段 | 语义 |
|------|------|
| `chat_id` | 会话 ID；群聊时为 `im_group.id`，直聊由业务分配 |
| `client_msg_id` | 与 `chat_id` 构成发送幂等键（当前对象唯一） |
| `server_seq` | 会话内单调序列（扩展领域规则）；当前对象内 `(chat_id, server_seq)` 唯一 |
| `status` | `normal` / `recalled` |
| `content` / `content_sha256` / `content_ref` | JSON 内容；大对象/二进制用摘要 + 外置引用 |
| `external_refs` | 业务引用 `[{system, id}]` |
| `recalled_at` / `recalled_by` | 撤回时间与操作者 |

纪律：

- 发送幂等：同一 `(chat_id, client_msg_id)` 重复 → `IM-409-001`；
- 编辑：`base_version` 乐观锁，冲突 → `IM-409-002`；
- **撤回是一次写**：追加新版本（`version+1`）并写审计，不删除历史；撤回后编辑/再次撤回 →
  `IM-409-003`；
- 群聊发送要求发送者为 active 群成员（`IM-403-001`）。

## 4. 会话与已读位点

- 会话设置按 `(chat_id, user_id)` 唯一；`pinned` / `muted` / `hidden`，`expected_version` 乐观锁；
- 已读位点按 `(chat_id, user_id, endpoint_id)` 唯一；`last_seq` 只增不减，回退 → `IM-409-004`；
  相同位点重复上报是幂等 no-op（仍写审计，`advanced=false`）。

## 5. 群组与成员

- `im_group.id` 即 `chat_id`；群主唯一且不可被移出（`IM-409-006`）；
- 移出群/退群是墓碑（`left_at` 非空 + 追加版本 + 审计）；重新入群复用同一对象；
- 解散仅群主可执行（`status=dissolved` + 审计）；解散后本群写命令 → `IM-409-003`；
- 加/移成员要求 owner/admin；改角色/禁言仅 owner；admin 不可移出其他 admin。

## 6. 好友与黑名单

- 好友对与方向无关，当前唯一；pending/accepted 重复申请 → `IM-409-008`；
  仅被申请人可接受/拒绝（`IM-403-002`），已处理 → `IM-409-009`；
- 黑名单阻止好友申请（`IM-409-007`）；拉黑同时把已接受好友关系置为 `removed`；
- 取消拉黑是写（`revoked_at`/`revoked_by`），未拉黑 → `IM-409-010`。

## 7. 查询面

- `GET /im/chats/{chatId}/messages` 与 `GET /im/chats/{chatId}/messages/{messageId}`；
- 遵循 `02` 查询契约：`as_of` / `recorded_as_of` / `min_version`（未追平 → `409 + Retry-After`）；
- `since_seq` / `before_seq` / `limit` 是扩展读模型（按 `server_seq` 分页），不是核心查询语义。

## 8. 明文边界：不做

| 不做项 | 理由 |
|---|---|
| 网关 / 长连接 / 路由 / 离线推送 / typing | 不产生可审计状态，保留在 IM 子系统 |
| `/sync/categories/*`、`/sync/progress/*` | 无状态机制不实体化，不进契约面 |
| at-most-once 拉取、0-RTT、大群扇出 | 实现/部署语义，进契约会被通用合规规则误伤 |
| 完整实时聊天、多端同步 | 首期只做通知 + 群组协作 + 审计 |
| 多租户字段 | 核心无 tenant；由部署/扩展解决 |
