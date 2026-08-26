"""Tabella "phase_transitions": la storia dei passaggi di fase."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import PhaseTransitionState

if TYPE_CHECKING:
    from app.models.phase import Phase
    from app.models.project import Project
    from app.models.user import User


class PhaseTransition(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Il passaggio di un progetto da una fase a un'altra.

    Questa tabella e' un registro: le righe si aggiungono, non si modificano e
    non si tolgono. L'unica cosa che cambia dopo la scrittura e' l'esito di una
    riga ancora "richiesta", che diventa "approvata" o "respinta" quando il
    project manager la guarda: la domanda non si riscrive, le si mette accanto
    la risposta.

    Messe in fila per data raccontano tutta la storia del progetto, compresi i
    passi indietro e le richieste che non sono state accolte.

    "from_phase_id" e' nullo per il primo passaggio, quello che fa entrare il
    progetto nella sua prima fase: prima non c'era nessuna fase da cui uscire.

    CHI CHIEDE E CHI DECIDE SONO DUE COLONNE DIVERSE, e devono restare
    distinguibili anche a distanza di anni: e' il senso di questa tabella. Un
    project manager che avanza per conto suo compare in tutte e due, ed e'
    esattamente quello che e' successo.

    "decided_by_id" si chiama cosi' e non "approved_by_id" perche' una
    richiesta si puo' anche **respingere**, e una colonna chiamata "approvato
    da" che contiene il nome di chi ha detto di no e' una colonna che mente a
    chi la legge fra due anni (D-057).

    "seen_at" e' la notifica dentro l'applicazione: dice quando chi aveva
    chiesto il passaggio ha letto l'esito. Finche' e' nullo, l'esito compare
    sul suo cruscotto. E' una colonna e non una tabella delle notifiche
    perche' la tabella delle notifiche e' lavoro della sessione 10, e
    anticiparla vorrebbe dire progettarla adesso per un caso solo (D-060).
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

    # A che punto e' questo passaggio: solo chiesto, accolto, oppure respinto.
    state: Mapped[PhaseTransitionState] = mapped_column(
        pg_enum(PhaseTransitionState, "phase_transition_state"),
        nullable=False,
        index=True,
        default=PhaseTransitionState.APPROVATA,
        server_default=PhaseTransitionState.APPROVATA.value,
    )

    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Quando la decisione e' stata presa. Non coincide con created_at: una
    # richiesta scritta lunedi' puo' essere approvata giovedi', e la fase e'
    # cambiata giovedi'. E' questa la data con cui si misura quanto e' durata
    # ciascuna fase.
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Il motivo del passaggio, scritto da chi lo richiede. In italiano.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Il motivo dell'approvazione o del rifiuto, scritto da chi decide.
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quando chi ha chiesto il passaggio ha letto l'esito. Vedi la docstring.
    seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship("Project")
    from_phase: Mapped["Phase | None"] = relationship(
        "Phase", foreign_keys=[from_phase_id]
    )
    to_phase: Mapped["Phase"] = relationship("Phase", foreign_keys=[to_phase_id])
    requested_by: Mapped["User"] = relationship("User", foreign_keys=[requested_by_id])
    decided_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[decided_by_id]
    )

    def __repr__(self) -> str:
        return (
            f"<PhaseTransition progetto {self.project_id} "
            f"-> {self.to_phase_id} ({self.state.value})>"
        )
