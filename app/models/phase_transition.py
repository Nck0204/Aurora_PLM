"""Tabella "phase_transitions": la storia dei passaggi di fase."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.phase import Phase
    from app.models.project import Project
    from app.models.user import User


class PhaseTransition(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Il passaggio di un progetto da una fase a un'altra.

    Questa tabella e' un registro: le righe si aggiungono, non si modificano e
    non si tolgono. Messe in fila per data raccontano tutta la storia del
    progetto, compresi i passi indietro.

    "from_phase_id" e' nullo per il primo passaggio, quello che fa entrare il
    progetto nella sua prima fase: prima non c'era nessuna fase da cui uscire.

    "approved_by_id" e' nullo finche' il passaggio e' solo richiesto. Chi
    richiede e chi approva sono due persone distinte, e devono restare
    distinguibili anche a distanza di anni: e' il senso di questa tabella.
    """

    __tablename__ = "phase_transitions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )

    from_phase_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phases.id"), nullable=True
    )
    to_phase_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("phases.id"), nullable=False
    )

    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Il motivo del passaggio, scritto da chi lo richiede. In italiano.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship("Project")
    from_phase: Mapped["Phase | None"] = relationship(
        "Phase", foreign_keys=[from_phase_id]
    )
    to_phase: Mapped["Phase"] = relationship("Phase", foreign_keys=[to_phase_id])
    requested_by: Mapped["User"] = relationship("User", foreign_keys=[requested_by_id])
    approved_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[approved_by_id]
    )

    def __repr__(self) -> str:
        return f"<PhaseTransition progetto {self.project_id} -> {self.to_phase_id}>"
