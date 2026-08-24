"""Tabella "documents": i documenti di un progetto."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import DocumentState

if TYPE_CHECKING:
    from app.models.classification import Classification
    from app.models.document_version import DocumentVersion
    from app.models.project import Project
    from app.models.user import User


class Document(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un documento: uno schema, una distinta, un'offerta, un verbale.

    Il documento e' il **contenitore**, non il file. Il file sta nelle righe di
    "document_versions": un documento ha una versione 1, poi una 2, poi una 3,
    e resta lo stesso documento. Titolo, tipo, classificazione e stato stanno
    qui perche' descrivono il documento, non il singolo file.

    Due meccanismi meritano una parola.

    **Presa in carico** ("check-out"). Quando qualcuno sta lavorando a una
    nuova versione, "checked_out_by_id" dice chi e "checked_out_at" da quando.
    Serve a evitare che due persone preparino in parallelo due versioni
    diverse dello stesso schema e una delle due butti via il lavoro dell'altra.

    **Cancellazione**. Non esiste. "deleted_at" e "deleted_by_id" segnano che
    il documento e' stato tolto dagli elenchi, chi lo ha tolto e quando. Il
    file nell'archivio resta dov'e' (D-004: potrebbe essere riferito da altri
    documenti che hanno lo stesso contenuto).
    """

    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Che genere di documento e': "Schema elettrico", "Distinta base",
    # "Offerta", "Verbale di collaudo". Testo libero in R1; se serviranno
    # valori controllati diventera' una tabella a se'.
    doc_type: Mapped[str] = mapped_column(String(80), nullable=False)

    # Obbligatoria: senza classificazione non si puo' decidere chi vede il
    # documento, e un documento che nessuno sa a chi mostrare non deve esistere.
    classification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classifications.id"), nullable=False, index=True
    )

    state: Mapped[DocumentState] = mapped_column(
        pg_enum(DocumentState, "document_state"),
        nullable=False,
        default=DocumentState.BOZZA,
        index=True,
    )

    checked_out_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    checked_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="documents")
    classification: Mapped["Classification"] = relationship("Classification")
    checked_out_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[checked_out_by_id]
    )
    deleted_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[deleted_by_id]
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        order_by="DocumentVersion.version_number",
    )

    @property
    def is_deleted(self) -> bool:
        """Vero se il documento e' stato tolto dagli elenchi."""
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<Document {self.title}>"
