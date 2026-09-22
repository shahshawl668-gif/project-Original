"""
The Indian payroll cost taxonomy.

A salary register answers "what did we pay?". A cost dashboard has to answer
"what did this cost us?", and in India those are materially different numbers:
what leaves the employer's account is gross pay *plus* the employer's EPF, EDLI
and administration charges, *plus* the employer's ESI share, *plus* the gratuity
that accrued this month whether or not anyone will claim it for five years.
Read only the register and a company understates its own payroll cost by
roughly a sixth.

So cost is assembled in three layers, which is how CTC is read here:

* **earnings** — what the register paid, split the way an Indian pay structure
  is actually built: Basic & DA (the statutory base), HRA, other allowances,
  variable pay and bonus, and arrears;
* **employer contributions** — EPF, EDLI and admin, ESI, the gratuity provision
  and LWF. Cost to the employer, never seen by the employee;
* **employee deductions** — EPF and ESI employee share, professional tax and
  TDS. These are *inside* gross, not on top of it, and are carried so the
  dashboard can show net alongside gross rather than implying that gross is
  what lands in a bank account.

``CTC = earnings + employer contributions``. Deductions are deliberately not
added: adding them would double-count money already inside gross, which is the
single most common way a payroll cost report overstates itself.

Where the figures come from
---------------------------
One rule, applied to every statutory amount: **the register's own figure wins;
the engine computes only to fill a gap.** A payroll system that reported ₹1,800
of employee PF is stating what it actually deducted, and that is the cost. Where
the engine thinks a different number was due, that disagreement is a *finding* —
the validation half of this product already reports it, and a cost dashboard
that quietly substituted its own arithmetic would put two irreconcilable totals
in front of the same reader.

Gratuity is the exception, and is always computed: no register carries it.

Every response reports how much of the statutory total was read versus filled
in, because "we computed this for you" and "your payroll system told us this"
deserve different amounts of trust.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import ComponentConfig, Entity, StatutorySettings
from app.services.config_service import ConfigService
from app.services.esic_engine import compute_esic, compute_esic_wage
from app.services.pf_basis import resolve as resolve_pf_basis
from app.services.pf_engine import compute_pf, compute_pf_wage

CENT = Decimal("0.01")

# 15 days' wages for each completed year, on a 26-day month, accrued monthly:
# 15 / 26 / 12 of Basic & DA. Usually quoted as "about 4.81%", which is this
# fraction rounded. The exact fraction is used so a year of provisions sums to
# the 15/26 the Act actually grants rather than to a rounded approximation.
GRATUITY_FRACTION = Decimal("15") / Decimal("26") / Decimal("12")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


# ---------------------------------------------------------------------------
# The measures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Measure:
    """One line of the cost taxonomy."""

    key: str
    label: str
    layer: str  # "earnings" | "employer" | "deduction"
    hint: str


MEASURES: tuple[Measure, ...] = (
    # ---- earnings: what the register paid -------------------------------
    Measure("basic_da", "Basic & DA", "earnings",
            "The statutory base. PF, gratuity and bonus are all computed on it."),
    Measure("hra", "HRA", "earnings",
            "House rent allowance, exempt in part against rent actually paid."),
    Measure("allowances", "Allowances", "earnings",
            "Conveyance, medical, special allowance and everything else fixed."),
    Measure("variable_pay", "Variable pay & bonus", "earnings",
            "Incentives, overtime and statutory bonus — the part that is not run rate."),
    Measure("arrears", "Arrears & one-time", "earnings",
            "Paid this month for earlier periods, including increment arrears."),
    # ---- employer: cost on top of gross ---------------------------------
    Measure("er_pf", "EPF — employer", "employer",
            "The employer's 12%, of which EPS takes 8.33% up to the ceiling."),
    Measure("er_pf_admin", "EDLI & PF admin", "employer",
            "Insurance and administration charges, payable on top of the 12%."),
    Measure("er_esi", "ESI — employer", "employer",
            "3.25% of ESI wages for employees under the wage ceiling."),
    Measure("gratuity", "Gratuity provision", "employer",
            "This month's accrual: 15/26 of a month's Basic & DA per year, spread monthly."),
    Measure("er_lwf", "LWF — employer", "employer",
            "Labour welfare fund, where the state levies one."),
    # ---- deductions: inside gross, not on top ---------------------------
    Measure("ee_pf", "EPF — employee", "deduction",
            "The employee's 12%, including any voluntary contribution."),
    Measure("ee_esi", "ESI — employee", "deduction",
            "0.75% of ESI wages."),
    Measure("pt", "Professional tax", "deduction",
            "State levy, by slab. Not applicable in every state."),
    Measure("ee_lwf", "LWF — employee", "deduction",
            "The employee's share of the labour welfare fund."),
    Measure("tds", "TDS", "deduction",
            "Income tax deducted at source, as reported by the payroll system."),
)

MEASURE_KEYS = tuple(m.key for m in MEASURES)
MEASURE_BY_KEY = {m.key: m for m in MEASURES}
EARNING_KEYS = tuple(m.key for m in MEASURES if m.layer == "earnings")
EMPLOYER_KEYS = tuple(m.key for m in MEASURES if m.layer == "employer")
DEDUCTION_KEYS = tuple(m.key for m in MEASURES if m.layer == "deduction")

# Derived roll-ups. These are not stored per row; they are sums of the above,
# named here so the API and the UI cannot disagree about what "CTC" means.
DERIVED = (
    ("gross", "Gross pay", tuple(EARNING_KEYS)),
    ("employer_cost", "Employer contributions", tuple(EMPLOYER_KEYS)),
    ("ctc", "Total CTC", tuple(EARNING_KEYS) + tuple(EMPLOYER_KEYS)),
    ("deductions", "Total deductions", tuple(DEDUCTION_KEYS)),
)
DERIVED_KEYS = tuple(k for k, _, _ in DERIVED)
DERIVED_LABELS = {k: label for k, label, _ in DERIVED}
DERIVED_PARTS = {k: parts for k, _, parts in DERIVED}

# "net" is gross minus deductions, and is derived from two derived figures, so
# it sits outside the table above.
ALL_MEASURE_KEYS = MEASURE_KEYS + DERIVED_KEYS + ("net",)


def zero_measures() -> dict[str, Decimal]:
    return {key: Decimal("0") for key in MEASURE_KEYS}


def with_derived(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Add the roll-ups to a dict of base measures."""
    out = dict(values)
    for key, _, parts in DERIVED:
        out[key] = sum((values.get(p, Decimal("0")) for p in parts), Decimal("0"))
    out["net"] = out["gross"] - out["deductions"]
    return out


# ---------------------------------------------------------------------------
# Classifying an earning component
# ---------------------------------------------------------------------------
# Matched against the normalised component name, longest and most specific
# first. A component nobody recognises is an allowance, which is where an
# unknown fixed earning belongs — never dropped, so the parts always sum to
# gross.
_BASIC_TOKENS = ("basic", "dearness", "_da", "da_", "basic_da", "basic_salary")
_HRA_TOKENS = ("hra", "house_rent", "rent_allowance")
_VARIABLE_TOKENS = (
    "bonus", "incentive", "variable", "commission", "performance",
    "overtime", "_ot", "ot_", "ex_gratia", "exgratia", "reward",
    "one_time", "onetime", "retention", "shift_allowance", "night_shift",
)


def _matches(key: str, tokens: tuple[str, ...]) -> bool:
    padded = f"_{key}_"
    for token in tokens:
        if token.startswith("_") or token.endswith("_"):
            if token in padded:
                return True
        elif token in key:
            return True
    return False


def classify_component(name: str) -> str:
    """Which earning bucket a component name belongs to."""
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if key == "da" or _matches(key, _BASIC_TOKENS):
        return "basic_da"
    if _matches(key, _HRA_TOKENS):
        return "hra"
    if _matches(key, _VARIABLE_TOKENS):
        return "variable_pay"
    return "allowances"


# ---------------------------------------------------------------------------
# What the register itself reported
# ---------------------------------------------------------------------------
# Register columns carrying a statutory figure the payroll system already
# calculated. Captured when the register is stored (see routers/payroll.py) so
# the cost dashboard can report the employer's own numbers rather than
# substituting its own.
REPORTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "er_pf": ("pf_employer", "employer_pf", "pf_er", "epf_employer"),
    "er_pf_admin": ("pf_admin", "edli", "pf_edli", "admin_charges"),
    "er_esi": ("esic_employer", "esi_employer", "employer_esic", "esic_er"),
    "er_lwf": ("lwf_employer", "employer_lwf"),
    "ee_pf": ("pf_employee", "employee_pf", "pf_emp", "epf_employee", "pf"),
    "ee_esi": ("esic_employee", "esi_employee", "employee_esic", "esic", "esi"),
    "pt": ("pt", "pt_amount", "professional_tax", "ptax"),
    "ee_lwf": ("lwf_employee", "employee_lwf", "lwf"),
    "tds": ("tds", "income_tax", "tds_amount", "it_deduction"),
}


# What a register calls the amount it told the bank to pay. Captured apart from
# the statutory figures above because it is not a deduction: it is the result of
# all of them, and it is the only figure a bank file can be matched against.
NET_PAY_COLUMNS: tuple[str, ...] = (
    "net_pay", "net_salary", "net_amount", "net_payable", "net",
    "take_home", "takehome", "net_pay_amount", "amount_payable", "payable_amount",
)


def capture_net_pay(row: dict[str, Any]) -> Decimal | None:
    """
    The net pay a register row states, or ``None`` where it states none.

    ``None`` and zero are kept distinct throughout: a register with no net-pay
    column has not told us what it paid, whereas one that says 0.00 is asserting
    that this employee was paid nothing. Only the second is reconcilable.
    """
    from app.services.payroll_parse import normalize_col

    normalised = {normalize_col(str(k)): v for k, v in row.items() if k is not None}
    for alias in NET_PAY_COLUMNS:
        if alias not in normalised:
            continue
        raw = normalised[alias]
        if raw in (None, ""):
            continue
        try:
            return _q(_dec(raw))
        except Exception:  # nosec B112
            # Try the next spelling rather than abandoning the row.
            continue
    return None


def capture_reported(row: dict[str, Any]) -> dict[str, float]:
    """
    The statutory figures a register row states for itself.

    Only amounts actually present are captured — a zero and an absent column
    mean different things, and conflating them would let a register that never
    mentioned ESI look like one that deducted nothing.
    """
    from app.services.payroll_parse import normalize_col

    normalised = {normalize_col(str(k)): v for k, v in row.items() if k is not None}
    out: dict[str, float] = {}
    for measure, aliases in REPORTED_COLUMNS.items():
        for alias in aliases:
            if alias not in normalised:
                continue
            raw = normalised[alias]
            if raw in (None, ""):
                continue
            try:
                out[measure] = float(_dec(raw))
            except Exception:  # nosec B112
                # A cell that will not parse as a number is skipped so the
                # next alias for this measure can be tried.
                continue
            break
    return out


# ---------------------------------------------------------------------------
# Per-row cost
# ---------------------------------------------------------------------------
@dataclass
class RowCost:
    """One employee-month, fully costed."""

    measures: dict[str, Decimal]
    # Which statutory measures were read from the register rather than computed,
    # so a total can say how much of itself it derived.
    reported_keys: set[str] = field(default_factory=set)

    @property
    def reported_amount(self) -> Decimal:
        return sum(
            (self.measures[k] for k in self.reported_keys if k in self.measures),
            Decimal("0"),
        )


class CostContext:
    """
    Everything needed to cost a register row, loaded once for a whole request.

    Costing a row needs the component configuration, the PF and ESI
    configuration and the PT and LWF slab tables. Loading those per row would
    turn a dashboard into a few thousand queries, so they are loaded once and
    the per-row work is arithmetic.
    """

    def __init__(self, db: Session, entity: Entity | Any):
        self.db = db
        self.entity_id = entity.id if hasattr(entity, "id") else entity

        components = (
            db.query(ComponentConfig)
            .filter(ComponentConfig.entity_id == self.entity_id)
            .all()
        )
        from app.services.validation import _component_key_map

        self.comp_by_key = _component_key_map(components)

        service = ConfigService(db)
        self.pf_cfg = service.get_pf_config(self.entity_id)
        self.esic_cfg = service.get_esic_config(self.entity_id)

        settings = (
            db.query(StatutorySettings)
            .filter(StatutorySettings.entity_id == self.entity_id)
            .first()
        )
        pt_states = list(getattr(settings, "pt_states", None) or [])
        lwf_states = list(getattr(settings, "lwf_states", None) or [])
        self.pt_states = set(pt_states)
        self.lwf_states = set(lwf_states)
        self.default_pt_state = pt_states[0] if pt_states else None
        self.default_lwf_state = lwf_states[0] if lwf_states else None
        self.pf_restrict_default = self.pf_cfg.wage.restrict_to_ceiling

        # Slab lookups repeat heavily across a month — the same state and the
        # same wage, once per employee on that grade. Memoised per request.
        self._pt_cache: dict[tuple[str | None, str, str], Decimal] = {}
        self._lwf_cache: dict[tuple[str | None, str, str], tuple[Decimal, Decimal]] = {}

    # -- slab lookups ----------------------------------------------------
    def _pt(self, state: str | None, wage: Decimal, as_of: date) -> Decimal:
        if not state:
            return Decimal("0")
        key = (state, str(wage), as_of.isoformat())
        if key not in self._pt_cache:
            from app.services.validation import lookup_pt

            amount, _ = lookup_pt(self.db, state, wage, as_of, entity_id=self.entity_id)
            self._pt_cache[key] = amount
        return self._pt_cache[key]

    def _lwf(self, state: str | None, wage: Decimal, as_of: date) -> tuple[Decimal, Decimal]:
        if not state:
            return Decimal("0"), Decimal("0")
        key = (state, str(wage), as_of.isoformat())
        if key not in self._lwf_cache:
            from app.services.validation import lookup_lwf

            _, _, employee, employer = lookup_lwf(
                self.db, state, wage, as_of, entity_id=self.entity_id
            )
            self._lwf_cache[key] = (employee, employer)
        return self._lwf_cache[key]

    def _state_for(self, dims: dict[str, Any], allowed: set[str], default: str | None) -> str | None:
        state = dims.get("work_state")
        if state and (not allowed or state in allowed):
            return state
        return default

    # -- the costing ------------------------------------------------------
    def cost_row(self, row: Any, *, pf_restricted: bool | None = None) -> RowCost:
        """
        Cost one stored register row.

        ``pf_restricted`` is the standing position from the employee master.
        The register's own flag for the month, captured when the register was
        stored, takes precedence over it; the entity default settles the rest.
        See services/pf_basis.py — the difference between the two bases is 12%
        of everything above the ceiling, which is not a rounding matter.
        """
        components = {str(k): _dec(v) for k, v in (row.components or {}).items()}
        arrears = {str(k): _dec(v) for k, v in (row.arrears or {}).items()}
        dims = row.dimensions or {}
        reported = row.deductions if isinstance(getattr(row, "deductions", None), dict) else {}
        as_of = row.period_month

        measures = zero_measures()

        # ---- earnings ---------------------------------------------------
        for name, amount in components.items():
            measures[classify_component(name)] += amount
        # Arrears stay one line rather than being spread back across the
        # buckets: an arrear is not this month's run rate, and folding it into
        # Basic would make a catch-up payment read as a pay rise.
        measures["arrears"] = (
            sum(arrears.values(), Decimal("0")) + _dec(row.increment_arrear_total)
        )

        # ---- statutory: computed, then overridden by what was reported ---
        pf_wage, vol_wage = compute_pf_wage(components, self.comp_by_key, self.pf_cfg)
        row_flag = getattr(row, "pf_restricted", None)
        basis = resolve_pf_basis(
            {} if row_flag is None else {"pf_restricted": row_flag},
            pf_restricted,
            self.pf_restrict_default,
        )
        pf = compute_pf(
            pf_wage,
            self.pf_cfg,
            vol_wage,
            restrict_override=basis.restricted,
            employment_type=str(dims.get("employment_type") or "employee"),
        )
        measures["er_pf"] = _dec(pf["pf_employer_total"])
        measures["er_pf_admin"] = _dec(pf["pf_edli"]) + _dec(pf["pf_admin"])
        measures["ee_pf"] = _dec(pf["pf_employee"]) + _dec(pf["pf_voluntary_employee"])

        esic_wage = compute_esic_wage(components, self.comp_by_key, self.esic_cfg)
        esic = compute_esic(
            esic_wage,
            self.esic_cfg,
            employment_type=str(dims.get("employment_type") or "employee"),
        )
        measures["er_esi"] = _dec(esic["esic_employer"])
        measures["ee_esi"] = _dec(esic["esic_employee"])

        measures["gratuity"] = _q(measures["basic_da"] * GRATUITY_FRACTION)

        pt_base = _sum_flagged(components, self.comp_by_key, "pt_applicable")
        measures["pt"] = self._pt(
            self._state_for(dims, self.pt_states, self.default_pt_state), pt_base, as_of
        )

        lwf_base = _sum_flagged(components, self.comp_by_key, "lwf_applicable")
        lwf_employee, lwf_employer = self._lwf(
            self._state_for(dims, self.lwf_states, self.default_lwf_state), lwf_base, as_of
        )
        measures["ee_lwf"] = lwf_employee
        measures["er_lwf"] = lwf_employer

        # TDS has no computed counterpart here. Projecting a month's tax needs
        # the whole year's declared investments and previous employment, which
        # a cost query does not have and should not guess at — so it is what the
        # register said, or nothing.
        measures["tds"] = Decimal("0")

        # ---- what the register said wins --------------------------------
        reported_keys: set[str] = set()
        for key, value in (reported or {}).items():
            if key not in measures:
                continue
            measures[key] = _dec(value)
            reported_keys.add(key)

        return RowCost(measures={k: _q(v) for k, v in measures.items()}, reported_keys=reported_keys)


def _sum_flagged(
    amounts: dict[str, Decimal],
    comp_by_key: dict[str, ComponentConfig],
    flag: str,
) -> Decimal:
    total = Decimal("0")
    for key, amount in amounts.items():
        comp = comp_by_key.get(key)
        if comp is not None and getattr(comp, flag, False):
            total += amount
    return total
