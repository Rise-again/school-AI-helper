"""Agent 状态与提示词。

提示词统一带版本号，便于回溯"这条回答是哪版提示词生成的"。
改提示词等于改行为，必须升版本并记录到 devlog。
"""

from __future__ import annotations

from typing import Any, TypedDict

PROMPT_VERSION = "p3-v2"

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
- chitchat：打招呼、道谢、问你是谁、问你能做什么这类寒暄
- unknown：与校园无关的其他请求（写诗、讲笑话、天气、电影、算术等），或看不懂的话

注意：问学校有没有某类岗位、政策、办法、规定（例如"校内有勤工助学岗位吗"），
即使含"校内""岗位""有没有"这类字眼，也属于 kb。只有明确问"最新/近期/今年"的通知公告才判 web。

keywords 规则（很重要，决定了能不能检索到）：
1. 知识库是学校官方文件，用词规范。**把口语换成公文里的标准说法**。
   如：勤工俭学/打工/兼职 → 勤工助学；贫困生 → 家庭经济困难学生；成绩单 → 成绩证明。
2. 用户问的是"是什么感觉/会怎样"，要**换成文件里可能出现的表述**。
   如："会不会和上课时间冲突" → "影响学习"；"一个月能拿多少钱" → "劳动报酬"；
   "报的人多不多" → "岗位设置"。
3. 只用空格分隔的关键词，不超过 20 字；intent 为 chitchat/unknown/edu 时留空。
4. 含"那/刚才/上面"等指代时，结合下文补全主语。

{terms}{context}用户问题：{query}
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

必须遵守的硬规则：
【规则一 · 标注】回答里每个事实句的句末都要写 [编号]。参考资料共 {evidence_count} 条，
编号只能是 1 到 {evidence_count}，不能超出。正确示例："考试作弊记零分 [1]。"
**只在最后一行写"参考：[1]"不算标注**，正文里每个事实句都必须自带编号；
即使只有一条参考，也要写成 [1]。一句里有多个依据就写 [1][2]。
【规则二 · 不编造】只能依据下面的资料作答，**不要用常识补全**。
资料里没有的具体岗位名称、材料、证件、金额、时间、部门，一律不要列举；
例如资料只说"分固定岗位和临时岗位"，就不要再补"图书馆管理、办公室助理"这类岗位。
原文用的是"勤工助学"，回答里不要改称"勤工俭学"。
【规则三 · 不凑字数】先直接回答问题，再补充必要细节，不要为显得完整而罗列申请流程。
问"多不多/难不难/好不好/有没有帮助"这类判断性问题时，资料没写就直接说"资料中没有明确说明"，
不要用"可能有帮助""影响不大""可能性较小"这类推测性结论，也不要用流程步骤充数。
资料与问题只是沾边、没有正面回答的，直接说"资料中没有直接说明这一点"，不要硬凑。

其他要求：
4. 涉及政策、期限、金额、办理材料等敏感内容时，结尾补一句"请以学校官方最新通知为准"。
5. 资料之间冲突时，优先采信生效日期较新的那条。
6. 回答控制在 300 字以内，不要罗列大段原文。
7. 回答的最后一行固定写一行"参考：[用到的编号]"，例如"参考：[1][2]"。这一行不能省略。

{role_tone}

【参考资料（共 {evidence_count} 条）】
{evidence}

现在开始作答。再次提醒：正文每个事实句的句末都要写 [编号]（1–{evidence_count}），
最后一行写"参考：[用到的编号]"。只依据上面的资料，不要补充资料里没有的具体名称。"""

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


def format_terms(titles: list[str]) -> str:
    """把知识库文件标题压成"用词参考"块，供改写时对齐官方说法。"""
    if not titles:
        return ""
    cleaned = []
    for title in titles[:30]:
        name = title.rsplit(".", 1)[0]
        if name and name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        return ""
    return "【知识库已有文件主题（参考用词，不要照抄整句）】\n" + "、".join(cleaned) + "\n\n"


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
