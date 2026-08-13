# skills/builtin/document/tools/doc_tools.py
# 文档处理工具 — 包装 DocProcessor 管线 + HMD 读取

from __future__ import annotations

import logging

logger = logging.getLogger("skill.document")


class DocTools:
    """文档处理：OCR/HMD 管线和读取。AI 通过 <tool>{"skill":"document","tool":"process_scan",...}</tool> 调用。"""

    def __init__(self):
        from apps.dsn.document.doc_processor import DocProcessor
        from apps.dsn.document.hmd import HmdClient
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

        logger.info("process_scan 完成: hmd=%s md=%s docs=%d photos=%d",
                     result.get("hmd_path") or "none",
                     result.get("md_path") or "none",
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

    def process_last_scan(self, user_id: int = 0) -> dict:
        """
        自动处理最近一次扫描产生的文件：列出 uploads 目录，按修改时间取最新的 PNG，直接走管线。
        零参数，无需手动构造文件列表。

        :param user_id: 用户 ID（默认 0=自动取第一个用户）
        :return: 同 process_scan 的返回
        """
        import os
        uid = user_id or 1
        from apps.dsn.utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        uploads = wm.user_uploads_dir(uid=uid)
        logger.info("process_last_scan: 扫描 %s (user_id=%d)", uploads, uid)

        pngs = []
        if os.path.isdir(uploads):
            for f in sorted(os.listdir(uploads), key=lambda f: os.path.getmtime(os.path.join(uploads, f)), reverse=True):
                if f.lower().endswith(".png"):
                    fp = os.path.join(uploads, f)
                    pngs.append({"filename": f, "filepath": fp, "size": os.path.getsize(fp)})

        if not pngs:
            return {"success": False, "error": f"在 {uploads} 中未找到 PNG 文件，请先执行 scan", "hmd_path": None, "feedback_text": ""}

        logger.info("process_last_scan: 找到 %d 个文件，自动传入 process_scan", len(pngs))
        return self.process_scan(scanned_files=pngs, user_id=uid)

    def describe_image(self, file_path: str, prompt: str = None) -> dict:
        """
        用视觉模型分析本地图片内容（非文档 OCR，而是通用图像理解）。

        :param file_path: 图片文件路径（支持 ~ 展开）
        :param prompt: 描述提示词，默认 "请详细描述这张图片的内容"
        :return: {success, description, error}
        """
        import os
        file_path = os.path.expanduser(file_path)
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        logger.info("describe_image: %s", file_path)

        # 先转 base64 data URL
        try:
            from apps.dsn.models import VisionModel
            data_url = VisionModel.encode_image(file_path)
        except Exception as e:
            return {"success": False, "error": f"读取图片失败: {e}"}

        # 尝试用 VisionModel (GLM-4.6V / 外部 API)
        from apps.dsn.config import Config
        if Config.VISION_API_KEY:
            try:
                vm = VisionModel()
                desc = vm.ask(
                    data_url,
                    prompt=(prompt or "请详细描述这张图片的内容"),
                    max_tokens=2048,
                    temperature=0.1,
                )
                logger.info("describe_image VisionModel 完成: %d chars", len(desc))
                return {"success": True, "description": desc}
            except Exception as e:
                logger.warning("VisionModel 失败，尝试 LMStudio 回退: %s", e)

        # 回退：用 LMStudio 多模态模型
        try:
            from apps.dsn.models import LMStudioChat
            chat = LMStudioChat(model_name=None)
            desc = chat.describe_image(
                data_url,
                prompt=(prompt or "请详细描述这张图片的内容"),
            )
            logger.info("describe_image LMStudio 完成: %d chars", len(desc))
            return {"success": True, "description": desc}
        except Exception as e:
            logger.error("describe_image 全部失败: %s", e)
            return {"success": False, "error": f"图片分析失败: {e}"}
