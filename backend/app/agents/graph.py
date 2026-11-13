"""LangGraph 状态机。

START → classify → (kb | web | edu | END)
生成不在图里：生成要逐 token 推给前端，放在 chat_service 里流式做，
图只负责"想清楚该用哪个工具、拿到什么证据"。

不用 checkpointer：会话历史由 MySQL 回灌，避免多一个持久化层导致状态双写不一致。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import AgentDeps, make_nodes
from app.agents.state import AgentState


def build_graph(deps: AgentDeps):
    nodes = make_nodes(deps)
    graph = StateGraph(AgentState)

    graph.add_node("classify", nodes["classify"])
    graph.add_node("kb", nodes["kb"])
    graph.add_node("web", nodes["web"])
    graph.add_node("edu", nodes["edu"])

    graph.add_edge(START, "classify")

    def route(state: AgentState) -> str:
        intent = state.get("intent", "kb")
        if intent in ("kb", "web", "edu"):
            return intent
        return "end"  # chitchat / unknown 不需要检索

    graph.add_conditional_edges("classify", route, {"kb": "kb", "web": "web", "edu": "edu", "end": END})
    graph.add_edge("kb", END)
    graph.add_edge("web", END)
    graph.add_edge("edu", END)
    return graph.compile()
