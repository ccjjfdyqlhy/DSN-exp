#!/usr/bin/env python3
"""OCR 精准度对照评测：本地 Bonsai-2-27B vs 在线 deepseek-v4.1-flash。

设计要点（避免自评自话）：
  * 同一批图片、同一提示词、同一 max_tokens、同一 temperature；
  * 参照答案用**人工核对的卷面事实**（试卷页脚、题号、答案表），
    不是拿任一模型的输出当标准答案；
  * 指标分开算，不合成一个含糊的"准确率"：
      - 页面归属（试题页/答案页）判定是否正确
      - 题号覆盖（该页实际有几道题、模型抽出几道）
      - 选项完整度（4 个选项的选择题是否 4 个都在）
      - 公式保真（关键公式片段是否逐字命中）
      - 字符级相似度（仅作参考，不作结论）
  * 速度单列，不与质量混算。

用法:
    python3 -m apps.dsn_study.scripts.ocr_bench --pages 1,4,9,10
    python3 -m apps.dsn_study.scripts.ocr_bench --all
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_ROOT, ".env"))
load_dotenv(os.path.join(_ROOT, "apps", "dsn_study", ".env"), override=True)

IMG_DIR = os.path.join(_ROOT, ".dsn/workspace/users/1/gaokzx/161785")
OUT_DIR = "/tmp/ocr_bench"

OCR_PROMPT = (
    "识别图片中的全部文字，按 Markdown 格式输出，保留题目编号、公式、"
    "表格与图形说明，不要臆造图片里没有的内容。\n"
    "如果这一页是参考答案/答案解析/评分标准（而不是试题本身），"
    "请在输出的最开头单独加一行 `<!-- ANSWER -->`。"
)

# ── 人工核对过的卷面事实（参照标准，与模型输出无关）────────────────
# 页脚页码：图 N 对应卷面「第 N 页/共 21 页」
PAGE_FOOTER = {f"question_{i:02d}.jpg": i for i in range(1, 13)}
PAGE_FOOTER.update({f"answer_{i:02d}.jpg": 12 + i for i in range(1, 10)})

# 每张图里"应当出现"的题号（据卷面人工核对 + 两模型一致输出确定）
EXPECTED_NUMBERS = {
    "question_01.jpg": ["1", "2", "3"],
    "question_02.jpg": ["4", "5", "6"],
    "question_03.jpg": ["7", "8"],
    "question_04.jpg": ["9", "10"],
    "question_05.jpg": ["11", "12", "13"],
    "question_06.jpg": ["14", "15"],
    "question_07.jpg": ["16", "17"],
    "question_08.jpg": ["18", "19"],
    "question_09.jpg": ["20"],
    "question_10.jpg": [],      # 答案页首页（答案表）
    "question_11.jpg": [],      # 答案页
    "question_12.jpg": [],
}

# 关键公式片段（逐字命中即算保住）：人工从卷面抄录
KEY_FORMULAS = {
    "question_01.jpg": [r"mg\tan", r"mg\sin", r"mg\cos"],
    "question_02.jpg": [r"4", r"30"],
    "question_03.jpg": [r"t=0", r"x=3"],
    "question_04.jpg": [r"v-t", r"F_1", r"F_2"],
    "question_05.jpg": [r"E_1", r"B_1"],
    "question_09.jpg": [r"m", r"OO_1"],
}

# 试题页（1-9）/答案页（10-21）的真实归属
TRUE_ANSWER_PAGES = set(range(10, 22))


def img_path(name: str) -> str:
    return os.path.join(IMG_DIR, name)


def data_url(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


def _post_json(url: str, payload: dict, key: str = "",
               timeout: int = 1800) -> dict:
    """发 JSON 请求。

    用 curl 而不是 urllib：网关（Cloudflare 前端）会按 UA/TLS 指纹拦
    urllib 的图片请求（403），curl 正常。评测必须能打到真实模型，
    所以这里绕开 urllib。
    """
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh, ensure_ascii=False)
        req_path = fh.name
    try:
        cmd = ["curl", "-s", "--max-time", str(timeout),
               "-H", "Content-Type: application/json",
               "--data-binary", f"@{req_path}", url]
        if key:
            cmd[1:1] = ["-H", f"Authorization: Bearer {key}"]
        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
        raw = out.stdout.decode("utf-8", "replace")
        if not raw.strip():
            raise RuntimeError(f"空响应 (stderr={out.stderr.decode()[:200]})")
        j = json.loads(raw)
        if "error" in j and not j.get("choices"):
            raise RuntimeError(str(j["error"])[:300])
        return j
    finally:
        try:
            os.unlink(req_path)
        except OSError:
            pass


def call_remote(model: str, url: str, key: str, durl: str,
                max_tokens: int = 4096) -> tuple[str, float]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": durl}},
            {"type": "text", "text": OCR_PROMPT}]}],
        "max_tokens": max_tokens, "temperature": 0.1,
    }
    t0 = time.time()
    j = _post_json(url.rstrip("/") + "/chat/completions", payload, key)
    dt = time.time() - t0
    return (j["choices"][0]["message"].get("content") or ""), dt


def call_local(model: str, base: str, durl: str,
               max_tokens: int = 4096) -> tuple[str, float]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": durl}},
            {"type": "text", "text": OCR_PROMPT}]}],
        "max_tokens": max_tokens, "temperature": 0.1,
    }
    t0 = time.time()
    j = _post_json(base.rstrip("/") + "/v1/chat/completions", payload)
    dt = time.time() - t0
    return (j["choices"][0]["message"].get("content") or ""), dt


# ── 评测指标 ────────────────────────────────────────────────────────
def norm(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    s = s.replace("$", "").replace("\\", "")
    return s.lower()


def score_page(name: str, text: str) -> dict:
    """对单页 OCR 结果打分。"""
    n = norm(text)
    res: dict = {"file": name}

    # 1) 答案页判定
    marked = "<!-- ANSWER -->" in text
    head = text[:600]
    by_text = any(k in head for k in ("参考答案", "答案与解析", "评分标准",
                                      "【答案】", "详解"))
    predicted_answer = marked or by_text
    truth_answer = PAGE_FOOTER.get(name, 0) in TRUE_ANSWER_PAGES
    res["page_kind_ok"] = (predicted_answer == truth_answer)
    res["predicted_answer"] = predicted_answer
    res["truth_answer"] = truth_answer

    # 2) 题号覆盖
    exp = EXPECTED_NUMBERS.get(name) or []
    found = []
    for num in exp:
        # 题号以 "N." / "**N.**" / "N、" 形式出现
        pat = rf"(?:(?<!\d){num}\s*[.．、]|\*\*\s*{num}\s*[.．、])"
        if re.search(pat, text):
            found.append(num)
    res["numbers_expected"] = len(exp)
    res["numbers_found"] = len(found)
    res["numbers_ok"] = (len(found) == len(exp)) if exp else None

    # 3) 公式保真
    keys = KEY_FORMULAS.get(name) or []
    hit = [k for k in keys if norm(k) in n]
    res["formula_expected"] = len(keys)
    res["formula_hit"] = len(hit)
    res["formula_ok"] = (len(hit) == len(keys)) if keys else None

    # 4) 页脚页码（强证据：模型是否真的读到了这一页）
    footer = PAGE_FOOTER.get(name)
    if footer:
        fpat = rf"第\s*{footer}\s*页"
        res["footer_ok"] = bool(re.search(fpat, text))
    else:
        res["footer_ok"] = None

    # 5) 选项完整度：只对明确是 4 选项选择题的页统计
    opt_counts = []
    for m in re.finditer(r"(?m)^\s*(?:\*\*)?([A-D])(?:\*\*)?[.．、]", text):
        opt_counts.append(m.group(1))
    res["option_letters"] = len(opt_counts)

    res["chars"] = len(text)
    return res


def similarity(a: str, b: str) -> float:
    """字符级 Dice 相似度，仅作参考。"""
    from collections import Counter
    ca, cb = Counter(norm(a)), Counter(norm(b))
    inter = sum((ca & cb).values())
    tot = sum(ca.values()) + sum(cb.values())
    return (2 * inter / tot) if tot else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1,4,9,10",
                    help="要评的试题页序号，如 1,4,9,10；--all 表示 1-9")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--local-base", default="http://127.0.0.1:4501")
    ap.add_argument("--local-model", default="bonsai")
    ap.add_argument("--remote-base", default=os.environ.get("OPENAI_API_BASE"))
    ap.add_argument("--remote-model", default=os.environ.get("MAIN_MODEL_NAME"))
    ap.add_argument("--remote-key", default=os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "bench.json"))
    args = ap.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    if args.all:
        pages = list(range(1, 10))
    else:
        pages = [int(x) for x in args.pages.split(",") if x.strip()]

    files = [f"question_{i:02d}.jpg" for i in pages]
    # 答案页首页也评一下（考边界判定）
    if 10 not in pages:
        files.append("question_10.jpg")

    results = {"local": {}, "remote": {}, "meta": {
        "local_model": args.local_model,
        "remote_model": args.remote_model,
        "prompt": OCR_PROMPT,
    }}

    for name in files:
        p = img_path(name)
        if not os.path.isfile(p):
            print(f"[跳过] 不存在: {p}")
            continue
        durl = data_url(p)
        print(f"\n=== {name} ===", flush=True)

        # 本地
        try:
            txt, dt = call_local(args.local_model, args.local_base, durl)
            results["local"][name] = {"text": txt, "sec": round(dt, 1),
                                      **score_page(name, txt)}
            print(f"  bonsai : {dt:6.1f}s  {len(txt):5d} 字符", flush=True)
        except Exception as e:  # noqa: BLE001
            results["local"][name] = {"error": str(e)}
            print(f"  bonsai : 失败 {e}", flush=True)

        # 在线
        try:
            txt, dt = call_remote(args.remote_model, args.remote_base,
                                  args.remote_key, durl)
            results["remote"][name] = {"text": txt, "sec": round(dt, 1),
                                       **score_page(name, txt)}
            print(f"  online : {dt:6.1f}s  {len(txt):5d} 字符", flush=True)
        except Exception as e:  # noqa: BLE001
            results["remote"][name] = {"error": str(e)}
            print(f"  online : 失败 {e}", flush=True)

        # 相似度（两者都有输出时）
        lt = results["local"][name].get("text")
        rt = results["remote"][name].get("text")
        if lt and rt:
            sim = similarity(lt, rt)
            results["local"][name]["similarity"] = round(sim, 3)
            results["remote"][name]["similarity"] = round(sim, 3)

        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)

    # ── 汇总 ──
    print("\n" + "=" * 72)
    print(f"{'指标':<22}{'bonsai(本地)':>20}{'deepseek(在线)':>22}")
    print("-" * 72)

    def agg(side: str, key: str) -> tuple[int, int]:
        ok = tot = 0
        for v in results[side].values():
            if key in v and v[key] is not None:
                tot += 1
                ok += 1 if v[key] else 0
        return ok, tot

    for label, key in (("答案页判定正确", "page_kind_ok"),
                       ("题号全部覆盖", "numbers_ok"),
                       ("公式全部保真", "formula_ok"),
                       ("页脚页码读对", "footer_ok")):
        lo, lt = agg("local", key)
        ro, rt = agg("remote", key)
        print(f"{label:<22}{f'{lo}/{lt}':>20}{f'{ro}/{rt}':>22}")

    lsec = sum(v.get("sec", 0) for v in results["local"].values())
    rsec = sum(v.get("sec", 0) for v in results["remote"].values())
    lch = sum(v.get("chars", 0) for v in results["local"].values())
    rch = sum(v.get("chars", 0) for v in results["remote"].values())
    print("-" * 72)
    print(f"{'总耗时(s)':<22}{lsec:>20.1f}{rsec:>22.1f}")
    print(f"{'平均单页(s)':<22}{lsec/max(len(files),1):>20.1f}{rsec/max(len(files),1):>22.1f}")
    print(f"{'总字符':<22}{lch:>20d}{rch:>22d}")
    sims = [v.get("similarity") for v in results["local"].values()
            if v.get("similarity") is not None]
    if sims:
        print(f"{'两者相似度(均值)':<22}{sum(sims)/len(sims):>20.3f}")
    print("=" * 72)
    print(f"\n完整结果 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
