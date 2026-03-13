"""
Unit tests for ImageUploader.

Tests media type detection, file validation, and upload with mocked HTTP.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from herds_cli.images import ImageUploader


@pytest.fixture
def uploader(mock_api_client, mock_session_manager):
    return ImageUploader(
        api_client=mock_api_client,
        session_manager=mock_session_manager,
    )


def _create_image_file(tmp_path, name="test.jpg", content=b"\xff\xd8\xff"):
    """Create a fake image file and return its path."""
    path = tmp_path / name
    path.write_bytes(content)
    return path


class TestDetectMediaType:
    def test_jpeg(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "photo.jpg")
        assert uploader.detect_media_type(path) == "image/jpeg"

    def test_jpeg_uppercase(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "photo.JPEG")
        assert uploader.detect_media_type(path) == "image/jpeg"

    def test_png(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "photo.png")
        assert uploader.detect_media_type(path) == "image/png"

    def test_webp(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "photo.webp")
        assert uploader.detect_media_type(path) == "image/webp"

    def test_gif(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "photo.gif")
        assert uploader.detect_media_type(path) == "image/gif"

    def test_unsupported_extension_raises(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "document.txt")
        with pytest.raises(ValueError, match="Unsupported"):
            uploader.detect_media_type(path)

    def test_no_extension_raises(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "noext")
        with pytest.raises(ValueError, match="Unsupported"):
            uploader.detect_media_type(path)

    def test_pdf_raises(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "file.pdf")
        with pytest.raises(ValueError):
            uploader.detect_media_type(path)


class TestValidateImageFile:
    def test_valid_image(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "valid.jpg")
        result = uploader.validate_image_file(str(path))
        assert result == path

    def test_missing_file_raises(self, uploader, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            uploader.validate_image_file(str(tmp_path / "nope.jpg"))

    def test_directory_raises(self, uploader, tmp_path):
        with pytest.raises(ValueError, match="not a file"):
            uploader.validate_image_file(str(tmp_path))

    def test_non_image_raises(self, uploader, tmp_path):
        path = _create_image_file(tmp_path, "readme.txt")
        with pytest.raises(ValueError, match="Invalid image file"):
            uploader.validate_image_file(str(path))


class TestUploadImage:
    def _setup_auth_and_response(self, uploader, mock_session_manager, status=200, json_data=None):
        """Set up session auth and mock HTTP response."""
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "fake-token"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        mock_response = MagicMock(status_code=status)
        mock_response.json.return_value = json_data or {"id": "img-001"}
        mock_response.text = ""
        uploader.api_client.session.request.return_value = mock_response
        return mock_response

    def test_upload_success(self, uploader, mock_session_manager, tmp_path):
        _create_image_file(tmp_path, "flyer.jpg")
        self._setup_auth_and_response(
            uploader, mock_session_manager,
            json_data={"id": "img-001", "status": "processing"},
        )

        result = uploader.upload_image(str(tmp_path / "flyer.jpg"), "test@example.com")

        assert result["id"] == "img-001"
        assert result["file_path"] == str(tmp_path / "flyer.jpg")
        assert result["media_type"] == "image/jpeg"

    def test_upload_passes_optional_fields(self, uploader, mock_session_manager, tmp_path):
        _create_image_file(tmp_path, "flyer.jpg")
        self._setup_auth_and_response(uploader, mock_session_manager)

        uploader.upload_image(
            str(tmp_path / "flyer.jpg"),
            "test@example.com",
            timezone="America/New_York",
            alg_version="v3",
            mock_mode=True,
            ocr_text="Some text",
            barcode="12345",
            add_to_calendar=True,
        )

        # Verify the request was made with form data
        call_args = uploader.api_client.session.request.call_args
        data = call_args.kwargs.get("data") or call_args[1].get("data", {})
        assert data["timezone"] == "America/New_York"
        assert data["alg_version"] == "v3"
        assert data["mock_mode"] == "true"
        assert data["ocr_text"] == "Some text"
        assert data["barcode"] == "12345"
        assert data["add_to_calendar"] == "true"

    def test_upload_no_session_raises(self, uploader, tmp_path):
        _create_image_file(tmp_path, "flyer.jpg")
        with pytest.raises(Exception, match="No valid session"):
            uploader.upload_image(str(tmp_path / "flyer.jpg"), "nobody@example.com")

    def test_upload_http_error_raises(self, uploader, mock_session_manager, tmp_path):
        _create_image_file(tmp_path, "flyer.jpg")
        mock_resp = self._setup_auth_and_response(
            uploader, mock_session_manager, status=401,
        )
        mock_resp.json.return_value = {"detail": "Token expired"}

        with pytest.raises(Exception, match="Upload failed.*401.*Token expired"):
            uploader.upload_image(str(tmp_path / "flyer.jpg"), "test@example.com")

    def test_upload_http_error_no_json(self, uploader, mock_session_manager, tmp_path):
        _create_image_file(tmp_path, "flyer.jpg")
        mock_resp = self._setup_auth_and_response(
            uploader, mock_session_manager, status=500,
        )
        mock_resp.json.side_effect = ValueError("no json")
        mock_resp.text = "Internal Server Error"

        with pytest.raises(Exception, match="Upload failed.*500.*Internal Server Error"):
            uploader.upload_image(str(tmp_path / "flyer.jpg"), "test@example.com")

    def test_upload_invalid_file_raises(self, uploader, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            uploader.upload_image(str(tmp_path / "nope.jpg"), "test@example.com")


class TestUploadMultipleImages:
    def test_mixed_results(self, uploader, mock_session_manager, tmp_path):
        good = _create_image_file(tmp_path, "good.jpg")
        bad = tmp_path / "missing.jpg"

        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"id": "img-001"}
        mock_response.text = ""
        uploader.api_client.session.request.return_value = mock_response

        results = uploader.upload_multiple_images(
            [str(good), str(bad)], "test@example.com"
        )

        assert len(results) == 2
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "error"
        assert "missing.jpg" in results[1]["file_path"]
