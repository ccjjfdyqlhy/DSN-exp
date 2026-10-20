# apps/dsn_ui/system1_api.py
"""System-1 决策接口 —— JEV 风格「单次前向输出校准概率」。

## 背景：为什么需要两套对话接口

DSN 现在挂载的 JEV-27B-VL 是一个**双系统混合模型**：

  * **System 2**（常规对话）—— 就是普通的 autoregressive 生成：
    逐 token 说出答案。走 `/v1/chat/completions`，dsn_ui 早已支持。

  * **System 1**（决策）—— 训练时融合进权重的 typed-decision 头。
    给它一个封闭选项集，它在**一次前向传播**里把答案分布直接写在
    下一个 token 的概率上，不生成推理文本。

System 1 在 llama.cpp 上的正确用法是读 **logprobs**，而不是读 content：

    请求里 max_tokens=1, logprobs=true, top_logprobs=N
    → choices[0].logprobs.content[0] 里就是该位置的词表分布
    → 把 "Y"/"N"、"A"/"B"、数字等选项 token 的概率取出并归一化

（README 里写的 `POST /v1/decide` 是配套 vLLM 服务 serve_decide.py 的接口，
 llama.cpp 没有这个端点，但用 logprobs 拿到的是同一个分布。）

## 本模块提供的接口

    POST /v1/decide              统一决策入口（type: yes_no | choice | score）
    GET  /v1/decide/capabilities 探测当前模型是否支持决策模式

请求体（type=yes_no）：
    {
      "model": "jev-27b-vl",          # 可选，缺省用默认模型
      "type": "yes_no",
      "state": "邮件正文……",           # 或者 "messages": [...]
      "question": "该邮件是否威胁取消订阅？",
      "image_url": "data:image/png;base64,..."   # 可选，图文决策
    }

响应：
    {
      "type": "yes_no",
      "answer": true,
      "probability": 0.9170,
      "distribution": {"Y": 0.9170, "N": 0.0830},
      "raw_candidates": {"Y": 0.9170, "N": 0.0829, "Yes": 0.0003},
      "model": "jev-27b-vl",
      "latency_ms": 412
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import urllib.request
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("DSNUISystem1")

#: 决策请求的默认超时（秒）。System 1 只有一次前向，通常几十毫秒到几秒。
_DECIDE_TIMEOUT = 120.0
#: 需要从词表里取出的候选 token 数。多选最多支持 256 项（双字母标签），
#: 这里给足余量，让服务端一次返回足够多的备选。
_TOP_LOGPROBS = 32


# ────────────────────────── 工具函数 ──────────────────────────

def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _token_probability(candidates: dict[str, float], variants: list[str]) -> float:
    """把同一个选项的多种写法（含前导空格 / 大小写 / 完整词）概率加总。

    为什么必须做：llama.cpp 的 tokenizer 里 `Y`、` Y`、`Yes`、`yes` 是不同
    token。只取完全相等的那个会漏掉一部分概率质量，导致归一化后的分布失真。
    """
    total = 0.0
    wanted = {v.strip().lower() for v in variants}
    for token, logprob in candidates.items():
        if token.strip().lower() in wanted:
            total += math.exp(logprob)
    return total


def _normalize(raw: dict[str, float]) -> dict[str, float]:
    """把各选项概率归一化到和为 1。"""
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in raw.items()}


def _label_variants(label: str) -> list[str]:
    """选项标签的常见 token 写法。"""
    base = [label, label.lower(), label.upper(), " " + label, " " + label.lower()]
    return list(dict.fromkeys(base))


# ────────────────────────── 提示词构造 ──────────────────────────

def _build_prompt(question: str, state: str, options_block: str, instruction: str) -> str:
    parts = []
    if question:
        parts.append(question.strip())
    if state:
        parts.append("State:\n" + state.strip())
    if options_block:
        parts.append(options_block)
    parts.append(instruction)
    return "\n\n".join(p for p in parts if p)


# ────────────────────────── 主注册函数 ──────────────────────────

def register_system1_routes(app, engine) -> None:
    """把 System-1 决策路由挂载到 FastAPI app。"""

    def _resolve_endpoint(model_name: Optional[str]) -> tuple[str, str]:
        """解析出 (model_name, llama-server base_url)。"""
        orch = engine.orchestrator
        name = model_name or orch.get_default_model()
        if not name:
            raise HTTPException(status_code=400, detail="未指定模型且无默认模型")

        spec = orch._specs.get(name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"模型不存在: {name}")

        # 本地 llama.cpp 模型：优先用 launcher 的真实端点（端口可能被动态调整）
        launcher = getattr(spec, "launcher", None)
        base_url = getattr(launcher, "base_url", None) or getattr(spec, "base_url", None)
        if not base_url:
            raise HTTPException(
                status_code=400,
                detail=f"模型 {name} 没有可直连的 HTTP 端点，无法做 System-1 决策",
            )
        return name, str(base_url).rstrip("/")

    def _post_chat(base_url: str, payload: dict) -> dict:
        """向 llama-server 发一次阻塞请求（在线程池里执行）。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_DECIDE_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _build_messages(body: dict, prompt: str) -> list[dict]:
        """构造发给模型的消息。支持 state/question，也支持直接透传 messages。"""
        # 调用方直接给了 OpenAI messages 就用它（便于前端拼接多轮上下文）
        raw_messages = body.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            messages = [m for m in raw_messages if isinstance(m, dict)]
            # 追加一条强约束：只回答选项标签
            instruction = body.get("instruction")
            if instruction:
                messages = list(messages) + [{"role": "user", "content": instruction}]
            return messages

        # 图文决策：state 里带图
        image_url = body.get("image_url")
        if image_url:
            content: list[dict] = [{"type": "text", "text": prompt}]
            content.append({"type": "image_url", "image_url": {"url": image_url}})
            return [{"role": "user", "content": content}]

        return [{"role": "user", "content": prompt}]

    @app.get("/v1/decide/capabilities")
    async def decide_capabilities(model: Optional[str] = None):
        """探测当前模型是否支持 System-1 决策（即能否拿到 logprobs）。"""
        try:
            name, base_url = _resolve_endpoint(model)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"error": e.detail})

        spec = engine.orchestrator._specs.get(name)
        cfg = getattr(spec, "llama_config", None)
        vision = bool(getattr(cfg, "mmproj_path", None)) if cfg is not None else False

        # 真正探测 System-1 能力，而不是无条件返回 True。
        #
        # 修复说明：原实现硬编码 "system1": True —— 只要模型有 HTTP 端点就报告
        # 支持决策，连没加载的 gemma-3-4b-it-gguf 也返回 True。结果是前端在
        # 任何模型下都点亮"决策模式"入口，点进去才发现不支持。
        #
        # 正确的判据是：这个模型能否在「只答一个 token」的位置给出稳定的
        # logprobs 分布。做法：发一次极小的 yes/no 决策请求，看是否真的拿到
        # logprobs。模型未加载 / 端点不可达 / 返回空分布，都判为不支持。
        loader = getattr(spec, "launcher", None) if spec is not None else None
        if loader is None and spec is not None:
            loader = None  # 远程 API 模型没有本地 launcher

        probe_payload = {
            "messages": [{"role": "user", "content": "Answer Y or N only. Is 1+1=2?"}],
            "max_tokens": 1,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": 3,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        def _probe() -> tuple[bool, str]:
            """返回 (是否支持决策, 失败原因)。"""
            # 第一步：确认该端点上的**确实是这个模型**。
            #
            # 这一步不可省。DSN 里所有本地 llama.cpp 模型默认都用 8080 端口，
            # 而同一时刻只有一个真正在跑。若直接探测，未加载的模型会打到
            # 别的模型上（实测 gemma 与 JEV 返回的概率完全一致，说明都命中了
            # JEV），于是"能拿到 logprobs"这个判据误判为支持。
            # 用 /props 的 model_path 做身份校验，不匹配就判为不可用。
            try:
                with urllib.request.urlopen(
                    base_url + "/props", timeout=10
                ) as pr:
                    props = json.loads(pr.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                return False, f"端点不可达: {e}"[:160]

            served = str(props.get("model_path") or "")
            want = ""
            cfg_path = getattr(cfg, "model_path", None) if cfg is not None else None
            if cfg_path:
                want = str(cfg_path)
            # 用文件名比对，避免路径前缀差异（~/ 展开等）
            if want and served:
                if want.rsplit("/", 1)[-1] != served.rsplit("/", 1)[-1]:
                    return False, (
                        "该模型当前未加载：端口 %s 上运行的是 %s"
                        % (base_url, served.rsplit("/", 1)[-1])
                    )[:200]
            elif not served:
                return False, "端点未报告模型信息，无法确认身份"

            # 第二步：真正试一次决策请求，确认能拿到 logprobs。
            try:
                resp = _post_chat(base_url, probe_payload)
            except Exception as e:  # noqa: BLE001 - 探测失败一律视为不支持
                return False, f"端点不可达: {e}"[:200]
            try:
                choice = (resp.get("choices") or [])[0]
                content_lp = ((choice.get("logprobs") or {}).get("content") or [])
                if not content_lp:
                    return False, "上游未返回 logprobs"
                return True, ""
            except Exception as e:  # noqa: BLE001
                return False, f"响应解析失败: {e}"[:200]

        ok, reason = await asyncio.to_thread(_probe)

        return {
            "model": name,
            "endpoint": base_url,
            "system1": ok,
            "system1_reason": reason or None,
            "system2": True,
            # 视觉能力决定能否做图文决策
            "vision": vision,
            "supported_types": ["yes_no", "choice", "score"] if ok else [],
            "max_choice_options": 256 if ok else 0,
            "note": "System-1 通过 logprobs 读取单次前向的概率分布，不生成推理文本"
            if ok else "该模型未能提供决策所需的 logprobs（可能未加载或不是决策模型）",
        }

    @app.post("/v1/decide")
    async def decide(req: Request):
        """System-1 决策端点。

        一次前向传播直接给出带校准概率的决策，不产生思维链文本。
        """
        started = time.perf_counter()
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

        dtype = str(body.get("type") or "yes_no").strip().lower()
        if dtype not in ("yes_no", "choice", "score"):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的决策类型: {dtype}（可选 yes_no / choice / score）",
            )

        model_name, base_url = _resolve_endpoint(body.get("model"))
        state = body.get("state") or body.get("text") or ""
        question = body.get("question") or ""

        # ── 按类型构造选项与提示词 ──
        if dtype == "yes_no":
            prompt = _build_prompt(
                question, state, "",
                "Answer with a single letter: Y for yes, N for no.",
            )
            # 注：yes_no 分支的 Y/N 概率在下面按 logprobs 单独计算，此处不设 labels。
        elif dtype == "choice":
            options = body.get("options")
            if isinstance(options, list):
                # ["billing", "technical"] → {"A": "billing", "B": "technical"}
                options = {
                    chr(ord("A") + i): str(o) for i, o in enumerate(options)
                }
            if not isinstance(options, dict) or not options:
                raise HTTPException(
                    status_code=400,
                    detail='choice 类型必须提供 options（对象 {"A": "说明"} 或数组）',
                )
            lines = "\n".join(f"  {k}: {v}" for k, v in options.items())
            prompt = _build_prompt(
                question, state,
                "Options (pick exactly one; the one-line description disambiguates):\n" + lines,
                "Answer with the option label only.",
            )
        else:  # score
            max_score = int(_coerce_float(body.get("max_score"), 5))
            max_score = max(1, min(max_score, 10))
            prompt = _build_prompt(
                question, state, "",
                f"Rate from 0 to {max_score}, where 0 is the lowest and {max_score} the highest. "
                "Answer with a single digit only.",
            )

        messages = _build_messages(body, prompt)

        payload = {
            "messages": messages,
            # 只要决策位置的分布，不需要多生成任何内容
            "max_tokens": 1,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": _TOP_LOGPROBS,
            # 关闭思维链：System 1 要的是第一步的输出分布，思考会污染它
            "chat_template_kwargs": {"enable_thinking": False},
        }

        try:
            resp = await asyncio.to_thread(_post_chat, base_url, payload)
        except Exception as e:  # noqa: BLE001
            logger.exception("System-1 决策请求失败: model=%s", model_name)
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "upstream_error", "message": str(e)}},
            )

        # ── 从 logprobs 还原决策分布 ──
        try:
            choice = (resp.get("choices") or [])[0]
            content_lp = ((choice.get("logprobs") or {}).get("content") or [])
            if not content_lp:
                raise ValueError("上游未返回 logprobs")
            first = content_lp[0]
            candidates: dict[str, float] = {first["token"]: float(first["logprob"])}
            for alt in (first.get("top_logprobs") or []):
                candidates[alt["token"]] = float(alt["logprob"])
        except Exception as e:  # noqa: BLE001
            logger.exception("System-1 解析 logprobs 失败")
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "parse_error", "message": str(e)}},
            )

        # 原始候选（转成概率，便于调试与前端展示）
        raw_candidates = {t: round(math.exp(lp), 6) for t, lp in candidates.items()}

        if dtype == "yes_no":
            p_yes = _token_probability(candidates, ["Y", "Yes", "YES", "是"])
            p_no = _token_probability(candidates, ["N", "No", "NO", "否"])
            dist = _normalize({"Y": p_yes, "N": p_no})
            if not dist:
                return JSONResponse(
                    status_code=502,
                    content={"error": {"type": "parse_error",
                                       "message": f"无法从词表识别 Y/N，候选: {raw_candidates}"}},
                )
            result = {
                "type": "yes_no",
                "answer": dist.get("Y", 0.0) >= 0.5,
                "probability": round(dist.get("Y", 0.0), 6),
                "distribution": {k: round(v, 6) for k, v in dist.items()},
            }
        elif dtype == "choice":
            raw = {
                label: _token_probability(candidates, _label_variants(str(label)))
                for label in options
            }
            dist = _normalize(raw)
            if not dist:
                return JSONResponse(
                    status_code=502,
                    content={"error": {"type": "parse_error",
                                       "message": f"无法从词表识别选项标签，候选: {raw_candidates}"}},
                )
            best = max(dist, key=dist.get)
            result = {
                "type": "choice",
                "answer": best,
                "label": options.get(best),
                "probability": round(dist[best], 6),
                "distribution": {k: round(v, 6) for k, v in dist.items()},
            }
        else:
            raw = {
                str(i): _token_probability(candidates, [str(i), " " + str(i)])
                for i in range(max_score + 1)
            }
            dist = _normalize(raw)
            if not dist:
                return JSONResponse(
                    status_code=502,
                    content={"error": {"type": "parse_error",
                                       "message": f"无法从词表识别数字，候选: {raw_candidates}"}},
                )
            scores = {int(k): round(v, 6) for k, v in dist.items()}
            result = {
                "type": "score",
                "answer": max(scores, key=scores.get),
                # dist 的键是字符串（"0".."5"），算期望值前必须转成整数，
                # 否则 "5" * 0.3 会触发 TypeError: can't multiply sequence by non-int。
                "expectation": round(
                    sum(int(k) * v for k, v in dist.items()), 6
                ),
                "probability": round(max(dist.values()), 6),
                "distribution": scores,
            }

        result.update({
            "model": model_name,
            "raw_candidates": dict(
                sorted(raw_candidates.items(), key=lambda kv: -kv[1])[:8]
            ),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        })
        return result

    logger.info("System-1 决策 API 已启用: GET /v1/decide/capabilities, POST /v1/decide")
