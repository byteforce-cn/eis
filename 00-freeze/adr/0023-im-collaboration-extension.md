# ADR-0023：IM 协作触达层扩展（`extensions/im/`）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #41（RFC 与评审结论）；ADR-0012 §4.2（归属裁决）；`extensions/im/`、`tools/ci/im-smoke.sql`、`docs/INTEGRATION-BOUNDARY.md`

## 1. 变更原因

issue #41 提出把 IM 纳入 EIS，并附了契约草案。维护者评审结论：**边界接受，草案需按 EIS 元结构
重写后再实现**。接受的部分是「IM 作为扩展、收窄为持久化业务状态的协作触达层」；必须先修正的是
草案与 EIS 元结构的六处冲突：

1. 复合主键与 `row_version`/`current_version` 不能作为实体身份/版本；
2. 「撤回是状态翻转、不追加版本」与 EIS 版本语义冲突；
3. 查询面未遵守 `as_of` / `recorded_as_of` / `min_version`；
4. `payload json/binary` 把大对象塞进业务行；
5. 未声明权限目录与调用方边界；
6. 审计事件未映射到 `02`/`05` 的事件形状。

本 ADR 记录重写后的形态，并落地 `extensions/im/` 1.0.0。核心六类契约不改。

## 2. 影响范围

- 扩展：新增 `extensions/im/` 1.0.0（领域扩展）
- 对象：`Message` / `Conversation` / `ReadPosition` / `Group` / `GroupMember` / `Friendship` / `Block`
- 命令：16 个（消息 3、会话 2、群组 3、成员 3、好友 3、黑名单 2）
- 读取面：`im.message.read`（消息历史/单条消息，`as_of` / `recorded_as_of` / `min_version`）
- 迁移：`migrations/V401__im_initial.sql`（自然键当前行唯一索引）
- CI：PostgreSQL 任务执行 V401 + `tools/ci/im-smoke.sql`
- 文档：本 ADR、`extensions/README.md`、`docs/ROADMAP.md`、`CHANGELOG.md`
- 核心契约：**无改动**

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增可选扩展）。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增 `extensions/im/` 1.0.0 | MINOR | 新增可选扩展，不采用者不受影响 |
| 新增 `IM-` 规则/错误码前缀 | 无 | 扩展命名空间，不占用 `EIS-` |
| 新增 V401 迁移 | 迁移加法 | 只建索引，不改核心表 |

- 破坏点：无。

## 4. 决策

### 4.1 归属与边界

- **领域扩展** `extensions/im/`（不新增第七类核心契约）；
- 只纳入**持久化业务状态**：消息/版本历史、会话元数据、已读位点、群组/成员、好友/黑名单、操作审计；
- **Transient 机制不入契约**：网关、长连接、路由、离线推送、typing、无状态类别查询
  （`/sync/categories/*`）、消息位点推进（`/sync/progress/*`）、at-most-once 拉取、0-RTT 重试、
  实时帧通道（WS/QUIC）保留在 IM 子系统内部；
- 与业务域**松耦合引用**：`external_refs: [{system, id}]`（`docs/INTEGRATION-BOUNDARY.md` 既有约定），
  IM 扩展不反向依赖 HR / 财务 / 审批。

### 4.2 对象模型（按 EIS 元结构重写）

每个对象都是「`id`（UUIDv7）+ `version`（每次写 +1）+ 双时间轴 + 审计字段」的单实体多版本行
（`01-data-contract`）。草案的复合主键与 `row_version`/`current_version` 废弃：

| 草案 | 重写后 |
|---|---|
| `im_message_version` 复合主键表 | 不需要独立版本表：编辑/撤回追加 `im_message` 新版本，历史由双时间轴保留 |
| `im_conversation(chat_id,user_id)` 复合主键 | `ImConversation` 独立对象；`(chat_id, user_id)` 用 V401 当前行唯一索引表达 |
| `im_group_member(group_id,user_id)` 复合主键 | `ImGroupMember` 独立对象；`(group_id, user_id)` 当前行唯一 |
| `im_read_position(chat_id,user_id,endpoint_id)` 复合主键 | `ImReadPosition` 独立对象；三列当前行唯一 |
| `row_version` / `current_version` | 统一使用 EIS `version`；`server_seq` 保留为扩展字段（会话内序列），不与 `version` 混用 |

### 4.3 消息与撤回

- 发送幂等键 `(chat_id, client_msg_id)`（当前对象唯一，`IM-409-001`）；
- `server_seq` 由服务端按会话分配（当前最大 + 1），当前对象内 `(chat_id, server_seq)` 唯一；
  它是**扩展领域规则**，不要求核心命令模型支持流式序列；
- **撤回是一次写**：追加新版本（`version+1`，`status=recalled`，`recalled_at/recalled_by`），
  写审计事件 `im.message.recalled`；历史版本与原始内容保留；
- 编辑使用 `base_version` 乐观锁（`IM-409-002`）；仅发送者可编辑；撤回可由发送者或群 owner/admin 执行（`IM-403-003`）；撤回后不可编辑/再次撤回（`IM-409-003`）；
- 大内容不塞业务行：`content_sha256`（64 位小写十六进制）+ `content_ref` 指向外部存储；
- 群聊发送要求发送者为 active 群成员（`IM-403-001`）。

### 4.4 群组与成员

- `im_group.id` 即该群的 `chat_id`；群主唯一且不可被移出（`IM-409-006`）；
- 移出群/退群是墓碑（`left_at` 非空 + 追加版本 + 审计），重新入群复用同一对象；
- 解散仅群主可执行，是写（`status=dissolved` + `dissolved_at/by` + 审计）；解散后本群写命令
  一律 `IM-409-003`；
- 管理权限：加/移成员要求 owner/admin，改角色/禁言仅 owner，administrator 不可移出其他 administrator。

### 4.5 关系与已读位点

- 好友对与方向无关，当前唯一（迁移用 `LEAST/GREATEST` 双向唯一索引兜底）；
  pending/accepted 重复申请 → `IM-409-008`；仅被申请人可处理 → `IM-403-002`；
- 黑名单阻止好友申请（`IM-409-007`）；拉黑同时把已接受好友关系置为 `removed`；
- 已读位点按端唯一，`last_seq` 只增不减（回退 `IM-409-004`）；相同位点重复上报是幂等 no-op
  （`advanced=false`，仍写审计）；
- 会话设置按 `(chat_id, user_id)` 唯一，`expected_version` 乐观锁。

### 4.6 查询面

- 读取面 `im.message.read` 遵循 `02` 查询契约：`as_of` / `recorded_as_of` / `min_version`；
- `since_seq` / `before_seq` / `limit` 是扩展读模型（按 `server_seq` 分页），在 OpenAPI 描述中
  明确标注为非核心查询语义；
- 撤回态在读投影中可见（`status` + `recalled_at/by`）。

### 4.7 权限、事件与多租户

- 每个命令与读取面都在 `manifest.permissions` 声明（`kind: command/read`），未声明即不可用；
- 本扩展没有仅限系统主体的命令，因此不声明 `callers`（不是遗漏：`callers` 只用于限制主体类型）；
- 命令产生的事件遵循 `02`/`05`（命名、`idempotency_key`、`subjects`、payload），
  审计哈希链由内核维护，扩展不另建链；
- 核心无 tenant 字段：多租户由部署/扩展字段解决，不进核心（ADR-0012 三层判据）。

### 4.8 明确不做

| 不做项 | 理由 |
|---|---|
| 网关/长连接/路由/离线推送/typing | 不产生可审计状态，保留在 IM 子系统 |
| 无状态类别增量查询、位点推进端点 | 不实体化无状态机制；不进契约面 |
| at-most-once 拉取、0-RTT、大群扇出 | 实现与部署语义，进契约会误伤 |
| 完整实时聊天（实时帧、多端同步） | 首期只做通知类 + 群组协作 + 审计 |
| 多租户字段 | 核心无 tenant；由部署/扩展解决 |
| 把 IM 反向依赖业务扩展 | 只用 `external_refs` 松耦合引用 |

## 5. 迁移方案

- 部署：`tools/schema-compiler compile --all` 生成 7 张表，执行 `migrations/V401__im_initial.sql`
  建自然键当前行唯一索引；
- 数据：新表，无核心表回填；历史 IM 子系统数据如需迁入，按对象/版本重建；
- 使用方：消息按 `(chat_id, client_msg_id)` 发送；编辑/撤回走命令；读面用 `as_of` /
  `recorded_as_of`，分页用 `since_seq`。

## 6. 回滚方案

- 回滚 V401（`V401__im_initial.rollback.sql`）→ 删除本扩展表；
- 回滚 = revert 本 ADR + 扩展目录 + CI 步骤；核心契约不受影响。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/im/manifest.yaml` | 7 对象 / 16 命令 / 3 规则 / 19 权限 |
| 对象 | `extensions/im/objects/*.schema.json` | 全部含 `id`/`version`/双时间轴；`server_seq` 为扩展字段 |
| 命令契约 | `extensions/im/operations/*.openapi.yaml` | 命令 + 只读消息面（`as_of`/`recorded_as_of`/`min_version`） |
| 处理器 | `extensions/im/handlers.py` | 幂等、seq、乐观锁、撤回追加版本、群/关系/位点 |
| 规则 | `extensions/im/rules/*.rules.yaml` | IM-MSG-001..009 / IM-GRP-001..008 / IM-REL-001..007 |
| 迁移 | `extensions/im/migrations/V401__*` | 当前行唯一索引 + 回滚 |
| 用例 | `extensions/im/tests/im.test.yaml` | 8 scenario（生命周期/幂等/冲突/群/好友/位点/直聊/授权）+ 4 static |
| CI 冒烟 | `tools/ci/im-smoke.sql`、`.github/workflows/ci.yml` | 发送幂等 / server_seq / 关系唯一 |
| 说明 | `extensions/im/README.md` | 边界、对象、命令、非目标 |

## 8. 验收用例

- `python3 tools/e2e-runner extensions/im/tests/im.test.yaml` → 12/12；
- `python3 tools/e2e-runner --all` → 全绿（计数随新增用例更新）；
- `python3 tools/contract-checker` → 通过（权限目录 / 引用完整性）；
- `python3 tools/schema-compiler check` → im 7 表编译通过（含 T-R009 排他约束）；
- CI PostgreSQL：V401 + `im-smoke.sql` 全过。
