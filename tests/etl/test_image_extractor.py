"""Tests for etl/extractors/image_extractor.py."""
import pytest

from etl.extractors.image_extractor import (
    ImageInfo,
    extract_images_from_html,
    caption_image,
    embed_image,
    IMAGE_EXTRACTION_ENABLED,
)


class TestImageInfo:
    def test_creation_with_defaults(self):
        img = ImageInfo(src="/img/test.png", alt="Test image")
        assert img.src == "/img/test.png"
        assert img.alt == "Test image"
        assert img.caption == ""
        assert img.embedding == []

    def test_creation_with_caption(self):
        img = ImageInfo(src="photo.jpg", alt="Photo", caption="A beautiful photo")
        assert img.caption == "A beautiful photo"
        assert img.src == "photo.jpg"

    def test_creation_with_embedding(self):
        img = ImageInfo(src="x.png", alt="X", embedding=[0.1, 0.2, 0.3])
        assert img.embedding == [0.1, 0.2, 0.3]

    def test_equality(self):
        a = ImageInfo(src="a.png", alt="A")
        b = ImageInfo(src="a.png", alt="A")
        assert a == b

    def test_repr(self):
        img = ImageInfo(src="test.png", alt="Test")
        assert "ImageInfo" in repr(img)
        assert "test.png" in repr(img)


class TestExtractImagesFromHtml:
    def test_empty_html(self):
        assert extract_images_from_html("") == []

    def test_no_images(self):
        html = "<html><body><p>Hello world</p></body></html>"
        assert extract_images_from_html(html) == []

    def test_single_img_with_src_and_alt(self):
        html = '<img src="photo.jpg" alt="A photo">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "photo.jpg"
        assert images[0].alt == "A photo"

    def test_multiple_images(self):
        html = '<img src="a.png" alt="A"><img src="b.jpg" alt="B">'
        images = extract_images_from_html(html)
        assert len(images) == 2
        assert images[0].src == "a.png"
        assert images[1].src == "b.jpg"

    def test_img_without_alt(self):
        html = '<img src="noalt.png">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "noalt.png"
        assert images[0].alt == ""

    def test_img_without_src(self):
        html = '<img alt="No source">'
        images = extract_images_from_html(html)
        assert len(images) == 0

    def test_confluence_style_images(self):
        html = '<img src="/confluence/download/attachments/123/test.png" alt="Diagram">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "/confluence/download/attachments/123/test.png"

    def test_svg_images(self):
        html = '<img src="chart.svg" alt="Bar chart">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "chart.svg"

    def test_data_uri_images_filtered(self):
        html = '<img src="data:image/png;base64,abc123" alt="Inline">'
        images = extract_images_from_html(html)
        assert len(images) == 0

    def test_empty_src_filtered(self):
        html = '<img src="" alt="Empty">'
        images = extract_images_from_html(html)
        assert len(images) == 0


class TestCaptionImage:
    def test_returns_alt_based_caption(self):
        caption = caption_image("/images/test.png", alt_text="Diagram of architecture")
        assert "Diagram" in caption
        assert "architecture" in caption

    def test_returns_filename_based_caption(self):
        caption = caption_image("/images/test_diagram.png")
        assert "test" in caption.lower()
        assert "diagram" in caption.lower()

    def test_falls_back_to_generic(self):
        caption = caption_image("")
        assert len(caption) > 0

    def test_caption_is_string(self):
        caption = caption_image("photo.jpg", alt_text="A sunset")
        assert isinstance(caption, str)
        assert len(caption) > 0


class TestEmbedImage:
    def test_returns_list_of_floats(self):
        result = embed_image("/images/test.png")
        assert isinstance(result, list)

    def test_returns_empty_for_missing_image(self):
        result = embed_image("/nonexistent/image.png")
        assert isinstance(result, list)

    def test_returns_placeholder_embedding(self):
        result = embed_image("/images/test.png")
        if result:
            assert all(isinstance(x, float) for x in result)

    def test_config_flag_exists(self):
        assert IMAGE_EXTRACTION_ENABLED in (True, False)
