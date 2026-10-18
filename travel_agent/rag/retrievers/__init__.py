"""Five retrievers dispatched in parallel by `parallel_retriever.py`:
dense/keyword/metadata (over `travel_guides`) + episodic/profile (over the
existing L2/L3 memory stores). Each exposes a module-level `retrieve(context)
-> list[RetrievedChunk]` so `ToolManager.call(retrieve, {"context": ...},
tool_name=...)` can dispatch them uniformly.
"""
