"""SQLAlchemy ORM models (SQLite). Money is stored as exact decimal text."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DecimalText(TypeDecorator):
    """Stores Decimal as TEXT so no binary floating point is ever involved."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(200), default="")
    gstin: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    pan: Mapped[str] = mapped_column(String(10), index=True)
    state_code: Mapped[str] = mapped_column(String(2))
    state: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    financial_year: Mapped[str] = mapped_column(String(7), default="")
    registration_type: Mapped[str] = mapped_column(String(40), default="Regular")
    return_frequency: Mapped[str] = mapped_column(String(20), default="Monthly")
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    mobile: Mapped[str] = mapped_column(String(20), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ImportTemplate(Base):
    __tablename__ = "import_templates"
    __table_args__ = (UniqueConstraint("name", name="uq_template_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(10))
    mapping_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceFile(Base):
    __tablename__ = "source_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(10))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    layout: Mapped[str] = mapped_column(String(40))
    period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    documents_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    documents_skipped_existing: Mapped[int] = mapped_column(Integer, default=0)
    mapping_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    imported_by: Mapped[str] = mapped_column(String(80), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    client: Mapped[Client] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_inv_client_source_period", "client_id", "source_type", "period"),
        Index("ix_inv_client_key", "client_id", "supplier_gstin", "invoice_no_norm"),
        Index("ix_inv_identity", "client_id", "identity_hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(10))
    source_rows: Mapped[str] = mapped_column(String(200), default="")
    supplier_gstin: Mapped[str] = mapped_column(String(15))
    supplier_name: Mapped[str] = mapped_column(String(200), default="")
    doc_type: Mapped[str] = mapped_column(String(3))
    invoice_no: Mapped[str] = mapped_column(String(100))
    invoice_no_norm: Mapped[str] = mapped_column(String(100))
    invoice_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(7))
    taxable: Mapped[Decimal] = mapped_column(DecimalText)
    igst: Mapped[Decimal] = mapped_column(DecimalText)
    cgst: Mapped[Decimal] = mapped_column(DecimalText)
    sgst: Mapped[Decimal] = mapped_column(DecimalText)
    cess: Mapped[Decimal] = mapped_column(DecimalText)
    invoice_value: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    place_of_supply: Mapped[str] = mapped_column(String(60), default="")
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    itc_availability: Mapped[str] = mapped_column(String(2), default="")
    itc_reason: Mapped[str] = mapped_column(Text, default="")
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    original_invoice_no: Mapped[str] = mapped_column(String(100), default="")
    original_invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_period: Mapped[str] = mapped_column(String(20), default="")
    identity_hash: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")  # schema v3
    ims_action: Mapped[str] = mapped_column(String(2), default="")  # schema v3
    source_file: Mapped[SourceFile] = relationship()


class ImportIssue(Base):
    __tablename__ = "import_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    sheet: Mapped[str] = mapped_column(String(80), default="")
    row_ref: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(12))
    message: Mapped[str] = mapped_column(Text)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class ReconRun(Base):
    __tablename__ = "recon_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    financial_year: Mapped[str] = mapped_column(String(7))
    period_from: Mapped[str] = mapped_column(String(7))
    period_to: Mapped[str] = mapped_column(String(7))
    comparison: Mapped[str] = mapped_column(String(20), default="BOOKS_VS_GSTR2B")
    settings_json: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(20))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    source_file_ids: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    created_by: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client: Mapped[Client] = relationship()


class ReconLineRow(Base):
    __tablename__ = "recon_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "line_no", name="uq_run_line"),
        Index("ix_line_books", "books_invoice_id"),
        Index("ix_line_g2b", "gstr2b_invoice_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("recon_runs.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80), index=True)
    books_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    gstr2b_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    match_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flags_json: Mapped[str] = mapped_column(Text, default="[]")
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    date_diff_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    remarks: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[str] = mapped_column(String(80), default="")
    action_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user: Mapped[str] = mapped_column(String(80), default="")
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(60), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")


V1_TABLES = [
    SchemaMigration, Client, ImportTemplate, SourceFile, Invoice, ImportIssue, ReconRun, ReconLineRow, AuditLog,
]


# ------------------------------------------------------------------ schema v2
class MatchDecision(Base):
    """A user's manual decision about a books / GSTR-2B pair. Active decisions are
    re-applied by every later reconciliation run of the client."""

    __tablename__ = "match_decisions"
    __table_args__ = (Index("ix_decision_client_active", "client_id", "active"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    books_invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    gstr2b_invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    decision: Mapped[str] = mapped_column(String(10))  # MATCH | REJECT
    remarks: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[str] = mapped_column(String(80), default="")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Vendor(Base):
    """Supplier contact and follow-up register, per client and supplier GSTIN."""

    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("client_id", "gstin", name="uq_vendor_client_gstin"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    gstin: Mapped[str] = mapped_column(String(15))
    name: Mapped[str] = mapped_column(String(200), default="")
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    followup_status: Mapped[str] = mapped_column(String(40), default="")
    next_followup: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Attachment(Base):
    """Supporting evidence for an exception. The file is copied into the app's
    attachment store; the line is identified by the documents it contains so the
    evidence stays visible when the period is re-run."""

    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attach_docs", "books_invoice_id", "gstr2b_invoice_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    run_id: Mapped[int] = mapped_column(Integer)
    line_no: Mapped[int] = mapped_column(Integer)
    books_invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gstr2b_invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


V2_TABLES = [MatchDecision, Vendor, Attachment]


# ------------------------------------------------------------------ schema v3
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ItcRuleRow(Base):
    """Configurable ITC review rule. ``client_id`` NULL = applies to every client."""

    __tablename__ = "itc_rules"
    __table_args__ = (UniqueConstraint("code", "client_id", name="uq_rule_code_client"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    definition_json: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(80), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ItcReview(Base):
    """Reviewer's decision on a rule flag for one document."""

    __tablename__ = "itc_reviews"
    __table_args__ = (UniqueConstraint("invoice_id", "rule_code", name="uq_review_doc_rule"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    rule_code: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(12))  # CONFIRMED | DISMISSED
    remarks: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[str] = mapped_column(String(80), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ItcClaim(Base):
    """ITC claim register: CLAIM, REVERSE and RECLAIM actions per books document and GSTR-3B period."""

    __tablename__ = "itc_claims"
    __table_args__ = (Index("ix_claim_client_period", "client_id", "period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # GSTR-3B period of the action
    action: Mapped[str] = mapped_column(String(10))  # CLAIM | REVERSE | RECLAIM
    igst: Mapped[Decimal] = mapped_column(DecimalText)
    cgst: Mapped[Decimal] = mapped_column(DecimalText)
    sgst: Mapped[Decimal] = mapped_column(DecimalText)
    cess: Mapped[Decimal] = mapped_column(DecimalText)
    reason: Mapped[str] = mapped_column(Text, default="")
    rule_ref: Mapped[str] = mapped_column(String(80), default="")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Gstr3bEntry(Base):
    """GSTR-3B Table 4 values per period, as imported. Re-imports supersede (never delete) older rows."""

    __tablename__ = "gstr3b_entries"
    __table_args__ = (Index("ix_3b_client_period", "client_id", "period", "active"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"))
    period: Mapped[str] = mapped_column(String(7))
    table_code: Mapped[str] = mapped_column(String(6))  # 4A1..4A5, 4B1, 4B2, 4C, 4D1, 4D2
    igst: Mapped[Decimal] = mapped_column(DecimalText)
    cgst: Mapped[Decimal] = mapped_column(DecimalText)
    sgst: Mapped[Decimal] = mapped_column(DecimalText)
    cess: Mapped[Decimal] = mapped_column(DecimalText)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OtherItc(Base):
    """GSTR-2B ITC outside invoice reconciliation: ISD credits and imports (bills of entry)."""

    __tablename__ = "itc_other"
    __table_args__ = (Index("ix_other_client_period", "client_id", "period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    section: Mapped[str] = mapped_column(String(10))  # ISD | ISDA | IMPG | IMPGSEZ
    party: Mapped[str] = mapped_column(String(60), default="")  # ISD GSTIN, SEZ supplier GSTIN or port code
    doc_type: Mapped[str] = mapped_column(String(10), default="")
    doc_no: Mapped[str] = mapped_column(String(60))
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    taxable: Mapped[Decimal] = mapped_column(DecimalText)
    igst: Mapped[Decimal] = mapped_column(DecimalText)
    cgst: Mapped[Decimal] = mapped_column(DecimalText)
    sgst: Mapped[Decimal] = mapped_column(DecimalText)
    cess: Mapped[Decimal] = mapped_column(DecimalText)
    itc_availability: Mapped[str] = mapped_column(String(2), default="")
    identity_hash: Mapped[str] = mapped_column(String(32))


V3_TABLES = [User, AppSetting, ItcRuleRow, ItcReview, ItcClaim, Gstr3bEntry, OtherItc]
