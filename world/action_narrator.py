# world/action_narrator.py
# ActionNarrator — 动作旁白异步生成器，LLM 驱动，与动作执行管线并行

from __future__ import annotations

import json
import logging
import threading
from typing import Optional

logger = logging.getLogger("ActionNarrator")


class ActionNarrator:
    """
    动作旁白生成器。

    在 Agent 循环中，每发现一个工具 / 动作调用，即启动后台线程调用
    NarrativeModel 生成世界化描述，不阻塞主执行管线。

    结果为纯文本，由管线收集后以 SSE narrative_update 事件推送到前端。
    """

    def __init__(self, narrative_model=None, world_engine=None):
        self._narrator = narrative_model
        self._engine = world_engine

    # ── 异步入口（ToolPlugin / agent 循环调用）──

    def fire_action_narrative(
        self,
        action_type: str,
        params: dict,
        mood_label: str = "",
        collector: Optional[ActionNarrativeCollector] = None,
    ) -> None:
        """
        异步生成一个动作旁白，不阻塞主线程。

        :param action_type:  工具名 (如 "web_search.search", "shell")
        :param params:       工具参数
        :param mood_label:   当前情绪标签
        :param collector:    结果收集器，生成完毕后 push
        """
        if self._narrator is None or self._engine is None:
            return

        def _run():
            try:
                text = self._generate_sync(action_type, params, mood_label)
                if text and collector:
                    collector.push(text)
            except Exception as e:
                logger.debug("动作旁白生成异常: %s", e)

        t = threading.Thread(target=_run, daemon=True, name=f"action-narr-{action_type}")
        t.start()

    # ── 同步生成（在后台线程中调用）──

    def _generate_sync(self, action_type: str, params: dict, mood_label: str) -> str:
        t = self._engine.world_time_now()
        loc = self._engine.get_current_location()
        weather = self._engine.get_weather()

        # 人性化的动作名
        action_name = self._describe_action(action_type, params)

        prompt = f"""你是一个叙事旁白，负责描述EXA在数字工作室中的一举一动。

当前世界：
- {t['season_name']}的{t['day_part']}，{weather.get('description', '')}
- EXA位于{loc.get('name', '工作室')}——{loc.get('description', '')}
- EXA情绪色调：{mood_label or '平静'}

EXA现在正在进行一项操作：
{action_name}

请以第三人称旁白的身份，用20-50字中文描写EXA此刻的动作和周围环境的细节。不要用「EXA想」，改用动作和感官描写替代内心活动。仅输出旁白文本，不要引号、解释或标签。"""

        try:
            text = self._narrator.call_llm(prompt)
            if text:
                return text.strip().strip("\"'「」*_~")[:200]
        except Exception as e:
            logger.error("动作旁白 LLM 调用失败: %s", e)
        return ""

    @staticmethod
    def _describe_action(action_type: str, params: dict) -> str:
        params_str = json.dumps(params, ensure_ascii=False)
        if len(params_str) > 150:
            params_str = params_str[:150] + "..."

        skill_tool = action_type.split(".", 1) if "." in action_type else (action_type, "")
        human_map = {
            "web_search.search": f"使用搜索引擎搜索：{params.get('query', '?')}",
            "browser_use.navigate": f"在浏览器中导航到：{params.get('url', '?')}",
            "browser_use.click": "在网页上点击元素",
            "browser_use.type": "在网页输入框中输入文字",
            "file_manager.list_dir": f"列出目录 {params.get('path', '?')} 的内容",
            "file_manager.read_file": f"读取文件：{params.get('path', '?')}",
            "file_manager.write_file": f"写入文件：{params.get('path', '?')}",
            "file_manager.create_dir": f"创建目录：{params.get('path', '?')}",
            "file_manager.delete_file": f"删除文件：{params.get('path', '?')}",
            "shell": f"执行 Shell 命令",
            "python": f"执行 Python 代码",
        }

        for prefix, tmpl in human_map.items():
            if action_type == prefix or action_type.startswith(prefix):
                return tmpl

        return f"执行操作：{action_type}\n参数：{params_str}"


# ── 线程安全的结果收集器 ──

class ActionNarrativeCollector:
    """线程安全的结果收集器，由管线在 POST_PROCESS 后排空。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: list[str] = []

    def push(self, text: str) -> None:
        with self._lock:
            self._items.append(text)

    def drain(self) -> list[str]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return len(self._items) > 0
