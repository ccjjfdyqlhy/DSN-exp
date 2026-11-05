# apps/dsn_study/skills/builtin/obsidian_notes/tools/obsidian_tools.py
# Obsidian 知识库工具 —— 把 dsn_study 的学习数据落到 Obsidian vault。
#
# 与「直接把 MCP 工具暴露给 AI」的区别：MCP 的 12 个原始工具（mcp.obsidian.*）
# 已经在 AgentLoop 里，AI 可以自由读写笔记；本技能补的是**领域动作**——
# 把知识图谱的知识点批量索引成结构化笔记、把学习记录写成笔记，这类需要
# dsn_study 内部数据（图谱/错题/计划）的复合操作。
#
# 全部写操作都经 MCP（obsidian-mcp → vault 文件），因此：
#   * Obsidian 桌面端无需运行，写完即生效；
#   * 删除走 trash（.obsidian-mcp/trash），可恢复；
#   * 写入带 etag 乐观锁，避免覆盖别人改过的笔记。

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger("skill.obsidian_notes")

#: 知识点 → 笔记文件名的净化（去掉路径分隔符与非法字符）
_BAD_CHARS = re.compile(r"[\\/:*?\"<>|]+")


class ObsidianNotesTool:
    """Obsidian 知识库索引与笔记工具。"""

    def __init__(self, mcp_bridge=None, graph_store=None, plan_engine=None,
                 vault_id: str = "study", kp_folder: str = "知识点库",
                 note_folder: str = "学习笔记"):
        # 属性名必须与 inject_dependencies 的 key 一致，否则依赖注入会被静默跳过
        self.mcp_bridge = mcp_bridge
        self.graph_store = graph_store
        self.plan_engine = plan_engine
        self._vault = vault_id
        self._kp_folder = (kp_folder or "知识点库").strip("/")
        self._note_folder = (note_folder or "学习笔记").strip("/")

    # ── 基础设施 ──

    async def _await_mcp(self, timeout: float = 30.0):
        """等待 MCP 连接就绪（后台线程在连接时给一点等待窗口）。"""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.mcp_bridge is not None and self.mcp_bridge.manager is not None:
                return self.mcp_bridge.manager
            await asyncio.sleep(0.5)
        raise RuntimeError("Obsidian MCP 未就绪（连接失败或仍在启动）")

    async def _call(self, tool: str, args: dict):
        """调用远端 MCP 工具，返回 (ok, 文本)。"""
        if self.mcp_bridge is None:
            return False, "Obsidian MCP 未接入"
        await self._await_mcp()
        result = await self.mcp_bridge.call("obsidian", tool, args)
        if not result.success:
            return False, str(result.error or "调用失败")
        return True, str(result.output or "")

    def _subject_label(self, code) -> str:
        """科目代码 → 中文名（取不到就退回代码）。"""
        raw = str(code or "").strip()
        if not raw:
            return "通用"
        try:
            conn = self.graph_store._db._get_connection()
            row = conn.execute(
                "SELECT name FROM subjects WHERE code = ?", (raw,)).fetchone()
            if row and row["name"]:
                return str(row["name"])
        except Exception:
            pass
        return raw

    @staticmethod
    def _safe_name(text: str) -> str:
        """把任意标题变成安全的文件名（保留中文）。"""
        cleaned = _BAD_CHARS.sub("", str(text or "")).strip()
        cleaned = cleaned.replace("\n", " ").strip()
        return (cleaned or "未命名")[:80]

    # ── 知识点库索引 ──

    async def index_knowledge_points(self, subject: str = "", limit: int = 50,
                                     overwrite: bool = False,
                                     user_id: int = 0) -> dict:
        """把知识图谱的知识点索引成 Obsidian 笔记。

        每个知识点一篇笔记，路径 <知识点库目录>/<科目>/<kp_code>.md，
        frontmatter 记录编码/科目/掌握度/下次复习，正文给出知识点说明与复习记录。
        """
        if self.graph_store is None:
            return {"error": "知识图谱未初始化"}
        nodes, states = self._collect_nodes(subject, user_id, limit)
        if isinstance(nodes, dict):
            return nodes
        if not nodes:
            return {"success": True, "indexed": 0, "message": "没有可索引的知识点"}

        ok, err = await self._call("obsidian_create_directory",
                                   {"vault": self._vault,
                                    "path": self._kp_folder})
        if not ok:
            return {"error": "创建目录失败: %s" % err}

        indexed, skipped, errors = 0, 0, []
        for node in nodes:
            subject_label = self._subject_label(node.get("subject"))
            path = "%s/%s/%s.md" % (self._kp_folder,
                                   self._safe_name(subject_label),
                                   self._safe_name(str(node.get("kp_code") or node.get("name"))))
            content = self._render_kp_note(node, states.get(str(node.get("kp_code")), {}))
            ok, out = await self._call("obsidian_create_note",
                                       {"vault": self._vault, "path": path,
                                        "content": content})
            # 注意：obsidian-mcp 把「笔记已存在」当作**成功**返回，正文里带
            # ALREADY_EXISTS 标记；因此必须按文本判定，不能只看 success。
            exists = "ALREADY_EXISTS" in out.upper()
            if ok and not exists:
                indexed += 1
                continue
            if overwrite:
                ok2, out2 = await self._call("obsidian_edit_note",
                                             {"vault": self._vault, "path": path,
                                              "mode": "replace", "content": content})
                if ok2 and "ALREADY_EXISTS" not in out2.upper():
                    indexed += 1
                    continue
                errors.append({"path": path, "error": (out2 or out)[:120]})
            else:
                skipped += 1

        return {"success": True, "indexed": indexed, "skipped": skipped,
                "total": len(nodes), "folder": self._kp_folder,
                "errors": errors[:10]}

    def _collect_nodes(self, subject: str, user_id: int, limit: int):
        """取知识点列表 + 用户掌握状态映射。返回 (nodes, states) 或错误 dict。"""
        store = self.graph_store
        try:
            if subject:
                nodes = store.get_nodes_by_subject(subject)
            else:
                # 未指定科目：汇总所有科目（subjects 表为空时退化为空列表）
                nodes = []
                subjects = []
                try:
                    conn = store._db._get_connection()
                    subjects = [r["code"] for r in conn.execute(
                        "SELECT code FROM subjects ORDER BY code").fetchall()]
                except Exception:
                    subjects = []
                for code in subjects:
                    try:
                        nodes.extend(store.get_nodes_by_subject(code))
                    except Exception:
                        continue
            nodes = list(nodes)[:max(1, int(limit or 50))]
        except Exception as e:
            return {"error": "读取知识点失败: %s" % e}, {}
        states = {}
        try:
            for st in store.get_user_states(int(user_id or 0), subject or None):
                states[str(st.get("kp_code"))] = st
        except Exception:
            states = {}
        return nodes, states

    def _render_kp_note(self, node: dict, state: dict) -> str:
        """渲染一篇知识点笔记（frontmatter + 正文）。"""
        kp_code = str(node.get("kp_code") or "")
        name = str(node.get("name") or kp_code)
        subject = str(node.get("subject") or "")
        desc = str(node.get("description") or "")
        mastery = (state or {}).get("confidence")
        next_review = (state or {}).get("next_review_at")

        fm = ["---",
              "kp_code: \"%s\"" % kp_code,
              "title: \"%s\"" % name.replace(chr(34), chr(39)),
              "subject: \"%s\"" % subject,
              "tags:",
              "  - 知识点"]
        if subject:
            fm.append("  - 学科/%s" % subject)
        if mastery is not None:
            fm.append("mastery: %s" % mastery)
        if next_review:
            fm.append("next_review: \"%s\"" % next_review)
        fm.append("source: dsn_study")
        fm.append("---")

        body = ["", "# %s" % name, ""]
        if desc:
            body += [desc, ""]
        body += ["## 复习记录", "",
                 "- 索引来源：dsn_study 知识图谱",
                 "- 知识点编码：%s" % kp_code]
        return "\n".join(fm + body) + "\n"

    # ── 笔记 ──

    async def write_study_note(self, title: str, content: str,
                               tags: str = "", subject: str = "",
                               filename: str = "") -> dict:
        """写一篇学习笔记到 Obsidian vault。"""
        if not title:
            return {"error": "缺少标题"}
        name = self._safe_name(filename or title)
        path = "%s/%s.md" % (self._note_folder, name)

        tag_list = ["学习笔记"]
        if subject:
            tag_list.append("学科/%s" % subject)
        if tags:
            tag_list.extend([t.strip() for t in tags.replace("，", ",").split(",")
                             if t.strip()])
        fm = ["---",
              "title: \"%s\"" % str(title).replace(chr(34), chr(39)),
              "tags:"]
        fm += ["  - %s" % t for t in tag_list]
        fm.append("source: dsn_study")
        fm.append("---")
        body = "\n".join(fm) + "\n\n# %s\n\n%s\n" % (title, content or "")

        ok, out = await self._call("obsidian_create_note",
                                   {"vault": self._vault, "path": path,
                                    "content": body})
        # obsidian-mcp 把「已存在」当成功返回，正文带 ALREADY_EXISTS 标记
        if ok and "ALREADY_EXISTS" not in out.upper():
            return {"success": True, "path": path, "tags": tag_list}
        if "ALREADY_EXISTS" in out.upper():
            ok2, out2 = await self._call("obsidian_append_to_note",
                                         {"vault": self._vault, "path": path,
                                          "content": "\n\n---\n\n" + (content or "")})
            if ok2:
                return {"success": True, "path": path, "appended": True,
                        "tags": tag_list}
            return {"error": out2[:200], "path": path}
        return {"error": out[:200], "path": path}

    async def search_notes(self, query: str, limit: int = 20) -> dict:
        """在 vault 中搜索笔记。"""
        if not query:
            return {"error": "缺少搜索词"}
        ok, out = await self._call("obsidian_search_vault",
                                   {"vault": self._vault, "query": query,
                                    "limit": limit})
        if not ok:
            return {"error": out[:200]}
        return {"success": True, "query": query, "result": out}

    async def list_notes(self, path: str = "", limit: int = 50) -> dict:
        """列出 vault 中的笔记（path 为空则列学习笔记目录）。"""
        ok, out = await self._call("obsidian_list_notes",
                                   {"vault": self._vault,
                                    "path": path or self._note_folder,
                                    "limit": limit})
        if not ok:
            return {"error": out[:200]}
        return {"success": True, "path": path or self._note_folder,
                "result": out}
