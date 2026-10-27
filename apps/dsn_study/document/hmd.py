# document/hmd.py
# HMD 客户端 — 调用 2md API + .hmd zip 包读写（自参考实现移植）

from __future__ import annotations

import base64
import json
import logging
import os
import zipfile

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger("HmdClient")


class HmdClient:
    """HMD 文档客户端。调用 2md API 将 PDF/PNG 转为结构化 HMD 包。"""

    def __init__(self, server_url: str = None):
        from apps.dsn_study.config import Config
        self.server_url = (server_url or Config.TWO_MD_API).rstrip("/")

    def convert(self, file_path: str, dpi: int = 200, pages: str = None) -> dict:
        """
        同步调用 /convert 接口，上传文件并等待转换完成。

        :param file_path: PDF 或图片路径
        :param dpi: 渲染 DPI
        :param pages: 页码范围，如 "1" / "1-5"
        :return: {basename, markdown (mdB), pages, images: {fname: b64}}
        """
        if requests is None:
            raise RuntimeError("需要安装 requests")

        url = f"{self.server_url}/convert"
        params = {"dpi": dpi}
        if pages:
            params["pages"] = pages

        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
            logger.info("上传文件: %s", file_path)
            resp = requests.post(url, params=params, files=files, timeout=300)

        if resp.status_code != 200:
            raise RuntimeError(f"2md API 返回 {resp.status_code}: {resp.text}")

        data = resp.json()
        logger.info("2md 转换完成: basename=%s pages=%d images=%d",
                    data.get("basename"), len(data.get("pages", [])), len(data.get("images", {})))
        return data

    @staticmethod
    def save_hmd(api_result: dict, mdA_list: list[dict], output_dir: str) -> str:
        """
        合并 OCR 输出 (mdA) 与 2md 输出 (mdB/json/images) → 生成 .hmd zip 包。

        .hmd 结构:
          <basename>.hmd (zip)
          ├── <basename>.mdA    ← OCR 纯文本（合并所有页）
          ├── <basename>.mdB    ← 2md 布局 markdown
          ├── <basename>.json   ← 页面元数据（不含 images base64）
          └── img_001.png ...   ← 2md 裁剪出的图/表

        :return: .hmd 文件路径
        """
        os.makedirs(output_dir, exist_ok=True)
        basename = api_result["basename"]
        hmd_path = os.path.join(output_dir, f"{basename}.hmd")

        mdA_text = "\n\n".join(
            [f"## {m.get('filename', '')}\n{m.get('markdown', '')}" for m in mdA_list]
        )
        mdB_text = api_result.get("markdown", "")

        pages_for_json = []
        for page in api_result.get("pages", []):
            p = {"page_info": page.get("page_info", {}), "layout_dets": []}
            for det in page.get("layout_dets", []):
                d = {k: v for k, v in det.items() if k not in ("image",)}
                p["layout_dets"].append(d)
            pages_for_json.append(p)

        images_b64 = api_result.get("images", {})

        with zipfile.ZipFile(hmd_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{basename}.mdA", mdA_text)
            zf.writestr(f"{basename}.mdB", mdB_text)
            zf.writestr(f"{basename}.json", json.dumps(pages_for_json, ensure_ascii=False, indent=2))
            for fname, b64_data in images_b64.items():
                zf.writestr(fname, base64.b64decode(b64_data))

        logger.info(".hmd 已保存: %s (mdA=%d, mdB=%d, json=%d页, images=%d)",
                    hmd_path, len(mdA_text), len(mdB_text), len(pages_for_json), len(images_b64))
        return hmd_path

    @classmethod
    def convert_via_vision(cls, image_paths: list, output_dir: str = "",
                           prompt: str = "", max_tokens: int = 4096) -> dict:
        """VISION_OVERRIDE 等价物：视觉模型直出 Markdown，不经 2md API。

        对每张图片调用 VisionModel.ocr_md，产出与 2md 管线同构的 .hmd 包
        （mdA=各页视觉识别文本，mdB=合并 Markdown），下游 process_hmd 无感。

        :param image_paths: 图片路径列表（PNG/JPG；PDF 请先自行渲染为图片）
        :param output_dir: .hmd 输出目录（缺省与首图同目录）
        :param prompt: 覆盖默认识别指令（可选）
        :return: {basename, hmd_path, pages, markdown}
        """
        import datetime as _dt
        from apps.dsn_study.models.clients import VisionModel

        if not image_paths:
            raise ValueError("image_paths 不能为空")
        vm = VisionModel()
        mdA_list = []
        for p in image_paths:
            data_url = VisionModel.encode_image(p)
            if prompt:
                md = vm.ask(data_url, prompt, max_tokens=max_tokens)
            else:
                md = vm.ocr_md(data_url, max_tokens=max_tokens)
            mdA_list.append({"filename": os.path.basename(str(p)), "markdown": md or ""})

        basename = _dt.datetime.now().strftime("vision_%Y%m%d_%H%M%S")
        markdown = "\n\n".join(m["markdown"] for m in mdA_list if m["markdown"])
        api_result = {
            "basename": basename,
            "markdown": markdown,
            "pages": [],      # 视觉直出无 layout_dets
            "images": {},
        }
        out_dir = output_dir or os.path.dirname(os.path.abspath(str(image_paths[0])))
        hmd_path = cls.save_hmd(api_result, mdA_list, out_dir)
        logger.info("VISION_OVERRIDE 转换完成: %d 页 → %s", len(mdA_list), hmd_path)
        return {"basename": basename, "hmd_path": hmd_path,
                "pages": len(mdA_list), "markdown": markdown}

    @staticmethod
    def read_hmd(hmd_path: str) -> dict:
        """
        解包 .hmd 文件，返回结构化数据供 AI 读取。

        :return: {mda, mdb, json, images: [{filename, data_url}]}
        """
        mda = ""
        mdb = ""
        json_data = {}
        images = []

        with zipfile.ZipFile(hmd_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".mdA"):
                    mda = zf.read(name).decode("utf-8")
                elif name.endswith(".mdB"):
                    mdb = zf.read(name).decode("utf-8")
                elif name.endswith(".json"):
                    json_data = json.loads(zf.read(name).decode("utf-8"))
                elif name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    raw = zf.read(name)
                    ext = name.rsplit(".", 1)[-1].lower()
                    mime = "png" if ext == "png" else "jpeg" if ext in ("jpg", "jpeg") else ext
                    data_url = f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"
                    images.append({"filename": name, "data_url": data_url})

        return {
            "mda": mda,
            "mdb": mdb,
            "json": json_data,
            "images": images,
        }
