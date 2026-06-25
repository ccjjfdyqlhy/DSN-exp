import logging
from collections import deque
from typing import Optional

logger = logging.getLogger("GraphEngine")


class GraphEngine:

    def __init__(self, graph_store: Optional['GraphStore'] = None):
        self._store = graph_store

    def find_weak_path(self, user_id: int, kp_code: str) -> list[dict]:
        """薄弱路径分析: 从不会的知识点 BFS 回溯到根因"""
        if not self._store:
            return []

        state = self._store.get_user_state(user_id, kp_code)
        is_weak = (state and state.get("confidence", 1.0) < 0.5) or state is None

        visited = set()
        queue = deque()
        parent_map = {}

        queue.append((kp_code, 0))
        visited.add(kp_code)

        while queue:
            current, depth = deque.popleft(queue)
            if depth > 5:
                continue
            parents = self._store.get_parents(current)
            for p in parents:
                pk = p["kp_code"]
                if pk not in visited:
                    visited.add(pk)
                    parent_map[pk] = current
                    p_state = self._store.get_user_state(user_id, pk)
                    p_weak = (p_state and p_state.get("confidence", 1.0) < 0.5) or p_state is None
                    if p_weak:
                        queue.append((pk, depth + 1))

        # 重建路径: 从最根源的薄弱节点到当前节点
        path = []
        cur = kp_code
        while cur in parent_map:
            cur = parent_map[cur]
        # cur 现在是根因
        start = cur
        while start != kp_code:
            node = self._store.get_node(start)
            if node:
                s = self._store.get_user_state(user_id, start)
                node["user_state"] = s
                path.append(node)
            children = self._store.get_children(start)
            next_found = None
            for c in children:
                if c["kp_code"] in parent_map or c["kp_code"] == kp_code:
                    next_found = c["kp_code"]
                    break
            if not next_found:
                break
            start = next_found

        node = self._store.get_node(kp_code)
        if node:
            s = self._store.get_user_state(user_id, kp_code)
            node["user_state"] = s
            path.append(node)

        return path

    def find_related(self, kp_code: str, depth: int = 2) -> list[dict]:
        """关联推荐: 沿边扩散"""
        if not self._store:
            return []
        visited = {kp_code}
        result = []
        queue = deque([(kp_code, 0)])
        while queue:
            current, d = deque.popleft(queue)
            if d >= depth:
                continue
            related = self._store.get_related(current)
            for node in related:
                pk = node["kp_code"]
                if pk not in visited:
                    visited.add(pk)
                    node["_depth"] = d + 1
                    result.append(node)
                    queue.append((pk, d + 1))
        return result

    def recommend_review(self, user_id: int, limit: int = 5) -> list[dict]:
        """间隔复习推荐"""
        if not self._store:
            return []
        due = self._store.get_due_reviews(user_id, limit=limit)
        return due

    def propagate_mastery(self, user_id: int, kp_code: str) -> None:
        """掌握传播: 子节点掌握 → 父节点置信度自动提升"""
        if not self._store:
            return
        state = self._store.get_user_state(user_id, kp_code)
        if not state or state.get("confidence", 0) < 0.7:
            return

        parents = self._store.get_parents(kp_code)
        for p in parents:
            pk = p["kp_code"]
            children = self._store.get_children(pk)
            if not children:
                continue
            total = 0.0
            count = 0
            for c in children:
                cs = self._store.get_user_state(user_id, c["kp_code"])
                if cs:
                    total += cs.get("confidence", 0.0)
                    count += 1
            if count > 0:
                avg_conf = total / count
                p_state = self._store.get_user_state(user_id, pk)
                if p_state:
                    new_conf = max(p_state.get("confidence", 0.0), avg_conf * 0.85)
                    self._store.update_node(pk, {"confidence": new_conf})

    def build_initial_graph(self, subject: str, textbook_outline: str) -> dict:
        """从教材目录生成初始知识图 (需要外部 LLM 调用)"""
        return {
            "success": False,
            "error": "需要 LLM 调用，请使用 KnowledgeGraphBuilder"
        }

    def get_mastery_summary(self, user_id: int, subject: str) -> dict:
        """掌握度概览"""
        if not self._store:
            return {"total": 0, "mastered": 0, "weak": 0, "untouched": 0}

        all_nodes = self._store.get_nodes_by_subject(subject)
        total = len(all_nodes)
        mastered = 0
        weak = 0
        untouched = 0

        for n in all_nodes:
            state = self._store.get_user_state(user_id, n["kp_code"])
            if not state:
                untouched += 1
            elif state.get("confidence", 0) >= 0.7:
                mastered += 1
            else:
                weak += 1

        return {
            "total": total,
            "mastered": mastered,
            "weak": weak,
            "untouched": untouched,
            "mastery_rate": round(mastered / total * 100, 1) if total > 0 else 0,
        }

    def get_subject_tree(self, subject: str) -> list[dict]:
        """返回科目知识点树"""
        if not self._store:
            return []
        nodes = self._store.get_nodes_by_subject(subject)
        node_map = {n["kp_code"]: n for n in nodes}
        roots = [n for n in nodes if n.get("level", 0) == 0]
        for n in nodes:
            n["children"] = []
        for n in nodes:
            parent_code = n.get("parent_code")
            if parent_code and parent_code in node_map:
                node_map[parent_code]["children"].append(n)
        return roots
