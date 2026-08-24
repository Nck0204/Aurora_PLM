"""Tabella "user_sessions": le sessioni di accesso aperte dagli utenti."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import (
    IP_ADDRESS_LENGTH,
    SHA256_HEX_LENGTH,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    pg_enum,
)
from app.models.enums import SessionKind
from app.models.user import User


class UserSession(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una sessione di accesso: un utente entrato da un browser.

    Nel database non finisce il gettone consegnato al browser ma la sua
    impronta SHA-256. E' lo stesso principio delle password: se qualcuno si
    procura una copia del database non deve poter entrare fingendosi un altro.

    Una sessione non si cancella mai: si segna la data in "revoked_at". Cosi'
    resta la traccia di chi era entrato, da dove e fino a quando.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    token_hash: Mapped[str] = mapped_column(
        String(SHA256_HEX_LENGTH), nullable=False, unique=True
    )

    kind: Mapped[SessionKind] = mapped_column(
        pg_enum(SessionKind, "session_kind"),
        nullable=False,
        default=SessionKind.SESSIONE,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Valorizzata quando l'utente esce, o quando un amministratore butta fuori
    # una sessione. Nulla finche' la sessione e' valida.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ip: Mapped[str | None] = mapped_column(String(IP_ADDRESS_LENGTH), nullable=True)

    # La riga "User-Agent" mandata dal browser. Serve a far riconoscere le
    # proprie sessioni a colpo d'occhio ("Chrome su Windows") ed e' lunga.
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    user: Mapped[User] = relationship(User)

    def __repr__(self) -> str:
        return f"<UserSession {self.id} kind={self.kind.value}>"
