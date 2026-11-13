"""Agent 状态与提示词。

提示词统一带版本号，便于回溯"这条回答是哪版提示词生成的"。
改提示词等于改行为，必须升版本并记录到 devlog。
"""

from __future__ import annotations

from typing import Any, TypedDict

PROMPT_VERSION = "p3-v1"

# 生成时的上下文预算：vLLM 侧 max-model-len 是 4096，留出回答空间
CONTEXT_TOKEN_BUDGET = 3400

INTENTS = ("kb", "web", "edu", "chitchat", "unknown")


class AgentState(TypedDict, total=False):
    """LangGraph 在各节点之间传递的状态。"""

    query: str
    role: str
    identity: str  # user:<id> 或 guest:<ip>，用于按用户计配额
    history: list[dict[str, str]]
    intent: str
    keywords: str  # 路由同时产出的检索关键词
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    degraded: str  # 非空表示某个环节降级，回答里要如实提示


ROUTER_PROMPT = """你是校园问答系统的路由器。只输出一行 JSON，不要解释、不要代码块。

{{"intent": "<kb|web|edu|chitchat|unknown>", "keywords": "<检索关键词>"}}

intent 取值：
- kb：学校的规章制度、办事流程、资助政策、奖惩办法等，答案在知识库里
- web：最新通知、公告、近期活动等时效性信息
- edu：本人的课表、成绩、学分、绩点等个人教务数据
- chitchat：打招呼、闲聊、问你是谁
- unknown：看不懂或与校园无关

keywords 规则：把问题改写成适合检索的关键词（空格分隔，≤20 字）；含"那/刚才/上面"等指代时结合上文补全主语；intent 为 chitchat/unknown/edu 时留空。

{context}用户问题：{query}
JSON："""

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

必须遵守的两条硬规则：
【规则一 · 标注】回答里每个事实句的句末都要写 [编号]。参考资料共 {evidence_count} 条，
编号只能是 1 到 {evidence_count}，不能超出。**没有标注编号的回答不合格**；
即使只有一条参考，也要写成 [1]。正确示例："考试作弊记零分 [1]。"
【规则二 · 不编造】只能依据下面的资料作答。资料里没有的，直接说"我没有找到相关依据"，
不要用常识补全、不要猜测。

其他要求：
3. 涉及政策、期限、金额、办理材料等敏感内容时，结尾补一句"请以学校官方最新通知为准"。
4. 资料之间冲突时，优先采信生效日期较新的那条。
5. 回答控制在 300 字以内，先给结论再给细节，不要罗列大段原文。
6. 回答的最后一行固定写一行"参考：[用到的编号]"，例如"参考：[1][2]"。这一行不能省略。

{role_tone}

【参考资料（共 {evidence_count} 条）】
{evidence}"""

NO_EVIDENCE_REPLY = (
    "我没有在知识库里找到与这个问题直接相关的依据，为避免给出错误信息，这里不做推测。\n\n"
    "建议直接咨询相关部门，或在官网查看最新通知。"
)

GUEST_EDU_REPLY = (
    "查询课表、成绩这类个人数据需要先登录（学号绑定）。\n\n"
    "登录后我就能帮你查了；不登录也可以先问招生政策、办事流程这些公开信息。"
)

MODEL_DOWN_REPLY = (
    "抱歉，回答服务暂时不可用，请稍后再试。\n\n"
    "已检索到的资料不受影响，你也可以先到学校官网查看相关通知。"
)

EDU_DEGRADED_REPLY = (
    "教务查询功能正在接入中，暂时无法直接读取你的课表与成绩。\n\n"
    "可以先到教务系统（zfjw.hntou.edu.cn）自行查看。"
)

CHITCHAT_PROMPT = """你是海南热带海洋学院的校园智能助手。用户在做简单寒暄或询问你的身份。
用一两句话友好回应，并提示可以问校园政策、办事流程、教务查询等问题。不要编造学校信息。

用户：{query}"""


def format_context(history: list[dict[str, str]], turns: int = 5) -> str:
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
