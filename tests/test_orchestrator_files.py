# tests/test_orchestrator_files.py
# The Files API uploader: an image is uploaded once per endpoint, a definite
# refusal is remembered, a network blip is not, and a rejected file reference
# flips the scope back to inline images.

from __future__ import annotations

from pathlib import Path

import pytest

from aicf.infra.orchestrator.files import (
    FilesUploader, file_reference_rejected, references_file, response_status,
)


class FakeCache:
    """The FileIdCache surface, in memory."""

    def __init__(self) -> None:
        self.ids: dict[tuple[str, str], str] = {}
        self.refusals: dict[str, str] = {}

    def get_id(self, scope: str, key: str) -> str:
        return self.ids.get((scope, key), '')

    def set_id(self, scope: str, key: str, file_id: str) -> None:
        self.ids[(scope, key)] = file_id

    def unsupported(self, scope: str) -> bool:
        return scope in self.refusals

    def mark_unsupported(self, scope: str, reason: str) -> None:
        self.refusals[scope] = reason


class FakeSdk:
    """Counts uploads and hands out one id per call."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_with = fail_with
        self.next_id = 'file-1'

    def _upload(self, upload, **kwargs) -> str:
        name, payload, media_type = upload
        self.calls.append((name, media_type))
        if self.fail_with is not None:
            raise self.fail_with
        self.next_id = f'file-{len(self.calls)}'
        return type('Created', (), {'id': self.next_id})()


class FakeOpenAI(FakeSdk):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.files = self

    def create(self, *, file, purpose: str) -> str:
        assert purpose == 'vision'
        return self._upload(file)


class FakeAnthropic(FakeSdk):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.files = self

    def upload(self, *, file) -> str:
        return self._upload(file)


@pytest.fixture()
def image(tmp_path) -> Path:
    path = tmp_path / 'shot.png'
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 32)
    return path


def test_an_image_is_uploaded_once(image):
    sdk = FakeOpenAI()
    cache = FakeCache()
    uploader = FilesUploader(sdk, cache, 'prov|host', api='openai')
    first = uploader.file_id(image, 'image/png', image.stat().st_size)
    assert first == 'file-1'
    assert uploader.file_id(image, 'image/png', image.stat().st_size) == first
    assert len(sdk.calls) == 1


def test_a_definite_refusal_is_remembered(image):
    sdk = FakeOpenAI(
        fail_with=type('Err', (Exception,), {'status_code': 404})())
    uploader = FilesUploader(sdk, FakeCache(), 'prov|host', api='openai')
    assert uploader.file_id(image, 'image/png', 10) == ''
    assert uploader.file_id(image, 'image/png', 10) == ''
    assert len(sdk.calls) == 1
    assert uploader.cache.unsupported('prov|host')


def test_a_transient_failure_is_not_remembered(image):
    sdk = FakeOpenAI(
        fail_with=type('Err', (Exception,), {'status_code': 503})())
    uploader = FilesUploader(sdk, FakeCache(), 'prov|host', api='openai')
    assert uploader.file_id(image, 'image/png', 10) == ''
    assert not uploader.cache.unsupported('prov|host')
    assert uploader.file_id(image, 'image/png', 10) == ''
    assert len(sdk.calls) == 2


def test_the_anthropic_route_uploads_without_a_purpose(image):
    sdk = FakeAnthropic()
    uploader = FilesUploader(sdk, FakeCache(), 'prov|host', api='anthropic')
    assert uploader.file_id(image, 'image/png', image.stat().st_size) \
        == 'file-1'
    assert sdk.calls == [('shot.png', 'image/png')]


def test_a_note_reaches_the_warn_sink_once(image):
    sdk = FakeOpenAI(
        fail_with=type('Err', (Exception,), {'status_code': 404})())
    notes: list[str] = []
    uploader = FilesUploader(sdk, FakeCache(), 'prov|host', api='openai',
                             warn=notes.append)
    uploader.file_id(image, 'image/png', 10)
    uploader.file_id(image, 'image/png', 10)
    assert len(notes) == 1


def test_a_rejected_reference_flips_the_scope_inline(image):
    uploader = FilesUploader(FakeOpenAI(), FakeCache(), 'prov|host',
                             api='openai')
    uploader.fallback_inline('file id rejected: 400')
    assert uploader.cache.unsupported('prov|host')
    assert uploader.file_id(image, 'image/png', 10) == ''


def test_reference_helpers():
    request = {'messages': [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'file_id': 'file-9'}}]}]}
    assert references_file(request)
    assert not references_file({'messages': []})
    assert file_reference_rejected(
        type('Err', (Exception,), {'status_code': 422})())
    assert not file_reference_rejected(
        type('Err', (Exception,), {'status_code': 500})())
    assert response_status(type('Err', (Exception,), {'status': 403})()) == 403
    assert response_status(ValueError('x')) == 0
