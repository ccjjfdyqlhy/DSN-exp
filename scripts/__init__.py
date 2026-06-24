# scripts/__init__.py
# 剧本系统 — ScriptEngine + OOCDetector + Recorder + Player + ScriptPlugin

from scripts.engine import ScriptEngine
from scripts.ooc import OOCDetector
from scripts.recorder import ScriptRecorder
from scripts.player import ScriptPlayer
from scripts.plugin import ScriptPlugin
from scripts.state import ScriptState

__all__ = [
    "ScriptEngine",
    "OOCDetector",
    "ScriptRecorder",
    "ScriptPlayer",
    "ScriptPlugin",
    "ScriptState",
]