"""主题过滤的单元测试：识别主题、按主题筛证据。"""

from __future__ import annotations

from app.rag.topics import detect_topics, keep_matching, split_topics


def test_detect_military_training_not_conscription():
    assert detect_topics("军训相关事项") == {"military_training"}
    assert detect_topics("新生军训需要准备什么") == {"military_training"}
    # 役前训练属于征兵，不是新生军训
    assert detect_topics("役前训练要带什么") == {"conscription"}
    assert detect_topics("大学生参军有什么政策") == {"conscription"}


def test_detect_multi_topic_and_empty():
    assert detect_topics("助学金和奖学金能同时拿吗") == {"financial_aid", "scholarship"}
    assert detect_topics("勤工助学一周几小时") == {"work_study"}
    assert detect_topics("学校食堂好吃吗") == set()
    assert detect_topics(None, "") == set()


def test_split_topics_variants():
    assert split_topics("tuition,financial_aid") == {"tuition", "financial_aid"}
    assert split_topics(["a", "b"]) == {"a", "b"}
    assert split_topics(None) == set()


def test_keep_matching_filters_by_topic():
    items = [
        {"content": "役前训练物资", "topics": "conscription"},
        {"content": "勤工助学工时", "topics": "work_study"},
        {"content": "绿色通道", "topics": "tuition,financial_aid,registration"},
    ]
    kept = keep_matching(items, {"military_training"})
    assert kept == []  # 库里没有军训主题文件 → 全部剔除
    assert [i["content"] for i in keep_matching(items, {"work_study"})] == ["勤工助学工时"]
    assert keep_matching(items, set()) == items  # 识别不到主题时不过滤
