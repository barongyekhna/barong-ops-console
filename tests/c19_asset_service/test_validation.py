from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject

from c19_asset_service.validation import (
    ContentValidationError,
    ValidationLimits,
    atomic_promote,
    validate_content,
)


def _image(path, image_format="PNG", *, size=(32, 24), frames=1):
    images = [Image.new("RGBA", size, (index * 20, 20, 30, 255)) for index in range(frames)]
    if frames > 1:
        images[0].save(
            path,
            format="GIF",
            save_all=True,
            append_images=images[1:],
            duration=50,
            loop=0,
        )
    else:
        image = images[0]
        if image_format == "JPEG":
            image = image.convert("RGB")
        image.save(path, format=image_format)


@pytest.mark.parametrize(
    ("image_format", "filename", "media_type"),
    [
        ("JPEG", "photo.jpg", "image/jpeg"),
        ("PNG", "photo.png", "image/png"),
        ("WEBP", "photo.webp", "image/webp"),
        ("GIF", "photo.gif", "image/gif"),
    ],
)
def test_supported_images_fully_decode_and_reencode_safe_thumbnail(
    tmp_path, image_format, filename, media_type
):
    source = tmp_path / filename
    thumbnail = tmp_path / "thumbnail.png"
    _image(source, image_format)
    result = validate_content(
        source,
        kind="image",
        filename=filename,
        declared_media_type=media_type,
        limits=ValidationLimits(),
        thumbnail_path=thumbnail,
    )
    assert result.media_type == media_type
    assert result.thumbnail_media_type == "image/png"
    assert result.thumbnail_size_bytes == thumbnail.stat().st_size
    with Image.open(thumbnail) as image:
        assert image.format == "PNG"
        assert image.width <= 512 and image.height <= 512
        assert not image.getexif()


def test_thumbnail_strips_exif_icc_and_png_text_metadata(tmp_path):
    source = tmp_path / "metadata.png"
    thumbnail = tmp_path / "metadata-thumbnail.png"
    text_metadata = PngInfo()
    text_metadata.add_text("Comment", "must not survive")
    exif = Image.Exif()
    exif[315] = "private author"
    Image.new("RGB", (24, 16), (12, 34, 56)).save(
        source,
        format="PNG",
        pnginfo=text_metadata,
        exif=exif,
        icc_profile=b"private fake profile",
    )
    with Image.open(source) as original:
        assert original.info.get("Comment") == "must not survive"
        assert original.info.get("icc_profile")
        assert original.getexif()

    validate_content(
        source,
        kind="image",
        filename="metadata.png",
        declared_media_type="image/png",
        limits=ValidationLimits(),
        thumbnail_path=thumbnail,
    )
    with Image.open(thumbnail) as safe:
        safe.load()
        assert not safe.getexif()
        assert "Comment" not in safe.info
        assert "icc_profile" not in safe.info
        assert not getattr(safe, "text", {})


def test_image_mime_dimension_frame_and_truncation_limits(tmp_path):
    source = tmp_path / "photo.png"
    _image(source, "PNG", size=(20, 20))
    with pytest.raises(ContentValidationError):
        validate_content(
            source,
            kind="image",
            filename="photo.jpg",
            declared_media_type="image/jpeg",
            limits=ValidationLimits(),
            thumbnail_path=tmp_path / "mismatch.png",
        )
    with pytest.raises(ContentValidationError):
        validate_content(
            source,
            kind="image",
            filename="photo.png",
            declared_media_type="image/png",
            limits=ValidationLimits(image_max_pixels=100),
            thumbnail_path=tmp_path / "large.png",
        )
    animated = tmp_path / "animated.gif"
    _image(animated, "GIF", frames=2)
    with pytest.raises(ContentValidationError):
        validate_content(
            animated,
            kind="image",
            filename="animated.gif",
            declared_media_type="image/gif",
            limits=ValidationLimits(image_max_frames=1),
            thumbnail_path=tmp_path / "animated-thumb.png",
        )
    with pytest.raises(ContentValidationError):
        validate_content(
            animated,
            kind="image",
            filename="animated.gif",
            declared_media_type="image/gif",
            limits=ValidationLimits(
                image_max_frames=10, image_max_total_frame_pixels=500
            ),
            thumbnail_path=tmp_path / "animated-budget-thumb.png",
        )
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(source.read_bytes()[:-8])
    with pytest.raises(ContentValidationError):
        validate_content(
            corrupt,
            kind="image",
            filename="corrupt.png",
            declared_media_type="image/png",
            limits=ValidationLimits(),
            thumbnail_path=tmp_path / "corrupt-thumb.png",
        )


def _write_zip(path, members, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, body in members:
            archive.writestr(name, body)


def _ooxml_members(extension):
    content_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    }
    main_parts = {
        ".docx": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".pptx": "ppt/presentation.xml",
    }
    main_xml = {
        ".docx": (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body/></w:document>'
        ),
        ".xlsx": (
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"/>'
        ),
        ".pptx": (
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
            'presentationml/2006/main"/>'
        ),
    }
    main_part = main_parts[extension]
    return [
        (
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                f'<Override PartName="/{main_part}" ContentType="{content_types[extension]}"/>'
                "</Types>"
            ),
        ),
        (
            "_rels/.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                f'Target="{main_part}"/>'
                "</Relationships>"
            ),
        ),
        (main_part, main_xml[extension]),
    ]


def _write_pdf(path, *, javascript=False, attachment=False, encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if javascript:
        writer.add_js("app.alert('blocked')")
    if attachment:
        writer.add_attachment("payload.txt", b"embedded")
    if encrypted:
        writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)


def _write_pdf_with_nested_active_object(path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer._root_object[NameObject("/PrivateContainer")] = DictionaryObject(
        {
            NameObject("/Nested"): DictionaryObject(
                {NameObject("/AA"): DictionaryObject()}
            )
        }
    )
    with path.open("wb") as output:
        writer.write(output)


def test_generic_zip_forces_path_member_and_bomb_limits(tmp_path):
    safe = tmp_path / "safe.zip"
    _write_zip(safe, [("folder/report.txt", "hello")])
    result = validate_content(
        safe,
        kind="file",
        filename="safe.zip",
        declared_media_type="application/zip",
        limits=ValidationLimits(),
    )
    assert result.size_bytes == safe.stat().st_size
    traversal = tmp_path / "traversal.zip"
    _write_zip(traversal, [("../escape.txt", "bad")])
    with pytest.raises(ContentValidationError):
        validate_content(
            traversal,
            kind="file",
            filename="traversal.zip",
            declared_media_type="application/zip",
            limits=ValidationLimits(),
        )
    executable = tmp_path / "executable.zip"
    _write_zip(executable, [("payload.js", "alert(1)")])
    with pytest.raises(ContentValidationError):
        validate_content(
            executable,
            kind="file",
            filename="executable.zip",
            declared_media_type="application/zip",
            limits=ValidationLimits(),
        )
    for member_name, body in (
        ("extensionless", b"\x7fELF" + b"\x00" * 16),
        ("payload.exe.", b"ordinary-looking"),
        ("nested.docx", b"PK\x03\x04nested-package"),
        ("nested-without-extension", b"PK\x03\x04nested-package"),
        ("script", b"#!/bin/sh\nexit 0\n"),
    ):
        disguised = tmp_path / f"disguised-{member_name.replace('.', '-')}.zip"
        _write_zip(disguised, [(member_name, body)])
        with pytest.raises(ContentValidationError):
            validate_content(
                disguised,
                kind="file",
                filename="disguised.zip",
                declared_media_type="application/zip",
                limits=ValidationLimits(),
            )
    bomb = tmp_path / "bomb.zip"
    _write_zip(bomb, [("zeros.txt", b"0" * 100_000)])
    with pytest.raises(ContentValidationError):
        validate_content(
            bomb,
            kind="file",
            filename="bomb.zip",
            declared_media_type="application/zip",
            limits=ValidationLimits(archive_max_ratio=2),
        )
    with pytest.raises(ContentValidationError):
        validate_content(
            safe,
            kind="file",
            filename="safe.zip",
            declared_media_type="application/zip",
            limits=ValidationLimits(archive_max_unpacked_bytes=2),
        )


def test_encrypted_zip_flag_is_rejected(tmp_path):
    path = tmp_path / "encrypted.zip"
    _write_zip(path, [("notes.txt", "hello")], compression=zipfile.ZIP_STORED)
    payload = bytearray(path.read_bytes())
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    payload[local + 6 : local + 8] = (1).to_bytes(2, "little")
    payload[central + 8 : central + 10] = (1).to_bytes(2, "little")
    path.write_bytes(payload)
    with pytest.raises(ContentValidationError):
        validate_content(
            path,
            kind="file",
            filename="encrypted.zip",
            declared_media_type="application/zip",
            limits=ValidationLimits(),
        )


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        (
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_ooxml_family_is_structurally_parsed(tmp_path, filename, media_type):
    path = tmp_path / filename
    _write_zip(path, _ooxml_members(path.suffix))
    assert validate_content(
        path,
        kind="file",
        filename=filename,
        declared_media_type=media_type,
        limits=ValidationLimits(),
    ).media_type == media_type


def test_macro_and_embedded_ooxml_are_rejected(tmp_path):
    for member in ("word/vbaProject.bin", "word/embeddings/object.bin", "word/activeX/a.xml"):
        path = tmp_path / (member.replace("/", "_") + ".docx")
        _write_zip(path, [*_ooxml_members(".docx"), (member, b"active")])
        with pytest.raises(ContentValidationError):
            validate_content(
                path,
                kind="file",
                filename="document.docx",
                declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                limits=ValidationLimits(),
            )


CORE_PROPERTIES_TYPE = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)


def _members_with_root_relationship(extension, relationship_type, target, extra_part=None):
    """Fixture members as saved by real Office: root rels carry docProps links."""
    main_part = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml"}[extension]
    members = []
    for name, body in _ooxml_members(extension):
        if name == "_rels/.rels":
            body = body.replace(
                "</Relationships>",
                f'<Relationship Id="rId2" Type="{relationship_type}" Target="{target}"/>'
                "</Relationships>",
            )
        members.append((name, body))
    if extra_part is not None:
        members.append(extra_part)
    assert main_part in {name for name, _ in members}
    return members


@pytest.mark.parametrize(
    ("extension", "media_type"),
    [
        (
            ".docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_real_office_core_properties_relationship_is_accepted(
    tmp_path, extension, media_type
):
    # Every genuine Excel/Word save carries this relationship; its Type URI
    # contains "/package/" and must not be mistaken for an embedded package.
    filename = f"office{extension}"
    path = tmp_path / filename
    core_xml = (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
        'metadata/core-properties"/>'
    )
    _write_zip(
        path,
        _members_with_root_relationship(
            extension,
            CORE_PROPERTIES_TYPE,
            "docProps/core.xml",
            extra_part=("docProps/core.xml", core_xml),
        ),
    )
    assert (
        validate_content(
            path,
            kind="file",
            filename=filename,
            declared_media_type=media_type,
            limits=ValidationLimits(),
        ).media_type
        == media_type
    )


@pytest.mark.parametrize(
    "relationship_type",
    [
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/vbaProject",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/control",
    ],
)
def test_embedded_and_active_relationship_names_are_still_rejected(
    tmp_path, relationship_type
):
    path = tmp_path / "active.docx"
    _write_zip(
        path,
        _members_with_root_relationship(
            ".docx",
            relationship_type,
            "word/media/payload.bin",
            extra_part=("word/media/payload.bin", b"payload"),
        ),
    )
    with pytest.raises(ContentValidationError):
        validate_content(
            path,
            kind="file",
            filename="active.docx",
            declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            limits=ValidationLimits(),
        )


def _external_rels(relationship_type, target, part="word/_rels/document.xml.rels"):
    return (
        part,
        (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId9" Type="{relationship_type}" '
            f'Target="{target}" TargetMode="External"/>'
            "</Relationships>"
        ),
    )


HYPERLINK_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
IMAGE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


@pytest.mark.parametrize(
    "target",
    [
        "https://example.invalid/",
        "http://example.invalid/path?x=1&amp;y=%E4%B8%AD#frag",
        "mailto:buyer@example.invalid",
        "HTTPS://Example.invalid/Upper",
    ],
)
@pytest.mark.parametrize(
    ("extension", "part", "media_type"),
    [
        (
            ".docx",
            "word/_rels/document.xml.rels",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            ".xlsx",
            "xl/worksheets/_rels/sheet1.xml.rels",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_ooxml_external_web_hyperlinks_are_inert_and_accepted(
    tmp_path, target, extension, part, media_type
):
    # A product-link column in a supplier sheet must not get the file quarantined.
    filename = f"links{extension}"
    path = tmp_path / filename
    members = [*_ooxml_members(extension)]
    if extension == ".xlsx":
        members.append(("xl/worksheets/sheet1.xml", "<worksheet/>"))
    members.append(_external_rels(HYPERLINK_TYPE, target, part))
    _write_zip(path, members)
    assert (
        validate_content(
            path,
            kind="file",
            filename=filename,
            declared_media_type=media_type,
            limits=ValidationLimits(),
        ).media_type
        == media_type
    )


@pytest.mark.parametrize(
    "extra_member",
    [
        _external_rels(HYPERLINK_TYPE, "file:///etc/passwd"),
        _external_rels(HYPERLINK_TYPE, "javascript:alert(1)"),
        _external_rels(HYPERLINK_TYPE, "ftp://example.invalid/"),
        _external_rels(HYPERLINK_TYPE, "//example.invalid/"),
        _external_rels(HYPERLINK_TYPE, "https://example.invalid/&#10;"),
        _external_rels(HYPERLINK_TYPE, "https://" + "a" * 5000),
        _external_rels(IMAGE_TYPE, "https://example.invalid/tracker.png"),
        _external_rels(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate",
            "https://example.invalid/template.dotm",
        ),
        (
            "word/extra.xml",
            '<!DOCTYPE x [<!ENTITY payload "boom">]><x>&payload;</x>',
        ),
        ("word/broken.xml", "<broken>"),
    ],
)
def test_ooxml_external_relationship_dtd_and_parse_failure_are_rejected(
    tmp_path, extra_member
):
    path = tmp_path / "unsafe.docx"
    _write_zip(path, [*_ooxml_members(".docx"), extra_member])
    with pytest.raises(ContentValidationError):
        validate_content(
            path,
            kind="file",
            filename="unsafe.docx",
            declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            limits=ValidationLimits(),
        )


def test_ooxml_requires_real_namespaces_main_part_and_content_type(tmp_path):
    for name, replacement in (
        ("[Content_Types].xml", "<Types><Override/></Types>"),
        ("_rels/.rels", "<Relationships/>"),
        ("word/document.xml", "<document/>") ,
    ):
        path = tmp_path / f"invalid-{name.replace('/', '-')}.docx"
        members = [
            (member_name, replacement if member_name == name else body)
            for member_name, body in _ooxml_members(".docx")
        ]
        _write_zip(path, members)
        with pytest.raises(ContentValidationError):
            validate_content(
                path,
                kind="file",
                filename="invalid.docx",
                declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                limits=ValidationLimits(),
            )


def test_pdf_text_csv_and_active_content_detection(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_pdf(pdf)
    assert validate_content(
        pdf,
        kind="file",
        filename="report.pdf",
        declared_media_type="application/pdf",
        limits=ValidationLimits(),
    ).media_type == "application/pdf"
    for name, options in (
        ("javascript", {"javascript": True}),
        ("attachment", {"attachment": True}),
        ("encrypted", {"encrypted": True}),
    ):
        active_pdf = tmp_path / f"{name}.pdf"
        _write_pdf(active_pdf, **options)
        with pytest.raises(ContentValidationError):
            validate_content(
                active_pdf,
                kind="file",
                filename=active_pdf.name,
                declared_media_type="application/pdf",
                limits=ValidationLimits(),
            )
    nested_active = tmp_path / "nested-active.pdf"
    _write_pdf_with_nested_active_object(nested_active)
    with pytest.raises(ContentValidationError):
        validate_content(
            nested_active,
            kind="file",
            filename="nested-active.pdf",
            declared_media_type="application/pdf",
            limits=ValidationLimits(),
        )
    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"%PDF-1.7\nnot a PDF object graph\n%%EOF\n")
    with pytest.raises(ContentValidationError):
        validate_content(
            malformed,
            kind="file",
            filename="malformed.pdf",
            declared_media_type="application/pdf",
            limits=ValidationLimits(),
        )
    empty = tmp_path / "empty.pdf"
    with empty.open("wb") as output:
        PdfWriter().write(output)
    with pytest.raises(ContentValidationError):
        validate_content(
            empty,
            kind="file",
            filename="empty.pdf",
            declared_media_type="application/pdf",
            limits=ValidationLimits(),
        )
    with pytest.raises(ContentValidationError):
        validate_content(
            pdf,
            kind="file",
            filename="report.pdf",
            declared_media_type="application/pdf",
            limits=ValidationLimits(pdf_max_objects=1),
        )
    text = tmp_path / "notes.txt"
    text.write_text("plain UTF-8 你好\n", encoding="utf-8")
    assert validate_content(
        text,
        kind="file",
        filename="notes.txt",
        declared_media_type="text/plain",
        limits=ValidationLimits(),
    ).media_type == "text/plain"
    html = tmp_path / "html.txt"
    html.write_text("<!doctype html><script>alert(1)</script>", encoding="utf-8")
    with pytest.raises(ContentValidationError):
        validate_content(
            html,
            kind="file",
            filename="html.txt",
            declared_media_type="text/plain",
            limits=ValidationLimits(),
        )
    csv_path = tmp_path / "data.csv"
    csv_path.write_text('name,value\n"A",1\n', encoding="utf-8")
    assert validate_content(
        csv_path,
        kind="file",
        filename="data.csv",
        declared_media_type="text/csv",
        limits=ValidationLimits(),
    ).media_type == "text/csv"


def test_atomic_promote_exposes_complete_copy_and_refuses_overwrite(tmp_path):
    source = tmp_path / "incoming" / "object"
    source.parent.mkdir()
    source.write_bytes(b"durable bytes")
    destination = tmp_path / "active" / "aa" / "object"
    atomic_promote(source, destination)
    assert source.read_bytes() == destination.read_bytes()
    assert not list(destination.parent.glob("*.promoting"))
    with pytest.raises(ContentValidationError):
        atomic_promote(source, destination)
