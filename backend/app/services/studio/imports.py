"""
Integration imports: employee master, CTC history, attendance and salary registers.

Records arrive as JSON (or, later, from a connector) and go through **the same
parsers the upload screens use** — the same header aliases, the same date and
number reading, the same commit. What this module adds is what an integration
needs and a person at a screen gets by looking:

* **Every record is accounted for.** Received = accepted + rejected + skipped,
  and accepted = created + updated + unchanged. Nothing is dropped unseen.
* **A value that cannot be read is a rejection, not a blank.** A date of
  "31/31/2026" or an amount of "abc" rejects the record with the field named.
  The screen parsers read those as absent — for a file someone is watching,
  a warning; for a feed nobody is watching, a silent loss. Absent and zero
  stay different claims: an empty cell is absent; "0" is zero.
* **Duplicates.** The same employee twice with identical values: the second is
  skipped and said so. Twice with different values: both are rejected, since
  which one is right is not something the product can know.
* **Identifiers keep their spelling.** Records are read as text, so "00123"
  stays "00123".
* **A salary register is all or nothing.** Validation reads a register as a
  whole — a register missing the rejected rows would report those people as
  unpaid. If any row is rejected, nothing is stored and the run fails with
  every rejected row listed.

Payroll rules are not here. This module moves data; the validation engine
judges it.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ComponentConfig, Entity, StudioRun, User
from app.services import ingest, register_ingest
from app.services.ctc_parse import RESERVED_KEYS as CTC_RESERVED
from app.services.ctc_parse import _parse_date as ctc_parse_date
from app.services.ctc_parse import parse_ctc_frame
from app.services.payroll_parse import normalize_col, suggested_mapping
from app.services.studio import runs
from app.services.workforce_parse import (
    ATTENDANCE_ALIASES,
    BOOLEAN_FIELDS,
    DATE_FIELDS,
    DECIMAL_FIELDS,
    EMPLOYEE_MASTER_ALIASES,
    build_header_map,
    parse_attendance,
    parse_date,
    parse_decimal,
    parse_employee_master,
)

logger = logging.getLogger("payroll.studio")

KINDS = ("employee_master", "ctc", "attendance", "salary_register")
LABELS = {
    "employee_master": "Employee master",
    "ctc": "CTC (current and historical)",
    "attendance": "Attendance",
    "salary_register": "Salary register",
}

#: Keys a record may carry that are about the record, not the employee.
META_KEYS = ("_source_record_id", "__source_row__", "_extra")
ROW_KEY = "__pol_row__"

#: Register fields that hold amounts or day counts. A value in one of these
#: that is not a number is rejected — never read as zero, never as text.
REGISTER_AMOUNT_FIELDS = {
    "total_days", "paid_days", "lop_days", "gross", "total_deductions", "net", "pf_employee",
    "pf_employer", "esic_employee", "esic_employer", "pt", "lwf_employee", "lwf_employer", "tds",
    "arrear_days", "arrear_months", "increment_arrear", "increment_arrear_total",
    "previous_months_lop_days", "notice_period_recovery", "loan_recovery", "pf_eps", "bonus", "gratuity",
}
_ID_KEYS = ("employee_id", "emp_id", "employee_code")


class ImportRefused(Exception):
    """A batch that cannot be processed at all (as opposed to rejected rows)."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "-", "na", "n/a"}


def _as_text_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Records as a frame of text, so no identifier loses a leading zero."""
    rows = [{k: (v if v is None or isinstance(v, (str, bool)) else str(v)) for k, v in r.items()} for r in records]
    frame = pd.DataFrame(rows, dtype=object)
    # A column one record lacks is absent for it — None, never NaN, which
    # reads as a truthy float to the parsers downstream.
    return frame.astype(object).where(pd.notna(frame), None)


def _canonical(clean: dict[str, Any], header_map: dict[str, str]) -> dict[str, Any]:
    """One record's fields under canonical names, so a batch mixing emp_id and
    employee_id reads every record the same way."""
    out: dict[str, Any] = {}
    for key, value in clean.items():
        out[header_map.get(key, key)] = value
    return out


# ---------------------------------------------------------------------------
# Shape checks at submission — before anything is queued
# ---------------------------------------------------------------------------
def check_submission(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """Validate the envelope of an import request. Returns normalised options."""
    if kind not in KINDS:
        raise ValueError(f"Unknown import type '{kind}'. Use one of: {', '.join(KINDS)}.")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("'records' must be a non-empty list of objects.")
    if len(records) > settings.integration_max_records:
        raise ValueError(
            f"A batch may hold at most {settings.integration_max_records:,} records; this one has "
            f"{len(records):,}. Split it, using the same batch_id with a suffix."
        )
    mode = body.get("mode") or ("upsert" if kind != "salary_register" else "replace")
    if kind in ("employee_master", "attendance") and mode not in ingest.MODES:
        raise ValueError("'mode' must be 'upsert' or 'replace'.")
    if kind == "ctc" and mode != "upsert":
        raise ValueError("CTC imports are always 'upsert': each record is kept at its own effective date.")
    if kind == "salary_register" and mode != "replace":
        raise ValueError("A salary register is always 'replace': the month's register is the batch.")

    def _month(field: str, required: bool) -> str | None:
        raw = body.get(field)
        if raw in (None, ""):
            if required:
                raise ValueError(f"'{field}' is required for a {LABELS[kind].lower()} import (YYYY-MM-DD).")
            return None
        try:
            return date.fromisoformat(str(raw)).replace(day=1).isoformat()
        except ValueError:
            raise ValueError(f"'{field}' must be a date (YYYY-MM-DD).")

    options: dict[str, Any] = {"mode": mode}
    if kind == "employee_master":
        options["effective_from"] = _month("effective_from", True)
    elif kind == "attendance":
        options["period_month"] = _month("period_month", True)
    elif kind == "ctc":
        raw = body.get("default_effective_from")
        if raw not in (None, ""):
            try:
                options["default_effective_from"] = date.fromisoformat(str(raw)).isoformat()
            except ValueError:
                raise ValueError("'default_effective_from' must be a date (YYYY-MM-DD).")
    elif kind == "salary_register":
        options["period_month"] = _month("period_month", True)
        run_type = body.get("run_type") or "regular"
        if run_type not in ("regular", "arrears", "increment_arrears", "full_and_final", "bonus"):
            raise ValueError("'run_type' must be regular, arrears, increment_arrears, full_and_final or bonus.")
        options["run_type"] = run_type
        mapping = body.get("column_mapping")
        if mapping is not None and not isinstance(mapping, dict):
            raise ValueError("'column_mapping' must be an object of source column → field.")
        options["column_mapping"] = mapping
        options["validate"] = bool(body.get("validate", False))
        options["allow_missing_components"] = bool(body.get("allow_missing_components", False))
    return options


# ---------------------------------------------------------------------------
# Processing — in the worker
# ---------------------------------------------------------------------------
def _number_rows(records: list[Any]) -> list[tuple[int, Any]]:
    """Row numbers as the source had them — kept through mapping."""
    return [(r.get("__source_row__", i) if isinstance(r, dict) else i, r) for i, r in enumerate(records, start=1)]


def _meta_of(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    clean = {k: v for k, v in record.items() if k not in META_KEYS}
    meta = {k: record[k] for k in META_KEYS if k in record}
    return clean, meta


def _lineage_base(run: StudioRun) -> dict[str, Any]:
    return {
        "channel": run.trigger if run.trigger != "api" else "api",
        "run_id": str(run.id),
        "source_system": run.source_system,
        "source_object": run.source_object,
        "batch_id": run.batch_id,
        "mapping_version": (run.versions or {}).get("mapping"),
        "imported_by": run.actor_label,
        "imported_at": datetime.now(UTC).isoformat(),
    }


def _dedupe(
    db: Session, run: StudioRun, parsed: list[dict[str, Any]], key_of, retain: int
) -> tuple[list[dict[str, Any]], int, int]:
    """Apply the duplicate policy. Returns (kept, rejected, skipped)."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    for record in parsed:
        groups.setdefault(key_of(record), []).append(record)
    kept: list[dict[str, Any]] = []
    rejected = skipped = 0

    def comparable(r: dict[str, Any]) -> str:
        return json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, sort_keys=True, default=str)

    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        if len({comparable(r) for r in group}) == 1:
            kept.append(group[0])
            for dup in group[1:]:
                runs.reject(db, run, row_number=dup["_row"], code="duplicate_identical",
                            message=f"Same record as row {group[0]['_row']}; kept once.",
                            record=dup.get("_raw"), record_key=str(key), disposition="skipped",
                            retain_days=retain)
                skipped += 1
            continue
        rows = ", ".join(str(r["_row"]) for r in group)
        for dup in group:
            runs.reject(db, run, row_number=dup["_row"], code="duplicate_conflict",
                        message=f"{key} appears in rows {rows} with different values. None were "
                                f"imported — send one record for {key}.",
                        record=dup.get("_raw"), record_key=str(key), retain_days=retain)
            rejected += 1
    kept.sort(key=lambda r: r["_row"])
    return kept, rejected, skipped


def _workforce(db: Session, run: StudioRun, entity: Entity, user: User, records: list[Any], kind: str) -> dict[str, Any]:
    aliases = EMPLOYEE_MASTER_ALIASES if kind == "employee_master" else ATTENDANCE_ALIASES
    parser = parse_employee_master if kind == "employee_master" else parse_attendance
    retain = settings.studio_rejection_retention_days
    rejected = 0
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []

    for row, record in _number_rows(records):
        if not isinstance(record, dict):
            runs.reject(db, run, row_number=row, code="invalid_record",
                        message="A record must be an object of field → value.", record=None,
                        retain_days=retain)
            rejected += 1
            continue
        clean, meta = _meta_of(record)
        header_map = build_header_map(list(clean.keys()), aliases)
        id_col = next((c for c, f in header_map.items() if f == "employee_id"), None)
        if id_col is None or _blank(clean.get(id_col)):
            runs.reject(db, run, row_number=row, code="missing_employee_id",
                        message="No employee id. Send it as employee_id (or a recognised alias).",
                        record=record, field="employee_id", retain_days=retain)
            rejected += 1
            continue
        problem = None
        for column, canonical in header_map.items():
            value = clean.get(column)
            if _blank(value):
                continue
            if canonical in DATE_FIELDS and parse_date(value) is None:
                problem = ("invalid_date", column, f"{column} “{value}” is not a date this import can read "
                           "(use YYYY-MM-DD).")
            elif canonical in DECIMAL_FIELDS and parse_decimal(value) is None:
                problem = ("invalid_number", column, f"{column} “{value}” is not a number.")
            elif canonical in BOOLEAN_FIELDS:
                from app.services.pf_basis import parse_flag

                if parse_flag(value) is None:
                    problem = ("invalid_value", column, f"{column} “{value}” is not a yes/no value.")
            if problem:
                break
        if problem:
            runs.reject(db, run, row_number=row, code=problem[0], field=problem[1], message=problem[2],
                        record=record, record_key=str(clean.get(id_col)).strip(), retain_days=retain)
            rejected += 1
            continue
        candidates.append((row, _canonical(clean, header_map), record | meta))

    parsed_all: list[dict[str, Any]] = []
    if candidates:
        frame = _as_text_frame([{**clean, ROW_KEY: str(row)} for row, clean, _ in candidates])
        parsed, _, _ = parser(frame)
        raw_by_row = {row: raw for row, _, raw in candidates}
        for record in parsed:
            extra = dict(record.get("extra") or {})
            row = int(extra.pop(normalize_col(ROW_KEY)))
            extra.update(raw_by_row[row].get("_extra") or {})
            record["extra"] = extra
            record["_row"] = row
            record["_raw"] = raw_by_row[row]
            record["_source_ref"] = {"record_id": raw_by_row[row].get("_source_record_id")}
            parsed_all.append(record)
        # Belt and braces: a candidate the parser did not return is reported,
        # never lost.
        returned = {r["_row"] for r in parsed_all}
        for row, _, raw in candidates:
            if row not in returned:
                runs.reject(db, run, row_number=row, code="unreadable_record",
                            message="This record could not be read.", record=raw, retain_days=retain)
                rejected += 1

    kept, dup_rejected, skipped = _dedupe(db, run, parsed_all, lambda r: r["employee_id"], retain)
    rejected += dup_rejected
    counts = {"received": len(records), "rejected": rejected, "skipped": skipped, "accepted": len(kept)}
    if not kept:
        return {"counts": counts, "result": None}

    options = run.options or {}
    lineage = _lineage_base(run)
    if kind == "employee_master":
        result = ingest.commit_master(
            db, entity=entity, user=user, effective_from=date.fromisoformat(options["effective_from"]),
            records=kept, filename=run.source_object or f"api:{run.batch_id or run.id}",
            mode=options.get("mode", "upsert"), lineage=lineage,
        )
        ref = {"master_upload_id": str(result["upload"].id)}
    else:
        result = ingest.commit_attendance(
            db, entity=entity, user=user, period_month=date.fromisoformat(options["period_month"]),
            records=kept, filename=run.source_object or f"api:{run.batch_id or run.id}",
            mode=options.get("mode", "upsert"), lineage=lineage,
        )
        ref = {"attendance_register_id": str(result["register"].id)}
    counts.update(result["counts"])
    return {"counts": counts, "result": ref}


def _ctc(db: Session, run: StudioRun, entity: Entity, user: User, records: list[Any]) -> dict[str, Any]:
    retain = settings.studio_rejection_retention_days
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise ImportRefused("configuration", "No salary components are configured for this company. "
                                             "Configure them before importing CTC.")
    component_keys = {normalize_col(c.component_name) for c in comps}
    default_eff = (run.options or {}).get("default_effective_from")
    default_eff_d = date.fromisoformat(default_eff) if default_eff else None
    rejected = 0
    ignored: set[str] = set()
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []

    for row, record in _number_rows(records):
        if not isinstance(record, dict):
            runs.reject(db, run, row_number=row, code="invalid_record",
                        message="A record must be an object of field → value.", record=None, retain_days=retain)
            rejected += 1
            continue
        clean, meta = _meta_of(record)
        norm = {normalize_col(k): v for k, v in clean.items()}
        eid = next((norm[k] for k in _ID_KEYS if not _blank(norm.get(k))), None)
        if eid is None:
            runs.reject(db, run, row_number=row, code="missing_employee_id", field="employee_id",
                        message="No employee id.", record=record, retain_days=retain)
            rejected += 1
            continue
        eff_raw = next((norm[k] for k in ("effective_from", "effective_date", "ctc_effective_from")
                        if not _blank(norm.get(k))), None)
        if eff_raw is None and default_eff_d is None:
            runs.reject(db, run, row_number=row, code="missing_effective_from", field="effective_from",
                        message="No effective date, and the batch gives no default_effective_from.",
                        record=record, record_key=str(eid), retain_days=retain)
            rejected += 1
            continue
        if eff_raw is not None and ctc_parse_date(eff_raw) is None:
            runs.reject(db, run, row_number=row, code="invalid_date", field="effective_from",
                        message=f"effective_from “{eff_raw}” is not a date (use YYYY-MM-DD).",
                        record=record, record_key=str(eid), retain_days=retain)
            rejected += 1
            continue
        bad = None
        for key, value in norm.items():
            if key in component_keys or key in ("annual_ctc", "ctc"):
                if not _blank(value) and parse_decimal(value) is None:
                    bad = key
                    break
            elif key not in CTC_RESERVED and not key.startswith("_"):
                ignored.add(key)
        if bad:
            runs.reject(db, run, row_number=row, code="invalid_number", field=bad,
                        message=f"{bad} “{norm[bad]}” is not an amount. Nothing was assumed for it.",
                        record=record, record_key=str(eid), retain_days=retain)
            rejected += 1
            continue
        canonical = {k: v for k, v in norm.items() if k not in _ID_KEYS
                     and k not in ("effective_from", "effective_date", "ctc_effective_from")}
        canonical["employee_id"] = str(eid).strip()
        if eff_raw is not None:
            canonical["effective_from"] = eff_raw
        candidates.append((row, canonical, record | meta))

    parsed_all: list[dict[str, Any]] = []
    if candidates:
        _, parsed = parse_ctc_frame(_as_text_frame([c for _, c, _ in candidates]), component_keys, default_eff_d)
        # Every candidate has an id and a readable date, so the parse returns
        # exactly one record per candidate, in order. If it ever does not, the
        # batch stops rather than pairing records with the wrong rows.
        if len(parsed) != len(candidates):
            raise ImportRefused("internal", "CTC records could not be matched to their rows.")
        for (row, _, raw), record in zip(candidates, parsed, strict=True):
            record["_row"] = row
            record["_raw"] = raw
            record["_source_ref"] = {"record_id": raw.get("_source_record_id")}
            parsed_all.append(record)

    kept, dup_rejected, skipped = _dedupe(
        db, run, parsed_all, lambda r: f"{r['employee_id']} @ {r['effective_from']}", retain
    )
    rejected += dup_rejected
    counts = {"received": len(records), "rejected": rejected, "skipped": skipped, "accepted": len(kept)}
    noted = {"ignored_columns": sorted(ignored)[:50]} if ignored else {}
    if not kept:
        return {"counts": counts, "result": noted or None}
    result = ingest.commit_ctc(
        db, entity=entity, user=user, records=kept,
        filename=run.source_object or f"api:{run.batch_id or run.id}",
        default_effective_from=default_eff_d, lineage=_lineage_base(run),
    )
    counts.update(result["counts"])
    return {"counts": counts, "result": {**noted, "ctc_upload_id": str(result["upload"].id)}}


def _register(db: Session, run: StudioRun, entity: Entity, user: User, records: list[Any],
              check_only: bool = False) -> dict[str, Any]:
    retain = settings.studio_rejection_retention_days
    options = run.options or {}
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise ImportRefused("configuration", "No salary components are configured for this company. "
                                             "Configure them under Settings → Salary components first.")
    comp_names = {c.component_name for c in comps}
    rejected = 0
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    for _, record in _number_rows(records):
        if isinstance(record, dict):
            keys.update(k for k in record if k not in META_KEYS)
    mapping = options.get("column_mapping") or suggested_mapping(sorted(keys), comp_names)
    component_keys = {normalize_col(c) for c in comp_names}
    numeric_sources = {src for src, dest in mapping.items()
                       if dest in component_keys or dest in REGISTER_AMOUNT_FIELDS
                       or (dest.endswith("_arrear") and dest[:-7] in component_keys)}
    id_sources = [src for src, dest in mapping.items() if dest == "employee_id"]
    seen: dict[str, int] = {}
    for row, record in _number_rows(records):
        if not isinstance(record, dict):
            runs.reject(db, run, row_number=row, code="invalid_record",
                        message="A record must be an object of field → value.", record=None, retain_days=retain)
            rejected += 1
            continue
        clean, _ = _meta_of(record)
        eid = next((clean[s] for s in id_sources if not _blank(clean.get(s))), None)
        if eid is None:
            runs.reject(db, run, row_number=row, code="missing_employee_id", field="employee_id",
                        message="No employee id.", record=record, retain_days=retain)
            rejected += 1
            continue
        eid = str(eid).strip()
        if eid in seen:
            runs.reject(db, run, row_number=row, code="duplicate_employee", field="employee_id",
                        message=f"{eid} already appears at row {seen[eid]}. A register has one row per employee.",
                        record=record, record_key=eid, retain_days=retain)
            rejected += 1
            continue
        seen[eid] = row
        bad = next((s for s in numeric_sources if not _blank(clean.get(s)) and parse_decimal(clean.get(s)) is None), None)
        if bad:
            runs.reject(db, run, row_number=row, code="invalid_number", field=bad,
                        message=f"{bad} “{clean.get(bad)}” is not an amount.", record=record, record_key=eid,
                        retain_days=retain)
            rejected += 1
            continue
        rows.append(clean)

    counts = {"received": len(records), "rejected": rejected, "skipped": 0}
    if rejected:
        counts["accepted"] = 0
        raise _AllOrNothing(counts, f"{rejected} of {len(records)} rows were rejected, so no rows were stored. "
                                    "A register is validated as a whole; send it again with every row corrected.")
    if check_only:
        mapped = {normalize_col(v) for v in mapping.values()}
        missing_components = sorted(
            c for c in comp_names
            if normalize_col(c) not in mapped and not options.get("allow_missing_components")
        )
        if missing_components:
            raise ImportRefused("input", "The register has no column for configured component(s): "
                                + ", ".join(missing_components[:10]) + ". Add or map them, or send "
                                "allow_missing_components: true if absent means zero.")
        counts.update({"accepted": len(rows), "created": len(rows), "updated": 0, "unchanged": 0})
        return {"counts": counts, "result": {"column_mapping": mapping}}
    identifier_sources = {src for src, dest in mapping.items() if dest == "employee_id"}
    typed = []
    for clean in rows:
        out = {}
        for key, value in clean.items():
            if key in numeric_sources:
                out[key] = None if _blank(value) else float(parse_decimal(value))
            elif key in identifier_sources or value is None or isinstance(value, str):
                out[key] = value if value is None else str(value).strip()
            else:
                out[key] = value
        typed.append(out)
    df = pd.DataFrame(typed, dtype=object)
    df = df.astype(object).where(pd.notna(df), None)
    content = json.dumps(records, sort_keys=True, default=str, separators=(",", ":")).encode()
    period = date.fromisoformat(options["period_month"])
    try:
        result = register_ingest.ingest_register(
            db, entity=entity, user=user, df=df, filename=run.source_object or f"api:{run.batch_id or run.id}",
            content=content, run_type=options.get("run_type", "regular"), period_month=period,
            # A component column the register leaves out is missing, not zero,
            # unless the caller says in so many words that absent means zero.
            strict=not options.get("allow_missing_components", False),
            column_mapping=mapping, channel="api",
        )
    except ValueError as exc:
        raise ImportRefused("input", f"The column mapping could not be applied: {exc}")
    if result["missing"]:
        raise ImportRefused("input", "The register is missing required columns: "
                            + ", ".join(result["missing"][:10]) + ". Add or map them and send it again.")
    counts.update({"accepted": len(rows), "created": len(rows), "updated": 0, "unchanged": 0})
    ref = {"register_upload_id": str(result["upload"].id),
           "register_id": str(result["register_id"]) if result["register_id"] else None,
           "warnings": result["warnings"][:20]}
    if options.get("validate"):
        from app.services import validation_jobs as jobs

        try:
            job = jobs.enqueue(
                db, entity_id=entity.id, user_id=user.id, period_month=period,
                register_id=result["upload"].register_id, upload_id=result["upload"].id,
                run_type=options.get("run_type", "regular"), params={},
            )
            job.employee_total = result["upload"].row_count
        except jobs.AlreadyQueued as exc:
            job = exc.job
            ref["validation_already_queued"] = True
        run.validation_job_id = job.id
    return {"counts": counts, "result": ref}


class _Cancelled(Exception):
    """A person cancelled the run while it was working."""


def _stop_if_cancelled(db: Session, run: StudioRun) -> None:
    """Raise if a cancel was requested since the run started.

    Read fresh, not from ``run``: the request arrives in another transaction.
    Nothing is committed until the run finishes, so stopping here keeps nothing.
    The run's own row is left untouched until then, so the cancel request is
    never kept waiting on this transaction's lock.
    """
    requested = (
        db.query(StudioRun.cancel_requested_at).filter(StudioRun.id == run.id).scalar()
    )
    if requested is not None:
        raise _Cancelled()


class _AllOrNothing(Exception):
    def __init__(self, counts: dict[str, int], message: str):
        super().__init__(message)
        self.counts = counts
        self.message = message


def process(db: Session, run: StudioRun) -> StudioRun:
    """Run one claimed import to completion. Commits."""
    records = runs.ungz(run.payload_gz)
    if records is None:
        runs.finish(db, run, "failed", error_category="internal",
                    error_message="The staged records no longer exist.")
        db.commit()
        return run
    return ingest_records(db, run, records)


def _apply_mapping(db: Session, run: StudioRun, records: list[Any]) -> tuple[list[Any], int]:
    """Map records with the run's mapping version. Returns (survivors, rejected)."""
    mapping_id = (run.versions or {}).get("mapping_id")
    if not mapping_id:
        return records, 0
    import uuid as _uuid

    from app.models import StudioMapping
    from app.services.studio import mapping as engine

    version = db.get(StudioMapping, _uuid.UUID(str(mapping_id)))
    if version is None:
        raise ImportRefused("configuration", "The mapping version this run was started with no longer exists.")
    retain = settings.studio_rejection_retention_days
    survivors: list[Any] = []
    rejected = 0
    for m in engine.apply(version.spec, records):
        if m.output is None:
            first = m.errors[0] if m.errors else {"code": "invalid_record", "field": "", "message": "Not mapped."}
            runs.reject(db, run, row_number=m.row, code=first["code"], field=first.get("field") or None,
                        message="; ".join(e["message"] for e in m.errors) or first["message"],
                        record=m.raw if isinstance(m.raw, dict) else None,
                        record_key=None, retain_days=retain, source_record_id=m.source_record_id)
            rejected += 1
        else:
            survivors.append({**m.output, "__source_row__": m.row})
    return survivors, rejected


def ingest_records(db: Session, run: StudioRun, records: list[Any], on_committed=None) -> StudioRun:
    """
    Map, check and store records for a run, and finish it. Commits once.

    ``on_committed(db, run, counts)`` runs inside the same transaction as the
    stored records and the finished run — so a sync checkpoint it advances can
    never get ahead of the data it describes.
    """
    entity = db.get(Entity, run.entity_id)
    user = db.get(User, run.actor_user_id)
    if entity is None or user is None:
        runs.finish(db, run, "failed", error_category="internal",
                    error_message="The company or the actor no longer exists.")
        db.commit()
        return run
    runs.heartbeat(db, run, "checking")
    received = len(records)
    try:
        mapped, mapping_rejected = _apply_mapping(db, run, records)
        _stop_if_cancelled(db, run)
        if mapping_rejected and run.object_type == "salary_register":
            raise _AllOrNothing(
                {"received": received, "accepted": 0, "rejected": mapping_rejected, "skipped": 0},
                f"{mapping_rejected} of {received} rows could not be mapped, so no rows were stored. "
                "A register is validated as a whole.")
        if run.object_type in ("employee_master", "attendance"):
            outcome = _workforce(db, run, entity, user, mapped, run.object_type)
        elif run.object_type == "ctc":
            outcome = _ctc(db, run, entity, user, mapped)
        elif run.object_type == "salary_register":
            outcome = _register(db, run, entity, user, mapped)
        else:
            raise ImportRefused("input", f"Unknown import type {run.object_type}.")
        _stop_if_cancelled(db, run)
    except _Cancelled:
        # Everything this run wrote is still uncommitted: roll it all back,
        # rejections included, and record that nothing was kept.
        db.rollback()
        run = db.get(StudioRun, run.id)
        runs.finish(db, run, "cancelled", counts={"received": received, "accepted": 0, "rejected": 0},
                    error_category="cancelled",
                    error_message="Cancelled while running. Nothing from this run was stored.")
        db.commit()
        return run
    except _AllOrNothing as exc:
        db.flush()
        runs.finish(db, run, "failed", counts=exc.counts, error_category="input", error_message=exc.message)
        db.commit()
        return run
    except ImportRefused as exc:
        # Nothing of this batch is kept, rejections included: the batch was
        # refused as a whole, and a partial list of reasons would mislead.
        db.rollback()
        run = db.get(StudioRun, run.id)
        from app.models import StudioRunRejection

        db.query(StudioRunRejection).filter(StudioRunRejection.run_id == run.id).delete()
        runs.finish(db, run, "failed", counts={"received": received, "rejected": 0, "accepted": 0},
                    error_category=exc.category, error_message=exc.message)
        db.commit()
        return run

    counts = outcome["counts"]
    counts["received"] = received
    counts["rejected"] = counts.get("rejected", 0) + mapping_rejected
    for key in ("created", "updated", "unchanged", "removed"):
        counts.setdefault(key, 0)
    if counts["received"] and counts.get("accepted", 0) == 0:
        status = "failed"
        category, message = "input", "Every record was rejected or skipped; nothing was stored."
    elif counts.get("rejected", 0):
        status = "partially_completed"
        category = "input"
        message = f"{counts['rejected']} record(s) were rejected; the rest were stored."
    else:
        status, category, message = "completed", None, None
    if on_committed is not None:
        on_committed(db, run, counts)
    runs.finish(db, run, status, counts=counts, error_category=category, error_message=message,
                result_ref=outcome.get("result") or {})
    db.commit()
    logger.info("studio %s %s %s: %s", run.kind, run.id, status, counts)
    return run


def retry_rejected(db: Session, run: StudioRun, *, actor: User, actor_label: str, actor_type: str,
                   service_account_id=None, credential_prefix: str | None = None) -> StudioRun:
    """Queue the retained rejected records of a run as a new run of their own."""
    from app.models import StudioRunRejection

    rows = (
        db.query(StudioRunRejection)
        .filter(StudioRunRejection.run_id == run.id, StudioRunRejection.disposition == "rejected",
                StudioRunRejection.retried_in_run_id.is_(None), StudioRunRejection.payload_gz.is_not(None))
        .order_by(StudioRunRejection.row_number)
        .all()
    )
    if not rows:
        raise ValueError("There are no retained rejected records to retry.")
    if run.object_type == "salary_register":
        raise ValueError("A salary register is imported whole. Send the corrected register as a new import.")
    payload = [runs.ungz(r.payload_gz) for r in rows]
    # A retry adds the corrected records to what the first run stored. It never
    # replaces: in "replace" mode the retried few would become the whole
    # version and silently remove every record the first run accepted.
    options = {k: v for k, v in (run.options or {}).items() if k not in ("deletions", "sync_mode", "stream_id")}
    options["mode"] = "upsert"
    versions = dict(run.versions or {})
    if versions.get("mapping_id"):
        # Retry with the mapping in force now, so a corrected mapping is what
        # reads the records again (a version pinned on the run's stream stays
        # pinned). The new run records which version it used.
        from app.models import StudioMapping
        from app.services.studio import profiles

        before = db.get(StudioMapping, uuid.UUID(str(versions["mapping_id"])))
        from app.models import StudioStream

        stream_id = (run.options or {}).get("stream_id")
        stream = db.get(StudioStream, uuid.UUID(stream_id)) if stream_id else None
        pinned = stream.mapping_version if stream is not None else None
        current = profiles.in_force(db, run.entity_id, before.key, pinned=pinned) if before is not None else None
        if current is None:
            raise ValueError("The mapping these records were read with has no published version in force. Publish one, then retry.")
        versions = {**versions, "mapping": f"{current.key} v{current.version}", "mapping_id": str(current.id)}
    new = runs.create(
        db, org_id=run.org_id, entity_id=run.entity_id, kind="import", object_type=run.object_type,
        actor_type=actor_type, actor_user_id=actor.id, actor_label=actor_label, trigger="retry",
        environment=run.environment, service_account_id=service_account_id,
        credential_prefix=credential_prefix, source_system=run.source_system,
        source_object=run.source_object, batch_id=(run.batch_id or str(run.id)[:8]) + "-retry",
        period_month=run.period_month, effective_from=run.effective_from, options=options,
        payload=payload, versions=versions, retry_of_run_id=run.id, connection_id=run.connection_id,
    )
    for r in rows:
        r.retried_in_run_id = new.id
    return new


def expected_counts_ok(counts: dict[str, int]) -> bool:
    """The reconciliation identities every import must satisfy."""
    received = counts.get("received", 0)
    accepted = counts.get("accepted", 0)
    return (
        received == accepted + counts.get("rejected", 0) + counts.get("skipped", 0)
        and (accepted == 0 or accepted == counts.get("created", 0) + counts.get("updated", 0) + counts.get("unchanged", 0))
    )


def to_decimal(value: Any) -> Decimal | None:
    return parse_decimal(value)


def dry_run(
    db: Session,
    *,
    entity: Entity,
    user: User,
    actor_label: str,
    actor_type: str,
    kind: str,
    body: dict[str, Any],
    environment: str = "production",
    max_rejections: int = 500,
) -> dict[str, Any]:
    """
    What an import would do, without doing it.

    Runs the same checks and the same commit as a real import inside a
    transaction that is then rolled back, so the counts — including created
    versus updated — are the counts the real import would report. A salary
    register is checked row by row and for its columns; storing it is not
    rehearsed, because storing a register is not a transaction that can be
    undone.
    """
    from app.models import StudioRunRejection

    options = check_submission(kind, body)
    records = body["records"]
    run = runs.create(
        db, org_id=entity.org_id, entity_id=entity.id, kind="import", object_type=kind,
        actor_type=actor_type, actor_user_id=user.id, actor_label=actor_label, trigger="api",
        environment=environment, options=options, status="running",
        source_system=body.get("source_system"), source_object=body.get("source_object"),
        batch_id=body.get("batch_id"),
    )
    if body.get("mapping_key"):
        from app.services.studio import profiles

        version = profiles.in_force(db, entity.id, body["mapping_key"])
        if version is None or version.object_type != kind:
            db.rollback()
            raise ValueError(f"No published {kind} mapping called {body['mapping_key']} is in force.")
        run.versions = {"mapping": f"{version.key} v{version.version}", "mapping_id": str(version.id)}
    error = None
    try:
        try:
            mapped, mapping_rejected = _apply_mapping(db, run, records)
            if mapping_rejected and kind == "salary_register":
                raise _AllOrNothing({"received": len(records), "accepted": 0, "rejected": mapping_rejected,
                                     "skipped": 0}, f"{mapping_rejected} rows could not be mapped, so no rows "
                                                    "would be stored.")
            if kind in ("employee_master", "attendance"):
                outcome = _workforce(db, run, entity, user, mapped, kind)
            elif kind == "ctc":
                outcome = _ctc(db, run, entity, user, mapped)
            else:
                outcome = _register(db, run, entity, user, mapped, check_only=True)
            counts = outcome["counts"]
            counts["received"] = len(records)
            counts["rejected"] = counts.get("rejected", 0) + mapping_rejected
        except _AllOrNothing as exc:
            counts, error = exc.counts, {"category": "input", "message": exc.message}
        except ImportRefused as exc:
            counts = {"received": len(records), "accepted": 0, "rejected": 0, "skipped": 0}
            error = {"category": exc.category, "message": exc.message}
        db.flush()
        rows = (
            db.query(StudioRunRejection)
            .filter(StudioRunRejection.run_id == run.id)
            .order_by(StudioRunRejection.row_number)
            .limit(max_rejections)
            .all()
        )
        rejected = [runs.describe_rejection(r) for r in rows]
        for r in rejected:
            r.pop("id", None)
            r.pop("retain_until", None)
            r.pop("payload_retained", None)
            r.pop("retried_in_run_id", None)
    finally:
        db.rollback()
    for key in ("created", "updated", "unchanged", "removed"):
        counts.setdefault(key, 0)
    return {
        "object_type": kind,
        "options": {k: v for k, v in options.items() if k != "column_mapping"},
        "counts": {k: counts.get(k, 0) for k in runs.COUNT_KEYS},
        "would_store": counts.get("accepted", 0) > 0 and error is None,
        "error": error,
        "rejections": rejected,
        "rejections_truncated": len(rejected) >= max_rejections,
    }


def records_from_file(content: bytes, filename: str, max_rows: int | None = None) -> list[dict[str, Any]]:
    """
    A CSV or Excel file as records of text, exactly as written.

    Everything is read as text — identifiers keep their leading zeros, and no
    number is reinterpreted — because the mapping decides how each field is
    read. Empty cells are absent, not empty strings.
    """
    import io

    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    elif lower.endswith(".xlsx"):
        frame = pd.read_excel(io.BytesIO(content), dtype=str, keep_default_na=False, engine="openpyxl")
    else:
        raise ValueError("Upload a .csv or .xlsx file.")
    limit = max_rows or settings.integration_max_records
    if len(frame) > limit:
        raise ValueError(f"The file has {len(frame):,} rows; at most {limit:,} can be imported at once.")
    return [{str(k): (v if v != "" else None) for k, v in row.items()} for row in frame.to_dict(orient="records")]
