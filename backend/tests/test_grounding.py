"""回答落地校验（grounding）单测。

用例取自真实回答：模型在资料没写时会补岗位名、补材料清单、补金额。
"""

from __future__ import annotations

from app.services.grounding import audit_answer, drop_violations, split_sentences

EVIDENCE = [
    {
        "content": (
            "第二十三条 校内固定岗位报酬不低于400元/月，每月工作时间不低于20小时，"
            "不超过40小时。校内临时岗位按小时计酬，每小时15元。\n"
            "第十五条 申请校内勤工助学固定岗位的学生应具备如下条件：遵纪守法；"
            "学习努力，上一学期考试中不及格科目不超过两科；被学校认定为家庭经济困难；"
            "生活勤俭节约。\n"
            "校内勤工助学岗位分为固定岗位和临时岗位两类。"
        )
    }
]


def test_clean_answer_passes():
    answer = (
        "校内固定岗位报酬不低于400元/月，每月工作时间20到40小时 [1]。"
        "岗位分为固定岗位和临时岗位两类 [1]。\n参考：[1]"
    )
    assert audit_answer(answer, EVIDENCE) == []


def test_hallucinated_job_titles_flagged():
    # 真实出现过的回答：资料只写"分固定和临时两类"，模型自己补了岗位名
    answer = "学生参加勤工助学活动通常涉及多种岗位，包括但不限于校内教学助理、科研助理、图书管理、后勤服务等 [1]。"
    spans = {v.span for v in audit_answer(answer, EVIDENCE)}
    assert "校内教学助理" in spans
    assert "科研助理" in spans
    assert "图书管理" in spans


def test_hallucinated_materials_flagged():
    answer = "需提供身份证复印件、家庭经济状况证明等材料 [1]。"
    spans = {v.span for v in audit_answer(answer, EVIDENCE)}
    assert "身份证复印件" in spans
    assert "家庭经济状况证明" in spans


def test_fabricated_number_flagged():
    answer = "校内固定岗位报酬不低于300元/月 [1]。"
    assert [v.kind for v in audit_answer(answer, EVIDENCE)] == ["number"]


def test_fabricated_book_title_flagged():
    answer = "需填写《海南热带海洋学院勤工助学申请表》 [1]。"
    assert [v.span for v in audit_answer(answer, EVIDENCE)] == ["海南热带海洋学院勤工助学申请表"]


def test_single_item_after_ru_not_treated_as_enumeration():
    answer = "如无特殊情况，按上述标准执行 [1]。"
    assert audit_answer(answer, EVIDENCE) == []


def test_two_class_split_not_treated_as_enumeration():
    answer = "岗位分为固定岗位和临时岗位 [1]。"
    assert audit_answer(answer, EVIDENCE) == []


def test_paraphrase_with_de_is_accepted():
    # "家庭经济困难的学生" 与原文"家庭经济困难"只差一个"的"
    answer = "需被学校认定为家庭经济困难的学生 [1]。"
    assert audit_answer(answer, EVIDENCE) == []


def test_reference_line_is_skipped():
    answer = "参考：[1]"
    assert audit_answer(answer, EVIDENCE) == []


def test_drop_violations_removes_whole_sentence():
    answer = "校内固定岗位报酬不低于400元/月 [1]。岗位包括图书管理、后勤服务等 [1]。"
    violations = audit_answer(answer, EVIDENCE)
    assert drop_violations(answer, violations) == "校内固定岗位报酬不低于400元/月 [1]。"


def test_drop_violations_can_empty_answer():
    answer = "岗位包括图书管理、后勤服务等 [1]。"
    assert drop_violations(answer, audit_answer(answer, EVIDENCE)) == ""


def test_no_evidence_no_audit():
    # 没有资料时不做校验，走固定话术
    assert audit_answer("随便说点什么 [1]", []) == []


def test_split_sentences_keeps_punctuation():
    assert split_sentences("第一句。第二句；第三句\n第四句") == [
        "第一句。",
        "第二句；",
        "第三句\n",
        "第四句",
    ]


def test_out_of_range_citation_flagged():
    answer = "校内固定岗位报酬不低于400元/月 [7]。"
    kinds = [v.kind for v in audit_answer(answer, EVIDENCE)]
    assert kinds == ["citation"]


def test_out_of_range_citation_keeps_sentence():
    """编号写错不该整句删掉，只摘掉编号。"""
    answer = "校内固定岗位报酬不低于400元/月 [7]。参考：[7]"
    out = drop_violations(answer, audit_answer(answer, EVIDENCE))
    assert "400元/月" in out
    assert "[7]" not in out


def test_title_split_by_page_header_is_accepted():
    """PDF 页眉把表格名切断时，不该误判成编造。"""
    evidence = [
        {"content": "第十一条 学生参加勤工助学活动，须填写《海南热带海洋 -167- 海南热带海洋学院 学生手册2025年 学生勤工助学申请表》后方可上岗。"}
    ]
    answer = "须填写《海南热带海洋学院学生勤工助学申请表》 [1]。"
    assert audit_answer(answer, evidence) == []
