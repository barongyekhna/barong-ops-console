"""Content validation and safe thumbnail generation for quarantined bytes."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import stat
import struct
import unicodedata
import warnings
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from .schemas import (
    BLOCKED_EXTENSIONS,
    IMAGE_MEDIA_BY_EXTENSION,
    OCTET_STREAM_MEDIA_TYPE,
    expected_media_type,
)


class ContentValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    image_max_pixels: int = 40_000_000
    image_max_dimension: int = 20_000
    image_max_frames: int = 500
    image_max_total_frame_pixels: int = 100_000_000
    archive_max_members: int = 2_000
    archive_max_unpacked_bytes: int = 256 * 1024 * 1024
    archive_max_ratio: int = 200
    thumbnail_max_dimension: int = 512
    thumbnail_max_bytes: int = 2 * 1024 * 1024
    pdf_max_objects: int = 100_000
    pdf_max_pages: int = 10_000
    xml_max_elements: int = 1_000_000


@dataclass(frozen=True, slots=True)
class ValidationResult:
    media_type: str
    size_bytes: int
    sha256_hex: str
    thumbnail_size_bytes: int | None = None
    thumbnail_sha256_hex: str | None = None
    thumbnail_media_type: str | None = None


IMAGE_FORMAT_MEDIA = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}
EXECUTABLE_MAGICS = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xca\xfe\xba\xbf",
    b"\xbe\xba\xfe\xca",
    b"\xbf\xba\xfe\xca",
    b"\x00asm",
)
ARCHIVE_MAGICS = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"BZh",
    b"\xfd7zXZ\x00",
)
# Executables and script hosts are refused both as attachments and as members
# of a ZIP. Everything else inside an archive is left to ClamAV.
FORBIDDEN_ARCHIVE_SUFFIXES = BLOCKED_EXTENSIONS
# Known container signatures for the non-deep-inspected file families. A file
# whose extension is listed here must start with one of the prefixes (offset 0)
# or carry the marker at the given offset; families without a stable signature
# are only checked against the executable magics and ClamAV.
FILE_SIGNATURES: dict[str, tuple[tuple[int, bytes], ...]] = {
    ".mp4": ((4, b"ftyp"),),
    ".m4v": ((4, b"ftyp"),),
    ".mov": ((4, b"ftyp"), (4, b"moov"), (4, b"mdat"), (4, b"wide"), (4, b"free")),
    ".3gp": ((4, b"ftyp"),),
    ".heic": ((4, b"ftyp"),),
    ".heif": ((4, b"ftyp"),),
    ".m4a": ((4, b"ftyp"),),
    ".webm": ((0, b"\x1a\x45\xdf\xa3"),),
    ".mkv": ((0, b"\x1a\x45\xdf\xa3"),),
    ".avi": ((0, b"RIFF"),),
    ".wav": ((0, b"RIFF"),),
    ".wmv": ((0, b"\x30\x26\xb2\x75"),),
    ".wma": ((0, b"\x30\x26\xb2\x75"),),
    ".flv": ((0, b"FLV"),),
    ".mpg": ((0, b"\x00\x00\x01\xba"), (0, b"\x00\x00\x01\xb3")),
    ".mpeg": ((0, b"\x00\x00\x01\xba"), (0, b"\x00\x00\x01\xb3")),
    ".mp3": ((0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2"), (0, b"\xff\xe3")),
    ".flac": ((0, b"fLaC"),),
    ".ogg": ((0, b"OggS"),),
    ".amr": ((0, b"#!AMR"),),
    ".rar": ((0, b"Rar!\x1a\x07"),),
    ".7z": ((0, b"7z\xbc\xaf\x27\x1c"),),
    ".gz": ((0, b"\x1f\x8b"),),
    ".tgz": ((0, b"\x1f\x8b"),),
    ".bz2": ((0, b"BZh"),),
    ".xz": ((0, b"\xfd7zXZ\x00"),),
    ".doc": ((0, b"\xd0\xcf\x11\xe0"), (0, b"{\\rtf"), (0, b"PK\x03\x04")),
    ".xls": ((0, b"\xd0\xcf\x11\xe0"), (0, b"PK\x03\x04")),
    ".ppt": ((0, b"\xd0\xcf\x11\xe0"), (0, b"PK\x03\x04")),
    ".rtf": ((0, b"{\\rtf"),),
    ".odt": ((0, b"PK\x03\x04"),),
    ".ods": ((0, b"PK\x03\x04"),),
    ".odp": ((0, b"PK\x03\x04"),),
    ".psd": ((0, b"8BPS"),),
    ".ai": ((0, b"%PDF"), (0, b"%!PS")),
}

OOXML_CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
OOXML_RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
OOXML_OFFICE_DOCUMENT_RELATIONSHIPS = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
}
OOXML_RELATIONSHIP_TYPE_PREFIXES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/",
    "http://schemas.openxmlformats.org/package/2006/relationships/",
)
# Clickable hyperlinks are the one external relationship an office file may
# carry: Office never fetches them on open, so a 1688/Amazon link column in a
# supplier spreadsheet is inert data. Every other external target (images,
# oleObject, attachedTemplate, externalLink, frames...) is auto-resolved by the
# application and stays rejected.
OOXML_HYPERLINK_RELATIONSHIP_TYPES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink",
    }
)
OOXML_EXTERNAL_HYPERLINK_SCHEMES = ("http://", "https://", "mailto:")
OOXML_EXTERNAL_HYPERLINK_MAX_LENGTH = 4096
OOXML_FAMILY = {
    ".docx": {
        "main_part": "word/document.xml",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "root_tags": {
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document",
            "{http://purl.oclc.org/ooxml/wordprocessingml/main}document",
        },
    },
    ".xlsx": {
        "main_part": "xl/workbook.xml",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "root_tags": {
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
            "{http://purl.oclc.org/ooxml/spreadsheetml/main}workbook",
        },
    },
    ".pptx": {
        "main_part": "ppt/presentation.xml",
        "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "root_tags": {
            "{http://schemas.openxmlformats.org/presentationml/2006/main}presentation",
            "{http://purl.oclc.org/ooxml/presentationml/main}presentation",
        },
    },
}

PDF_FORBIDDEN_KEYS = {
    "/AA",
    "/AF",
    "/AcroForm",
    "/AdditionalActions",
    "/Collection",
    "/EF",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/JS",
    "/JavaScript",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
    "/RichMediaContent",
    "/RichMediaSettings",
    "/URI",
    "/XFA",
}
PDF_FORBIDDEN_NAMES = {
    "/3D",
    "/EmbeddedFile",
    "/FileAttachment",
    "/Filespec",
    "/GoToR",
    "/ImportData",
    "/JavaScript",
    "/Launch",
    "/Movie",
    "/Rendition",
    "/RichMedia",
    "/Sound",
    "/SubmitForm",
    "/URI",
}


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _validate_image(
    path: Path,
    declared_media_type: str,
    limits: ValidationLimits,
    thumbnail_path: Path,
) -> tuple[int, str, str]:
    try:
        _verify_image_container(path, declared_media_type)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image_format = (image.format or "").upper()
                actual_media = IMAGE_FORMAT_MEDIA.get(image_format)
                if actual_media != declared_media_type:
                    raise ContentValidationError("image format mismatch")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > limits.image_max_dimension
                    or height > limits.image_max_dimension
                    or width * height > limits.image_max_pixels
                ):
                    raise ContentValidationError("image dimensions exceed limit")
                frame_count = int(getattr(image, "n_frames", 1))
                if frame_count <= 0 or frame_count > limits.image_max_frames:
                    raise ContentValidationError("image frame count exceeds limit")
                # Loading every frame is intentional; verify() alone does not fully
                # exercise decompression or animated image payloads.
                total_frame_pixels = 0
                for frame in ImageSequence.Iterator(image):
                    frame_width, frame_height = frame.size
                    frame_pixels = frame_width * frame_height
                    if (
                        frame_pixels > limits.image_max_pixels
                        or frame_width > limits.image_max_dimension
                        or frame_height > limits.image_max_dimension
                    ):
                        raise ContentValidationError("image frame exceeds limit")
                    total_frame_pixels += frame_pixels
                    if total_frame_pixels > limits.image_max_total_frame_pixels:
                        raise ContentValidationError(
                            "image total decode budget exceeds limit"
                        )
                    frame.load()
                # Animated originals are attachment-only. The inline thumbnail is
                # deliberately a static, safely re-encoded first frame.
                image.seek(0)
                safe = ImageOps.exif_transpose(image).copy()
                safe.thumbnail(
                    (limits.thumbnail_max_dimension, limits.thumbnail_max_dimension),
                    Image.Resampling.LANCZOS,
                )
                if safe.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                    safe = safe.convert("RGBA" if "A" in safe.getbands() else "RGB")
                # Image.copy()/transpose may retain EXIF, ICC, PNG text and other
                # source ``info`` fields. The inline derivative must contain only
                # decoded pixels plus the new PNG container.
                safe.info.clear()
                safe.getexif().clear()
                thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                with thumbnail_path.open("xb") as output:
                    safe.save(
                        output,
                        format="PNG",
                        optimize=True,
                        pnginfo=None,
                        exif=b"",
                        icc_profile=None,
                    )
                    output.flush()
                    os.fsync(output.fileno())
    except ContentValidationError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ContentValidationError("invalid image content") from exc
    thumbnail_size, thumbnail_hash = _hash_file(thumbnail_path)
    if thumbnail_size > limits.thumbnail_max_bytes:
        raise ContentValidationError("generated thumbnail exceeds byte limit")
    return thumbnail_size, thumbnail_hash, "image/png"


def _verify_image_container(path: Path, media_type: str) -> None:
    """Reject structurally truncated containers before Pillow's tolerant decode."""

    payload = path.read_bytes()
    if media_type == "image/png":
        signature = b"\x89PNG\r\n\x1a\n"
        if not payload.startswith(signature):
            raise ContentValidationError("PNG signature mismatch")
        position = len(signature)
        chunk_count = 0
        saw_iend = False
        while position < len(payload):
            if len(payload) - position < 12:
                raise ContentValidationError("truncated PNG chunk")
            length = struct.unpack(">I", payload[position : position + 4])[0]
            chunk_type = payload[position + 4 : position + 8]
            end = position + 12 + length
            if end > len(payload):
                raise ContentValidationError("truncated PNG chunk")
            data = payload[position + 8 : position + 8 + length]
            stored_crc = struct.unpack(">I", payload[position + 8 + length : end])[0]
            if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != stored_crc:
                raise ContentValidationError("PNG checksum mismatch")
            chunk_count += 1
            if chunk_count == 1 and chunk_type != b"IHDR":
                raise ContentValidationError("invalid PNG header")
            position = end
            if chunk_type == b"IEND":
                if length != 0 or position != len(payload):
                    raise ContentValidationError("invalid PNG trailer")
                saw_iend = True
                break
        if not saw_iend:
            raise ContentValidationError("missing PNG trailer")
        return
    if media_type == "image/jpeg":
        if len(payload) < 4 or not payload.startswith(b"\xff\xd8\xff") or not payload.endswith(b"\xff\xd9"):
            raise ContentValidationError("invalid JPEG container")
        return
    if media_type == "image/gif":
        if not payload.startswith((b"GIF87a", b"GIF89a")) or not payload.endswith(b";"):
            raise ContentValidationError("invalid GIF container")
        return
    if media_type == "image/webp":
        if (
            len(payload) < 12
            or payload[:4] != b"RIFF"
            or payload[8:12] != b"WEBP"
            or int.from_bytes(payload[4:8], "little") + 8 != len(payload)
        ):
            raise ContentValidationError("invalid WebP container")
        return
    if media_type == "image/bmp":
        if len(payload) < 14 or not payload.startswith(b"BM"):
            raise ContentValidationError("invalid BMP container")
        return
    if media_type == "image/tiff":
        if not payload.startswith((b"II*\x00", b"MM\x00*")):
            raise ContentValidationError("invalid TIFF container")
        return
    raise ContentValidationError("unsupported image media type")


def _safe_zip_members(
    archive: zipfile.ZipFile, limits: ValidationLimits
) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > limits.archive_max_members:
        raise ContentValidationError("archive member limit exceeded")
    names: set[str] = set()
    canonical_names: set[str] = set()
    total_unpacked = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        raw_parts = name.rstrip("/").split("/")
        canonical_name = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        if (
            not name
            or len(name) > 1024
            or "\x00" in name
            or "\\" in name
            or unicodedata.normalize("NFC", name) != name
            or any(
                not part
                or part in {".", ".."}
                or part.rstrip(" .") != part
                or any(
                    unicodedata.category(character).startswith("C")
                    for character in part
                )
                for part in raw_parts
            )
            or path.is_absolute()
            or ".." in path.parts
            or any(":" in part for part in path.parts)
            or name in names
            or canonical_name in canonical_names
        ):
            raise ContentValidationError("unsafe archive member")
        names.add(name)
        canonical_names.add(canonical_name)
        if member.flag_bits & 0x1:
            raise ContentValidationError("encrypted archives are unsupported")
        unix_mode = (member.external_attr >> 16) & 0xFFFF
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise ContentValidationError("archive links are unsupported")
        total_unpacked += member.file_size
        if total_unpacked > limits.archive_max_unpacked_bytes:
            raise ContentValidationError("archive expansion limit exceeded")
        if member.file_size and (
            member.compress_size == 0
            or member.file_size > member.compress_size * limits.archive_max_ratio
        ):
            raise ContentValidationError("archive compression ratio exceeded")
    return members


def _member_suffix(name: str) -> str:
    # Windows/macOS commonly discard trailing dots/spaces. Normalize only for
    # policy comparison so ``payload.exe.`` cannot disguise an executable.
    basename = PurePosixPath(name).name.rstrip(" .")
    return PurePosixPath(basename).suffix.casefold()


def _is_executable_prefix(prefix: bytes) -> bool:
    return prefix.startswith(EXECUTABLE_MAGICS) or prefix.startswith(b"#!")


def _parse_ooxml_xml_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    limits: ValidationLimits,
) -> tuple[
    str,
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Stream-parse one XML part while rejecting DTD/entity expansion."""

    parser = ET.XMLPullParser(events=("start", "end"))
    root_tag: str | None = None
    relationships: list[dict[str, str]] = []
    overrides: list[dict[str, str]] = []
    defaults: list[dict[str, str]] = []
    element_count = 0
    token_overlap = b""

    def consume_events() -> None:
        nonlocal root_tag, element_count
        for event, element in parser.read_events():
            element_count += 1
            if element_count > limits.xml_max_elements:
                raise ContentValidationError("OOXML element limit exceeded")
            if event == "start" and root_tag is None:
                root_tag = element.tag
            if event != "end":
                continue
            local_name = element.tag.rsplit("}", 1)[-1]
            if local_name == "Relationship":
                if element.tag != f"{{{OOXML_RELATIONSHIPS_NAMESPACE}}}Relationship":
                    raise ContentValidationError("invalid OOXML relationship namespace")
                if len(relationships) >= 10_000:
                    raise ContentValidationError("OOXML relationship limit exceeded")
                relationships.append(dict(element.attrib))
            elif local_name == "Override":
                if element.tag != f"{{{OOXML_CONTENT_TYPES_NAMESPACE}}}Override":
                    raise ContentValidationError("invalid OOXML content type namespace")
                if len(overrides) >= 10_000:
                    raise ContentValidationError("OOXML content type limit exceeded")
                overrides.append(dict(element.attrib))
            elif local_name == "Default":
                if element.tag != f"{{{OOXML_CONTENT_TYPES_NAMESPACE}}}Default":
                    raise ContentValidationError("invalid OOXML content type namespace")
                if len(defaults) >= 10_000:
                    raise ContentValidationError("OOXML content type limit exceeded")
                defaults.append(dict(element.attrib))
            element.clear()

    try:
        with archive.open(member, "r") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                probe = (token_overlap + block).upper()
                ascii_probe = probe.replace(b"\x00", b"")
                if b"<!DOCTYPE" in ascii_probe or b"<!ENTITY" in ascii_probe:
                    raise ContentValidationError("OOXML DTD and entities are unsupported")
                token_overlap = probe[-64:]
                parser.feed(block)
                consume_events()
        parser.close()
        consume_events()
    except ContentValidationError:
        raise
    except (ET.ParseError, OSError, ValueError) as exc:
        raise ContentValidationError("invalid OOXML XML content") from exc
    if root_tag is None:
        raise ContentValidationError("empty OOXML XML part")
    return root_tag, relationships, overrides, defaults


def _is_inert_external_hyperlink(relation_type: str, target: str) -> bool:
    if relation_type not in OOXML_HYPERLINK_RELATIONSHIP_TYPES:
        return False
    if not target or target != target.strip():
        return False
    if len(target) > OOXML_EXTERNAL_HYPERLINK_MAX_LENGTH:
        return False
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in target):
        return False
    return target.casefold().startswith(OOXML_EXTERNAL_HYPERLINK_SCHEMES)


def _validate_ooxml_relationships(
    relationships_by_part: dict[str, list[dict[str, str]]],
    names: set[str],
) -> None:
    # Matched against the relationship *name* (last path segment of the Type
    # URI), never as a substring of the whole URI: the standard
    # ".../package/2006/relationships/metadata/core-properties" relationship
    # that every real Excel/Word file carries for docProps/core.xml contains
    # "/package" and used to quarantine every genuine Office document.
    dangerous_relationship_names = frozenset(
        {
            "attachedtemplate",
            "control",
            "oleobject",
            "package",
            "vbaproject",
        }
    )
    for relationship_part, relationships in relationships_by_part.items():
        relationship_ids = [item.get("Id", "") for item in relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ContentValidationError("duplicate OOXML relationship identifier")
        if relationship_part == "_rels/.rels":
            source_directory = PurePosixPath()
        else:
            relationship_path = PurePosixPath(relationship_part)
            if (
                relationship_path.parent.name != "_rels"
                or not relationship_path.name.endswith(".rels")
            ):
                raise ContentValidationError("invalid OOXML relationship part name")
            source_directory = relationship_path.parent.parent
        for relationship in relationships:
            relation_type = relationship.get("Type", "")
            target = relationship.get("Target", "")
            target_mode = relationship.get("TargetMode")
            if not relationship.get("Id") or not relation_type or not target:
                raise ContentValidationError("incomplete OOXML relationship")
            if not relation_type.startswith(OOXML_RELATIONSHIP_TYPE_PREFIXES):
                raise ContentValidationError("non-standard OOXML relationship type")
            if target_mode is not None and target_mode.casefold() != "internal":
                if _is_inert_external_hyperlink(relation_type, target):
                    continue
                raise ContentValidationError("external OOXML relationships are unsupported")
            decoded_target = unquote(target)
            lowered_target = decoded_target.casefold()
            if (
                target != target.strip()
                or "%" in target
                or "\\" in decoded_target
                or "?" in decoded_target
                or "#" in decoded_target
                or PurePosixPath(decoded_target).is_absolute()
                or any(":" in part for part in PurePosixPath(decoded_target).parts)
                or lowered_target.startswith(
                    ("//", "http:", "https:", "file:", "ftp:", "data:")
                )
                or relation_type.rstrip("/").rsplit("/", 1)[-1].casefold()
                in dangerous_relationship_names
            ):
                raise ContentValidationError("active OOXML relationship is unsupported")
            resolved_parts = list(source_directory.parts)
            for part in PurePosixPath(decoded_target).parts:
                if part in {"", "."}:
                    continue
                if part == "..":
                    if not resolved_parts:
                        raise ContentValidationError("OOXML relationship escapes package")
                    resolved_parts.pop()
                else:
                    resolved_parts.append(part)
            resolved_target = PurePosixPath(*resolved_parts).as_posix()
            if not resolved_target or resolved_target not in names:
                raise ContentValidationError("OOXML relationship target is missing")


def _inspect_ooxml(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
    extension: str,
    limits: ValidationLimits,
) -> None:
    family = OOXML_FAMILY.get(extension)
    if family is None:
        raise ContentValidationError("unsupported OOXML family")
    names = {member.filename for member in members}
    lowered_names = {name.casefold() for name in names}
    main_part = str(family["main_part"])
    if (
        "[Content_Types].xml" not in names
        or "_rels/.rels" not in names
        or main_part not in names
    ):
        raise ContentValidationError("invalid OOXML package")
    if any(
        "vbaproject.bin" in name
        or "/activex/" in f"/{name}"
        or "/embeddings/" in f"/{name}"
        or _member_suffix(name) in {".docm", ".xlsm", ".pptm"}
        for name in lowered_names
    ):
        raise ContentValidationError("active OOXML content is unsupported")

    roots: dict[str, str] = {}
    relationships_by_part: dict[str, list[dict[str, str]]] = {}
    content_overrides: list[dict[str, str]] = []
    content_defaults: list[dict[str, str]] = []
    for member in members:
        lowered = member.filename.casefold()
        if member.is_dir() or not (
            lowered.endswith(".xml") or lowered.endswith(".rels")
        ):
            continue
        root_tag, relationships, overrides, defaults = _parse_ooxml_xml_member(
            archive, member, limits
        )
        roots[member.filename] = root_tag
        if lowered.endswith(".rels"):
            expected_root = f"{{{OOXML_RELATIONSHIPS_NAMESPACE}}}Relationships"
            if root_tag != expected_root:
                raise ContentValidationError("invalid OOXML relationships root")
            relationships_by_part[member.filename] = relationships
        if member.filename == "[Content_Types].xml":
            expected_root = f"{{{OOXML_CONTENT_TYPES_NAMESPACE}}}Types"
            if root_tag != expected_root:
                raise ContentValidationError("invalid OOXML content types root")
            content_overrides = overrides
            content_defaults = defaults

    _validate_ooxml_relationships(relationships_by_part, names)
    if roots.get(main_part) not in family["root_tags"]:
        raise ContentValidationError("OOXML main part does not match its family")
    override_matches = [
        item
        for item in content_overrides
        if item.get("PartName") == f"/{main_part}"
        and item.get("ContentType") == family["content_type"]
    ]
    all_content_types = [
        item.get("ContentType", "").casefold()
        for item in [*content_overrides, *content_defaults]
    ]
    override_names = [item.get("PartName", "") for item in content_overrides]
    default_extensions = [
        item.get("Extension", "").casefold() for item in content_defaults
    ]
    invalid_content_entry = (
        len(override_names) != len(set(override_names))
        or len(default_extensions) != len(set(default_extensions))
        or not any(
            item.get("Extension", "").casefold() == "rels"
            and item.get("ContentType")
            == "application/vnd.openxmlformats-package.relationships+xml"
            for item in content_defaults
        )
        or any(
            not item.get("PartName", "").startswith("/")
            or not item.get("ContentType")
            for item in content_overrides
        )
        or any(
            not item.get("Extension")
            or any(character in item.get("Extension", "") for character in "/\\.")
            or not item.get("ContentType")
            for item in content_defaults
        )
    )
    if (
        len(override_matches) != 1
        or invalid_content_entry
        or any(
            marker in content_type
            for content_type in all_content_types
            for marker in ("macroenabled", "vba", "activex", "oleobject")
        )
    ):
        raise ContentValidationError("invalid or active OOXML content type")
    root_office_relationships = [
        item
        for item in relationships_by_part.get("_rels/.rels", [])
        if item.get("Type") in OOXML_OFFICE_DOCUMENT_RELATIONSHIPS
    ]
    if (
        len(root_office_relationships) != 1
        or root_office_relationships[0].get("Target", "").lstrip("/") != main_part
    ):
        raise ContentValidationError("OOXML office document relationship is invalid")


def _inspect_zip(
    path: Path,
    extension: str,
    limits: ValidationLimits,
) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = _safe_zip_members(archive, limits)
            is_ooxml = extension in OOXML_FAMILY
            if is_ooxml:
                _inspect_ooxml(archive, members, extension, limits)
            else:
                for member in members:
                    if member.is_dir():
                        continue
                    if _member_suffix(member.filename) in FORBIDDEN_ARCHIVE_SUFFIXES:
                        raise ContentValidationError("unsupported archive member type")
            # Stream every member to force CRC/decompression verification. The
            # central-directory limits above cap the work before extraction.
            for member in members:
                if member.is_dir():
                    continue
                observed = 0
                prefix = bytearray()
                with archive.open(member, "r") as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        if len(prefix) < 16:
                            prefix.extend(block[: 16 - len(prefix)])
                        observed += len(block)
                        if observed > member.file_size:
                            raise ContentValidationError("archive member size mismatch")
                if observed != member.file_size:
                    raise ContentValidationError("archive member size mismatch")
                if not is_ooxml and _is_executable_prefix(bytes(prefix)):
                    raise ContentValidationError("executable archive member is unsupported")
    except ContentValidationError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ContentValidationError("invalid archive content") from exc


def _validate_text(path: Path, *, csv_mode: bool) -> None:
    try:
        raw = path.read_bytes()
        if raw.startswith(EXECUTABLE_MAGICS) or raw.startswith(b"#!"):
            raise ContentValidationError("executable content is unsupported")
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContentValidationError("text must be UTF-8") from exc
    if "\x00" in text or any(
        ord(character) < 32 and character not in "\t\r\n" for character in text
    ):
        raise ContentValidationError("text contains unsupported controls")
    leading = text.lstrip("\ufeff\t\r\n ").lower()
    if leading.startswith(("<!doctype", "<html", "<script", "<svg", "<?xml", "javascript:")):
        raise ContentValidationError("active text content is unsupported")
    if csv_mode:
        try:
            for row in csv.reader(io.StringIO(text, newline="")):
                if len(row) > 10_000:
                    raise ContentValidationError("CSV column limit exceeded")
        except csv.Error as exc:
            raise ContentValidationError("invalid CSV content") from exc


def _validate_pdf(path: Path, limits: ValidationLimits) -> None:
    """Strictly parse and bound-walk every reachable PDF object."""

    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ContentValidationError("encrypted PDF files are unsupported")
        pending: list[object] = [reader.trailer]
        page_count = 0
        for page in reader.pages:
            page_count += 1
            if page_count > limits.pdf_max_pages:
                raise ContentValidationError("PDF page limit exceeded")
            pending.append(page)
        if page_count == 0:
            raise ContentValidationError("PDF must contain at least one page")
        visited_indirect: set[tuple[int, int]] = set()
        visited_containers: set[int] = set()
        traversed = 0
        while pending:
            value = pending.pop()
            traversed += 1
            if traversed > limits.pdf_max_objects:
                raise ContentValidationError("PDF object traversal limit exceeded")
            if isinstance(value, IndirectObject):
                marker = (value.idnum, value.generation)
                if marker in visited_indirect:
                    continue
                visited_indirect.add(marker)
                pending.append(value.get_object())
                continue
            if isinstance(value, (DictionaryObject, ArrayObject, dict, list, tuple)):
                marker = id(value)
                if marker in visited_containers:
                    continue
                visited_containers.add(marker)
            if isinstance(value, (DictionaryObject, dict)):
                if str(value.get("/Type", "")) == "/Pages":
                    declared_pages = value.get("/Count")
                    try:
                        if int(declared_pages) > limits.pdf_max_pages:
                            raise ContentValidationError("PDF page limit exceeded")
                    except (TypeError, ValueError):
                        raise ContentValidationError("invalid PDF page tree") from None
                for raw_key, item in value.items():
                    key = str(raw_key)
                    if key in PDF_FORBIDDEN_KEYS:
                        raise ContentValidationError("active PDF object is unsupported")
                    pending.append(item)
                continue
            if isinstance(value, (ArrayObject, list, tuple)):
                pending.extend(value)
                continue
            if str(value) in PDF_FORBIDDEN_NAMES:
                raise ContentValidationError("active PDF object is unsupported")
    except ContentValidationError:
        raise
    except Exception as exc:
        # pypdf raises several format/object errors lazily while pages and
        # indirect objects are traversed. Every parser ambiguity fails closed.
        raise ContentValidationError("invalid PDF content") from exc


def _validate_file(
    path: Path,
    filename: str,
    declared_media_type: str,
    limits: ValidationLimits,
) -> None:
    extension = Path(filename).suffix.lower()
    if expected_media_type("file", filename) != declared_media_type:
        raise ContentValidationError("file declaration mismatch")
    with path.open("rb") as handle:
        prefix = handle.read(16)
    if prefix.startswith(EXECUTABLE_MAGICS):
        raise ContentValidationError("executable content is unsupported")
    if extension == ".pdf":
        _validate_pdf(path, limits)
    elif extension == ".txt":
        _validate_text(path, csv_mode=False)
    elif extension == ".csv":
        _validate_text(path, csv_mode=True)
    elif extension in OOXML_FAMILY or extension == ".zip":
        if not zipfile.is_zipfile(path):
            raise ContentValidationError("archive signature mismatch")
        _inspect_zip(path, extension, limits)
    elif extension in FILE_SIGNATURES:
        if not any(
            prefix[offset : offset + len(marker)] == marker
            for offset, marker in FILE_SIGNATURES[extension]
        ):
            raise ContentValidationError("file signature mismatch")
    elif declared_media_type == OCTET_STREAM_MEDIA_TYPE:
        # Unknown container: executables were refused above, ClamAV already ran.
        return


def validate_content(
    path: Path,
    *,
    kind: str,
    filename: str,
    declared_media_type: str,
    limits: ValidationLimits,
    thumbnail_path: Path | None = None,
) -> ValidationResult:
    if not path.is_file() or path.is_symlink():
        raise ContentValidationError("incoming object is unavailable")
    size, digest = _hash_file(path)
    if size <= 0:
        raise ContentValidationError("empty objects are unsupported")
    extension = Path(filename).suffix.lower()
    if kind == "image":
        if IMAGE_MEDIA_BY_EXTENSION.get(extension) != declared_media_type:
            raise ContentValidationError("image declaration mismatch")
        if thumbnail_path is None:
            raise ContentValidationError("image thumbnail output is required")
        thumb_size, thumb_hash, thumb_media = _validate_image(
            path, declared_media_type, limits, thumbnail_path
        )
        return ValidationResult(
            media_type=declared_media_type,
            size_bytes=size,
            sha256_hex=digest,
            thumbnail_size_bytes=thumb_size,
            thumbnail_sha256_hex=thumb_hash,
            thumbnail_media_type=thumb_media,
        )
    if kind != "file":
        raise ContentValidationError("unsupported asset kind")
    _validate_file(path, filename, declared_media_type, limits)
    return ValidationResult(
        media_type=declared_media_type, size_bytes=size, sha256_hex=digest
    )


def atomic_promote(source: Path, destination: Path) -> None:
    """Copy across volumes, fsync, then atomically expose within the target volume."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.promoting")
    if destination.exists() or temporary.exists():
        raise ContentValidationError("promotion target already exists")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
