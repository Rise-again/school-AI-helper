"""LangGraph 状态机。

START → classify → (retrieve | edu | END)

kb 和 web 两个意图合并到同一个 `retrieve` 节点：先跑静态 RAG，按分数决定是否补联网，
合并后统一重排。这样路由判错最多是"多查了一次网"，不会直接答错。

生成不在图里：要逐 token 推给前端，放在 chat_service 里流式做。
不用 checkpointer：会话历史由 MySQL 回灌。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import AgentDeps, make_nodes
from app.agents.state import AgentState


def build_graph(deps: AgentDeps):
    nodes = make_nodes(deps)
    graph = StateGraph(AgentState)

    graph.add_node("classify", nodes["classify"])
    graph.add_node("retrieve", nodes["retrieve"])
    graph.add_node("edu", nodes["edu"])

    graph.add_edge(START, "classify")

    def route(state: AgentState) -> str:
        intent = state.get("intent", "kb")
        if intent in ("kb", "web"):
            return "retrieve"
        if intent == "edu":
            return "edu"
        return "end"  # chitchat / unknown 不检索

    graph.add_conditional_edges(
        "classify",
        route,
        {"retrieve": "retrieve", "edu": "edu", "end": END},
    )
    graph.add_edge("retrieve", END)
    graph.add_edge("edu", END)
    return graph.compile()
