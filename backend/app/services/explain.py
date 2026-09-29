"""
"Why this result?" — the evidence behind one finding, assembled from the run.

Everything here is read from what the run froze, never recomputed from today's
state: the upload the run validated (file name, sheet, row, the values as
uploaded), the configuration snapshot it recorded (rates, ceilings, rounding,
tolerance), the computed row it stored, and the finding itself. A signed-off
month can therefore be explained exactly as it was, after the rates change.

The calculation text is built per rule family from those recorded values. It
restates what the engine did; it does not re-derive it. Where the engine's
arithmetic is not reconstructable from what was recorded, the explanation says
so rather than guessing.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.register_uploads import SOURCE_ROW_KEY

#: Register fields that feed each rule family's calculation — shown as inputs.
INPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "PF": ("pf_employee", "pf_employer", "pf_eps", "pf_restricted", "international_worker", "doj", "dob"),
    "ESIC": ("esic_employee", "esic_employer", "esi_number", "disability"),
    "PT": ("pt", "state", "gender"),
    "LWF": ("lwf_employee", "lwf_employer", "state"),
    "LOP": ("paid_days", "lop_days", "total_days"),
    "TDS": ("tds", "pan", "tax_regime"),
    "ID": ("pan", "aadhaar", "uan", "esi_number", "ifsc", "dob", "doj", "dol"),
    "AGG": ("gross", "total_deductions", "net"),
}

FAMILY_OF_RULE = {
    "STAT-001": "PF", "STAT-002": "PF", "STAT-003": "PF", "STAT-004": "PF", "PF-004": "PF",
    "PF-008": "PF", "PF-009": "PF", "ARR-004": "PF",
    "STAT-005": "ESIC", "STAT-006": "ESIC", "STAT-007": "ESIC", "ESI-005": "ESIC", "ESI-006": "ESIC",
    "STAT-008": "PT", "PT-002": "PT", "PT-003": "PT",
    "STAT-009": "LWF", "STAT-010": "LWF",
    "LOP-001": "LOP", "LOP-002": "LOP", "LOP-003": "LOP",
    "TDS-001": "TDS", "TDS-002": "TDS", "STAT-011": "TDS",
    "AGG-001": "AGG", "AGG-002": "AGG", "AGG-003": "AGG", "AGG-004": "AGG",
}

#: Rules whose findings carry a rupee amount that is a real monetary difference.
#: Everything else is a finding about data or eligibility: its impact is not
#: zero, it is *not calculated*, and must be shown that way.
MONETARY_RULES = {
    "STAT-001", "STAT-002", "STAT-003", "STAT-006", "STAT-007", "STAT-008", "STAT-009",
    "STAT-010", "STAT-014", "PF-004", "PF-008", "PF-009", "ESI-006", "PT-002", "PT-003",
    "LOP-002", "MOM-002", "MOM-003", "MOM-005", "MOM-006", "ADV-002", "ADV-003",
    "AGG-001", "AGG-002", "BON-002", "GRAT-003", "TDS-001", "TDS-002", "DATA-003",
    "ATT-020", "ATT-022", "ATT-023", "MW-001", "STRUCT-001",
}

#: Findings that describe the same rupees from two angles. Counting both would
#: double the exposure, so within each group only the largest is counted.
OVERLAP_GROUPS: tuple[frozenset[str], ...] = (
    # PF employee share: a miscalculation or the wrong restriction basis — one or the other.
    frozenset({"STAT-001", "PF-009"}),
    # Pay not reduced for LOP, seen from attendance and from CTC proration.
    frozenset({"ATT-020", "LOP-002"}),
    # A month-on-month salary movement reported per component and as a whole.
    frozenset({"MOM-002", "ADV-002"}),
    frozenset({"MOM-003", "MOM-005", "ADV-003"}),
)


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def impact_known(rule_id: str, financial_impact: Any) -> bool:
    """Is this finding's rupee figure a calculated difference?"""
    amount = _d(financial_impact) or Decimal("0")
    return rule_id in MONETARY_RULES and amount != 0


def deduplicated_exposure(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Total financial exposure without counting the same rupees twice.

    Per employee, overlapping findings contribute only their largest amount.
    Findings whose impact is not calculated contribute nothing and are counted
    separately, so the total never presents "unknown" as zero.
    """
    by_employee: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_employee.setdefault(str(f.get("employee_id") or ""), []).append(f)

    total = Decimal("0")
    overlapped = Decimal("0")
    not_calculated = 0
    for items in by_employee.values():
        grouped: dict[int, Decimal] = {}
        for f in items:
            rule = str(f.get("rule_id") or "")
            amount = _d(f.get("financial_impact")) or Decimal("0")
            if not impact_known(rule, amount):
                not_calculated += 1
                continue
            group = next((i for i, g in enumerate(OVERLAP_GROUPS) if rule in g), None)
            if group is None:
                total += abs(amount)
            else:
                prev = grouped.get(group)
                if prev is not None:
                    overlapped += min(prev, abs(amount))
                grouped[group] = max(prev or Decimal("0"), abs(amount))
        total += sum(grouped.values(), Decimal("0"))
    return {
        "exposure": total.quantize(Decimal("0.01")),
        "overlap_excluded": overlapped.quantize(Decimal("0.01")),
        "impact_not_calculated": not_calculated,
    }


def _money(value: Any) -> str:
    d = _d(value)
    return "—" if d is None else f"₹{d.quantize(Decimal('0.01')):,}"


def calculation(rule_id: str, result: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    """The arithmetic the engine applied, restated from recorded values."""
    eff = ((config or {}).get("effective_statutory") or {})
    thresholds = eff.get("rule_thresholds") or {}
    tolerances = thresholds.get("tolerances") or {}
    tolerance = tolerances.get("statutory_mismatch")
    family = FAMILY_OF_RULE.get(rule_id)
    steps: list[str] = []
    basis: dict[str, Any] = {}

    if family == "PF":
        pf = eff.get("pf") or {}
        wage = (pf.get("wage") or {})
        rates = (pf.get("rates") or pf.get("rate") or {})
        breakup = result.get("pf_breakup") or {}
        basis = {
            "pf_wage": result.get("pf_wage"),
            "ceiling": wage.get("wage_ceiling"),
            "restricted_to_ceiling": result.get("pf_restricted"),
            "basis_source": result.get("pf_basis_source"),
            "employee_rate": rates.get("employee_rate"),
            "rounding": (pf.get("rounding") or {}).get("mode"),
        }
        steps = [
            f"PF wage = sum of PF-applicable components = {_money(result.get('pf_wage'))}",
            f"Wage used = {'min(PF wage, ceiling ' + _money(wage.get('wage_ceiling')) + ')' if result.get('pf_restricted') else 'full PF wage (unrestricted)'}"
            f" = {_money(breakup.get('wage_capped'))} (basis from {result.get('pf_basis_source') or 'entity default'})",
            f"Employee PF = wage used × {rates.get('employee_rate', '12%')} = {_money(result.get('pf_amount_employee'))}",
            f"Employer PF = {_money(result.get('pf_amount_employer'))} (EPS {_money(breakup.get('eps'))}, EPF {_money(breakup.get('epf'))})",
        ]
    elif family == "ESIC":
        esic = eff.get("esic") or {}
        basis = {
            "esic_wage": result.get("esic_wage"),
            "eligible": result.get("esic_eligible"),
            "ceiling": (esic.get("wage") or {}).get("wage_ceiling"),
            "rounding": (esic.get("rounding") or {}).get("mode"),
        }
        steps = [
            f"ESIC wage = sum of ESIC-applicable components = {_money(result.get('esic_wage'))}",
            f"Eligible: {'yes' if result.get('esic_eligible') else 'no'} (ceiling {_money(basis['ceiling'])})",
            f"Employee share = {_money(result.get('esic_employee'))}; employer share = {_money(result.get('esic_employer'))}"
            f" (rounded {basis['rounding'] or 'as configured'})",
        ]
    elif family == "PT":
        basis = {"state": result.get("pt_applicable_state"), "pt_wage": result.get("pt_wage_base"),
                 "slab": result.get("pt_monthly_slab")}
        steps = [
            f"PT state = {result.get('pt_applicable_state') or 'not mapped'}",
            f"PT wage = {_money(result.get('pt_wage_base'))}",
            f"Slab applied for the period = {result.get('pt_monthly_slab') or '—'} → PT due {_money(result.get('pt_due'))}",
        ]
    elif family == "LWF":
        basis = {"state": result.get("lwf_applicable_state"), "lwf_wage": result.get("lwf_wage_base")}
        steps = [
            f"LWF state = {result.get('lwf_applicable_state') or 'not mapped'}",
            f"Employee {_money(result.get('lwf_employee'))}, employer {_money(result.get('lwf_employer'))} from the dated schedule",
        ]
    elif family == "LOP":
        basis = {"paid_days": result.get("paid_days"), "lop_days": result.get("lop_days"),
                 "days_in_month": result.get("days_in_month")}
        steps = [
            f"Days in month = {result.get('days_in_month')}",
            f"Paid days = {result.get('paid_days')}, LOP days = {result.get('lop_days')}",
            "Proration: monthly amount × paid days ÷ days in month" if rule_id == "LOP-002" else
            "Paid days + LOP days must equal the days in the month",
        ]
    return {
        "family": family,
        "steps": steps,
        "basis": basis,
        "tolerance": tolerance,
        "reconstructed_from": "the run's recorded computation and configuration snapshot",
    }


def source_location(
    upload: Any, source_row: dict[str, Any] | None, component: str | None
) -> dict[str, Any]:
    """Where in the uploaded file the value came from."""
    if upload is None:
        return {"recorded": False}
    field = (component or "").strip().lower().replace(" ", "_") or None
    mapping = upload.column_mapping or {}
    source_column = next((src for src, dest in mapping.items() if dest == field), None)
    return {
        "recorded": True,
        "filename": upload.filename,
        "sheet": upload.sheet_name,
        "file_sha256": upload.file_sha256,
        "revision": upload.revision,
        "row": (source_row or {}).get(SOURCE_ROW_KEY),
        "field": field,
        "source_column": source_column or field,
        "value": (source_row or {}).get(field) if field else None,
    }


def input_values(rule_id: str, source_row: dict[str, Any] | None) -> dict[str, Any]:
    fields = INPUT_FIELDS.get(FAMILY_OF_RULE.get(rule_id) or "", ())
    row = source_row or {}
    return {f: row.get(f) for f in fields if f in row}
