import hashlib
import json
import logging
import re
from typing import Any, Optional

from apps.dsn.semantic_cache.models import ActionGraph, ActionNode, ActionEdge

logger = logging.getLogger("L2Cache")

PLACEHOLDER_RE = re.compile(r"\{\{(\w+):\s*(\w+)\}\}")

TYPE_CHECK_MAP = {
    "Path":  lambda v: isinstance(v, (str,)) and ("/" in v or "\\" in v),
    "Email": lambda v: isinstance(v, str) and re.match(r"[^@]+@[^@]+\.[^@]+", v) is not None,
    "URL":   lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
    "int":   lambda v: isinstance(v, int) or (isinstance(v, str) and v.isdigit()),
    "float": lambda v: isinstance(v, (int, float)),
    "str":   lambda v: isinstance(v, str),
    "bool":  lambda v: isinstance(v, bool) or str(v).lower() in ("true", "false", "1", "0"),
}


class FallbackException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def compute_action_signature(operations: list[str]) -> str:
    sorted_ops = sorted(operations)
    hashes = [hashlib.sha256(op.encode()).hexdigest() for op in sorted_ops]
    while len(hashes) > 1:
        pairs = list(zip(hashes[::2], hashes[1::2]))
        hashes = [hashlib.sha256((a + b).encode()).hexdigest() for a, b in pairs]
    return hashes[0] if hashes else hashlib.sha256(b"empty").hexdigest()[:24]


def compute_slot_hash(slots: dict[str, Any]) -> str:
    data = json.dumps(slots, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def extract_placeholders(dag: ActionGraph) -> dict[str, str]:
    placeholders = {}
    for node in dag.nodes:
        for key, value in node.params.items():
            match = PLACEHOLDER_RE.match(str(value))
            if match:
                name, typ = match.groups()
                placeholders[name] = typ
    return placeholders


def jit_compile(dag: ActionGraph, slots: dict[str, Any]) -> ActionGraph:
    compiled_nodes = []
    for node in dag.nodes:
        new_params = {}
        for key, value in node.params.items():
            match = PLACEHOLDER_RE.match(str(value))
            if match:
                name, typ = match.groups()
                if name not in slots:
                    raise FallbackException(f"缺失必填槽位: {name}")
                slot_value = slots[name]
                checker = TYPE_CHECK_MAP.get(typ)
                if checker and not checker(slot_value):
                    raise FallbackException(
                        f"类型不匹配: {name} 期望 {typ}, 实际 {type(slot_value).__name__}"
                    )
                new_params[key] = slot_value
            else:
                new_params[key] = value
        compiled_nodes.append(ActionNode(
            node_id=node.node_id, operation=node.operation,
            params=new_params, timeout_sec=node.timeout_sec,
            retry_count=node.retry_count,
        ))

    return ActionGraph(nodes=compiled_nodes, edges=list(dag.edges))


class L2Cache:

    def __init__(self, store):
        self._store = store

    def get_dag(self, action_signature: str) -> Optional[ActionGraph]:
        entry = self._store.get_l2_dag(action_signature)
        if not entry or not entry.get("dag_json"):
            return None
        try:
            dag_dict = json.loads(entry["dag_json"])
            return ActionGraph.from_dict(dag_dict)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("解析 DAG 失败: %s", e)
            return None

    def save_dag(self, action_signature: str, intent_id: str,
                 dag: ActionGraph, model_version: str = "") -> bool:
        dag_json = json.dumps(dag.to_dict(), ensure_ascii=False)
        return self._store.put_l2_dag(
            action_signature=action_signature,
            intent_id=intent_id,
            dag_json=dag_json,
            model_version=model_version,
        )

    def get_result(self, action_signature: str, slot_hash: str) -> Optional[dict]:
        return self._store.get_l2_result(action_signature, slot_hash)

    def save_result(self, action_signature: str, slot_hash: str,
                    result_text: str, tts_path: str = "",
                    response_json: str = "", duration_ms: int = 0) -> bool:
        return self._store.put_l2_result(
            action_signature=action_signature,
            slot_hash=slot_hash,
            result_text=result_text,
            tts_path=tts_path,
            response_json=response_json,
            duration_ms=duration_ms,
        )

    def record_hit(self, action_signature: str):
        self._store.update_l2_hit(action_signature)

    def build_dag_from_response(self, reply_text: str, intent_id: str = "") -> Optional[ActionGraph]:
        tool_pattern = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)
        matches = tool_pattern.findall(reply_text)

        if not matches:
            return None

        nodes = []
        edges = []

        for i, match in enumerate(matches):
            try:
                tool_data = json.loads(match.strip())
                skill = tool_data.get("skill", "")
                tool = tool_data.get("tool", "")
                params = tool_data.get("params", {})

                typed_params = {}
                for k, v in params.items():
                    if isinstance(v, str):
                        if "/" in v or "\\" in v:
                            typed_params[k] = f"{{{{{k}: Path}}}}"
                        elif "@" in v and "." in v:
                            typed_params[k] = f"{{{{{k}: Email}}}}"
                        elif v.startswith(("http://", "https://")):
                            typed_params[k] = f"{{{{{k}: URL}}}}"
                        elif v.isdigit():
                            typed_params[k] = f"{{{{{k}: int}}}}"
                        else:
                            typed_params[k] = f"{{{{{k}: str}}}}"
                    elif isinstance(v, (int, float)):
                        typed_params[k] = f"{{{{{k}: {'int' if isinstance(v, int) else 'float'}}}}}"
                    else:
                        typed_params[k] = f"{{{{{k}: str}}}}"

                node = ActionNode(
                    node_id=f"node_{i}",
                    operation=f"{skill}.{tool}",
                    params=typed_params,
                )
                nodes.append(node)

                if i > 0:
                    edges.append(ActionEdge(
                        source=f"node_{i-1}",
                        target=f"node_{i}",
                        data_flow=[],
                    ))

            except json.JSONDecodeError:
                continue

        if not nodes:
            return None

        return ActionGraph(nodes=nodes, edges=edges)

    def compile_and_check(self, action_signature: str,
                          slots: dict[str, Any]) -> tuple[Optional[ActionGraph], str]:
        dag = self.get_dag(action_signature)
        if not dag:
            return None, "DAG 不存在"

        try:
            compiled = jit_compile(dag, slots)
            return compiled, "ok"
        except FallbackException as e:
            return None, str(e)
