"""Tabella "audit_logs": il registro di chi ha fatto che cosa."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import IP_ADDRESS_LENGTH, TimestampMixin, UuidPrimaryKeyMixin
from app.models.user import User


class AuditLog(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una riga del registro delle operazioni.

    E' la tabella che rende vera la regola 6 di CLAUDE.md. Ogni riga risponde
    sempre alle stesse cinque domande: chi, che cosa, su quale oggetto, quando,
    da quale indirizzo.

    Si scrive e non si tocca piu': niente UPDATE, niente DELETE. Un registro
    che si puo' correggere non e' un registro.

    Quattro scelte che vale la pena di spiegare.

    "entity_id" e' un UUID **senza** chiave esterna. Deve poter puntare a
    qualunque tabella, e una chiave esterna punta a una tabella sola. In piu'
    una chiave esterna impedirebbe di registrare operazioni su righe che al
    momento della registrazione non esistono ancora o non esistono piu'.

    "user_id" puo' essere nullo: certe operazioni le fa il programma da solo,
    per esempio un lavoro pianificato di notte, e non c'e' nessuna persona da
    indicare. Meglio nullo che una persona finta.

    "old_value" e "new_value" contengono solo i campi cambiati, non la riga
    intera: serve capire che cosa e' cambiato, non tenere venti copie di ogni
    riga.

    "occurred_at" e "created_at" quasi sempre coincidono, e restano comunque
    due colonne diverse perche' dicono due cose diverse: la prima quando il
    fatto e' successo, la seconda quando la riga e' stata scritta. Se un giorno
    le registrazioni verranno scritte in differita, la differenza fra le due
    sara' l'unico modo di rimettere i fatti nell'ordine giusto.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # Le due interrogazioni che si fanno a un registro: "tutto quello che
        # e' successo a questo oggetto" e "tutto quello che ha fatto questa
        # persona", in ordine di tempo.
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_logs_user_occurred", "user_id", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Che cosa e' stato fatto, in inglese e in forma breve, per esempio
    # "document.upload", "project.close", "user.login".
    action: Mapped[str] = mapped_column(String(80), nullable=False)

    # Su che tipo di oggetto, con il nome della tabella: "documents",
    # "projects", "users".
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUuid(as_uuid=True), nullable=True
    )

    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(IP_ADDRESS_LENGTH), nullable=True)

    user: Mapped[User | None] = relationship(User)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} su {self.entity_type}>"
