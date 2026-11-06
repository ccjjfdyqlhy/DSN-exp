
# infra/finetune/gguf.py
# GGUF 元数据读取（**容错**：遇到私有量化类型不抛异常）。
#
# 为什么不用上游 gguf-py：
#   Bonsai-2 的 PQ2_0 权重用的 type id 是 142，越过了上游 GGML_TYPE_COUNT（本地 llama.cpp
#   的 ggml.h 里是 43）。上游 gguf-py 读到它会直接抛
#   ValueError: 142 is not a valid GGMLQuantizationType —— 这条已在实测中确认。
#   而「读元数据」是我们自己要的最小能力，所以这里自带一个只读头部的解析器：
#   它把未知 type id 当成「私有类型」记录下来，而不是当成错误。
#
# 另外：上游 llama.cpp 拒绝加载越过 GGML_TYPE_COUNT 的类型，
# 所以「能不能被上游加载」这件事可以用本模块的元数据直接判断，
# 不必真的去跑一次 llama-server（省一次 7.2GB 的读盘）。
#
# 本模块不 import numpy / torch，纯标准库。

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Optional

logger = logging.getLogger("infra.finetune.gguf")

#: 上游 ggml 的 GGML_TYPE_COUNT（本地 llama.cpp ggml.h 的实测值）。
#: type id >= 该值即"越过上游边界"，上游 llama.cpp / gguf-py 都会拒绝。
UPSTREAM_TYPE_COUNT = 43

#: GGUF metadata value 类型编号。
_GGUF_TYPE_UINT8 = 0
_GGUF_TYPE_INT8 = 1
_GGUF_TYPE_UINT16 = 2
_GGUF_TYPE_INT16 = 3
_GGUF_TYPE_UINT32 = 4
_GGUF_TYPE_INT32 = 5
_GGUF_TYPE_FLOAT32 = 6
_GGUF_TYPE_BOOL = 7
_GGUF_TYPE_STRING = 8
_GGUF_TYPE_ARRAY = 9
_GGUF_TYPE_UINT64 = 10
_GGUF_TYPE_INT64 = 11
_GGUF_TYPE_FLOAT64 = 12

#: **张量**量化类型 id → 名字（对齐上游 ggml.h 的 GGML_TYPE_* 枚举）。
#: 注意 6/7/8/9 的顺序容易记错：Q5_0=6、Q5_1=7、Q8_0=8、Q8_1=9。
TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1",
    8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K",
    14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS", 17: "IQ2_XS", 18: "IQ3_XXS",
    19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS",
    24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64", 29: "IQ1_M",
    30: "BF16", 34: "TQ1_0", 35: "TQ2_0", 39: "MXFP4", 40: "NVFP4",
    41: "Q1_0", 42: "Q2_0",
}

#: **文件级**量化类型 id → 名字（对齐上游 llama.h 的 LLAMA_FTYPE_* 枚举）。
#: 这套编号与张量类型编号是两套独立的枚举，混用会得到错误结论——
#: 例如 general.file_type=15 在张量枚举里是 Q8_K，在文件枚举里才是 Q4_K_M。
FILE_TYPE_NAMES = {
    0: "ALL_F32", 1: "MOSTLY_F16", 2: "MOSTLY_Q4_0", 3: "MOSTLY_Q4_1",
    7: "MOSTLY_Q8_0", 8: "MOSTLY_Q5_0", 9: "MOSTLY_Q5_1", 10: "MOSTLY_Q2_K",
    11: "MOSTLY_Q3_K_S", 12: "MOSTLY_Q3_K_M", 13: "MOSTLY_Q3_K_L",
    14: "MOSTLY_Q4_K_S", 15: "MOSTLY_Q4_K_M", 16: "MOSTLY_Q5_K_S",
    17: "MOSTLY_Q5_K_M", 18: "MOSTLY_Q6_K", 19: "MOSTLY_IQ2_XXS",
    20: "MOSTLY_IQ2_XS", 21: "MOSTLY_Q2_K_S", 22: "MOSTLY_IQ3_XS",
    23: "MOSTLY_IQ3_XXS", 24: "MOSTLY_IQ1_S", 25: "MOSTLY_IQ4_NL",
    26: "MOSTLY_IQ3_S", 27: "MOSTLY_IQ3_M", 28: "MOSTLY_IQ2_S",
    29: "MOSTLY_IQ2_M",
}


class GGUFError(Exception):
    """GGUF 文件结构异常（不是"未知量化类型"——那类要容错，不该抛）。"""


@dataclass(slots=True)
class TensorInfo:
    name: str
    shape: tuple[int, ...]
    type_id: int

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type_id, f"type_{self.type_id}")


@dataclass(slots=True)
class GGUFMeta:
    """GGUF 文件头部的元数据。"""

    path: str
    version: int = 0
    tensor_count: int = 0
    kv: dict[str, Any] = field(default_factory=dict)
    tensors: list[TensorInfo] = field(default_factory=list)

    @property
    def architecture(self) -> str:
        return str(self.kv.get("general.architecture", ""))

    @property
    def name(self) -> str:
        return str(self.kv.get("general.name", ""))

    @property
    def file_type(self) -> int:
        return int(self.kv.get("general.file_type", -1))

    @property
    def file_type_name(self) -> str:
        return FILE_TYPE_NAMES.get(self.file_type, f"ftype_{self.file_type}")

    @property
    def unknown_type_ids(self) -> set[int]:
        """文件里出现过的、上游不认识的**张量**量化类型 id。

        这才是"上游能不能加载"的真正判据：
        general.file_type 走的是另一套 LLAMA_FTYPE_* 编号，不能拿它跟
        GGML_TYPE_COUNT 比。
        """
        return {t.type_id for t in self.tensors if t.type_id >= UPSTREAM_TYPE_COUNT}

    def upstream_compatible(self) -> tuple[bool, list[str]]:
        """能否被上游 llama.cpp 加载。返回 (是否兼容, 原因列表)。

        实测结论：Bonsai-2 的 PQ2_0（张量 type id 141/142）在这里就会被判为不兼容，
        与上游 `ValueError: 142 is not a valid GGMLQuantizationType` 的表现一致，
        而且**不需要真的去加载 7.2GB 权重**。
        """
        reasons: list[str] = []
        unknown = sorted(self.unknown_type_ids)
        if unknown:
            reasons.append(
                f"存在越过上游 GGML_TYPE_COUNT({UPSTREAM_TYPE_COUNT}) 的私有量化类型: "
                + ", ".join(f"{t}({TYPE_NAMES.get(t, '未知')})" for t in unknown)
            )
        if self.file_type not in FILE_TYPE_NAMES and self.file_type >= 0:
            reasons.append(f"文件级量化类型 {self.file_type} 不在上游 LLAMA_FTYPE 枚举内")
        return (not reasons, reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "version": self.version,
            "architecture": self.architecture,
            "name": self.name,
            "file_type": self.file_type,
            "file_type_name": self.file_type_name,
            "tensor_count": self.tensor_count,
            "unknown_type_ids": sorted(self.unknown_type_ids),
            "upstream_compatible": self.upstream_compatible()[0],
            "kv": dict(self.kv),
        }


class _Reader:
    """极简二进制读取器（只读大端 GGUF）。"""

    def __init__(self, fh: BinaryIO):
        self.fh = fh

    def read(self, n: int) -> bytes:
        data = self.fh.read(n)
        if len(data) != n:
            raise GGUFError(f"文件意外结束：需要 {n} 字节，实际 {len(data)}")
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def i8(self) -> int:
        return struct.unpack("<b", self.read(1))[0]

    def i16(self) -> int:
        return struct.unpack("<h", self.read(2))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.read(8))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.read(8))[0]

    def string(self) -> str:
        length = self.u64()
        return self.read(length).decode("utf-8", errors="replace")


def _read_value(r: _Reader, value_type: int) -> Any:
    if value_type == _GGUF_TYPE_UINT8:
        return r.read(1)[0]
    if value_type == _GGUF_TYPE_INT8:
        return r.i8()
    if value_type == _GGUF_TYPE_UINT16:
        return struct.unpack("<H", r.read(2))[0]
    if value_type == _GGUF_TYPE_INT16:
        return r.i16()
    if value_type == _GGUF_TYPE_UINT32:
        return r.u32()
    if value_type == _GGUF_TYPE_INT32:
        return r.i32()
    if value_type == _GGUF_TYPE_FLOAT32:
        return r.f32()
    if value_type == _GGUF_TYPE_BOOL:
        return bool(r.read(1)[0])
    if value_type == _GGUF_TYPE_STRING:
        return r.string()
    if value_type == _GGUF_TYPE_ARRAY:
        # 注意顺序：先读元素类型，再读数量，最后读元素。
        # 早期实现把这两者读反了会直接把数组解析成一团乱码——
        # 这是 GGUF 解析最容易踩的坑，务必保持这个顺序。
        elem_type = r.u32()
        count = r.u64()
        return [_read_value(r, elem_type) for _ in range(count)]
    if value_type == _GGUF_TYPE_UINT64:
        return r.u64()
    if value_type == _GGUF_TYPE_INT64:
        return r.i64()
    if value_type == _GGUF_TYPE_FLOAT64:
        return r.f64()
    raise GGUFError(f"未知的 GGUF value 类型: {value_type}")


def read_meta(path: str | Path) -> GGUFMeta:
    """读取 GGUF 文件头部元数据（不读张量数据）。"""
    p = Path(path).expanduser()
    if not p.exists():
        raise GGUFError(f"文件不存在: {p}")
    with open(p, "rb") as fh:
        magic = fh.read(4)
        if magic != b"GGUF":
            raise GGUFError(f"不是 GGUF 文件（magic={magic!r}）: {p}")
        r = _Reader(fh)
        version = r.u32()
        tensor_count = r.u64()
        kv_count = r.u64()

        kv: dict[str, Any] = {}
        for _ in range(kv_count):
            key = r.string()
            value_type = r.u32()
            kv[key] = _read_value(r, value_type)

        tensors: list[TensorInfo] = []
        for _ in range(tensor_count):
            name = r.string()
            n_dims = r.u32()
            shape = tuple(r.u64() for _ in range(n_dims))
            type_id = r.u32()
            r.u64()  # offset，读取头部时用不上
            tensors.append(TensorInfo(name=name, shape=shape, type_id=type_id))

    return GGUFMeta(
        path=str(p),
        version=version,
        tensor_count=tensor_count,
        kv=kv,
        tensors=tensors,
    )


def describe(path: str | Path) -> dict[str, Any]:
    """便捷函数：读元数据并返回可 JSON 序列化的摘要。"""
    meta = read_meta(path)
    compatible, reasons = meta.upstream_compatible()
    info = meta.to_dict()
    info["incompatible_reasons"] = reasons
    return info
