# ADR-0003：IAM 首落地——扩展边界与审计范围

- **状态**：Accepted（随 `docs/LANDING-IAM.md` v1.0.0 执行完毕）
- **日期**：2026-10-10
- **决策者**：核心维护者（LANDING-IAM 评估点 1 / 2 正式落档）
- **关联**：`docs/LANDING-IAM.md`（§4 / §8 #1 #2 / §11 执行回报）、`extensions/iam/**`、`tools/lib/kernel.py`

## 1. 变更原因

IAM 是 EIS 规范的首个全量落地扩展，落地评审提出两个必须先于编码定案、且影响后续所有扩展的边界问题：

1. **扩展与核心 04（授权契约）的边界**——管理面需要 Role / RoleBinding 的
   DDL 与可执行用例，但 04 的判定语义是冻结权威。若不先定边界，将出现
   「同一概念两处定义、语义漂移」的解冻风险。
2. **审计范围**——认证失败/命令拒绝是否进入审计链。核心语义为「受理才入
   链」，但安全侧存在「拒绝也应可追溯」的诉求，需要正式口径。

**不做的后果**：边界不清 → 05/04 契约事实性双写、后续扩展各自为政；
审计口径不清 → 安全审计缺口无正式记录载体。

## 2. 影响范围

- 契约：**无修改**（01–06 冻结文件未触碰；本 ADR 只记录落地口径）。
- 扩展：新增 `extensions/iam`（对象 5 / 命令 11 / 规则 5 / 用例 10 场景）。
- 案例：`cases/` 无变更。
- 工具：`tools/lib/kernel.py` 增 IAM 命令处理器；`tools/e2e-runner` 用例面扩展（53 全绿）。

## 3. 兼容性分析

- 级别判定：**MINOR**（`compatibility.rules.yaml`：纯新增扩展与工具能力，无冻结工件变更）。
- 破坏点：无。既有扩展（accounting/inventory/approval）语义与工件不受影响。

## 4. 迁移方案

不适用（纯新增，无数据迁移）。

## 5. 回滚方案

删除 `extensions/iam` 并回退 kernel 处理器即可（无外部状态残留）；用例随扩展移除。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/iam/manifest.yaml` | 对象 / 操作 / 规则 / 不变量声明 |
| 对象契约 | `extensions/iam/objects/*.schema.json` | UserAccount / Credential / Role / RoleBinding / AuthSession |
| 操作契约 | `extensions/iam/operations/*.openapi.yaml` | 11 命令（含错误码与脱敏标注） |
| 规则声明 | `extensions/iam/rules/*.yaml` | username_unique / root_protected / no_self_grant / binding_sod_precheck / old_credential_check |
| 生成物 DDL | `build/ddl/iam.ddl` | schema-compiler 生成（`iam_*` 表） |
| 可执行用例 | `extensions/iam/tests/iam.test.yaml` | 10 场景（创建/唯一/级联/保护/轮换/SoD/时间旅行/幂等/自授权） |
| 参考内核 | `tools/lib/kernel.py` | IAM 命令实现（行为基准） |

**决策记录（要点）**：

- **#1 边界（方案 A）**：管理面（对象/命令/规则）全部落 IAM 扩展；04 判定语义
  **不动**——判定唯一权威为 04 语义实现（seedj `starter-eis-authz` / 参考
  `authz-resolver`）；扩展中的 Role/RoleBinding 为**管理面镜像**，与 04 的
  「授权事实」经投影对接，不做语义复制。
- **#2 审计范围（v1 方案 A）**：**受理才入审计链**（与核心语义一致）；拒绝命令在
  `command` 表以 `rejected` + 错误码留痕（`eis_command_rejection`），**不入审计
  链**。若合规要求更严，另起 ADR 增补「安全审计通道」（不修改现有链语义）。

## 7. 验收用例

- `python3 tools/e2e-runner --all` → 用例 **53/53**、场景 1/1、流水线 5/5（全绿）。
- 审计口径：场景「重复用户名被拒绝」验证拒绝不入链、对象计数不变；
  「创建用户并写入审计链」验证受理入链且链验 valid。
- 落地回归：三仓执行回报见 `docs/LANDING-IAM.md` §11（server `mvn verify`
  15/15 + `scripts/smoke-login.sh` 全过）。
