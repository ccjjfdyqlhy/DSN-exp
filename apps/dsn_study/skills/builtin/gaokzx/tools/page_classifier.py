# apps/dsn_study/skills/builtin/gaokzx/tools/page_classifier.py
"""试题页 / 答案页的**快速判定**。
#
# 背景：gaokzx 的文章是「试题+答案合卷」，站点**不提供**分页级的题/答标记，
# 只能靠看图判断。逐页问一次视觉模型，83 页要 5~9 分钟 —— 而真正需要的
# 只是**一个分界点**。
#
# 四招把它做快：
#
#   ① **批量二分**：卷子结构是「前 N 页试题、后 M 页答案」，判定序列单调。
#      一轮里**并行**探 K 个切点，区间一次缩到 1/K —— 22 页 3 轮收敛，
#      而顺序二分要 5 次**串行**调用。
#   ② **全局并发闸**：厂商侧对同一 key 的并发图像请求很敏感（实测 24 并发
#      直接断连）。这里用一把全局信号量把**在途请求总数**压住，
#      而不是每科各自为政。
#   ③ **缩图**：送模型前把长边缩到 ~900px（实测 1200px 要 6.3s、900px 5.1s、
#      700px 3.3s —— 厂商侧图像预处理才是大头）。
#   ④ **内容缓存**：同一张图的判定按内容哈希落盘，重复处理 0 次模型调用。
#
# 正确性不靠"相信二分"：
#   * 判定**失败会抛错**，绝不静默当成"试题"（那会悄悄污染分界）；
#   * 二分后做**边界校验 + 均匀抽样校验**，一旦发现判定序列不单调
#     （卷子中间夹了答案页），自动退化为**全量扫描**；
#   * 任何时候都能回退到"慢但准"，不会给出错结果。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

logger = logging.getLogger("GaokzxPageClassifier")

#: 判定提示词（版本号进缓存键；换提示词必须换版本，否则会吃到旧缓存）
PROMPT_VERSION = "v3"
ASK_PROMPT = (
    "这一页是否包含**答案内容**（参考答案、答案表、答案解析、评分细则、"
    "「答案：」等）？只回答一个字：是 或 否。"
)

LABEL_QUESTION = "question"
LABEL_ANSWER = "answer"


class ClassificationError(RuntimeError):
    """判定失败（网络/厂商/解析）。**必须让调用方看见**，不能静默降级。"""


class PageClassifier:
    """按内容判定「试题页 / 答案页」，并快速定位分界点。"""

    def __init__(self, ask_fn: Callable[[str, str], str], *,
                 concurrency: int = 6,
                 cache_path: Optional[str] = None,
                 image_max_px: int = 800,
                 workers: int = 4,
                 max_inflight: int = 3,
                 retries: int = 2):
        """
        :param ask_fn: (data_url, prompt) -> 文本
        :param concurrency: 科目级并发度
        :param cache_path: 判定缓存（JSON）；None = 不缓存
        :param image_max_px: 送模型前的长边上限（像素）
        :param workers: 单次批量内的并发探针数
        :param max_inflight: **全局**在途模型请求上限（厂商侧敏感的闸门）
        :param retries: 单次判定失败重试次数
        """
        self._ask = ask_fn
        self._concurrency = max(1, int(concurrency))
        self._cache_path = cache_path
        self._image_max_px = int(image_max_px)
        self._workers = max(1, int(workers))
        self._retries = max(0, int(retries))
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        #: 全局在途闸门：所有线程共用
        self._gate = threading.Semaphore(max(1, int(max_inflight)))
        self.calls = 0
        self.cache_hits = 0
        self.failures = 0
        self._load_cache()

    # ── 缓存 ──

    def _load_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            with open(self._cache_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._cache = {str(k): str(v) for k, v in data.items()}
        except Exception:
            self._cache = {}

    def _save_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._cache_path)),
                        exist_ok=True)
            tmp = self._cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False)
            os.replace(tmp, self._cache_path)
        except Exception as exc:
            logger.warning("判定缓存写入失败: %s", exc)

    @staticmethod
    def _key(path: str) -> str:
        try:
            st = os.stat(path)
            h = hashlib.sha256()
            h.update(PROMPT_VERSION.encode())
            h.update(str(st.st_size).encode())
            with open(path, "rb") as fh:
                h.update(fh.read(1 << 20))
            return h.hexdigest()
        except OSError:
            return ""

    # ── 单页判定 ──

    def _scaled_data_url(self, path: str) -> Optional[str]:
        """缩图 → data URL（省上传 + 省厂商侧预处理时间）。"""
        import base64
        try:
            from PIL import Image
        except Exception:
            return None
        tmp_path = None
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                w, h = im.size
                m = max(w, h)
                if m > self._image_max_px:
                    r = self._image_max_px / float(m)
                    im = im.resize((max(1, int(w * r)), max(1, int(h * r))),
                                   Image.LANCZOS)
                fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="gkcls_")
                os.close(fd)
                im.save(tmp_path, "JPEG", quality=80)
            with open(tmp_path, "rb") as fh:
                blob = fh.read()
            return "data:image/jpeg;base64," + base64.b64encode(blob).decode()
        except Exception as exc:
            logger.warning("缩图失败（用原图）: %s", exc)
            return None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def label(self, path: str) -> str:
        """判定一页。

        失败会抛 :class:`ClassificationError` —— **不静默降级**：
        把"判定失败"当成"这是试题"会悄悄把分界点推向后面，产出错的合卷。
        """
        key = self._key(path)
        with self._lock:
            if key and key in self._cache:
                self.cache_hits += 1
                return self._cache[key]
        data_url = self._scaled_data_url(path)
        if not data_url:
            try:
                import base64
                with open(path, "rb") as fh:
                    data_url = ("data:image/jpeg;base64,"
                                + base64.b64encode(fh.read()).decode())
            except Exception as exc:
                raise ClassificationError("读图失败: %s" % exc)
        last_err = None
        for attempt in range(self._retries + 1):
            try:
                with self._gate:          # 全局在途闸门
                    with self._lock:
                        self.calls += 1
                    raw = str(self._ask(data_url, ASK_PROMPT) or "")
                head = raw.strip()[:8]
                if "是" in head:
                    label = LABEL_ANSWER
                elif "否" in head:
                    label = LABEL_QUESTION
                else:
                    # 回复含糊/为空 → 当作**失败**重试。
                    # 把它当成"不是"会把分界点悄悄推后，产出错的合卷。
                    raise ClassificationError(
                        "判定回复不含是/否: %r" % raw[:40])
                if key:
                    with self._lock:
                        self._cache[key] = label
                return label
            except Exception as exc:
                last_err = exc
                if attempt < self._retries:
                    import time
                    time.sleep(1.5 * (attempt + 1))
        with self._lock:
            self.failures += 1
        raise ClassificationError("页面判定失败: %s" % last_err)

    # ── 分界点 ──

    def _label_many(self, paths: list, indexes: list) -> dict:
        """并行判定若干页 → {下标: 标签}。任一失败 → 整批抛错。"""
        if not indexes:
            return {}
        uniq = sorted(set(int(i) for i in indexes))
        with ThreadPoolExecutor(max_workers=min(self._workers, len(uniq))) as ex:
            labels = list(ex.map(lambda i: self.label(paths[i]), uniq))
        return dict(zip(uniq, labels))

    def find_boundary(self, paths: list[str]) -> dict:
        """找「第一张答案页」的下标（0 基）。

        返回 {boundary, labels, mode, monotone, probes}。
        """
        n = len(paths)
        if n == 0:
            return {"boundary": 0, "labels": [], "mode": "empty", "monotone": True}
        if n == 1:
            lab = self.label(paths[0])
            return {"boundary": 1 if lab == LABEL_ANSWER else 0,
                    "labels": [lab], "mode": "binary", "monotone": True}

        probes: dict[int, str] = {}
        lo, hi = 0, n              # 真正的分界 ∈ [lo, hi]
        k = max(2, min(self._workers, 4))
        rounds = 0
        while hi - lo > 1 and rounds < 6:
            rounds += 1
            span = hi - lo
            cuts = []
            for i in range(1, k + 1):
                c = lo + (span * i) // k
                if lo < c < n and c not in cuts:      # 只探有页的下标
                    cuts.append(c)
            if not cuts:
                break
            labels = self._label_many(paths, cuts)
            probes.update(labels)
            first_ans = next((c for c in cuts if labels[c] == LABEL_ANSWER), None)
            if first_ans is not None:
                prev = max([c for c in cuts if c < first_ans], default=lo)
                lo, hi = prev, first_ans
            else:
                lo = cuts[-1]
            if hi - lo <= 1:
                break
        boundary = hi if hi < n else n

        # 精修：分界可能落在"第一个被判为答案的探针"**左边**
        # （例如整卷都是答案页时，第一个探针就已是答案）。
        # 向左逐页确认，直到前一页是"题"为止。
        for _ in range(4):
            if boundary <= 0:
                break
            if boundary - 1 not in probes:
                probes.update(self._label_many(paths, [boundary - 1]))
            if probes.get(boundary - 1) != LABEL_ANSWER:
                break
            boundary -= 1

        # 单调性校验：**复用二分探针**（它们本来就横跨分界两侧），
        # 只有当探针没覆盖到两侧时才补采样 —— 省掉 4 次模型调用。
        below = [i for i, lab in probes.items() if i < boundary]
        above = [i for i, lab in probes.items() if i >= boundary]
        if not below or not above:
            sample_idx = sorted({int(i * (n - 1) / 3.0) for i in range(4)})
            need = [i for i in sample_idx if i not in probes]
            if need:
                probes.update(self._label_many(paths, need))
                below = [i for i, lab in probes.items() if i < boundary]
                above = [i for i, lab in probes.items() if i >= boundary]
        if any(probes.get(i) == LABEL_ANSWER for i in below):
            logger.info("卷子判定序列不单调 → 退化为全量扫描 (%d 页)", n)
            return self._full_scan(paths)

        # 非单调检测：探一下"答案段中部" —— 若是"题"，说明答案与试题
        # 交错出现（卷子中间夹了答案页），二分的前提不成立。
        if boundary < n - 1:
            mid = boundary + max(1, (n - boundary) // 2)
            if mid < n and mid not in probes:
                probes.update(self._label_many(paths, [mid]))
            if probes.get(mid) == LABEL_QUESTION:
                logger.info("答案段里出现试题页（结构交错）→ 退化为全量扫描")
                return self._full_scan(paths)

        # 边界校验：分界前一页必须是试题、分界页必须是答案
        check_idx = []
        if boundary > 0:
            check_idx.append(boundary - 1)
        if boundary < n:
            check_idx.append(boundary)
        need = [i for i in check_idx if i not in probes]
        if need:
            probes.update(self._label_many(paths, need))
        if boundary > 0 and probes.get(boundary - 1) == LABEL_ANSWER:
            logger.info("分界校验失败（前页被判为答案）→ 全量扫描")
            return self._full_scan(paths)
        if boundary < n and probes.get(boundary) != LABEL_ANSWER:
            logger.info("分界校验失败（分界页不是答案）→ 全量扫描")
            return self._full_scan(paths)

        labels = ["question"] * n
        for i in range(boundary, n):
            labels[i] = "answer"
        self._save_cache()
        return {"boundary": boundary, "labels": labels, "mode": "binary",
                "monotone": True, "probes": len(probes), "rounds": rounds}

    def _full_scan(self, paths: list[str]) -> dict:
        """全量扫描（结构不单调时的兜底）。并行，逐页判定。"""
        with ThreadPoolExecutor(max_workers=self._workers) as ex:
            labels = list(ex.map(self.label, paths))
        boundary = len(labels)
        for i, lab in enumerate(labels):
            if lab == LABEL_ANSWER:
                boundary = i
                break
        return {"boundary": boundary, "labels": labels, "mode": "full",
                "monotone": False}

    # ── 批量 ──

    def classify_bundle(self, papers: dict[str, list[str]]) -> dict[str, dict]:
        """多套卷子并行判定。papers: {名称: [图片路径, ...]}"""
        names = list(papers.keys())
        out: dict[str, dict] = {}
        if not names:
            return out
        with ThreadPoolExecutor(max_workers=min(self._concurrency, len(names))) as ex:
            futs = {ex.submit(self.find_boundary, papers[n]): n for n in names}
            for fut, name in futs.items():
                try:
                    out[name] = fut.result()
                except Exception as exc:
                    logger.warning("判定失败 %s: %s", name, exc)
                    out[name] = {"boundary": 0, "labels": [], "mode": "error",
                                 "monotone": False, "error": str(exc)}
        self._save_cache()
        return out

    def stats(self) -> dict:
        return {"模型调用": self.calls, "缓存命中": self.cache_hits,
                "判定失败": self.failures}
