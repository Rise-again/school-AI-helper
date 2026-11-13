"""Agent 状态与提示词。

提示词统一带版本号，便于回溯"这条回答是哪版提示词生成的"。
改提示词等于改行为，必须升版本并记录到 devlog。
"""

from __future__ import annotations

from typing import Any, TypedDict

PROMPT_VERSION = "p3-v1"

INTENTS = ("kb", "web", "edu", "chitchat", "unknown")


class AgentState(TypedDict, total=False):
    """LangGraph 在各节点之间传递的状态。"""

    query: str
    role: str
    history: list[dict[str, str]]
    intent: str
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    degraded: str  # 非空表示某个环节降级，回答里要如实提示


INTENT_PROMPT = """你是校园问答系统的意图分类器。只输出一个标签，不要解释。

标签定义：
- kb：问学校的规章制度、办事流程、资助政策、奖惩办法等，答案通常在知识库里
- web：问最新通知、公告、近期活动、时效性信息，需要联网查
- edu：问本人的课表、成绩、学分、绩点等个人教务数据
- chitchat：打招呼、闲聊、问你是谁
- unknown：看不懂，或与校园无关

如果问题中出现"那""刚才""上面说的""这个"等指代，按【对话上文】的主题判断意图，不要因为句子短就归为 chitchat。

{context}用户问题：{query}
标签："""

REWRITE_PROMPT = """把用户的口语问题改写成适合知识库检索的关键词短语。
只输出关键词，用空格分隔，不要标点、不要解释，不超过 20 个字。
示例：入学时实在交不起学费，绿色通道谁能走？ -> 新生入学 绿色通道 申请条件
如果问题含指代（那/刚才/上面说的），必须结合【对话上文】补全主语后再输出关键词。

{context}用户问题：{query}
关键词："""

ROLE_TONE = {
    "guest": "对方是访客（新生或家长），只回答招生政策、校园百科类公开信息，不要涉及任何个人数据。",
    "student": "对方是在校学生，可以回答本人教务数据与校内事务，语气亲和、口语化。",
    "admin": "对方是运维老师，语气简洁专业，可直接给结论与操作步骤。",
}

SYSTEM_PROMPT = """你是海南热带海洋学院的校园智能助手。当前提示词版本：{version}。

回答规则（必须遵守）：
1. 只能依据下面给出的【参考资料】回答。资料里没有的，直接说"我没有找到相关依据"，不要猜测、不要用常识补全。
2. 每条结论句末必须标注出处，格式为 [编号]。参考资料共 {evidence_count} 条，编号只能是 1 到 {evidence_count}；即使只有一条也要写成 [1]，不能不标。示例："考试作弊记零分 [1]。"
3. 涉及政策、期限、金额、办理材料等敏感内容时，结尾补一句"请以学校官方最新通知为准"。
4. 资料之间存在冲突时，优先采信生效日期较新的那条。
5. 回答控制在 300 字以内，先给结论再给细节，不要罗列大段原文。

{role_tone}

【参考资料（共 {evidence_count} 条）】
{evidence}"""

NO_EVIDENCE_REPLY = (
    "我没有在知识库里找到与这个问题直接相关的依据，为避免给出错误信息，这里不做推测。\n\n"
    "建议直接咨询相关部门，或在官网查看最新通知。"
)

EDU_DEGRADED_REPLY = (
    "教务查询功能正在接入中，暂时无法直接读取你的课表与成绩。\n\n"
    "可以先到教务系统（zfjw.hntou.edu.cn）自行查看。"
)

CHITCHAT_PROMPT = """你是海南热带海洋学院的校园智能助手。用户在做简单寒暄或询问你的身份。
用一两句话友好回应，并提示可以问校园政策、办事流程、教务查询等问题。不要编造学校信息。

用户：{query}"""


def format_context(history: list[dict[str, str]], turns: int = 3) -> str:
    """把最近几轮对话压成上下文块；空历史返回空串，避免污染提示词。"""
    if not history:
        return ""
    recent = history[-turns * 2:]
    lines = []
    for msg in recent:
        role = "用户" if msg.get("role") == "user" else "助手"
        text = " ".join(str(msg.get("content", "")).split())[:120]
        lines.append(f"{role}：{text}")
    return "【对话上文】\n" + "\n".join(lines) + "\n\n"


def format_evidence(chunks: list[dict[str, Any]]) -> str:
    """把检索结果拼成带编号的参考资料块。"""
    if not chunks:
        return "（无）"
    blocks = []
    for idx, chunk in enumerate(chunks, start=1):
        meta = []
        if chunk.get("filename"):
            meta.append(str(chunk["filename"]))
        if chunk.get("heading_path"):
            meta.append(str(chunk["heading_path"]))
        if chunk.get("page_no"):
            meta.append(f"第{chunk['page_no']}页")
        header = "·".join(meta) or "未知出处"
        blocks.append(f"[{idx}] （{header}）\n{chunk.get('content', '')}")
    return "\n\n".join(blocks)
