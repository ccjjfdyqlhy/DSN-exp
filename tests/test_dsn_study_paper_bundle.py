# -*- coding: utf-8 -*-
"""试卷合集准备流程的测试（**全程不联网**）。

覆盖三件关键事：
  1. **分界判定快且准**：二分 + 并行的探针数是 O(log n)，结果与逐页判定一致；
  2. **失败不静默**：判定失败必须抛错 —— 把它当成"这是试题"会悄悄把分界点
     推向后面，产出错的合卷；
  3. **顺序不能错**：送进二分的页面必须按**文档顺序**（试题在前、答案在后），
     字母序会把 answer_* 排到前面，分界点直接算错。
"""

from __future__ import annotations

import os

import pytest

from apps.dsn_study.skills.builtin.gaokzx.tools.page_classifier import (
    ClassificationError, PageClassifier,
)


# ── 假判定器：按"第 boundary 页起是答案"来回答 ──

class _FakeAsk:
    """返回固定答案的假判定器。记录调用次数与每次问的是哪张图。"""

    def __init__(self, boundary: int, total: int, fail_on: set = None,
                 ambiguous_on: set = None):
        self.boundary = boundary
        self.total = total
        self.fail_on = set(fail_on or ())
        self.ambiguous_on = set(ambiguous_on or ())
        self.calls = 0
        self.asked = []

    def __call__(self, data_url: str, prompt: str) -> str:
        # data_url 里带图片序号（测试构造时塞进去）
        idx = int(data_url.rsplit("#", 1)[-1])
        self.calls += 1
        self.asked.append(idx)
        if idx in self.fail_on:
            raise RuntimeError("厂商 500")
        if idx in self.ambiguous_on:
            return "……"
        return "是" if idx >= self.boundary else "否"


def _make_images(tmp_path, total: int):
    """造 N 个"假图片"（内容不同 → 缓存键不同）。"""
    paths = []
    for i in range(total):
        p = tmp_path / ("p%02d.jpg" % i)
        p.write_bytes(b"IMG" + bytes([i]) * 50)
        paths.append(str(p))
    return paths


def _ask_factory(fake: _FakeAsk):
    """把假判定器接到 PageClassifier 上（绕开真实图片缩放）。"""
    clf = PageClassifier(fake, cache_path=None, max_inflight=4, workers=4)

    def _scaled(path):
        # 用文件名序号当"图片标识"，让假判定器知道问的是哪一页
        return "data:image/jpeg;base64,#" + str(int(
            os.path.basename(path)[1:3]))
    clf._scaled_data_url = _scaled
    return clf


# ── 1. 分界判定 ──

@pytest.mark.parametrize("total,boundary", [
    (10, 4), (15, 10), (22, 12), (22, 0), (22, 22), (5, 2),
])
def test_find_boundary_matches_sequential_truth(tmp_path, total, boundary):
    paths = _make_images(tmp_path, total)
    fake = _FakeAsk(boundary, total)
    clf = _ask_factory(fake)
    res = clf.find_boundary(paths)
    assert res["boundary"] == boundary, res
    assert res["monotone"] is True


def test_probe_count_is_logarithmic(tmp_path):
    """探针数必须是 O(log n) —— 这是"快"的根本保证。"""
    paths = _make_images(tmp_path, 64)
    fake = _FakeAsk(30, 64)
    clf = _ask_factory(fake)
    res = clf.find_boundary(paths)
    assert res["boundary"] == 30
    # 顺序二分要 6 次；批量二分 + 校验应显著更少
    assert fake.calls <= 16, "探针太多: %d" % fake.calls


def test_non_monotone_falls_back_to_full_scan(tmp_path):
    """结构不单调（中间夹答案页）→ 自动退化为全量扫描，而不是给出错结果。"""
    paths = _make_images(tmp_path, 8)

    class _Weird:
        def __init__(self):
            self.calls = 0
        def __call__(self, d, p):
            idx = int(d.rsplit("#", 1)[-1])
            self.calls += 1
            return "是" if idx in (2, 6) else "否"

    clf = _ask_factory(_Weird())
    res = clf.find_boundary(paths)
    assert res["mode"] == "full", res
    assert res["monotone"] is False


# ── 2. 失败必须显式 ──

def test_failed_judgement_raises(tmp_path):
    """判定失败必须抛 ClassificationError，不能静默当成"试题"。"""
    paths = _make_images(tmp_path, 6)
    fake = _FakeAsk(3, 6, fail_on={0})
    clf = _ask_factory(fake)
    with pytest.raises(ClassificationError):
        clf.label(paths[0])
    # 全页都失败时，二分也必须把错误抛出去
    fake2 = _FakeAsk(3, 6, fail_on=set(range(6)))
    clf2 = _ask_factory(fake2)
    with pytest.raises(ClassificationError):
        clf2.find_boundary(paths)


def test_ambiguous_reply_raises(tmp_path):
    """回复不含是/否（空/跑题）也算失败。"""
    paths = _make_images(tmp_path, 4)
    fake = _FakeAsk(2, 4, ambiguous_on={1})
    clf = _ask_factory(fake)
    with pytest.raises(ClassificationError):
        clf.find_boundary(paths)


# ── 3. 缓存 ──

def test_cache_avoids_second_call(tmp_path):
    """第二次处理同一批图 → 0 次模型调用。"""
    paths = _make_images(tmp_path, 10)
    cache = str(tmp_path / "cache.json")
    fake = _FakeAsk(4, 10)
    clf = _ask_factory(fake)
    clf._cache_path = cache
    clf.find_boundary(paths)
    first = fake.calls
    assert first > 0
    clf2 = _ask_factory(fake)
    clf2._cache_path = cache
    clf2._load_cache()
    clf2.find_boundary(paths)
    assert fake.calls == first, "缓存没命中：又调了 %d 次" % (fake.calls - first)
    assert clf2.cache_hits > 0


# ── 4. 文档顺序（回归护栏） ──

def test_classify_papers_uses_document_order(tmp_path, monkeypatch):
    """送进判定的页面必须按文档顺序：question_* 在前、answer_* 在后。

    ⚠️ 这是一个真实踩过的坑：直接 sorted(glob) 会把 answer_* 排到前面
    （字母序），二分拿到乱序页面 → 分界点算错（数学曾算出 0）。
    """
    from apps.dsn_study.skills.builtin.gaokzx.tools.gaokzx_tools import GaokzxTool

    d = tmp_path / "gaokzx" / "1"
    d.mkdir(parents=True)
    for name in ("question_01.jpg", "question_02.jpg",
                 "answer_01.jpg", "answer_02.jpg"):
        (d / name).write_bytes(b"x" + name.encode())

    class _FakeWorkspace:
        def user_subdir(self, uid, name, display_name=""):
            # 工具会再拼 / <paper_id>，所以这里只给到 uid 层
            return tmp_path / "gaokzx"

    tool = GaokzxTool()
    tool._workspace = _FakeWorkspace()
    order = {}

    def _fake_classify(paths):
        order["paths"] = list(paths)
        return {"boundary": 1, "labels": [], "mode": "stub", "monotone": True}

    monkeypatch.setattr(tool, "_vision_ask", lambda: (lambda d, p: "否"))
    monkeypatch.setattr(PageClassifier, "classify_bundle",
                        lambda self, papers: order.update(paths=papers) or {})
    res = tool.classify_papers([{"subject": "数学", "paper_id": 1}],
                                user_id=1, use_vision=True)
    names = [os.path.basename(p) for p in order.get("paths", {}).get("数学|1", [])]
    assert names == ["question_01.jpg", "question_02.jpg",
                     "answer_01.jpg", "answer_02.jpg"], names


# ── 5. PDF 合成（A4 页面） ──

def test_build_pdf_uses_a4_page_size(tmp_path):
    """合卷 PDF 必须是 A4 页面（双面长边翻转要求所有页尺寸一致）。"""
    from apps.dsn_study.question_bank.paper_import import PaperImporter

    jpg = tmp_path / "p.jpg"
    from PIL import Image
    Image.new("RGB", (600, 800), "white").save(jpg, "JPEG")
    out = str(tmp_path / "out.pdf")
    res = PaperImporter.build_pdf([str(jpg)], out, page_size="A4")
    assert res["success"], res
    import subprocess
    info = subprocess.run(["pdfinfo", out], capture_output=True).stdout.decode()
    assert "595.28 x 841.89 pts (A4)" in info, info
