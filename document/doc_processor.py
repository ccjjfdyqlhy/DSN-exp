# document/doc_processor.py
# 文档处理管线 — 扫描→分类→OCR→HMD→合并存储

from __future__ import annotations

import logging
import os

from config import Config
from .inputs import load_document_image, normalize_document_inputs

logger = logging.getLogger("DocProcessor")


class DocProcessor:
    """
    文档处理管线。

    流程（标准模式）:
      Step 0: 扫描 → 获取 PNG 列表
      Step 1: 每张图用 vision 分类 (document / photo / mixed)
      Step 2: 纯文档/mixed → deepseek-ocr → mdA; 照片 → vision describe → 直接给 AI
      Step 3: 调用 2md API → 获取 mdB + json + 关联图表
      Step 4: 合并 mdA + mdB + json + 图表 → 打包 .hmd → 存 workspace/<user>/documents/
      Step 5: 生成 AI 可读的反馈文本

    流程（VISION_OVERRIDE 模式）:
      Step 0-1 同上
      Step 2: VisionModel.ocr_md() → 直接生成完整 Markdown（替代 OCR + 2md）
      Step 3-5: 同上（用 VisionModel 的输出构造 api_results）
    """

    def __init__(self, ocr_model=None, hmd_client=None, vision_model=None):
        self._ocr = ocr_model
        self._hmd = hmd_client
        self._vm = vision_model
        self._override = Config.VISION_OVERRIDE
        if self._override:
            logger.info("VISION_OVERRIDE=True：VisionModel 将接管所有 OCR 及布局分析")

    def _classify_image(self, data_url: str) -> str:
        """判断图片类型"""
        if not data_url:
            return "document"
        if self._override:
            vm = self._get_vm()
            return vm.classify_image(data_url)
        ocr = self._get_ocr()
        text = ocr.ocr(data_url, max_tokens=256)
        return "document" if len(text.strip()) > 30 else "photo"

    def _get_ocr(self):
        if self._ocr is None:
            from models import OCRModel
            self._ocr = OCRModel()
            logger.info("OCRModel 已初始化 (model=%s)", Config.OCR_MODEL)
        return self._ocr

    def _get_vm(self):
        if self._vm is None:
            from models import VisionModel
            self._vm = VisionModel()
            logger.info("VisionModel 已初始化 (model=%s)", Config.VISION_MODEL_NAME)
        return self._vm

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

        hmd_c = self._get_hmd()

        doc_images = []
        photo_images = []

        scanned_images = normalize_document_inputs(scanned_images)

        if not scanned_images:
            logger.warning("process_scan: scanned_images 为空或格式全部错误")
            return {
                "hmd_path": None, "md_path": None,
                "feedback_text": "错误：scanned_files 参数格式错误，请传入文件路径列表，如 [\"/path/to/file.png\"]",
                "documents": [], "photos": [],
            }

        for img in scanned_images:
            filepath = img.get("filepath", "")
            filename = img.get("filename", "")
            try:
                filename, filepath, data_url = load_document_image(img)
            except FileNotFoundError:
                logger.warning("文件不存在，跳过: %s", filepath)
                photo_images.append({"filename": filename, "filepath": filepath, "data_url": "", "category": "photo"})
                continue

            category = self._classify_image(data_url)
            logger.info("分类 %s → %s (user_id=%d)", filename, category, user_id)

            entry = {"filename": filename, "filepath": filepath, "data_url": data_url, "category": category}

            if category == "document":
                doc_images.append(entry)
            elif category == "mixed":
                doc_images.append(entry)
                photo_images.append(entry)
            else:
                photo_images.append(entry)

        if self._override:
            # ---- VisionModel 接管模式：直接生成 Markdown，跳过 2md ----
            vm = self._get_vm()
            md_list = []
            if doc_images:
                logger.info("VISION_OVERRIDE: VisionModel OCR %d 张文档图片", len(doc_images))
                ocr_input = [{"filename": d["filename"], "data_url": d["data_url"]} for d in doc_images]
                md_list = vm.ocr_md_batch(ocr_input)

            # 用 VisionModel 输出构造伪 api_results（替代 2md 返回）
            api_results = []
            for m in md_list:
                fname = m.get("filename", "unknown")
                md_text = m.get("markdown", "")
                basename = os.path.splitext(fname)[0]
                api_results.append({
                    "basename": basename,
                    "markdown": md_text,
                    "pages": [{"page_info": {"page_number": 1, "filename": fname}, "layout_dets": []}],
                    "images": {},
                })

            mdA_list = md_list
        else:
            # ---- 标准模式：OCRModel + 2md API ----
            ocr = self._get_ocr()
            mdA_list = []
            if doc_images:
                logger.info("OCR 处理 %d 张文档图片 (user_id=%d)", len(doc_images), user_id)
                ocr_input = [{"filename": d["filename"], "data_url": d["data_url"]} for d in doc_images]
                mdA_list = ocr.ocr_batch(ocr_input)

            api_results = []
            for img in scanned_images:
                if not isinstance(img, dict):
                    continue
                fpath = img.get("filepath", "")
                if fpath and os.path.exists(fpath):
                    try:
                        result = hmd_c.convert(fpath)
                        api_results.append(result)
                        logger.info("2md 转换完成: %s → basename=%s", img.get("filename"), result.get("basename"))
                    except Exception as e:
                        logger.error("2md 转换失败 %s: %s", img.get("filename"), e)

        hmd_path = None
        md_path = None
        if api_results and scanned_images:
            try:
                output_dir = self._documents_dir(user_id)
                merged = self._merge_2md_results(api_results)
                hmd_path = hmd_c.save_hmd(merged, mdA_list, output_dir)
                logger.info(".hmd 已保存: %s (user_id=%d)", hmd_path, user_id)

                # VISION_OVERRIDE 模式下额外保存独立 .md 文件，方便 AI 直接读取
                if self._override and mdA_list:
                    md_text = "\n\n".join(
                        m.get("markdown", "") for m in mdA_list if m.get("markdown")
                    )
                    if md_text:
                        basename = merged.get("basename", "document")
                        md_path = os.path.join(output_dir, f"{basename}.md")
                        with open(md_path, "w", encoding="utf-8") as f:
                            f.write(md_text)
                        logger.info(".md 已保存: %s (user_id=%d)", md_path, user_id)
            except Exception as e:
                logger.error("保存 .hmd 失败: %s", e)

        feedback = self._build_feedback(
            mdA_list, api_results, hmd_path, doc_images, photo_images,
            vision_override=self._override,
            md_path=md_path,
        )

        logger.info("process_scan 完成: user_id=%d docs=%d photos=%d hmd=%s md=%s",
                     user_id, len(doc_images), len(photo_images), hmd_path or "none", md_path or "none")

        return {
            "hmd_path": hmd_path,
            "md_path": md_path,
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
        from utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        d = wm.user_documents_dir(uid=user_id)
        logger.debug("document 输出目录: %s (user_id=%d)", d, user_id)
        return str(d)

    @staticmethod
    def _build_feedback(mdA_list: list[dict], api_results: list[dict],
                        hmd_path: str, doc_images: list[dict],
                        photo_images: list[dict],
                        vision_override: bool = False,
                        md_path: str = None) -> str:
        parts = []

        if doc_images:
            parts.append(f"## OCR 结果 ({len(doc_images)} 页)")
            for m in mdA_list:
                fname = m.get("filename", "")
                md_text = m.get("markdown", "")
                if md_text:
                    parts.append(f"### {fname}\n{md_text[:300]}")

        if photo_images:
            parts.append(f"\n## 非文档图片 ({len(photo_images)} 张) — 已跳过 OCR")

        if api_results:
            label = "文档布局 (VM)" if vision_override else "文档布局 (2md)"
            parts.append(f"\n## {label}")
            if len(api_results) == 1:
                parts.append(api_results[0].get("markdown", ""))
            else:
                for i, r in enumerate(api_results):
                    parts.append(f"### 第 {i+1} 页\n{r.get('markdown', '')}")

        if hmd_path:
            parts.append(f"\n---\n.hmd 已保存: {hmd_path}")
        if md_path:
            parts.append(f".md 已保存: {md_path}")

        return "\n".join(parts)
