"""
Retention and erasure of payroll personal data.

**Retention.** A company sets how many months of payroll periods it keeps. Every
period older than that is removed, everywhere it is held: the register and its
uploads, validation runs and their findings, attendance, bank files and their
reconciliation, payment-file checks, the month's sign-off. Leavers whose exit is
older than the period leave the employee master and CTC history with it. The
audit trail stays: it is the record that all of this happened.

**Erasure.** One person's data, on the company's request. Their master, CTC and
attendance records are deleted. Where their pay sits inside a month the company
keeps — a register, a run, a finding — the person is replaced by a random token
and every identifier is removed (name, PAN, Aadhaar, UAN, ESI and PF numbers,
bank account, IFSC, date of birth, contact details), so the month's totals still
add up and nothing in them names anyone. The token is not recorded anywhere:
keeping it would keep the link.

Three kinds of record are signed decisions rather than working data, and are
not rewritten: a month's sign-off, a payment-file check and its approval, and
the audit trail. Rewriting them would make them say something other than what
was approved. An erasure names each one that still mentions the person, and
why, and the retention period removes them with their month. Whether keeping
them meets the company's obligations is a question for its legal adviser; the
product does not answer it.

Nothing here is reversible, and nothing happens without an owner's decision.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRegister,
    AttendanceRow,
    AuditEvent,
    BankFile,
    BankFileRow,
    CtcRecord,
    DisbursementApproval,
    DisbursementRun,
    EmployeeRecord,
    Entity,
    ErasureRequest,
    FindingAttachment,
    FindingComment,
    FindingRecord,
    FindingState,
    FindingStateEvent,
    PeriodSignOff,
    ReconException,
    ReconRun,
    RegisterCosting,
    RegisterUpload,
    ReportJob,
    RetentionPolicy,
    SalaryRegister,
    SalaryRegisterRow,
    SignOffEvent,
    StudioRun,
    StudioRunRejection,
    ValidationJob,
    ValidationRun,
    ValidationRunEmployee,
)
from app.services import audit
from app.services.clock import india_today
from app.services.finding_store import fingerprint
from app.services.payroll_parse import normalize_col
from app.services.register_uploads import decode_rows, encode_rows, gzip_json

logger = logging.getLogger("payroll.data_protection")

MIN_MONTHS = 12
MAX_MONTHS = 180
ERASED = "[erased]"

#: Fields that identify a person, as column names arrive after normalisation.
#: Exact names, not substrings: "pan" is inside "company" and "esi" inside
#: "esic_employee", which is an amount.
IDENTITY_KEYS = frozenset({
    "employee_name", "name", "full_name", "first_name", "middle_name", "last_name",
    "father_name", "fathers_name", "spouse_name", "mother_name",
    "pan", "pan_number", "pan_no", "aadhaar", "aadhar", "aadhaar_number", "aadhaar_no",
    "uan", "uan_number", "uan_no", "esi_number", "esi_no", "ip_number", "esic_ip_number",
    "esic_number", "esic_no", "pf_number", "pf_no", "pf_account_number",
    "bank_account", "bank_account_number", "bank_account_no", "account_number", "account_no",
    "ifsc", "ifsc_code", "bank_name", "bank_branch", "beneficiary_name",
    "dob", "date_of_birth", "birth_date",
    "email", "personal_email", "work_email", "email_id", "mobile", "mobile_number", "phone",
    "phone_number", "contact_number", "address", "permanent_address", "current_address",
    "passport_number", "passport_no",
})
EMPLOYEE_ID_KEYS = frozenset({"employee_id", "emp_id", "employee_code", "emp_code", "employee_no"})

#: Findings whose expected or actual value is an identifier (a PAN that failed
#: its format check, a bank account shared by two people).
IDENTITY_RULES = frozenset({"DATA-006", "DATA-007", "DATA-008", "DATA-009", "MST-004", "MST-005"})


class ErasureRefused(Exception):
    """The request cannot be carried out as asked; the message says why."""


def _now() -> datetime:
    return datetime.now(UTC)


def _identity_rule(rule_id: str | None) -> bool:
    rule_id = str(rule_id or "")
    return rule_id.startswith("ID-") or rule_id in IDENTITY_RULES


def _ungz(blob: bytes | None) -> Any:
    return json.loads(gzip.decompress(blob).decode("utf-8")) if blob else None


def _ungz_text(blob: bytes | None) -> str:
    return gzip.decompress(blob).decode("utf-8", errors="replace") if blob else ""


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
def cutoff_for(months: int, today: date | None = None) -> date:
    """The first period kept: ``months`` months back from the current month, inclusive."""
    today = today or india_today()
    index = today.year * 12 + (today.month - 1) - (months - 1)
    return date(index // 12, index % 12 + 1, 1)


def policy_for(db: Session, entity_id) -> RetentionPolicy | None:
    return db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == entity_id).one_or_none()


def set_policy(db: Session, entity: Entity, user: Any, months: int | None, reason: str) -> RetentionPolicy:
    if months is not None and not MIN_MONTHS <= months <= MAX_MONTHS:
        raise ValueError(f"The retention period must be between {MIN_MONTHS} and {MAX_MONTHS} months.")
    policy = policy_for(db, entity.id)
    before = policy.payroll_months if policy else None
    if policy is None:
        policy = RetentionPolicy(org_id=entity.org_id, entity_id=entity.id, last_applied_counts={})
        db.add(policy)
    policy.payroll_months = months
    policy.reason = reason
    policy.set_by_email = getattr(user, "email", None)
    policy.set_at = _now()
    # A new period is applied afresh: the worker runs it on its next pass.
    policy.last_applied_at = None
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user, action="retention.policy_set",
        object_type="retention_policy", object_id=str(entity.id),
        summary=("Payroll data retention set to " + (f"{months} months" if months else "no period (keep everything)")
                 + f". Reason: {reason}"),
        detail={"before": before, "after": months, "reason": reason},
    )
    return policy


@dataclass
class _Periods:
    entity_id: Any
    before: date


def _period_queries(db: Session, p: _Periods) -> dict[str, Any]:
    """Each store's rows older than the cut-off, in an order that deletes children first."""
    e, before = p.entity_id, p.before
    runs = db.query(ValidationRun.id).filter(ValidationRun.entity_id == e, ValidationRun.period_month < before)
    registers = db.query(SalaryRegister.id).filter(SalaryRegister.entity_id == e, SalaryRegister.period_month < before)
    att = db.query(AttendanceRegister.id).filter(AttendanceRegister.entity_id == e, AttendanceRegister.period_month < before)
    files = db.query(BankFile.id).filter(BankFile.entity_id == e, BankFile.period_month < before)
    recon = db.query(ReconRun.id).filter(ReconRun.entity_id == e, ReconRun.period_month < before)
    pay = db.query(DisbursementRun.id).filter(DisbursementRun.entity_id == e, DisbursementRun.period_month < before)
    signoffs = db.query(PeriodSignOff.id).filter(PeriodSignOff.entity_id == e, PeriodSignOff.period_month < before)
    states = db.query(FindingState.id).filter(FindingState.entity_id == e, FindingState.last_seen_period < before)
    return {
        "Validation jobs": db.query(ValidationJob).filter(ValidationJob.entity_id == e, ValidationJob.period_month < before),
        "Findings": db.query(FindingRecord).filter(FindingRecord.run_id.in_(runs.scalar_subquery())),
        "Validation results per employee": db.query(ValidationRunEmployee).filter(
            ValidationRunEmployee.run_id.in_(runs.scalar_subquery())),
        "Validation runs": db.query(ValidationRun).filter(ValidationRun.entity_id == e, ValidationRun.period_month < before),
        "Issue history": db.query(FindingStateEvent).filter(FindingStateEvent.state_id.in_(states.scalar_subquery())),
        "Issue comments": db.query(FindingComment).filter(FindingComment.state_id.in_(states.scalar_subquery())),
        "Issue attachments": db.query(FindingAttachment).filter(FindingAttachment.state_id.in_(states.scalar_subquery())),
        "Issues": db.query(FindingState).filter(FindingState.entity_id == e, FindingState.last_seen_period < before),
        "Register uploads": db.query(RegisterUpload).filter(RegisterUpload.entity_id == e,
                                                            RegisterUpload.period_month < before),
        "Register costings": db.query(RegisterCosting).filter(RegisterCosting.register_id.in_(registers.scalar_subquery())),
        "Register rows": db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id.in_(registers.scalar_subquery())),
        "Salary registers": db.query(SalaryRegister).filter(SalaryRegister.entity_id == e,
                                                            SalaryRegister.period_month < before),
        "Attendance rows": db.query(AttendanceRow).filter(AttendanceRow.register_id.in_(att.scalar_subquery())),
        "Attendance registers": db.query(AttendanceRegister).filter(AttendanceRegister.entity_id == e,
                                                                    AttendanceRegister.period_month < before),
        "Reconciliation exceptions": db.query(ReconException).filter(ReconException.run_id.in_(recon.scalar_subquery())),
        "Reconciliations": db.query(ReconRun).filter(ReconRun.entity_id == e, ReconRun.period_month < before),
        "Bank file rows": db.query(BankFileRow).filter(BankFileRow.file_id.in_(files.scalar_subquery())),
        "Bank files": db.query(BankFile).filter(BankFile.entity_id == e, BankFile.period_month < before),
        "Payment-file approvals": db.query(DisbursementApproval).filter(
            DisbursementApproval.run_id.in_(pay.scalar_subquery())),
        "Payment-file checks": db.query(DisbursementRun).filter(DisbursementRun.entity_id == e,
                                                                DisbursementRun.period_month < before),
        "Sign-off history": db.query(SignOffEvent).filter(SignOffEvent.signoff_id.in_(signoffs.scalar_subquery())),
        "Month sign-offs": db.query(PeriodSignOff).filter(PeriodSignOff.entity_id == e,
                                                          PeriodSignOff.period_month < before),
    }


def _leavers(db: Session, entity_id, before: date) -> list[str]:
    """Employees whose latest master record shows an exit before the cut-off."""
    latest = (
        db.query(EmployeeRecord.employee_id, func.max(EmployeeRecord.effective_from).label("latest"))
        .filter(EmployeeRecord.entity_id == entity_id)
        .group_by(EmployeeRecord.employee_id)
        .subquery()
    )
    rows = (
        db.query(EmployeeRecord.employee_id)
        .join(latest, (EmployeeRecord.employee_id == latest.c.employee_id)
              & (EmployeeRecord.effective_from == latest.c.latest))
        .filter(EmployeeRecord.entity_id == entity_id, EmployeeRecord.date_of_exit.is_not(None),
                EmployeeRecord.date_of_exit < before)
        .all()
    )
    return sorted({r[0] for r in rows})


def _leaver_queries(db: Session, entity_id, leavers: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for start in range(0, len(leavers), 500):
        chunk = leavers[start:start + 500]
        for label, query in (
            ("Employee master (leavers)", db.query(EmployeeRecord).filter(
                EmployeeRecord.entity_id == entity_id, EmployeeRecord.employee_id.in_(chunk))),
            ("CTC history (leavers)", db.query(CtcRecord).filter(
                CtcRecord.entity_id == entity_id, CtcRecord.employee_id.in_(chunk))),
        ):
            out.setdefault(label, []).append(query)
    return out


def retention_plan(db: Session, entity_id, months: int, today: date | None = None) -> dict[str, Any]:
    """What applying ``months`` today would remove, by store. Nothing is written."""
    before = cutoff_for(months, today)
    counts = {label: q.count() for label, q in _period_queries(db, _Periods(entity_id, before)).items()}
    for label, queries in _leaver_queries(db, entity_id, _leavers(db, entity_id, before)).items():
        counts[label] = sum(q.count() for q in queries)
    return {"keep_from": before.isoformat(), "counts": {k: v for k, v in counts.items() if v}}


def apply_retention(db: Session, entity: Entity, policy: RetentionPolicy, user: Any = None,
                    today: date | None = None) -> dict[str, int]:
    """Remove everything older than the policy allows. Commits."""
    months = policy.payroll_months
    if not months:
        return {}
    before = cutoff_for(months, today)
    leavers = _leavers(db, entity.id, before)
    counts: dict[str, int] = {}
    for label, query in _period_queries(db, _Periods(entity.id, before)).items():
        n = query.delete(synchronize_session=False)
        if n:
            counts[label] = n
    for label, queries in _leaver_queries(db, entity.id, leavers).items():
        n = sum(q.delete(synchronize_session=False) for q in queries)
        if n:
            counts[label] = n
    # Copies of imported records past the window go with their month.
    cutoff_dt = datetime(before.year, before.month, 1, tzinfo=UTC)
    n = (db.query(StudioRun)
         .filter(StudioRun.entity_id == entity.id, StudioRun.created_at < cutoff_dt, StudioRun.payload_gz.is_not(None),
                 StudioRun.status.notin_(("queued", "running")))
         .update({StudioRun.payload_gz: None}, synchronize_session=False))
    if n:
        counts["Imported record copies"] = n
    policy.last_applied_at = _now()
    policy.last_applied_counts = {"keep_from": before.isoformat(), "counts": counts}
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user, action="retention.applied",
        object_type="retention_policy", object_id=str(entity.id),
        summary=(f"Retention applied ({months} months, keeping from {before:%b %Y}): "
                 + (", ".join(f"{v} {k.lower()}" for k, v in counts.items()) if counts else "nothing was older")),
        detail={"keep_from": before.isoformat(), "counts": counts, "automatic": user is None},
    )
    db.commit()
    return counts


def apply_due(db: Session, today: date | None = None) -> int:
    """Apply every company's policy at most once a day. Called from the worker's housekeeping."""
    today = today or india_today()
    applied = 0
    policies = db.query(RetentionPolicy).filter(RetentionPolicy.payroll_months.is_not(None)).all()
    for policy in policies:
        last = policy.last_applied_at
        if last is not None and last.date() >= today:
            continue
        entity = db.get(Entity, policy.entity_id)
        if entity is None:
            continue
        try:
            apply_retention(db, entity, policy, None, today)
            applied += 1
        except Exception:  # noqa: BLE001 — one company's failure must not stop the others
            db.rollback()
            logger.exception("retention failed for entity %s", policy.entity_id)
    return applied


# ---------------------------------------------------------------------------
# Erasure
# ---------------------------------------------------------------------------
class _Scrubber:
    """Removes one person from text and JSON."""

    def __init__(self, employee_id: str, token: str, strong: Iterable[str], names: Iterable[str]):
        self.employee_id = employee_id
        self.token = token
        self._id_re = re.compile(rf"(?<![\w-]){re.escape(employee_id)}(?![\w-])")
        strong = sorted({s for s in strong if s and len(s) >= 6}, key=len, reverse=True)
        names = sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True)
        self._strong_re = re.compile("|".join(rf"(?<!\w){re.escape(s)}(?!\w)" for s in strong), re.I) if strong else None
        self._name_re = re.compile("|".join(rf"(?<!\w){re.escape(n)}(?!\w)" for n in names), re.I) if names else None

    def is_person(self, value: Any) -> bool:
        if value is None:
            return False
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].isdigit():   # an Excel number read as a float
            text = text[:-2]
        return text == self.employee_id

    def text(self, value: str | None, names: bool = True) -> str | None:
        if not value:
            return value
        out = self._id_re.sub(self.token, value)
        if self._strong_re is not None:
            out = self._strong_re.sub(ERASED, out)
        if names and self._name_re is not None:
            out = self._name_re.sub(ERASED, out)
        return out

    def value(self, obj: Any, names: bool = True) -> Any:
        if isinstance(obj, dict):
            out = {}
            for key, val in obj.items():
                norm = normalize_col(str(key))
                if norm in IDENTITY_KEYS:
                    continue
                if norm in EMPLOYEE_ID_KEYS and self.is_person(val):
                    out[key] = self.token
                    continue
                out[key] = self.value(val, names)
            if _identity_rule(out.get("rule_id")):
                for field in ("expected_value", "actual_value", "expected", "actual", "reason"):
                    if field in out:
                        out[field] = ERASED
            return out
        if isinstance(obj, list):
            return [self.value(v, names) for v in obj]
        if isinstance(obj, str):
            return self.text(obj, names)
        return obj

    def mentions(self, text: str) -> bool:
        return bool(text) and (self._id_re.search(text) is not None
                               or (self._strong_re is not None and self._strong_re.search(text) is not None))


def _row_is_person(row: dict[str, Any], sc: _Scrubber) -> bool:
    return any(normalize_col(str(k)) in EMPLOYEE_ID_KEYS and sc.is_person(v) for k, v in row.items())


def _identifiers(db: Session, entity_id, employee_id: str) -> tuple[set[str], set[str]]:
    """Every identifier and name the company's data holds for this person."""
    strong: set[str] = set()
    names: set[str] = set()
    for rec in db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == entity_id,
                                                EmployeeRecord.employee_id == employee_id):
        names.add(rec.employee_name or "")
        strong.update(str(v) for v in (rec.pan, rec.aadhaar, rec.uan, rec.pf_number, rec.esic_ip_number,
                                       rec.bank_account) if v)
    for model in (CtcRecord, AttendanceRow, SalaryRegisterRow, BankFileRow, ValidationRunEmployee):
        for (name,) in db.query(model.employee_name).filter(model.entity_id == entity_id,
                                                            model.employee_id == employee_id).distinct():
            names.add(name or "")
    for (account,) in db.query(BankFileRow.account_number).filter(BankFileRow.entity_id == entity_id,
                                                                  BankFileRow.employee_id == employee_id).distinct():
        strong.add(account or "")
    for (dims,) in db.query(SalaryRegisterRow.dimensions).filter(SalaryRegisterRow.entity_id == entity_id,
                                                                 SalaryRegisterRow.employee_id == employee_id):
        for key, val in (dims or {}).items():
            if normalize_col(str(key)) in IDENTITY_KEYS and val not in (None, ""):
                (names if "name" in normalize_col(str(key)) else strong).add(str(val))
    strong.discard("")
    names.discard("")
    return strong, names


def _signed_records(db: Session, entity_id, sc: _Scrubber) -> list[dict[str, Any]]:
    """Records of decisions that still name the person, and why they stay."""
    signoffs = sum(
        1 for (snap,) in db.query(PeriodSignOff.snapshot).filter(PeriodSignOff.entity_id == entity_id)
        if sc.mentions(json.dumps(snap or {}, default=str))
    )
    payments = 0
    for run in db.query(DisbursementRun).filter(DisbursementRun.entity_id == entity_id):
        if sc.mentions(_ungz_text(run.report_gz)) or sc.mentions(_ungz_text(run.paid_gz)):
            payments += 1
    audit_rows = sum(
        1 for (summary, detail) in db.query(AuditEvent.summary, AuditEvent.detail).filter(
            AuditEvent.entity_id == entity_id)
        if sc.mentions(summary or "") or sc.mentions(json.dumps(detail or {}, default=str))
    )
    active = sum(
        1 for run in db.query(StudioRun).filter(StudioRun.entity_id == entity_id,
                                                StudioRun.status.in_(("queued", "running")),
                                                StudioRun.payload_gz.is_not(None))
        if sc.mentions(_ungz_text(run.payload_gz))
    )
    out = []
    if signoffs:
        out.append({"store": "Month sign-offs", "count": signoffs,
                    "why": "The signed record of what was approved for the month. Removed with the month by "
                           "the retention period."})
    if payments:
        out.append({"store": "Payment-file checks", "count": payments,
                    "why": "The record of a salary payment release and its approval. The clean file and paid "
                           "list are cleared after the payment-file window; the check is removed with the "
                           "month by the retention period."})
    if audit_rows:
        out.append({"store": "Audit trail", "count": audit_rows,
                    "why": "Append-only record of who did what, including this erasure. Not rewritten."})
    if active:
        out.append({"store": "Imports in progress", "count": active,
                    "why": "An import still running carries the record; its copy can be cleared once it "
                           "finishes, by erasing again."})
    return out


def erasure_plan(db: Session, entity_id, employee_id: str) -> dict[str, Any]:
    """What an erasure would change, by store, and what would still name the person. Nothing is written."""
    employee_id = (employee_id or "").strip()
    e = entity_id
    counts = {
        "Employee master": db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == e,
                                                           EmployeeRecord.employee_id == employee_id).count(),
        "CTC history": db.query(CtcRecord).filter(CtcRecord.entity_id == e, CtcRecord.employee_id == employee_id).count(),
        "Attendance rows": db.query(AttendanceRow).filter(AttendanceRow.entity_id == e,
                                                          AttendanceRow.employee_id == employee_id).count(),
        "Register rows": db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == e,
                                                            SalaryRegisterRow.employee_id == employee_id).count(),
        "Validation results": db.query(ValidationRunEmployee).filter(
            ValidationRunEmployee.entity_id == e, ValidationRunEmployee.employee_id == employee_id).count(),
        "Findings": db.query(FindingRecord).filter(FindingRecord.entity_id == e,
                                                   FindingRecord.employee_id == employee_id).count(),
        "Issues": db.query(FindingState).filter(FindingState.entity_id == e,
                                                FindingState.employee_id == employee_id).count(),
        "Bank file rows": db.query(BankFileRow).filter(BankFileRow.entity_id == e,
                                                       BankFileRow.employee_id == employee_id).count(),
        "Reconciliation exceptions": db.query(ReconException).filter(
            ReconException.entity_id == e, ReconException.employee_id == employee_id).count(),
    }
    strong, names = _identifiers(db, e, employee_id)
    sc = _Scrubber(employee_id, "ERASED-PREVIEW", strong, names)
    return {"employee_id": employee_id, "counts": {k: v for k, v in counts.items() if v},
            "retained": _signed_records(db, e, sc)}


def erase_employee(db: Session, entity: Entity, user: Any, employee_id: str, reason: str) -> ErasureRequest:
    """Erase one person's data across the company. Commits; cannot be undone."""
    employee_id = (employee_id or "").strip()
    e = entity.id
    if not employee_id:
        raise ErasureRefused("Give the employee ID to erase.")
    if db.query(ValidationJob).filter(ValidationJob.entity_id == e,
                                      ValidationJob.state.in_(("queued", "running"))).first() is not None:
        raise ErasureRefused("A validation is in progress for this company. Erase once it has finished, "
                             "so it cannot write the person back.")
    plan = erasure_plan(db, e, employee_id)
    if not plan["counts"]:
        raise ErasureRefused(f"No data is held for employee ID “{employee_id}” in this company. "
                             "Check the ID exactly as it appears in the register.")

    strong, names = _identifiers(db, e, employee_id)
    token = "ERASED-" + secrets.token_hex(4).upper()
    sc = _Scrubber(employee_id, token, strong, names)
    counts: dict[str, int] = {}

    def bump(label: str, n: int = 1) -> None:
        if n:
            counts[label] = counts.get(label, 0) + n

    # Records about the person and nothing else: deleted.
    for label, model in (("Employee master", EmployeeRecord), ("CTC history", CtcRecord),
                         ("Attendance rows", AttendanceRow)):
        bump(label, db.query(model).filter(model.entity_id == e, model.employee_id == employee_id)
             .delete(synchronize_session=False))

    # Their pay inside months the company keeps: the person replaced by the token.
    for row in db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == e,
                                                  SalaryRegisterRow.employee_id == employee_id):
        row.employee_id = token
        row.employee_name = None
        row.dimensions = sc.value(dict(row.dimensions or {}))
        bump("Register rows")

    for upload_id in [u for (u,) in db.query(RegisterUpload.id).filter(RegisterUpload.entity_id == e)]:
        upload = db.get(RegisterUpload, upload_id)
        rows = decode_rows(upload.rows_gz)
        changed = 0
        for i, row in enumerate(rows):
            if isinstance(row, dict) and _row_is_person(row, sc):
                rows[i] = sc.value(row)
                changed += 1
        if changed:
            upload.rows_gz, upload.rows_sha256 = encode_rows(rows)
            bump("Uploaded register rows", changed)
        db.flush()
        db.expunge(upload)

    for vre in db.query(ValidationRunEmployee).filter(ValidationRunEmployee.entity_id == e,
                                                      ValidationRunEmployee.employee_id == employee_id):
        vre.employee_id = token
        vre.employee_name = None
        vre.detail_gz = gzip_json(sc.value(_ungz(vre.detail_gz)))
        bump("Validation results")

    for rec in db.query(FindingRecord).filter(FindingRecord.entity_id == e, FindingRecord.employee_id == employee_id):
        rec.employee_id = token
        rec.employee_name = None
        rec.fingerprint = fingerprint(e, token, rec.rule_id, rec.component)
        if _identity_rule(rec.rule_id):
            rec.expected_value = rec.actual_value = rec.reason = ERASED
        else:
            rec.expected_value = sc.text(rec.expected_value)
            rec.actual_value = sc.text(rec.actual_value)
            rec.reason = sc.text(rec.reason)
        rec.suggested_fix = sc.text(rec.suggested_fix)
        rec.evidence = sc.value(rec.evidence) if rec.evidence else rec.evidence
        bump("Findings")

    state_ids = []
    for state in db.query(FindingState).filter(FindingState.entity_id == e, FindingState.employee_id == employee_id):
        state.employee_id = token
        state.employee_name = None
        state.fingerprint = fingerprint(e, token, state.rule_id, state.component)
        state_ids.append(state.id)
        bump("Issues")
    if state_ids:
        for comment in db.query(FindingComment).filter(FindingComment.state_id.in_(state_ids)):
            comment.body = sc.text(comment.body) or ""
            bump("Issue comments")
        for event in db.query(FindingStateEvent).filter(FindingStateEvent.state_id.in_(state_ids)):
            event.reason = sc.text(event.reason)
        # Files attached to the person's issues are evidence about the person.
        bump("Issue attachments", db.query(FindingAttachment).filter(FindingAttachment.state_id.in_(state_ids))
             .delete(synchronize_session=False))

    # Other people's findings that name this one (a shared PAN, a shared account).
    like = f"%{employee_id}%"
    for rec in db.query(FindingRecord).filter(FindingRecord.entity_id == e, FindingRecord.employee_id != token,
                                              or_(FindingRecord.reason.like(like),
                                                  FindingRecord.actual_value.like(like))):
        if sc.mentions(rec.reason or "") or sc.mentions(rec.actual_value or ""):
            rec.reason = sc.text(rec.reason, names=False)
            rec.actual_value = sc.text(rec.actual_value, names=False)
            bump("Other findings naming the person")

    for row in db.query(BankFileRow).filter(BankFileRow.entity_id == e, BankFileRow.employee_id == employee_id):
        row.employee_id = token
        row.employee_name = None
        row.account_number = None
        row.ifsc = None
        row.raw = sc.value(dict(row.raw or {}))
        bump("Bank file rows")
    for exc in db.query(ReconException).filter(ReconException.entity_id == e, ReconException.employee_id == employee_id):
        exc.employee_id = token
        exc.employee_name = None
        exc.title = sc.text(exc.title) or ""
        exc.detail = sc.text(exc.detail)
        exc.context = sc.value(dict(exc.context or {}))
        bump("Reconciliation exceptions")

    for run in db.query(ValidationRun).filter(ValidationRun.entity_id == e):
        if run.summary and sc.mentions(json.dumps(run.summary, default=str)):
            run.summary = sc.value(run.summary, names=False)
            bump("Run summaries")

    for rej in db.query(StudioRunRejection).filter(StudioRunRejection.entity_id == e):
        if sc.is_person(rej.record_key) or (rej.payload_gz and sc.mentions(_ungz_text(rej.payload_gz))):
            rej.record_key = token if sc.is_person(rej.record_key) else rej.record_key
            rej.payload_gz = None
            rej.message = sc.text(rej.message)
            bump("Rejected import records")
    for run in db.query(StudioRun).filter(StudioRun.entity_id == e, StudioRun.payload_gz.is_not(None),
                                          StudioRun.status.notin_(("queued", "running"))):
        if sc.mentions(_ungz_text(run.payload_gz)):
            run.payload_gz = None
            bump("Imported record copies")

    # Derived copies: recomputed from what is left on the next read.
    registers = db.query(SalaryRegister.id).filter(SalaryRegister.entity_id == e).scalar_subquery()
    db.query(RegisterCosting).filter(RegisterCosting.register_id.in_(registers)).delete(synchronize_session=False)
    bump("Generated report files expired",
         db.query(ReportJob).filter(ReportJob.entity_id == e, ReportJob.artifact.is_not(None))
         .update({ReportJob.artifact: None, ReportJob.stage: "expired"}, synchronize_session=False))

    retained = _signed_records(db, e, sc)
    request = ErasureRequest(
        org_id=entity.org_id, entity_id=e, employee_id=employee_id, reason=reason,
        requested_by_user_id=getattr(user, "id", None), requested_by_email=getattr(user, "email", "") or "",
        counts=counts, retained=retained,
    )
    db.add(request)
    audit.record(
        db, entity_id=e, org_id=entity.org_id, user=user, action="data.erasure",
        object_type="erasure_request", object_id=employee_id,
        summary=f"Personal data of employee {employee_id} erased. Reason: {reason}",
        detail={"counts": counts, "retained": [{"store": r["store"], "count": r["count"]} for r in retained]},
    )
    db.commit()
    return request


def describe_request(req: ErasureRequest) -> dict[str, Any]:
    return {
        "id": str(req.id),
        "employee_id": req.employee_id,
        "reason": req.reason,
        "requested_by": req.requested_by_email,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "counts": req.counts or {},
        "retained": req.retained or [],
    }


def describe_policy(db: Session, entity_id, today: date | None = None) -> dict[str, Any]:
    policy = policy_for(db, entity_id)
    months = policy.payroll_months if policy else None
    out: dict[str, Any] = {
        "payroll_months": months,
        "min_months": MIN_MONTHS,
        "max_months": MAX_MONTHS,
        "reason": policy.reason if policy else None,
        "set_by": policy.set_by_email if policy else None,
        "set_at": policy.set_at.isoformat() if policy and policy.set_at else None,
        "last_applied_at": policy.last_applied_at.isoformat() if policy and policy.last_applied_at else None,
        "last_applied": (policy.last_applied_counts or {}) if policy else {},
        "status": "set" if months else "not_set",
        "statement": (f"Payroll periods older than {months} months are removed automatically, once a day."
                      if months else
                      "No retention period is set: nothing is deleted. Set one when the company has decided "
                      "how long this copy of its payroll data should be kept."),
    }
    if months:
        out["pending"] = retention_plan(db, entity_id, months, today)
    return out
