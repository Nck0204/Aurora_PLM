"""Tabella "login_attempts": ogni tentativo di entrare, riuscito o no."""

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IP_ADDRESS_LENGTH, TimestampMixin, UuidPrimaryKeyMixin


class LoginAttempt(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un tentativo di accesso.

    Si registra il nome utente **scritto**, come stringa, non un collegamento
    alla tabella degli utenti: la meta' dei tentativi interessanti riguarda
    nomi utente che non esistono, e quelli un collegamento non potrebbe
    rappresentarli. Per la stessa ragione la colonna non ha vincoli.

    Serve a due cose: bloccare temporaneamente chi sbaglia troppe volte di
    seguito, e accorgersi di un tentativo di indovinare le password.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        # Le due domande che si fanno a questa tabella sono sempre "quanti
        # tentativi falliti da questo nome utente / da questo indirizzo nel
        # giro degli ultimi minuti": due indici su nome e data, e su IP e data.
        Index("ix_login_attempts_username_created", "username", "created_at"),
        Index("ix_login_attempts_ip_created", "ip", "created_at"),
    )

    username: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(IP_ADDRESS_LENGTH), nullable=True)

    def __repr__(self) -> str:
        esito = "riuscito" if self.success else "fallito"
        return f"<LoginAttempt {self.username} {esito}>"
