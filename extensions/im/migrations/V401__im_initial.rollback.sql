-- ============================================================================
-- V401__im_initial.rollback.sql — 回滚 V401
-- 不删表（表由 build/ddl/im.ddl 生成）；仅移除本迁移新增的索引。
-- ============================================================================

DROP INDEX IF EXISTS uq_im_block_pair_current;
DROP INDEX IF EXISTS uq_im_friendship_pair_current;
DROP INDEX IF EXISTS uq_im_group_member_pair_current;
DROP INDEX IF EXISTS uq_im_read_position_endpoint_current;
DROP INDEX IF EXISTS uq_im_conversation_user_current;
DROP INDEX IF EXISTS idx_im_message_chat_seq;
DROP INDEX IF EXISTS uq_im_message_server_seq_current;
DROP INDEX IF EXISTS uq_im_message_client_msg_current;
