-- 0002_kb_source_url.sql
-- 知识库文件记录原文链接，回答引用时可点击回到官方页面
ALTER TABLE `kb_file`
  ADD COLUMN `source_url` VARCHAR(512) NULL COMMENT '原文链接（官网页面）' AFTER `source_dept`;
