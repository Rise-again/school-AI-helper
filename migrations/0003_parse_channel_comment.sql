-- 0003_parse_channel_comment.sql
-- 修正 parse_channel 的取值说明：实际会产生四种值，不只是 markitdown / ocr
ALTER TABLE `kb_file`
  MODIFY COLUMN `parse_channel` VARCHAR(16) NULL
  COMMENT '解析通道：markitdown / pdf-text / pdf-text+ocr / ocr';
