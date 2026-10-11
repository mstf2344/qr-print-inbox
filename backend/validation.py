import re
import unicodedata
import warnings
from pathlib import Path, PurePosixPath
from typing import Set
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class InboxError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def safe_name(value: str, allowed: Set[str]) -> str:
    # Browsers may send a Windows or POSIX basename. Never retain path components.
    value = unicodedata.normalize("NFC", value.replace("\\", "/").rsplit("/", 1)[-1])
    value = "".join(
        character for character in value if not unicodedata.category(character).startswith("C")
    )
    value = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    suffix = Path(value).suffix.lower()
    if suffix not in allowed:
        raise InboxError(415, "Bu dosya türü desteklenmiyor.")
    stem = value[: -len(suffix)].strip(" .")
    if not stem:
        stem = "dosya"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", stem.split(".")[0]):
        stem = "_" + stem
    # Keep UTF-8 bytes and UTF-16 code units comfortably below filesystem limits.
    while len(stem.encode("utf-8")) > 120:
        stem = stem[:-1]
    return stem + suffix


OFFICE_TYPES = {
    ".docx": ("word/document.xml", "wordprocessingml.document.main+xml", "document"),
    ".xlsx": ("xl/workbook.xml", "spreadsheetml.sheet.main+xml", "workbook"),
    ".pptx": ("ppt/presentation.xml", "presentationml.presentation.main+xml", "presentation"),
}
OFFICE_NAMESPACES = {
    ".docx": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    ".xlsx": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    ".pptx": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def validate_office(path: Path, suffix: str) -> None:
    main, content_type, root_name = OFFICE_TYPES[suffix]
    with ZipFile(path) as archive:
        infos = archive.infolist()
        names = [entry.filename for entry in infos]
        if len(infos) > 2000 or len(set(names)) != len(names):
            raise ValueError("Archive entry limit/duplicates")
        total = 0
        for entry in infos:
            total += entry.file_size
            name = entry.filename.lower()
            if (
                entry.file_size > 32 * 1024 * 1024
                or total > 100 * 1024 * 1024
                or entry.file_size > max(entry.compress_size, 1) * 200
                or entry.flag_bits & 1
                or ".." in PurePosixPath(name).parts
                or name.startswith("/")
                or "\\" in name
                or "vbaproject" in name
                or "/embeddings/" in name
                or Path(name).suffix in {".exe", ".dll", ".js", ".vbs", ".bat", ".cmd"}
            ):
                raise ValueError("Unsafe Office archive")
        if any(required not in names for required in (main, "[Content_Types].xml", "_rels/.rels")):
            raise ValueError("Missing Office parts")
        if any(
            archive.getinfo(name).file_size > 8 * 1024 * 1024
            for name in (main, "[Content_Types].xml", "_rels/.rels")
        ):
            raise ValueError("Office XML too large")
        types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
        if types.tag != "{http://schemas.openxmlformats.org/package/2006/content-types}Types":
            raise ValueError("Invalid content types root")
        if not any(
            child.attrib.get("PartName") == "/" + main
            and child.attrib.get("ContentType")
            == "application/vnd.openxmlformats-officedocument." + content_type
            for child in types
        ):
            raise ValueError("Office content type mismatch")
        for child in types:
            if any(
                word in child.attrib.get("ContentType", "").lower()
                for word in ("macroenabled", "vbaproject", "activex")
            ):
                raise ValueError("Active Office content")
        root = ElementTree.fromstring(archive.read(main))
        if root.tag != "{" + OFFICE_NAMESPACES[suffix] + "}" + root_name:
            raise ValueError("Office XML mismatch")
        relationships = ElementTree.fromstring(archive.read("_rels/.rels"))
        if (
            relationships.tag
            != "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships"
        ):
            raise ValueError("Invalid package relationships")
        if not any(
            child.attrib.get("Type")
            == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
            and child.attrib.get("Target", "").lstrip("/") == main
            and child.attrib.get("TargetMode", "Internal") == "Internal"
            for child in relationships
        ):
            raise ValueError("Missing main document relationship")
        if archive.testzip() is not None:
            raise ValueError("Corrupt Office archive")


def validate_content(path: Path, name: str) -> None:
    suffix = Path(name).suffix.lower()
    try:
        if suffix in OFFICE_TYPES:
            validate_office(path, suffix)
        elif suffix == ".pdf":
            with path.open("rb") as source:
                if not source.read(8).startswith(b"%PDF-"):
                    raise ValueError("PDF signature mismatch")
                source.seek(0)
                reader = PdfReader(source, strict=True)
                if reader.is_encrypted or not len(reader.pages):
                    raise ValueError("Encrypted or empty PDF")
        else:
            expected = "PNG" if suffix == ".png" else "JPEG"
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path, formats=[expected]) as image:
                    if image.width * image.height > 25_000_000:
                        raise ValueError("Image pixel limit")
                    image.verify()
                with Image.open(path, formats=[expected]) as image:
                    image.load()
    except (
        ValueError,
        OSError,
        SyntaxError,
        KeyError,
        BadZipFile,
        DefusedXmlException,
        PdfReadError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise InboxError(
            415, "Dosya içeriği geçersiz, korumalı veya desteklenen türle uyuşmuyor."
        ) from error
