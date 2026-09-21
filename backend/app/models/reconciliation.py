"""
Bank file and journal voucher reconciliation.

This is the control that closes payroll. Validation asks whether the register
is *correct*; reconciliation asks whether what was correct is what actually
left the bank and what actually reached the ledger. Those are three different
numbers in most companies, and the gaps between them are where both errors and
fraud live:

* the register says ₹868 lakh of net pay is due;
* the bank file says ₹868.4 lakh was paid, to 1,204 accounts;
* the journal voucher posted ₹9.1 crore of cost to the general ledger.

Nothing in a payroll system reconciles those for you, because the payroll
system produced all three and has no independent view. This product never runs
payroll, which is exactly why it can hold the three against each other.

Why so much configuration
-------------------------
Two things here are different at every single company, and a module that
assumes either one is useless at the second client:

**Bank files.** Every bank's bulk-payment layout differs, and so does the
subset of columns a given corporate account is set up to send. Account number
in column 3 at one bank and column 7 at another; amounts in rupees here and
paise there; a header and two trailer rows at one bank and neither at the next.
So a bank format is *data* — :class:`BankFileProfile` — not code.

**Journal vouchers.** There is no standard payroll JV. One company posts a
single consolidated voucher; another posts one per cost centre. One debits
gratuity as an expense monthly; another only on payment. Chart-of-accounts
codes are unique to the company by definition. One exports to Tally, the next
to SAP. So a JV format is also data — a :class:`JvTemplate` of ordered
:class:`JvRule` lines, each mapping payroll cost measures onto an account and
a side.

Because a JV rule names measures from ``services/cost_model``, the voucher and
the cost dashboard are built from one set of numbers. They cannot drift apart:
if the dashboard says payroll cost ₹9.1 crore, a balanced JV built from the
same measures posts ₹9.1 crore.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Bank side: how to read this company's bank file
# ---------------------------------------------------------------------------
class BankFileProfile(Base):
    """
    A named, editable description of one bank file layout.

    Held per entity rather than globally: a bureau's clients bank with
    different banks, and two clients at the same bank can be provisioned with
    different column sets.
    """

    __tablename__ = "bank_file_profiles"
    __table_args__ = (UniqueConstraint("entity_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_label: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)

    # What kind of file this reads. A payment advice is what goes *to* the bank;
    # a statement or a return file is what comes *back*. They reconcile against
    # different things, so the kind is part of the profile rather than guessed.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="payment_advice")

    # ---- layout ---------------------------------------------------------
    layout: Mapped[str] = mapped_column(String(16), nullable=False, default="delimited")
    delimiter: Mapped[str] = mapped_column(String(4), nullable=False, default=",")
    encoding: Mapped[str] = mapped_column(String(32), nullable=False, default="utf-8")
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    skip_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Banks routinely end a file with a control total. Counting it as a payment
    # inflates the file total by roughly double, so it is dropped by count.
    trailer_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # {field: column name, 1-based index, or [start, length] for fixed width}
    column_map: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # ---- value handling -------------------------------------------------
    amount_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="rupees")
    amount_sign: Mapped[str] = mapped_column(String(24), nullable=False, default="as_is")
    date_format: Mapped[str | None] = mapped_column(String(32))
    # Employee codes are the join key, and they are rarely clean on both sides.
    # "EMP0042" in the register and "42" in the bank file is the same person.
    employee_id_transform: Mapped[str] = mapped_column(String(32), nullable=False, default="trim")

    # Keep only rows whose column matches: {"column": "txn_type", "in": ["SAL"]}
    row_filter: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class BankFile(Base):
    """One uploaded bank file, kept so a reconciliation stays reproducible."""

    __tablename__ = "bank_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("bank_file_profiles.id", ondelete="SET NULL")
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="payment_advice")
    filename: Mapped[str | None] = mapped_column(String(512))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    # What the file's own trailer claimed, where it had one. A file whose stated
    # total disagrees with the sum of its own rows is truncated or edited, and
    # that is worth knowing before any of it is reconciled.
    stated_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    problems: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_by_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rows = relationship("BankFileRow", back_populates="file", cascade="all, delete-orphan")


class BankFileRow(Base):
    """One payment line as the bank file stated it."""

    __tablename__ = "bank_file_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bank_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    employee_id: Mapped[str | None] = mapped_column(String(64), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(255))
    account_number: Mapped[str | None] = mapped_column(String(64))
    ifsc: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=Decimal("0"))
    reference: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str | None] = mapped_column(String(64))
    value_date: Mapped[date | None] = mapped_column(Date)
    # The line exactly as read, so an operator can see what the profile did to
    # their file when a mapping turns out to be wrong.
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    file = relationship("BankFile", back_populates="rows")


# ---------------------------------------------------------------------------
# Ledger side: how this company builds its journal voucher
# ---------------------------------------------------------------------------
class JvTemplate(Base):
    """
    One company's way of turning a month of payroll cost into a voucher.

    Approved rather than merely saved, for the same reason a budget is: the
    voucher that goes to the ledger is a number the auditor will ask about, and
    "someone edited the mapping in March" has to be answerable.
    """

    __tablename__ = "jv_templates"
    __table_args__ = (UniqueConstraint("entity_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    # ---- the options that differ company to company ---------------------
    # accrual: gratuity and every employer contribution hit the month they are
    #   earned, which is what Ind AS expects.
    # cash: only what is actually disbursed or remitted. Smaller companies post
    #   this way and provide for gratuity annually instead.
    posting_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="accrual")
    # consolidated: one voucher, each line optionally tagged with a cost centre.
    # per_group: a separate voucher per cost centre, which is what companies
    #   whose ERP posts by profit centre need.
    split_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="consolidated")
    # Which dimension is the cost centre here. Companies disagree: some post by
    # department, some by the cost_center code, some by location.
    group_by: Mapped[str | None] = mapped_column(String(32))
    # summary: one line per account. by_component: one per measure within the
    # account. by_employee: employee-wise, which a few small companies still do.
    detail_level: Mapped[str] = mapped_column(String(16), nullable=False, default="summary")
    # two_column: separate debit and credit columns. signed: one amount column
    # with credits negative, which most ERP imports want.
    sign_convention: Mapped[str] = mapped_column(String(16), nullable=False, default="two_column")
    # Which net-pay figure the salary-payable credit is built from. "computed"
    # is gross less the deductions in the taxonomy, and always balances against
    # the cost side. "stated" is the net the register itself declared, which is
    # what the bank was actually told to pay — truer to the disbursement, but it
    # will not balance where the register deducts something it does not itemise,
    # such as a salary advance. Companies genuinely do both, so it is a choice
    # rather than a default, and the difference is always reported either way.
    net_pay_source: Mapped[str] = mapped_column(String(16), nullable=False, default="computed")
    voucher_date_rule: Mapped[str] = mapped_column(String(24), nullable=False, default="month_end")
    voucher_type: Mapped[str] = mapped_column(String(32), nullable=False, default="Journal")
    narration_template: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Payroll for {period_label}{scope_suffix}"
    )
    export_format: Mapped[str] = mapped_column(String(24), nullable=False, default="generic_csv")

    # A rupee or two of rounding across thousands of employees is ordinary; a
    # lakh is a mapping error. The tolerance separates the two, and what happens
    # to a within-tolerance difference is itself a choice.
    balance_tolerance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("1.00")
    )
    rounding_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    rounding_account: Mapped[str | None] = mapped_column(String(64))

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_email: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rules = relationship(
        "JvRule",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="JvRule.sequence",
    )


class JvRule(Base):
    """
    One posting line: these measures, to this account, on this side.

    ``measures`` names keys from ``services.cost_model`` — the same taxonomy the
    cost dashboard reports. That is the whole point of the indirection: an
    account mapped to ``er_pf`` posts exactly the employer PF the dashboard
    shows, so the ledger and the dashboard cannot tell two different stories.
    """

    __tablename__ = "jv_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jv_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    account_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    account_name: Mapped[str | None] = mapped_column(String(160))
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="debit")
    measures: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # Restrict this line to part of the workforce: {"department": ["Sales"]}.
    # A company that books field staff to a different account needs this; one
    # that does not leaves it empty.
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Tag each posted line with a dimension value, overriding the template's
    # own grouping for this line only.
    cost_center_from: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)

    template = relationship("JvTemplate", back_populates="rules")


# ---------------------------------------------------------------------------
# The reconciliation itself
# ---------------------------------------------------------------------------
class ReconRun(Base):
    """
    A reconciliation someone ran and kept.

    Reconciliation is only a control if it leaves a record. A run stores what
    was compared, what came out, and who signed it off, so "payroll was
    reconciled for June" is a fact with evidence behind it rather than a claim.
    """

    __tablename__ = "recon_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # "bank" | "jv" | "both"
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="bank")
    bank_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("bank_files.id", ondelete="SET NULL")
    )
    jv_template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jv_templates.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_by_email: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exceptions = relationship(
        "ReconException", back_populates="run", cascade="all, delete-orphan"
    )


class ReconException(Base):
    """One thing that did not reconcile, and by how much."""

    __tablename__ = "recon_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recon_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    employee_id: Mapped[str | None] = mapped_column(String(64), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(255))
    scope: Mapped[str | None] = mapped_column(String(255))
    expected: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    actual: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    difference: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    run = relationship("ReconRun", back_populates="exceptions")
