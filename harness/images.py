# harness/images.py
# Image references for conversations: markers, on-disk storage, wire helpers.
#
# Images referenced from a conversation live as files and are named by a tiny
# "[image: path]" marker.  A wire adapter turns a marker into a native image
# part only while a request is being built, so base64 never enters the stored
# message history, the session JSON or the token estimates.  Clipboard capture
# stays app-side and is not part of the core.

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The marker is the only thing stored in a message.  It survives sessions,
# rewind, fork and compaction because it is plain text.
MARKER_RE = re.compile(r'\[image:\s*([^\[\]\r\n]+?)\s*\]')

# Providers bill an image by its area, not by the marker's character count.
# A fixed estimate keeps the automatic compaction honest for typical screenshots.
IMAGE_TOKEN_ESTIMATE = 1_200
# The Messages API accepts at most 5 MB per image, so a file that passes this
# check is safe for every wire.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
SUPPORTED_MEDIA = ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
_MEDIA_EXTENSIONS = {
    'image/png': '.png', 'image/jpeg': '.jpg',
    'image/gif': '.gif', 'image/webp': '.webp',
}


def image_marker(reference: str) -> str:
    return f'[image: {str(reference).replace(os.sep, "/")}]'


def has_image_marker(text: str) -> bool:
    return bool(MARKER_RE.search(text))


def count_image_markers(text: str) -> int:
    return len(MARKER_RE.findall(text))


def estimate_marker_charge(text: str) -> int:
    """Token charge for the image markers in a text (the estimate is fixed)."""
    return IMAGE_TOKEN_ESTIMATE * count_image_markers(text)


def strip_image_markers(text: str, replacement: str = '') -> str:
    return MARKER_RE.sub(replacement, text)


def summarize_image_markers(text: str) -> str:
    """Shorten markers for display: only the file name stays readable."""
    def shorten(match: re.Match[str]) -> str:
        reference = match.group(1).strip()
        if reference.startswith(('http://', 'https://')):
            return f'[image: {reference}]'
        return f'[image: {reference.rsplit("/", 1)[-1]}]'

    return MARKER_RE.sub(shorten, text)


def iter_segments(text: str) -> list[tuple[str, str]]:
    """Split a message into ('text', chunk) and ('image', reference) parts."""
    segments: list[tuple[str, str]] = []
    position = 0
    for match in MARKER_RE.finditer(text):
        if match.start() > position:
            segments.append(('text', text[position:match.start()]))
        segments.append(('image', match.group(1).strip()))
        position = match.end()
    if position < len(text):
        segments.append(('text', text[position:]))
    return segments


def is_image_url(reference: str) -> bool:
    """True for an http(s) URL that names an image file."""
    value = reference.strip().strip('"\'').lower()
    if not value.startswith(('http://', 'https://')):
        return False
    path = value.split('?', 1)[0].split('#', 1)[0]
    return path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))


def sniff_media_type(data: bytes) -> str | None:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def image_info(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) read from the header, or None."""
    media_type = sniff_media_type(data)
    try:
        if media_type == 'image/png' and len(data) >= 24:
            return struct.unpack('>II', data[16:24])
        if media_type == 'image/gif' and len(data) >= 10:
            return struct.unpack('<HH', data[6:10])
        if media_type == 'image/jpeg':
            return _jpeg_size(data)
        if media_type == 'image/webp':
            return _webp_size(data)
    except (struct.error, IndexError):
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index, length = 2, len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        size = struct.unpack('>H', data[index + 2:index + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack('>HH', data[index + 5:index + 9])
            return (width, height)
        index += 2 + size
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 25:
        return None
    kind = data[12:16]
    if kind == b'VP8 ':
        if len(data) < 30 or data[23:26] != b'\x9d\x01\x2a':
            return None
        width, height = struct.unpack('<HH', data[26:30])
        return (width & 0x3FFF, height & 0x3FFF)
    if kind == b'VP8L':
        if data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], 'little')
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if kind == b'VP8X' and len(data) >= 30:
        return (int.from_bytes(data[24:27], 'little') + 1,
                int.from_bytes(data[27:30], 'little') + 1)
    return None


@dataclass(frozen=True)
class ImageRef:
    """One resolved image: a local file or a remote URL."""

    reference: str
    path: Path | None = None
    url: str = ''
    media_type: str = ''
    size: int = 0


def resolve_image(reference: str, base_dir: str = '') -> ImageRef | None:
    """Resolve a marker path against the workspace, or accept an http(s) URL."""
    raw = reference.strip().strip('"\'')
    if not raw:
        return None
    if raw.startswith(('http://', 'https://')):
        return ImageRef(reference=raw, url=raw)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(base_dir or os.getcwd()) / path
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        with path.open('rb') as stream:
            head = stream.read(16)
    except OSError:
        return None
    media_type = sniff_media_type(head)
    if media_type not in SUPPORTED_MEDIA or size > MAX_IMAGE_BYTES:
        return None
    return ImageRef(reference=reference, path=path, media_type=media_type, size=size)


def data_url(ref: ImageRef) -> str:
    """Inline image URL, built at request time and thrown away afterwards."""
    if ref.url:
        return ref.url
    data = ref.path.read_bytes() if ref.path is not None else b''
    encoded = base64.b64encode(data).decode('ascii')
    return f'data:{ref.media_type};base64,{encoded}'


def anthropic_source(ref: ImageRef, file_id: str = '') -> dict[str, object]:
    """Anthropic image source.

    A file uploaded to the Files API is referenced by id, so the request body
    stays tiny.  Otherwise the SDK is handed the ``Path`` and reads and encodes
    the bytes while serializing, so the engine never holds base64 itself.
    """
    if ref.url:
        return {'type': 'url', 'url': ref.url}
    if file_id:
        return {'type': 'file', 'file_id': file_id}
    return {
        'type': 'base64',
        'media_type': ref.media_type,
        'data': ref.path,
    }


class FileIdCache:
    """Provider-scoped file ids issued by a provider's Files API.

    Uploading is a network round trip, so ids are remembered on disk keyed by
    the local image and the provider endpoint.  A provider that rejects the
    upload is remembered too, so every later request does not retry it.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _entry(self, scope: str) -> dict[str, Any]:
        entry = self._data.get(scope)
        if not isinstance(entry, dict):
            entry = {}
            self._data[scope] = entry
        files = entry.get('files')
        if not isinstance(files, dict):
            entry['files'] = {}
        return entry

    def get_id(self, scope: str, key: str) -> str:
        with self._lock:
            value = self._entry(scope)['files'].get(key)
            return str(value) if value else ''

    def set_id(self, scope: str, key: str, file_id: str) -> None:
        if not file_id:
            return
        with self._lock:
            self._entry(scope)['files'][key] = file_id
            self._save()

    def unsupported(self, scope: str) -> bool:
        with self._lock:
            return bool(self._entry(scope).get('unsupported'))

    def mark_unsupported(self, scope: str, reason: str = '') -> None:
        with self._lock:
            entry = self._entry(scope)
            if entry.get('unsupported'):
                return
            entry['unsupported'] = True
            if reason:
                entry['reason'] = reason[:200]
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(f'.{self.path.name}.tmp')
            temp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                            encoding='utf-8')
            os.replace(temp, self.path)
        except OSError:
            pass


class ImageStore:
    """Content-addressed image files under the session directory."""

    def __init__(self, directory: str | os.PathLike[str],
                 base_dir: str | os.PathLike[str] | None = None) -> None:
        self.directory = Path(directory)
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()

    def save(self, data: bytes, prefix: str = 'paste') -> str:
        media_type = sniff_media_type(data)
        if media_type is None:
            raise ValueError('the payload does not contain a supported image')
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(
                f'image is {len(data) / 1_048_576:.1f} MB; the limit is '
                f'{MAX_IMAGE_BYTES // 1_048_576} MB')
        digest = hashlib.sha256(data).hexdigest()[:12]
        path = self.directory / f'{prefix}-{digest}{_MEDIA_EXTENSIONS[media_type]}'
        if not path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f'.{path.name}.tmp')
            try:
                temp.write_bytes(data)
                os.replace(temp, path)
            finally:
                if temp.exists():
                    temp.unlink()
        return self._relative(path)

    def _relative(self, path: Path) -> str:
        try:
            relative = os.path.relpath(path, self.base_dir)
        except ValueError:
            relative = str(path)
        return relative.replace(os.sep, '/')
