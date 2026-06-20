# document/doc_processor.py
# 文档处理管线 — 扫描→分类→OCR→HMD→合并存储

from __future__ import annotations

import base64
import logging
import os
import tempfile

from config import Config

logger = logging.getLogger("DocProcessor")


class DocProcessor:
    """
    文档处理管线。

    流程:
      Step 0: 扫描 → 获取 PNG 列表
      Step 1: 每张图用 vision 分类 (document / photo / mixed)
      Step 2: 纯文档/mixed → deepseek-ocr → mdA; 照片 → vision describe → 直接给 AI
      Step 3: 调用 2md API → 获取 mdB + json + 关联图表
      Step 4: 合并 mdA + mdB + json + 图表 → 打包 .hmd → 存 workspace/<user>/documents/
      Step 5: 生成 AI 可读的反馈文本
    """

    def __init__(self, vision_chat=None, ocr_model=None, hmd_client=None):
        self._vision = vision_chat
        self._ocr = ocr_model  # OCRModel 实例，为 None 时惰性初始化
        self._hmd = hmd_client

    def _get_vision(self):
        if self._vision is None:
            from models import LMStudioChat
            self._vision = LMStudioChat(
                base_url=Config.LMSTUDIO_BASE_URL,
                model_name=Config.MEMORY_MODEL,
                timeout=300,
            )
            logger.info("Vision 模型已初始化: %s @ %s", Config.MEMORY_MODEL, Config.LMSTUDIO_BASE_URL)
        return self._vision

    def _get_ocr(self):
        if self._ocr is None:
            from models import OCRModel
            self._ocr = OCRModel()
            logger.info("OCRModel 已初始化 (model=%s)", Config.OCR_MODEL)
        return self._ocr

    def _get_hmd(self):
        if self._hmd is None:
            from .hmd import HmdClient
            self._hmd = HmdClient()
            logger.info("HmdClient 已初始化 (api=%s)", Config.TWO_MD_API)
        return self._hmd

    def process_scan(self, user_id: int, scanned_images: list[dict]) -> dict:
        """
        完整处理一趟扫描。

        :param user_id: 用户 ID
        :param scanned_images: [{filename, filepath}, ...]
        :return: {hmd_path, feedback_text, documents: [...], photos: [...]}
        """
        logger.info("process_scan 开始: user_id=%d, images=%d", user_id, len(scanned_images))

        vision = self._get_vision()
        ocr = self._get_ocr()
        hmd_c = self._get_hmd()

        doc_images = []
        photo_images = []

        for img in scanned_images:
            filepath = img.get("filepath", "")
            filename = img.get("filename", "")
            data_url = ""
            if filepath and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    raw = f.read()
                ext = os.path.splitext(filename)[-1].lower().lstrip(".")
                mime = "png" if ext == "png" else "jpeg" if ext in ("jpg", "jpeg") else ext
                data_url = f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"

            category = vision.classify_image(data_url) if data_url else "document"
            logger.info("分类 %s → %s (user_id=%d)", filename, category, user_id)

            entry = {"filename": filename, "filepath": filepath, "data_url": data_url, "category": category}

            if category == "document":
                doc_images.append(entry)
            elif category == "mixed":
                doc_images.append(entry)
                photo_images.append(entry)
            else:
                photo_images.append(entry)

        mdA_list = []
        if doc_images:
            logger.info("OCR 处理 %d 张文档图片 (user_id=%d)", len(doc_images), user_id)
            ocr_input = [{"filename": d["filename"], "data_url": d["data_url"]} for d in doc_images]
            mdA_list = ocr.ocr_batch(ocr_input)

        photo_descriptions = ""
        if photo_images:
            logger.info("Vision 描述 %d 张图片 (user_id=%d)", len(photo_images), user_id)
            try:
                photo_descriptions = vision.describe_images(
                    [{"filename": p["filename"], "data_url": p["data_url"]} for p in photo_images]
                )
            except Exception as e:
                logger.error("多图描述失败: %s", e)
                photo_descriptions = ""

        api_results = []
        for img in scanned_images:
            fpath = img.get("filepath", "")
            if fpath and os.path.exists(fpath):
                try:
                    result = hmd_c.convert(fpath)
                    api_results.append(result)
                    logger.info("2md 转换完成: %s → basename=%s", img.get("filename"), result.get("basename"))
                except Exception as e:
                    logger.error("2md 转换失败 %s: %s", img.get("filename"), e)

        hmd_path = None
        if api_results and scanned_images:
            try:
                output_dir = self._documents_dir(user_id)
                merged = self._merge_2md_results(api_results)
                hmd_path = hmd_c.save_hmd(merged, mdA_list, output_dir)
                logger.info(".hmd 已保存: %s (user_id=%d)", hmd_path, user_id)
            except Exception as e:
                logger.error("保存 .hmd 失败: %s", e)

        feedback = self._build_feedback(
            mdA_list, photo_descriptions, api_results, hmd_path, doc_images, photo_images
        )

        logger.info("process_scan 完成: user_id=%d docs=%d photos=%d hmd=%s",
                     user_id, len(doc_images), len(photo_images), hmd_path or "none")

        return {
            "hmd_path": hmd_path,
            "feedback_text": feedback,
            "documents": doc_images,
            "photos": photo_images,
        }

    @staticmethod
    def _merge_2md_results(results: list[dict]) -> dict:
        if not results:
            return {}
        if len(results) == 1:
            return results[0]
        merged_md = []
        merged_pages = []
        merged_images = {}
        merged_basename = results[0].get("basename", "merged")
        for r in results:
            merged_md.append(r.get("markdown", ""))
            merged_pages.extend(r.get("pages", []))
            merged_images.update(r.get("images", {}))
        return {
            "basename": merged_basename,
            "markdown": "\n\n".join(merged_md),
            "pages": merged_pages,
            "images": merged_images,
        }

    def _documents_dir(self, user_id: int) -> str:
        from workspace import get_workspace_manager
        wm = get_workspace_manager()
        d = wm.user_documents_dir(uid=user_id)
        logger.debug("document 输出目录: %s (user_id=%d)", d, user_id)
        return str(d)

    @staticmethod
    def _build_feedback(mdA_list: list[dict], photo_descs: str,
                        api_results: list[dict], hmd_path: str,
                        doc_images: list[dict], photo_images: list[dict]) -> str:
        parts = []

        if doc_images:
            parts.append(f"## 文档处理结果 ({len(doc_images)} 页)")
            for m in mdA_list:
                fname = m.get("filename", "")
                md_text = m.get("markdown", "")
                parts.append(f"### {fname}\n{md_text}")

        if api_results:
            parts.append("\n## 文档布局 (2md)")
            if len(api_results) == 1:
                parts.append(api_results[0].get("markdown", ""))
            else:
                for i, r in enumerate(api_results):
                    parts.append(f"### 第 {i+1} 页\n{r.get('markdown', '')}")

        if photo_images:
            parts.append(f"\n## 图片描述 ({len(photo_images)} 张)")
            parts.append(photo_descs)

        if hmd_path:
            parts.append(f"\n---\n.hmd 已保存: {hmd_path}")

        return "\n".join(parts)
