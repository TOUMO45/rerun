"""SQLAlchemy ORM models. SQLite, single tenant, zero ops (§4.1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One end-to-end reproducibility attempt against a single repo."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    repo_url: Mapped[str] = mapped_column(String(1024))
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stage: Mapped[str] = mapped_column(String(64), default="INTAKE")
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    taxonomy_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indeterminate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    build_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    attempts: Mapped[list["RepairAttempt"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    certificate: Mapped["Certificate | None"] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")


class RepairAttempt(Base):
    """One tamper-gate-checked repair attempt within a run's bounded loop (§5.4)."""

    __tablename__ = "repair_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    diff_text: Mapped[str] = mapped_column(Text)
    gate_decision: Mapped[str] = mapped_column(String(16))  # "PASS" | "REJECT"
    gate_violations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="attempts")


class Certificate(Base):
    """The finalized, passport-signed verdict certificate for a run (§8 S3, §6.3)."""

    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), unique=True)
    verdict: Mapped[str] = mapped_column(String(32))
    full_log: Mapped[str] = mapped_column(Text)
    build_plan: Mapped[dict] = mapped_column(JSON)
    diffs: Mapped[list] = mapped_column(JSON)
    reproduction_passport_hash: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="certificate")
