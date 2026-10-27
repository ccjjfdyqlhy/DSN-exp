# tests/test_dsn_study_vision.py
# dsn_study 视觉 OCR 通道（阶段 5，FEATURE_GAP.md）验收。
# VisionModel 经 monkeypatch 打桩，不联网、不需要真实视觉后端。

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.dsn_study.engine_support import LLMService
from apps.dsn_study.document.hmd import HmdClient


# ── LLMService.describe_image ──

class _StubChat:
    def invoke(self, messages, tools=None):
        raise AssertionError("describe_image 不应走主模型")


def test_describe_image_uses_vision_model(monkeypatch, tmp_path):
    from apps.dsn_study.config import Config
    monkeypatch.setattr(Config, "VISION_API_KEY", "sk-test", raising=False)

    captured = {}

    def fake_ask(self, data_url, prompt, **kw):
        captured["data_url"] = data_url
        captured["prompt"] = prompt
        return "视觉识别结果"

    import infra.orchestrator.vision as vision_mod
    monkeypatch.setattr(vision_mod.VisionModel, "ask", fake_ask)

    # 用 data URL 直传，避免真实读图
    out = LLMService(_StubChat()).describe_image(
        "data:image/png;base64,AAAA", "识别题目")
    assert out == "视觉识别结果"
    assert captured["data_url"].startswith("data:image/png")
    assert captured["prompt"] == "识别题目"


def test_describe_image_falls_back_to_lmstudio(monkeypatch):
    from apps.dsn_study.config import Config
    monkeypatch.setattr(Config, "VISION_API_KEY", "", raising=False)

    called = {}

    def fake_fallback(self, data_url, prompt):
        called["ok"] = True
        return "LMStudio 描述"

    import apps.dsn_study.models.clients as clients_mod
    monkeypatch.setattr(clients_mod.LMStudioVisionFallback,
                        "describe_image", fake_fallback)
    out = LLMService(_StubChat()).describe_image("data:image/png;base64,AAAA")
    assert out == "LMStudio 描述" and called.get("ok")


def test_describe_image_accepts_file_path(monkeypatch, tmp_path):
    """文件路径入参 → encode_image 转为 data URL（打桩避免真实编码）。"""
    from apps.dsn_study.config import Config
    monkeypatch.setattr(Config, "VISION_API_KEY", "sk-test", raising=False)
    img = tmp_path / "page.png"
    img.write_bytes(b"\x89PNG fake")

    import infra.orchestrator.vision as vision_mod
    monkeypatch.setattr(vision_mod.VisionModel, "encode_image",
                        staticmethod(lambda p: "data:image/png;base64,STUB"))
    monkeypatch.setattr(vision_mod.VisionModel, "ask",
                        lambda self, du, prompt, **kw: "ok")
    out = LLMService(_StubChat()).describe_image(str(img))
    assert out == "ok"


# ── HmdClient.convert_via_vision（VISION_OVERRIDE 等价物） ──

@pytest.fixture()
def fake_images(tmp_path):
    """两张假图片（内容不重要，ocr_md 已打桩）。"""
    imgs = []
    for i in range(2):
        p = tmp_path / f"page{i + 1}.png"
        p.write_bytes(b"\x89PNG fake")
        imgs.append(str(p))
    return imgs


def test_convert_via_vision_builds_hmd(monkeypatch, fake_images, tmp_path):
    pages = ["# 第 1 页\n1+1=?", "# 第 2 页\n解方程 x^2=4"]

    import apps.dsn_study.models.clients as clients_mod
    monkeypatch.setattr(clients_mod.VisionModel, "ocr_md",
                        lambda self, du, max_tokens=4096: pages[len(pages) - 1] if False else pages[0])
    # 逐页返回：用迭代器包装
    it = iter(pages)
    monkeypatch.setattr(clients_mod.VisionModel, "ocr_md",
                        lambda self, du, max_tokens=4096: next(it))

    out_dir = tmp_path / "hmd_out"
    result = HmdClient.convert_via_vision(fake_images, output_dir=str(out_dir))
    assert result["pages"] == 2
    assert Path(result["hmd_path"]).exists()

    # read_hmd 往返：mdA 含两页文本
    data = HmdClient.read_hmd(result["hmd_path"])
    assert "1+1=?" in data["mda"] and "x^2=4" in data["mda"]
    assert "第 1 页" in data["mdb"] and "第 2 页" in data["mdb"]


def test_convert_via_vision_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        HmdClient.convert_via_vision([], output_dir=str(tmp_path))


# ── doc_to_questions.process_images 全链路（桩管线） ──

def test_doc_to_questions_process_images(monkeypatch, fake_images, tmp_path):
    import importlib.util
    skill_file = (Path(__file__).resolve().parents[1]
                  / "apps/dsn_study/skills/builtin/doc_to_questions/tools/doc_to_questions.py")
    spec = importlib.util.spec_from_file_location("dtq_test", str(skill_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tool = mod.DocToQuestionsTool()

    captured = {}

    class StubPipeline:
        def process_text(self, text, user_id, subject_code="math"):
            captured["text"] = text
            captured["uid"] = user_id
            return {"success": True, "questions_found": 2, "questions_added": 2}

    tool._pipeline = StubPipeline()

    import apps.dsn_study.models.clients as clients_mod
    it = iter(["# 第 1 页\n1+1=?"])
    monkeypatch.setattr(clients_mod.VisionModel, "ocr_md",
                        lambda self, du, max_tokens=4096: next(it))

    out = tool.process_images(fake_images[:1], subject_code="math", user_id=3)
    assert out["success"] is True
    assert "1+1=?" in captured["text"]
    assert captured["uid"] == 3
    assert Path(out["hmd_path"]).exists()
