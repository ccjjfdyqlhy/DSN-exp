#!/usr/bin/env python3
"""生成「双面打印页序标定」PDF（纯矢量文本，不依赖 PIL）。

多张纸时背面那一摞的出纸顺序，与正面一致还是相反，决定了背面该打
2,4,6… 还是 6,4,2…。这个只能实测。

标定卷：4 页，每页一个巨大的 P1/P2/P3/P4。
  第一步：打印奇数页（1,3）→ 两张纸，正面分别是 P1、P3
  第二步：人工翻面后打印偶数页 → 看背面落位
  结论：P1 的背面是 P2 → 页序一致；是 P4 → 背面页序需反转
"""

from __future__ import annotations

import os
import sys

# A4 点值 (1pt = 1/72 inch)
A4_W, A4_H = 595.0, 842.0


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build(out_path: str, labels=("P1", "P2", "P3", "P4")) -> str:
    objects: list[bytes] = [b"", b""]      # 1=Catalog 2=Pages
    page_ids: list[int] = []

    for lab in labels:
        content = (
            f"BT /F1 220 Tf 0 0 0 rg {A4_W/2 - 66} {A4_H/2 - 80} Td ({_esc(lab)}) Tj ET\n"
            f"0.6 w 40 40 {A4_W-80} {A4_H-80} re S\n"
            f"BT /F1 26 Tf 60 {A4_H-120} Td (page label: {_esc(lab)}) Tj ET\n"
        ).encode("latin-1", "replace")
        content_id = len(objects) + 1
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content
                       + b"\nendstream")
        page_id = len(objects) + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (int(A4_W), int(A4_H), len(objects) + 2, content_id))
        # 字体对象放在页面对象之后
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        page_ids.append(page_id)

    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (b"<< /Type /Pages /Kids [" + kids
                  + b"] /Count %d >>" % len(page_ids))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for idx, body in enumerate(objects, start=1):
        offsets[idx] = len(out)
        out += b"%d 0 obj\n" % idx + body + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += b"xref\n0 %d\n" % n + b"0000000000 65535 f \n"
    for idx in range(1, n):
        out += b"%010d 00000 n \n" % offsets[idx]
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (n, xref_pos))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(bytes(out))
    return out_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dsn-print/duplex_calibration.pdf"
    p = build(out)
    print(p, os.path.getsize(p), "bytes")
