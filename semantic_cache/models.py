from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CacheEntry:
    cache_key: str = ""
    user_id: int = 0
    intent_class: str = ""
    query_text: str = ""
    query_embedding: Optional[list[float]] = None
    reply_text: str = ""
    reply_tts_path: str = ""
    hit_count: int = 0
    score: float = 1.0
    created_at: str = ""
    last_hit_at: str = ""


@dataclass
class L1Entry:
    intent_id: str = ""
    speech_act_type: str = ""
    text: str = ""
    tts_path: str = ""
    hit_count: int = 0


@dataclass
class SearchResult:
    cache_key: str = ""
    query_text: str = ""
    reply_text: str = ""
    reply_tts_path: str = ""
    similarity: float = 0.0
    score: float = 1.0


@dataclass
class ActionNode:
    node_id: str = ""
    operation: str = ""
    params: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 30
    retry_count: int = 0


@dataclass
class ActionEdge:
    source: str = ""
    target: str = ""
    data_flow: list[str] = field(default_factory=list)


@dataclass
class ActionGraph:
    nodes: list[ActionNode] = field(default_factory=list)
    edges: list[ActionEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {"node_id": n.node_id, "operation": n.operation,
                 "params": n.params, "timeout_sec": n.timeout_sec,
                 "retry_count": n.retry_count}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target,
                 "data_flow": e.data_flow}
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionGraph":
        nodes = [
            ActionNode(
                node_id=n["node_id"], operation=n["operation"],
                params=n.get("params", {}), timeout_sec=n.get("timeout_sec", 30),
                retry_count=n.get("retry_count", 0),
            )
            for n in data.get("nodes", [])
        ]
        edges = [
            ActionEdge(
                source=e["source"], target=e["target"],
                data_flow=e.get("data_flow", []),
            )
            for e in data.get("edges", [])
        ]
        return cls(nodes=nodes, edges=edges)

    def topological_sort(self) -> list[ActionNode]:
        in_degree = {n.node_id: 0 for n in self.nodes}
        adj = {n.node_id: [] for n in self.nodes}
        for e in self.edges:
            adj[e.source].append(e.target)
            in_degree[e.target] = in_degree.get(e.target, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        node_map = {n.node_id: n for n in self.nodes}

        while queue:
            nid = queue.pop(0)
            result.append(node_map[nid])
            for next_id in adj[nid]:
                in_degree[next_id] -= 1
                if in_degree[next_id] == 0:
                    queue.append(next_id)

        return result


@dataclass
class L2Entry:
    action_signature: str = ""
    intent_id: str = ""
    dag: Optional[ActionGraph] = None
    model_version: str = ""
    hit_count: int = 0
    created_at: str = ""
    last_hit_at: str = ""


@dataclass
class L2Result:
    result_id: int = 0
    action_signature: str = ""
    slot_hash: str = ""
    result_text: str = ""
    reply_tts_path: str = ""
    response_json: str = ""
    executed_at: str = ""
    duration_ms: int = 0


@dataclass
class SlotEntry:
    slot_name: str = ""
    slot_type: str = ""
    value: Any = None
    value_json: str = ""
    confidence: float = 1.0
    source: str = "extracted"
    session_id: str = ""
    created_at: str = ""
    expires_at: str = ""
