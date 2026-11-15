-- 0005: 知识库主题标签（P8-04 主题过滤）
-- 目的：给文件打主题，检索时剔掉主题不符的证据，避免"征兵役前训练"被当成"新生军训"。

ALTER TABLE `kb_file`
  ADD COLUMN `topics` VARCHAR(128) NULL COMMENT '主题标签，逗号分隔：conscription/financial_aid/work_study/tuition/...' AFTER `source_dept`;

UPDATE `kb_file` SET `topics` = 'registration' WHERE `filename` = '学籍管理规定.txt';
UPDATE `kb_file` SET `topics` = 'conscription' WHERE `filename` LIKE '%征兵%';
UPDATE `kb_file` SET `topics` = 'conscription' WHERE `filename` LIKE '%参军%';
UPDATE `kb_file` SET `topics` = 'internship' WHERE `filename` LIKE '%实习%';
UPDATE `kb_file` SET `topics` = 'transfer_major' WHERE `filename` LIKE '%转专业%';
UPDATE `kb_file` SET `topics` = 'physical_test' WHERE `filename` LIKE '%体质健康%';
UPDATE `kb_file` SET `topics` = 'course_select' WHERE `filename` LIKE '%选课%' OR `filename` LIKE '%开课目录%';
UPDATE `kb_file` SET `topics` = 'financial_aid' WHERE `filename` = '海南热带海洋学院国家助学金评定实施办法.pdf';
UPDATE `kb_file` SET `topics` = 'scholarship,financial_aid' WHERE `filename` = '海南热带海洋学院国家励志奖学金评审实施办法.pdf';
UPDATE `kb_file` SET `topics` = 'work_study' WHERE `filename` LIKE '%勤工助学%';
UPDATE `kb_file` SET `topics` = 'tuition,financial_aid' WHERE `filename` = '海南热带海洋学院家庭经济困难学生学费减免实施办法.pdf';
UPDATE `kb_file` SET `topics` = 'financial_aid' WHERE `filename` = '海南热带海洋学院家庭经济困难学生认定办法.pdf';
UPDATE `kb_file` SET `topics` = 'tuition,financial_aid' WHERE `filename` = '海南热带海洋学院少数民族学生学费补助实施办法.pdf';
UPDATE `kb_file` SET `topics` = 'tuition,financial_aid,registration' WHERE `filename` LIKE '%绿色通道%';
UPDATE `kb_file` SET `topics` = 'scholarship,financial_aid' WHERE `filename` = '海南热带海洋学院海南省优秀贫困大学生奖学金评审实施办法.pdf';
