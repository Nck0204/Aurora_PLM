"""Tabella "email_messages": la posta archiviata e collegata ai prodotti."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import (
    SHA256_HEX_LENGTH,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    pg_enum,
)
from app.models.enums import EmailAssignmentState

if TYPE_CHECKING:
    from app.models.email_attachment import EmailAttachment
    from app.models.product_version import ProductVersion
    from app.models.user import User


class EmailMessage(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un messaggio di posta archiviato dentro Aurora.

    Nella documentazione tecnica meta' delle decisioni sta nelle mail: la
    modifica concordata al telefono e confermata per iscritto, il nulla osta
    del cliente, la richiesta di deroga. Se restano nella casella personale di
    chi le ha ricevute, il giorno che quella persona cambia lavoro spariscono.

    Il messaggio si attacca a una **versione di prodotto**, non a un progetto:
    la corrispondenza con il cliente continua anche dopo che il progetto e'
    chiuso e il prodotto e' in produzione.

    "assignment_state" dice come e' avvenuto il collegamento. Quando vale
    "quarantena" il collegamento non c'e' ancora: "product_version_id" e' nullo
    e il messaggio aspetta che una persona lo smisti. E' l'unico caso in cui
    quella colonna e' vuota, ed e' il motivo per cui puo' esserlo.

    Le tre colonne "internet_message_id", "in_reply_to" e "thread_references"
    sono le intestazioni standard della posta: sono quelle che permettono di
    ricostruire le catene di risposte, ed e' anche cosi' che il programma
    indovina a quale prodotto appartiene un messaggio nuovo. Il "Message-ID" e'
    unico per costruzione, e qui il vincolo di unicita' serve a non archiviare
    due volte lo stesso messaggio se la casella viene riletta.
    """

    __tablename__ = "email_messages"

    # Nullo solo quando assignment_state vale "quarantena".
    product_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_versions.id"), nullable=True, index=True
    )

    internet_message_id: Mapped[str] = mapped_column(
        String(998), nullable=False, unique=True
    )
    in_reply_to: Mapped[str | None] = mapped_column(String(998), nullable=True)

    # L'intestazione "References" per intero: e' la catena di tutti i messaggi
    # precedenti del filo e puo' essere lunghissima, quindi Text e non String.
    thread_references: Mapped[str | None] = mapped_column(Text, nullable=True)

    sender: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    # Destinatari come elenco di oggetti, per esempio
    # [{"tipo": "a", "indirizzo": "mario@cliente.it", "nome": "Mario Rossi"}].
    # Un elenco e non una stringa perche' su un elenco si puo' cercare.
    recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # L'oggetto scomposto negli elementi riconosciuti, per esempio il codice
    # prodotto trovato dentro. Come "code_parts" dei prodotti: e' un dato
    # ricavato, serve a smistare, non e' la fonte della verita'.
    subject_parsed: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Quando e' stato spedito (secondo il messaggio) e quando lo abbiamo
    # ricevuto noi. Sono due cose diverse e possono distare parecchio.
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Impronta SHA-256 del file .eml completo, depositato nell'archivio come
    # tutti gli altri file (D-004). Il messaggio originale si conserva intero:
    # le colonne qui sotto sono una copia comoda per cercare, non un sostituto.
    storage_hash: Mapped[str] = mapped_column(
        String(SHA256_HEX_LENGTH), nullable=False, index=True
    )

    # Il corpo del messaggio in testo semplice, per la ricerca a parole.
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignment_state: Mapped[EmailAssignmentState] = mapped_column(
        pg_enum(EmailAssignmentState, "email_assignment_state"),
        nullable=False,
        default=EmailAssignmentState.QUARANTENA,
        index=True,
    )

    # Chi ha fatto lo smistamento a mano. Nullo quando lo ha fatto il
    # programma da solo o quando il messaggio e' ancora in quarantena.
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    product_version: Mapped["ProductVersion | None"] = relationship("ProductVersion")
    assigned_by: Mapped["User | None"] = relationship("User")
    attachments: Mapped[list["EmailAttachment"]] = relationship(
        "EmailAttachment", back_populates="message"
    )

    def __repr__(self) -> str:
        return f"<EmailMessage {self.subject}>"
