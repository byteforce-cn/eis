-- ============================================================================
-- V401__im_initial.sql — IM 协作触达层扩展（im 1.0.0）增量迁移
-- 前置：已执行 01-data-contract/core.ddl 与 build/ddl/im.ddl
--       （schema-compiler 生成 im_message / im_conversation / im_read_position /
--        im_group / im_group_member / im_friendship / im_block）
-- 内容：当前对象的自然键唯一索引（IM-MSG-001/002、IM-GRP-003、IM-REL-001/005/006/007）
-- 回滚：V401__im_initial.rollback.sql
-- ============================================================================

-- 消息：客户端幂等键 + 会话内序列（当前版本唯一）
CREATE UNIQUE INDEX uq_im_message_client_msg_current
    ON im_message (chat_id, client_msg_id)
    WHERE superseded_at IS NULL;
CREATE UNIQUE INDEX uq_im_message_server_seq_current
    ON im_message (chat_id, server_seq)
    WHERE superseded_at IS NULL;
CREATE INDEX idx_im_message_chat_seq
    ON im_message (chat_id, server_seq);

-- 会话设置：用户维度唯一
CREATE UNIQUE INDEX uq_im_conversation_user_current
    ON im_conversation (chat_id, user_id)
    WHERE superseded_at IS NULL;

-- 已读位点：端维度唯一
CREATE UNIQUE INDEX uq_im_read_position_endpoint_current
    ON im_read_position (chat_id, user_id, endpoint_id)
    WHERE superseded_at IS NULL;

-- 群成员：同一群同一用户一个当前关系（left_at 墓碑不复用行）
CREATE UNIQUE INDEX uq_im_group_member_pair_current
    ON im_group_member (group_id, user_id)
    WHERE superseded_at IS NULL;

-- 好友：与方向无关的唯一对（A→B 与 B→A 视为同一对）
CREATE UNIQUE INDEX uq_im_friendship_pair_current
    ON im_friendship (LEAST(from_user_id, to_user_id), GREATEST(from_user_id, to_user_id))
    WHERE superseded_at IS NULL;

-- 黑名单：同一对当前唯一
CREATE UNIQUE INDEX uq_im_block_pair_current
    ON im_block (user_id, blocked_user_id)
    WHERE superseded_at IS NULL;
