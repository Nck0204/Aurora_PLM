"""Tabella "document_versions": i file veri e propri, uno per versione."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SHA256_HEX_LENGTH, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class DocumentVersion(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una versione di un documento: un file caricato, in un certo momento.

    Le righe di questa tabella non si modificano mai. Una versione caricata e'
    un fatto avvenuto: se il file era sbagliato si carica la versione
    successiva, non si corregge quella prima.

    Il file non e' qui dentro. "storage_hash" e' l'impronta SHA-256 del suo
    contenuto, e da quella si ricava il percorso nell'archivio (D-004). Due
    caricamenti dello stesso identico file hanno la stessa impronta e occupano
    un file solo sul disco, pur restando due righe distinte qui.

    "original_filename" e' il nome che il file aveva sul computer di chi lo ha
    caricato: e' quello che l'utente riconosce, e quello con cui glielo si
    restituisce quando lo riscarica.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_doc_number"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Impronta SHA-256 del contenuto, in esadecimale minuscolo. Indicizzata
    # perche' la domanda "dove altro compare questo stesso file" si fa spesso.
    storage_hash: Mapped[str] = mapped_column(
        String(SHA256_HEX_LENGTH), nullable=False, index=True
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # BigInteger e non Integer: i 2 GB del tipo normale sono pochi per un file.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)

    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Che cosa e' cambiato rispetto alla versione precedente, scritto da chi
    # carica. In italiano: lo legge un collega, non il programma.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="versions")
    author: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return f"<DocumentVersion {self.version_number} di {self.document_id}>"
