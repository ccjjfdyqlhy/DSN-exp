# infra/orchestrator/files.py
# Uploads images to a provider's Files API and reuses the issued ids.
#
# An image referenced from a conversation lives on disk; a wire request can
# carry it either inline (base64 in the request body) or as a Files API id.
# The id route keeps the request body tiny, but it costs one upload per
# image and an endpoint may refuse the whole feature.  This module is the
# single place that owns that trade-off:
#   * ids are cached per (endpoint scope, image) so an image is uploaded once,
#   * an endpoint that refuses the upload is remembered, so the first failure
#     costs one request rather than one per turn,
#   * a network blip is not remembered: the next request tries again.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("FilesUploader")

#: statuses a provider uses to refuse an uploaded-file reference; the
#: request can then be rebuilt with the image inline
FILE_ID_REJECTED_STATUSES = frozenset({400, 403, 404, 422})

#: statuses that mean the endpoint has no Files API at all; a 5xx or a
#: network error is transient and is retried on the next request
UPLOAD_UNSUPPORTED_STATUSES = frozenset({400, 401, 403, 404, 405, 415, 501})


def response_status(error: Exception) -> int:
    """The HTTP status an SDK error carries, 0 when it has none."""
    return int(getattr(error, "status_code", 0)
               or getattr(error, "status", 0) or 0)


def references_file(payload: Any) -> bool:
    """True when a built request references an uploaded file by id."""
    if isinstance(payload, dict):
        file_id = payload.get("file_id")
        if isinstance(file_id, str) and file_id:
            return True
        return any(references_file(value) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(references_file(value) for value in payload)
    return False


def file_reference_rejected(error: Exception) -> bool:
    """True for the statuses a provider uses to refuse a file reference."""
    return response_status(error) in FILE_ID_REJECTED_STATUSES


class FilesUploader:
    """Upload images to a provider's Files API and cache the issued ids.

    Args:
        sdk: the raw provider SDK object (``.files.create`` / ``.files.upload``).
        cache: a FileIdCache (harness.images); ids and refusals live there.
        scope: the cache scope, typically ``provider|endpoint-host``.
        api: ``openai`` (``files.create(purpose='vision')``) or ``anthropic``
            (``files.upload``).
        warn: sink for one-time notices about upload fallbacks.
    """

    def __init__(self, sdk: Any, cache: Any, scope: str, *,
                 api: str = "openai",
                 warn: Optional[Callable[[str], None]] = None) -> None:
        self._sdk = sdk
        self.cache = cache
        self.scope = scope
        self._api = api
        self._warn = warn
        self._notes: set[str] = set()

    def file_id(self, path: Path | str, media_type: str, size: int) -> str:
        """The Files API id for an image, uploading it once.

        An endpoint that refuses the upload is remembered in the cache, so
        the first failure costs one request rather than one per turn; the
        caller then falls back to an inline image.
        """
        if self.cache is None or not path:
            return ""
        key = self._file_key(path, size)
        if not key:
            return ""
        # A rejected file reference disables the scope even while ids remain
        # cached: they are only valid until the provider says otherwise.
        if self.cache.unsupported(self.scope):
            return ""
        cached = self.cache.get_id(self.scope, key)
        if cached:
            return cached
        try:
            file_id = self._upload(path, media_type)
        except Exception as error:    # noqa: BLE001 - the refusal is recorded
            self.upload_failed(error)
            return ""
        if not file_id:
            self.upload_failed(None)
            return ""
        self.cache.set_id(self.scope, key, file_id)
        return file_id

    @staticmethod
    def _file_key(path: Path | str, size: int) -> str:
        try:
            resolved = Path(path).resolve()
        except OSError:
            resolved = Path(path)
        return f"{resolved}|{size}"

    def _upload(self, path: Path | str, media_type: str) -> str:
        upload = (Path(path).name, Path(path).read_bytes(), media_type)
        if self._api == "anthropic":
            created = self._sdk.files.upload(file=upload)
        else:
            created = self._sdk.files.create(file=upload, purpose="vision")
        return str(getattr(created, "id", "") or "")

    def upload_failed(self, error: Optional[Exception]) -> None:
        status = response_status(error) if error is not None else 0
        # Only a definite refusal means the endpoint has no Files API; a
        # network blip or a 5xx should be retried on the next request.
        if error is None or status in UPLOAD_UNSUPPORTED_STATUSES:
            if self.cache is not None:
                self.cache.mark_unsupported(
                    self.scope,
                    str(error) if error is not None else "upload rejected")
            self._note(f"Files API unavailable at {self.scope}; "
                       "images are sent inline.")
        else:
            self._note(f"Image upload failed ({error}); "
                       "sending the image inline.")

    def fallback_inline(self, reason: str) -> None:
        """Stop using uploaded file ids after the provider rejected one."""
        if self.cache is not None:
            self.cache.mark_unsupported(self.scope, reason)
        self._note("The provider rejected the uploaded image reference; "
                   "images are sent inline from now on.")

    def _note(self, text: str) -> None:
        if text in self._notes:
            return
        self._notes.add(text)
        logger.warning(text)
        if self._warn is not None:
            try:
                self._warn(text)
            except Exception:    # noqa: BLE001 - a broken sink never raises
                pass
