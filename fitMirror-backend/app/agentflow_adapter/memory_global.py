"""全局 MemoryManager 访问器。

AgentFlowRuntime 在 app.router.chat 中实例化，而 chat_service / pipeline_nodes
需要读取用户画像注入到 LLM prompt。直接 import router.chat 会造成循环导入，
因此通过本模块中转单例引用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agentflow_adapter.memory import MemoryManager

_instance: "MemoryManager | None" = None


def set_memory_manager(mm: "MemoryManager") -> None:
    global _instance
    _instance = mm


def get_memory_manager() -> "MemoryManager | None":
    return _instance
