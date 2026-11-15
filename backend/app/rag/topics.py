"""知识库主题标签与查询主题识别（P8-04 第一层：主题过滤）。

解决的是"同领域不同事项被当成同一件事"：知识库里只有《征兵20问》，
用户问"新生军训"，检索分数 0.80，级联判定"知识库够用"，于是把役前集训的
物资清单当成军训材料回答。这里给文件打主题、给问题识别主题，两边不匹配的
证据在进重排/合并之前就剔掉；识别到主题但库里没有对应文件时，按"库外"处理
（走联网或拒答），不再拿相近主题的文档硬凑。

原则：
- 只做过滤，不改提示词、不改分数、不改模型；
- 问题识别不到主题时不删任何证据（宁漏不误伤）；
- 一个文件可以有多个主题（如绿色通道同时涉及学费与资助）。
"""

from __future__ import annotations

from typing import Any, Iterable

# 主题 -> 触发词。词要够具体："训练"太泛不收，"军训"才收。
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "military_training": ("新生军训", "入学军训", "军训"),
    "conscription": ("征兵", "参军", "入伍", "役前", "服役", "军旅", "应征"),
    "financial_aid": ("助学金", "家庭经济困难", "困难认定", "困难生", "资助"),
    "scholarship": ("奖学金", "励志", "优秀贫困"),
    "work_study": ("勤工助学", "勤工俭学", "打工", "兼职"),
    "tuition": ("学费减免", "学费补助", "绿色通道", "缓交", "学费"),
    "transfer_major": ("转专业",),
    "physical_test": ("体质健康", "体测", "体育测试"),
    "course_select": ("选课", "通识课", "选修课", "开课目录"),
    "internship": ("实习",),
    "registration": ("报到", "学籍", "注册", "入学手续"),
    # 以下两类知识库里没有对应文件，识别到即走联网（用于动态搜索）
    "admissions": ("招生", "录取", "分数线", "招生简章", "专升本", "新增专业", "招生计划"),
    "campus_service": ("食堂", "宿舍", "校医院", "班车", "报修", "快递", "校园卡", "图书馆", "接站", "超市", "浴室", "开水"),
}

# 文件主题（迁移 0005 已落到 kb_file.topics；这里保留一份便于测试与新增文件参考）
FILE_TOPICS: dict[str, str] = {
    "学籍管理规定.txt": "registration",
    "2026年10月秋季征兵折页.pdf": "conscription",
    "三亚-实习岗位征集表.xls": "internship",
    "人文社会科学学院2026年本科生转专业实施方案.pdf": "transfer_major",
    "儋州-实习计划表.xls": "internship",
    "关于2026-2027学年《国家学生体质健康标准》测试工作通知..pdf": "physical_test",
    "参军量化考核标准.pdf": "conscription",
    "大学体育3选课操作方法(7).pdf": "course_select",
    "海南热带海洋学院国家助学金评定实施办法.pdf": "financial_aid",
    "海南热带海洋学院国家励志奖学金评审实施办法.pdf": "scholarship,financial_aid",
    "海南热带海洋学院学生勤工助学管理办法.pdf": "work_study",
    "海南热带海洋学院家庭经济困难学生学费减免实施办法.pdf": "tuition,financial_aid",
    "海南热带海洋学院家庭经济困难学生认定办法.pdf": "financial_aid",
    "海南热带海洋学院少数民族学生学费补助实施办法.pdf": "tuition,financial_aid",
    "海南热带海洋学院新生入学“绿色通道”实施办法.pdf": "tuition,financial_aid,registration",
    "海南热带海洋学院校内勤工助学岗位管理办法.pdf": "work_study",
    "海南热带海洋学院海南省优秀贫困大学生奖学金评审实施办法.pdf": "scholarship,financial_aid",
    "2025-2026-1通识类选修课开课目录.xlsx": "course_select",
    "热海大高校征兵20问解答（最新版）.pdf": "conscription",
    "计算机学院2025-2026学年第二学期学生转专业工作实施方案.pdf": "transfer_major",
}


def detect_topics(*texts: str | None) -> set[str]:
    """从问题与改写关键词里识别主题；识别不到返回空集（表示不过滤）。"""
    merged = " ".join(str(t) for t in texts if t)
    if not merged:
        return set()
    return {
        topic
        for topic, words in TOPIC_KEYWORDS.items()
        if any(word in merged for word in words)
    }


def split_topics(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, (set, list, tuple)):
        return {str(v).strip() for v in value if str(v).strip()}
    return {part.strip() for part in str(value).split(",") if part.strip()}


def keep_matching(items: Iterable[dict[str, Any]], topics: set[str]) -> list[dict[str, Any]]:
    """按主题保留证据；topics 为空、或整批证据都没有标签时原样返回（不做无依据的过滤）。"""
    if not topics:
        return list(items)
    rows = list(items)
    if not any(split_topics(item.get("topics")) for item in rows):
        return rows
    return [item for item in rows if split_topics(item.get("topics")) & topics]
