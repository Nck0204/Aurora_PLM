"""Tabella "email_attachments": gli allegati dei messaggi archiviati."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SHA256_HEX_LENGTH, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.email_message import EmailMessage


class EmailAttachment(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un allegato staccato da un messaggio e messo nell'archivio.

    Gli allegati si estraggono e si depositano come tutti gli altri file, per
    impronta (D-004). Il vantaggio si vede subito: lo stesso datasheet che gira
    allegato a venti mail occupa un file solo, e si trova cercando una volta.

    Un allegato non e' un documento di progetto. Se merita di diventarlo,
    qualcuno lo promuove creando un "document": e' un gesto voluto, non
    automatico, perche' un allegato e' quello che ha mandato qualcun altro
    mentre un documento e' quello di cui l'azienda risponde.
    """

    __tablename__ = "email_attachments"

    email_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_messages.id"), nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    storage_hash: Mapped[str] = mapped_column(
        String(SHA256_HEX_LENGTH), nullable=False, index=True
    )

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)

    message: Mapped["EmailMessage"] = relationship(
        "EmailMessage", back_populates="attachments"
    )

    def __repr__(self) -> str:
        return f"<EmailAttachment {self.filename}>"
