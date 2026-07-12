#!/usr/bin/env python3
"""Seal and verify a tamper-evident full C19 disaster-recovery bundle.

The bundle joins the Barong control database, the C19 Record database, and the
portable Asset database/object archive.  This module never starts, stops, or
restores a service.  The shell coordinator owns the quiesce boundary; this
module makes that boundary and every captured byte independently auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


FORMAT = "barong-c19-full-dr-v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$")
REVISION = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ASSET_OBJECT_KEY = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{28}$")
EXPECTED_WRITERS = (
    "barong:console_backend",
    "barong:r-w-worker",
    "barong:r-a-worker",
    "barong:k-worker",
    "barong:key-health-worker",
    "c19-record:c19-record-service",
    "c19-asset:c19-asset-api",
    "c19-asset:c19-asset-gateway",
    "c19-asset:c19-asset-worker",
)


class BundleError(RuntimeError):
    """Raised when a bundle cannot be trusted."""


def _fail(message: str) -> None:
    raise BundleError(message)


def _parse_metadata(path: Path, *, allowed: set[str], required: set[str]) -> dict[str, str]:
    _safe_file(path, label="metadata")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        if "=" not in raw_line:
            _fail(f"metadata contains a malformed line: {path.name}")
        key, value = raw_line.split("=", 1)
        if key not in allowed:
            _fail(f"metadata contains an unsupported key: {key}")
        if key in values:
            _fail(f"metadata contains a duplicate key: {key}")
        if not value or any(character in value for character in "\r\n\x00"):
            _fail(f"metadata contains an invalid value: {key}")
        values[key] = value
    missing = sorted(required - values.keys())
    if missing:
        _fail(f"metadata is missing required keys: {', '.join(missing)}")
    return values


def _safe_file(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} must be a regular non-symlink file: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        _fail(f"{label} must not be group/world accessible: {path}")


def _inside(root: Path, path: Path, *, label: str) -> Path:
    root = root.resolve(strict=True)
    path = path.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError:
        _fail(f"{label} is outside the generation directory")
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
        _fail(f"{label} traverses a symbolic link")
    return relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_hash(value: str, *, label: str) -> None:
    if SHA256.fullmatch(value) is None:
        _fail(f"{label} is not a SHA-256 digest")


def _require_revision(value: str, *, label: str) -> None:
    if REVISION.fullmatch(value) is None:
        _fail(f"{label} is invalid")


def _require_identifier(value: str, *, label: str) -> None:
    if IDENTIFIER.fullmatch(value) is None:
        _fail(f"{label} is invalid")


def _require_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(f"{label} must use YYYYmmddTHHMMSSZ")
    return parsed


def _key(path: Path) -> bytes:
    _safe_file(path, label="HMAC key file")
    value = path.read_bytes()
    if value.endswith(b"\n"):
        value = value[:-1]
    if len(value) < 32 or b"CHANGE-ME" in value.upper():
        _fail("HMAC key must contain at least 32 non-placeholder bytes")
    return value


def _canonical(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _artifact(root: Path, path: Path, *, label: str) -> dict[str, Any]:
    _safe_file(path, label=label)
    relative = _inside(root, path, label=label)
    return {
        "path": relative.as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _verify_pg_dump_magic(path: Path, *, label: str) -> None:
    with path.open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            _fail(f"{label} is not a PostgreSQL custom-format archive")


def _asset_manifest(path: Path) -> dict[str, tuple[int, str]]:
    values: dict[str, tuple[int, str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) != 3:
                _fail(f"asset object manifest line {line_number} is malformed")
            digest, raw_size, name = parts
            relative = PurePosixPath(name)
            if (
                ASSET_OBJECT_KEY.fullmatch(name) is None
                or relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or name != relative.as_posix()
            ):
                _fail("asset object manifest contains an unsafe path")
            try:
                size = int(raw_size)
            except ValueError:
                _fail("asset object manifest contains an invalid size")
            if size <= 0 or SHA256.fullmatch(digest) is None:
                _fail("asset object manifest contains invalid object metadata")
            if name in values:
                _fail("asset object manifest contains a duplicate path")
            values[name] = (size, digest)
    return values


def _verify_asset_tar(path: Path, expected: dict[str, tuple[int, str]]) -> None:
    observed: dict[str, tuple[int, str]] = {}
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or member.name != relative.as_posix()
                    or not member.isfile()
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                ):
                    _fail("asset object archive contains an unsafe member")
                if member.name in observed:
                    _fail("asset object archive contains a duplicate member")
                source = archive.extractfile(member)
                if source is None:
                    _fail("asset object archive member has no byte stream")
                digest = hashlib.sha256()
                size = 0
                while block := source.read(1024 * 1024):
                    size += len(block)
                    digest.update(block)
                observed[member.name] = (size, digest.hexdigest())
    except (tarfile.TarError, OSError) as exc:
        raise BundleError("asset object archive is unreadable") from exc
    if observed != expected:
        _fail("asset object archive differs from its exact object manifest")


def _load_json(path: Path) -> dict[str, Any]:
    _safe_file(path, label="bundle manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError("bundle manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        _fail("bundle manifest must be a JSON object")
    return value


def seal(args: argparse.Namespace) -> None:
    root = args.generation_dir.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        _fail("generation directory must be a regular directory")
    os.chmod(root, 0o700)
    _require_identifier(args.generation_id, label="generation id")
    _require_identifier(args.barong_dataset_id, label="Barong dataset id")
    _require_identifier(args.record_dataset_id, label="Record dataset id")
    _require_identifier(args.asset_dataset_id, label="Asset dataset id")
    started = _require_timestamp(args.quiesced_at, label="quiesced_at")
    completed = _require_timestamp(args.captured_at, label="captured_at")
    if completed < started:
        _fail("captured_at precedes quiesced_at")

    manifest_path = args.manifest.resolve()
    signature_path = Path(f"{manifest_path}.hmac")
    if manifest_path.exists() or signature_path.exists():
        _fail("bundle manifest or signature already exists")
    _inside(root, manifest_path.parent, label="manifest directory")

    barong_archive = args.barong_archive.resolve(strict=True)
    barong_metadata_path = Path(f"{barong_archive}.metadata")
    record_archive = args.record_archive.resolve(strict=True)
    record_metadata_path = Path(f"{record_archive}.metadata")
    asset_metadata_path = args.asset_metadata.resolve(strict=True)
    asset_base = asset_metadata_path.with_suffix("")
    asset_database = Path(f"{asset_base}.dump")
    asset_objects = Path(f"{asset_base}.objects.tar")
    asset_object_manifest = Path(f"{asset_base}.manifest")

    barong_metadata = _parse_metadata(
        barong_metadata_path,
        allowed={
            "created_at",
            "source_dataset_id",
            "app_version",
            "alembic_revision",
            "database_url",
            "format",
            "archive",
            "archive_sha256",
        },
        required={
            "created_at",
            "source_dataset_id",
            "app_version",
            "alembic_revision",
            "format",
            "archive_sha256",
        },
    )
    record_metadata = _parse_metadata(
        record_metadata_path,
        allowed={
            "created_at",
            "source_dataset_id",
            "alembic_revision",
            "format",
            "archive_sha256",
        },
        required={
            "created_at",
            "source_dataset_id",
            "alembic_revision",
            "format",
            "archive_sha256",
        },
    )
    asset_metadata = _parse_metadata(
        asset_metadata_path,
        allowed={
            "created_at",
            "source_dataset_id",
            "alembic_revision",
            "blob_format_revision",
            "database_format",
            "object_archive_format",
            "object_count",
            "object_bytes",
            "database_sha256",
            "objects_sha256",
            "manifest_sha256",
        },
        required={
            "created_at",
            "source_dataset_id",
            "alembic_revision",
            "blob_format_revision",
            "database_format",
            "object_archive_format",
            "object_count",
            "object_bytes",
            "database_sha256",
            "objects_sha256",
            "manifest_sha256",
        },
    )

    if barong_metadata["format"] != "pg_dump_custom":
        _fail("Barong metadata has an unsupported archive format")
    if record_metadata["format"] != "pg_dump_custom":
        _fail("Record metadata has an unsupported archive format")
    if asset_metadata["database_format"] != "pg_dump_custom":
        _fail("Asset metadata has an unsupported database format")
    if asset_metadata["object_archive_format"] != "posix_tar":
        _fail("Asset metadata has an unsupported object archive format")
    if asset_metadata["blob_format_revision"] != "1":
        _fail("Asset blob format revision is unsupported")
    if record_metadata["source_dataset_id"] != args.record_dataset_id:
        _fail("Record backup dataset differs from the coordinated plan")
    if asset_metadata["source_dataset_id"] != args.asset_dataset_id:
        _fail("Asset backup dataset differs from the coordinated plan")
    if barong_metadata["source_dataset_id"] != args.barong_dataset_id:
        _fail("Barong backup dataset differs from the coordinated plan")

    for label, metadata in (
        ("Barong", barong_metadata),
        ("Record", record_metadata),
        ("Asset", asset_metadata),
    ):
        created = _require_timestamp(
            metadata["created_at"], label=f"{label} backup created_at"
        )
        if created < started or created > completed:
            _fail(f"{label} backup falls outside the sealed quiesce interval")

    for label, value in (
        ("Barong revision", barong_metadata["alembic_revision"]),
        ("Record revision", record_metadata["alembic_revision"]),
        ("Asset revision", asset_metadata["alembic_revision"]),
    ):
        _require_revision(value, label=label)
    for label, value in (
        ("Record archive checksum", record_metadata["archive_sha256"]),
        ("Asset database checksum", asset_metadata["database_sha256"]),
        ("Asset object checksum", asset_metadata["objects_sha256"]),
        ("Asset manifest checksum", asset_metadata["manifest_sha256"]),
    ):
        _require_hash(value, label=label)

    artifacts = {
        "barong_archive": _artifact(root, barong_archive, label="Barong archive"),
        "barong_metadata": _artifact(
            root, barong_metadata_path, label="Barong metadata"
        ),
        "record_archive": _artifact(root, record_archive, label="Record archive"),
        "record_metadata": _artifact(
            root, record_metadata_path, label="Record metadata"
        ),
        "asset_database": _artifact(root, asset_database, label="Asset database"),
        "asset_objects": _artifact(root, asset_objects, label="Asset objects"),
        "asset_object_manifest": _artifact(
            root, asset_object_manifest, label="Asset object manifest"
        ),
        "asset_metadata": _artifact(root, asset_metadata_path, label="Asset metadata"),
    }
    if artifacts["record_archive"]["sha256"] != record_metadata["archive_sha256"]:
        _fail("Record archive differs from its component metadata")
    if artifacts["asset_database"]["sha256"] != asset_metadata["database_sha256"]:
        _fail("Asset database differs from its component metadata")
    if artifacts["asset_objects"]["sha256"] != asset_metadata["objects_sha256"]:
        _fail("Asset objects differ from their component metadata")
    if (
        artifacts["asset_object_manifest"]["sha256"]
        != asset_metadata["manifest_sha256"]
    ):
        _fail("Asset object manifest differs from its component metadata")
    _require_hash(barong_metadata["archive_sha256"], label="Barong archive checksum")
    if artifacts["barong_archive"]["sha256"] != barong_metadata["archive_sha256"]:
        _fail("Barong archive differs from its component metadata")

    _verify_pg_dump_magic(barong_archive, label="Barong archive")
    _verify_pg_dump_magic(record_archive, label="Record archive")
    _verify_pg_dump_magic(asset_database, label="Asset database")
    exact_objects = _asset_manifest(asset_object_manifest)
    if len(exact_objects) != int(asset_metadata["object_count"]):
        _fail("Asset object count differs from its component metadata")
    if sum(size for size, _ in exact_objects.values()) != int(
        asset_metadata["object_bytes"]
    ):
        _fail("Asset object byte count differs from its component metadata")
    _verify_asset_tar(asset_objects, exact_objects)

    document: dict[str, Any] = {
        "format": FORMAT,
        "generation_id": args.generation_id,
        "sealed_at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "quiesce": {
            "state": "all_c19_writers_stopped_during_capture",
            "started_at": args.quiesced_at,
            "completed_at": args.captured_at,
            "writers": list(EXPECTED_WRITERS),
        },
        "datasets": {
            "barong": args.barong_dataset_id,
            "record": args.record_dataset_id,
            "asset": args.asset_dataset_id,
        },
        "revisions": {
            "barong": barong_metadata["alembic_revision"],
            "record": record_metadata["alembic_revision"],
            "asset": asset_metadata["alembic_revision"],
            "asset_blob_format": int(asset_metadata["blob_format_revision"]),
        },
        "barong_app_version": barong_metadata["app_version"],
        "asset_objects": {
            "count": int(asset_metadata["object_count"]),
            "bytes": int(asset_metadata["object_bytes"]),
        },
        "archive_validation": {
            "method": "pg_restore_list",
            "state": "required_tables_verified_before_seal",
        },
        "artifacts": artifacts,
    }
    payload = _canonical(document)
    signature = hmac.new(_key(args.hmac_key_file), payload, hashlib.sha256).hexdigest()
    manifest_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest_path.write_bytes(payload)
    signature_path.write_text(f"{signature}\n", encoding="ascii")
    os.chmod(manifest_path, 0o600)
    os.chmod(signature_path, 0o600)
    print(f"manifest: {manifest_path}")
    print(f"signature: {signature_path}")
    print(f"manifest_sha256: {_sha256(manifest_path)}")
    print("C19 full backup bundle sealed")


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        _fail(f"{label} has an unexpected shape")


def verify(args: argparse.Namespace) -> None:
    manifest_path = args.manifest.resolve(strict=True)
    root = manifest_path.parent.resolve(strict=True)
    signature_path = Path(f"{manifest_path}.hmac")
    _safe_file(signature_path, label="bundle signature")
    payload = manifest_path.read_bytes()
    supplied = signature_path.read_text(encoding="ascii").strip()
    if SHA256.fullmatch(supplied) is None:
        _fail("bundle signature is malformed")
    expected_signature = hmac.new(
        _key(args.hmac_key_file), payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected_signature):
        _fail("bundle manifest signature does not match")
    document = _load_json(manifest_path)
    _exact_keys(
        document,
        {
            "format",
            "generation_id",
            "sealed_at",
            "quiesce",
            "datasets",
            "revisions",
            "barong_app_version",
            "asset_objects",
            "archive_validation",
            "artifacts",
        },
        label="bundle manifest",
    )
    if document["format"] != FORMAT:
        _fail("bundle format is unsupported")
    _require_identifier(document["generation_id"], label="generation id")
    _require_timestamp(document["sealed_at"], label="sealed_at")

    quiesce = document["quiesce"]
    if not isinstance(quiesce, dict):
        _fail("quiesce evidence is malformed")
    _exact_keys(
        quiesce,
        {"state", "started_at", "completed_at", "writers"},
        label="quiesce evidence",
    )
    if (
        quiesce["state"] != "all_c19_writers_stopped_during_capture"
        or tuple(quiesce["writers"]) != EXPECTED_WRITERS
    ):
        _fail("bundle lacks the required single-writer quiesce evidence")
    started = _require_timestamp(quiesce["started_at"], label="quiesce started_at")
    completed = _require_timestamp(
        quiesce["completed_at"], label="quiesce completed_at"
    )
    if completed < started:
        _fail("quiesce evidence has an inverted time range")

    datasets = document["datasets"]
    revisions = document["revisions"]
    if not isinstance(datasets, dict) or not isinstance(revisions, dict):
        _fail("dataset or revision evidence is malformed")
    _exact_keys(datasets, {"barong", "record", "asset"}, label="datasets")
    _exact_keys(
        revisions,
        {"barong", "record", "asset", "asset_blob_format"},
        label="revisions",
    )
    for name, value in datasets.items():
        _require_identifier(value, label=f"{name} dataset")
    for name in ("barong", "record", "asset"):
        _require_revision(revisions[name], label=f"{name} revision")
    if revisions["asset_blob_format"] != 1:
        _fail("asset blob format is unsupported")
    archive_validation = document["archive_validation"]
    if archive_validation != {
        "method": "pg_restore_list",
        "state": "required_tables_verified_before_seal",
    }:
        _fail("database archive validation evidence is missing")

    expected_values = {
        "barong": args.expected_barong_dataset,
        "record": args.expected_record_dataset,
        "asset": args.expected_asset_dataset,
    }
    for name, expected in expected_values.items():
        if expected is not None and datasets[name] != expected:
            _fail(f"{name} dataset does not match the restore target")
    expected_revisions = {
        "barong": args.expected_barong_revision,
        "record": args.expected_record_revision,
        "asset": args.expected_asset_revision,
    }
    for name, expected in expected_revisions.items():
        if expected is not None and revisions[name] != expected:
            _fail(f"{name} revision does not match the restore target")

    artifacts = document["artifacts"]
    expected_artifacts = {
        "barong_archive",
        "barong_metadata",
        "record_archive",
        "record_metadata",
        "asset_database",
        "asset_objects",
        "asset_object_manifest",
        "asset_metadata",
    }
    if not isinstance(artifacts, dict):
        _fail("artifact evidence is malformed")
    _exact_keys(artifacts, expected_artifacts, label="artifacts")
    resolved: dict[str, Path] = {}
    for name, evidence in artifacts.items():
        if not isinstance(evidence, dict):
            _fail("artifact evidence is malformed")
        _exact_keys(evidence, {"path", "sha256", "size_bytes"}, label=name)
        relative = PurePosixPath(evidence["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            _fail("artifact evidence contains an unsafe path")
        _require_hash(evidence["sha256"], label=f"{name} checksum")
        if not isinstance(evidence["size_bytes"], int) or evidence["size_bytes"] < 0:
            _fail("artifact evidence contains an invalid size")
        path = root.joinpath(*relative.parts)
        _safe_file(path, label=name)
        _inside(root, path, label=name)
        if path.stat().st_size != evidence["size_bytes"]:
            _fail(f"{name} size differs from the sealed manifest")
        if _sha256(path) != evidence["sha256"]:
            _fail(f"{name} checksum differs from the sealed manifest")
        resolved[name] = path

    _verify_pg_dump_magic(resolved["barong_archive"], label="Barong archive")
    _verify_pg_dump_magic(resolved["record_archive"], label="Record archive")
    _verify_pg_dump_magic(resolved["asset_database"], label="Asset database")
    exact_objects = _asset_manifest(resolved["asset_object_manifest"])
    object_summary = document["asset_objects"]
    if not isinstance(object_summary, dict):
        _fail("asset object summary is malformed")
    _exact_keys(object_summary, {"count", "bytes"}, label="asset object summary")
    if len(exact_objects) != object_summary["count"] or sum(
        size for size, _ in exact_objects.values()
    ) != object_summary["bytes"]:
        _fail("asset object summary differs from the exact manifest")
    _verify_asset_tar(resolved["asset_objects"], exact_objects)

    print(f"generation_id: {document['generation_id']}")
    print(f"barong_dataset: {datasets['barong']}")
    print(f"record_dataset: {datasets['record']}")
    print(f"asset_dataset: {datasets['asset']}")
    print(f"barong_revision: {revisions['barong']}")
    print(f"record_revision: {revisions['record']}")
    print(f"asset_revision: {revisions['asset']}")
    print(f"manifest_sha256: {_sha256(manifest_path)}")
    print("C19 full backup bundle verification passed")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="c19-full-dr")
    commands = value.add_subparsers(dest="command", required=True)

    seal_parser = commands.add_parser("seal")
    seal_parser.add_argument("--generation-dir", type=Path, required=True)
    seal_parser.add_argument("--generation-id", required=True)
    seal_parser.add_argument("--barong-dataset-id", required=True)
    seal_parser.add_argument("--record-dataset-id", required=True)
    seal_parser.add_argument("--asset-dataset-id", required=True)
    seal_parser.add_argument("--barong-archive", type=Path, required=True)
    seal_parser.add_argument("--record-archive", type=Path, required=True)
    seal_parser.add_argument("--asset-metadata", type=Path, required=True)
    seal_parser.add_argument("--quiesced-at", required=True)
    seal_parser.add_argument("--captured-at", required=True)
    seal_parser.add_argument("--manifest", type=Path, required=True)
    seal_parser.add_argument("--hmac-key-file", type=Path, required=True)
    seal_parser.set_defaults(handler=seal)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--hmac-key-file", type=Path, required=True)
    verify_parser.add_argument("--expected-barong-dataset")
    verify_parser.add_argument("--expected-record-dataset")
    verify_parser.add_argument("--expected-asset-dataset")
    verify_parser.add_argument("--expected-barong-revision")
    verify_parser.add_argument("--expected-record-revision")
    verify_parser.add_argument("--expected-asset-revision")
    verify_parser.set_defaults(handler=verify)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.handler(args)
    except (BundleError, OSError, ValueError) as exc:
        print(f"C19 full DR verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
