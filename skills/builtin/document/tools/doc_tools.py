# skills/builtin/document/tools/doc_tools.py
# 文档处理工具 — 包装 DocProcessor 管线 + HMD 读取

from __future__ import annotations

import logging

logger = logging.getLogger("skill.document")


class DocTools:
    """文档处理：OCR/HMD 管线和读取。AI 通过 <tool>{"skill":"document","tool":"process_scan",...}</tool> 调用。"""

    def __init__(self):
        from document.doc_processor import DocProcessor
        from document.hmd import HmdClient
        self._processor = DocProcessor()
        self._hmd = HmdClient()
        logger.info("DocTools 已就绪")

    def process_scan(self, scanned_files: list[dict],
                     user_id: int = 0) -> dict:
        """
        处理扫描结果：分类→OCR→2md→打包 .hmd。

        :param scanned_files: 扫描产出的文件列表
        :param user_id: 用户 ID（默认 0=自动取第一个用户）
        :return: {hmd_path, feedback_text, documents_summary, photos_summary}
        """
        uid = user_id or 1
        logger.info("process_scan 开始: %d 文件 (user_id=%d)", len(scanned_files), uid)
        result = self._processor.process_scan(
            user_id=uid,
            scanned_images=scanned_files,
        )
        # 移除 data_url（base64 图片）避免 payload 爆炸，仅保留文件名和路径
        for lst_key in ("documents", "photos"):
            lst = result.get(lst_key, [])
            summary_list = []
            for item in lst:
                summary_list.append({
                    "filename": item.get("filename", ""),
                    "filepath": item.get("filepath", ""),
                    "category": item.get("category", ""),
                })
            result[f"{lst_key}_summary"] = summary_list
            result.pop(lst_key, None)

        logger.info("process_scan 完成: hmd=%s docs=%d photos=%d",
                     result.get("hmd_path") or "none",
                     len(result.get("documents_summary", [])),
                     len(result.get("photos_summary", [])))
        return result

    def read_hmd(self, hmd_path: str) -> dict:
        """
        解包 .hmd 文件，返回结构化数据供 AI 阅读。
        mda 返回全文，其他字段仅返回摘要（避免 payload 过大）。

        :param hmd_path: .hmd 文件路径
        :return: {success, mda, mdb_summary, json_keys, images_count}
        """
        logger.info("read_hmd: %s", hmd_path)
        data = self._hmd.read_hmd(hmd_path)
        mda = data.get("mda", "")
        mdb = data.get("mdb", "")
        images = data.get("images", [])
        js = data.get("json", {})
        logger.info("read_hmd 完成: mdA=%d chars, mdB=%d chars, images=%d",
                     len(mda), len(mdb), len(images))
        return {
            "success": True,
            "mda": mda,
            "mdb_summary": f"[mdb: {len(mdb)} chars, 布局分析全文未载入，按需询问细节]",
            "json_keys": list(js.keys()) if isinstance(js, dict) else [],
            "images_count": len(images),
        }
