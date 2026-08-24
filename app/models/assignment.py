"""Tabella "assignments": chi lavora a quale progetto e con che ruolo."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import ProjectRole

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class Assignment(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """L'assegnazione di una persona a un progetto, con un ruolo.

    E' la riga che da' i permessi: un utente vede un progetto se e solo se ha
    un'assegnazione non revocata su quel progetto, e quello che ci puo' fare
    dipende dal ruolo scritto qui, incrociato con la classificazione del
    documento (vedi "permission_rules").

    Un'assegnazione non si cancella: si revoca, scrivendo data e autore in
    "revoked_at" e "revoked_by_id". "Chi aveva accesso a quel progetto nel
    marzo scorso" e' una domanda a cui bisogna poter rispondere.

    "assigned_by_id" e' chi ha dato l'incarico, "user_id" chi lo ha ricevuto:
    sono due collegamenti diversi alla stessa tabella, per questo le due
    relazioni qui sotto devono dichiarare esplicitamente su quale colonna
    poggiano.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        # Una persona ha al massimo **un** ruolo attivo su un progetto: due
        # ruoli contemporanei renderebbero ambiguo il calcolo dei permessi.
        # L'indice e' parziale (vale solo per le righe non revocate), cosi' la
        # stessa persona puo' essere riassegnata dopo una revoca, e la storia
        # delle assegnazioni precedenti resta tutta nella tabella.
        Index(
            "uq_assignments_active_user_per_project",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    project_role: Mapped[ProjectRole] = mapped_column(
        pg_enum(ProjectRole, "project_role"), nullable=False
    )

    assigned_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="assignments")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    assigned_by: Mapped["User"] = relationship("User", foreign_keys=[assigned_by_id])
    revoked_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[revoked_by_id]
    )

    def __repr__(self) -> str:
        return f"<Assignment {self.user_id} come {self.project_role.value}>"
