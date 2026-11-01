# apps/dsn_study/document/ocr.py
# OCR 通道 — 纯视觉→Markdown 模型客户端。
#
# 与参考实现（DSN-exp models/clients.py 的 OCRModel）的差异：
#   参考版自带 LMStudio 模型调度器（ModelScheduler + load/unload），
#   依赖一整套模型生命周期管理；dsn_study 的视觉能力已下沉
#   infra/orchestrator/vision.py，VisionModel.ocr_md / ocr_md_batch
#   即"纯图→markdown"通道，配置与超时由 infra 统一处理。
#
# 因此这里只做薄封装，保持参考版的调用契约（ocr / ocr_batch / unload），
# 让 document 技能与 DocProcessor 管线可以零改动移植。

from __future__ import annotations

import logging

from apps.dsn_study.models.clients import VisionModel

logger = logging.getLogger("OCRModel")


class OCRModel:
    """OCR 客户端 — 纯图→Markdown，无文本提示。

    用法:
        ocr = OCRModel()
        md = ocr.ocr(data_url)         # 单张 → markdown
        results = ocr.ocr_batch([...]) # 批量 → [{filename, markdown}]
        ocr.unload()                   # 兼容参考版的卸载接口（no-op）
    """

    def __init__(self, base_url: str = None, model_name: str = None,
                 auto_load: bool = True, managed: bool = True):
        self._model = VisionModel(base_url=base_url, model_name=model_name)
        self.logger = logger

    def ocr(self, data_url: str, max_tokens: int = 4096) -> str:
        """对单张图片执行 OCR，返回 markdown 文本。"""
        results = self.ocr_batch([{"filename": "image", "data_url": data_url}],
                                 max_tokens)
        return results[0]["markdown"] if results else ""

    def ocr_batch(self, images: list, max_tokens: int = 4096) -> list:
        """批量 OCR：[{filename, data_url}] → [{filename, markdown}]"""
        results = []
        for img in images or []:
            filename = img.get("filename", "unknown")
            try:
                text = self._model.ocr_md(img.get("data_url", ""),
                                          max_tokens=max_tokens)
            except Exception as e:
                self.logger.warning("OCR 失败: %s — %s", filename, e)
                text = ""
            results.append({"filename": filename, "markdown": text})
        self.logger.info("OCR 完成: %d 张", len(results))
        return results

    def unload(self) -> bool:
        """兼容参考版的卸载接口（infra 视觉层无独立模型生命周期，恒 True）。"""
        return True

    def __repr__(self):
        return "<OCRModel model=%s>" % getattr(self._model, "model_name", "")
