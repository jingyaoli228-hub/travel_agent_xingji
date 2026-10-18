"""4-layer Memory system.

L0 Working Memory: `working_memory.py` -- a view over LangGraph `AgentState`, no storage.
L1 Conversation Memory: `conversation_memory.py` -- Redis-backed (`redis_memory.py`), in-memory fallback.
L2 Trip Episodic Memory: `episodic_memory.py` -- local JSONL (vector DB pluggable later).
L3 User Profile Memory: `profile_memory.py` -- local JSON profile store.
`memory_manager.py` (`MemoryManager`) is the single façade over L1-L3, used by
the Requirement Agent and Planner Agent (see `graph/nodes.py`).
"""
