from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document.inputs import load_document_image, normalize_document_inputs
from utils.media import image_data_url, image_file_data_url, image_mime_type


def test_image_helpers_preserve_mime_type_and_data(tmp_path):
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"image-bytes")

    assert image_mime_type(image) == "image/jpeg"
    assert image_data_url(b"image-bytes", "image/jpeg") == "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="
    assert image_file_data_url(image) == "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="


def test_document_input_normalization_supports_paths_and_scanner_records(tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-data")

    normalized = normalize_document_inputs([
        str(image),
        {"filename": "copy.png", "filepath": str(image), "size": 999},
        42,
    ])

    assert len(normalized) == 2
    assert normalized[0]["filename"] == "page.png"
    assert normalized[0]["size"] == len(b"png-data")
    assert normalized[1]["size"] == 999
    filename, filepath, data_url = load_document_image(normalized[0])
    assert filename == "page.png"
    assert filepath == str(image)
    assert data_url == "data:image/png;base64,cG5nLWRhdGE="
