"""Tabella "phases": le singole fasi dentro un modello di percorso."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.phase_template import PhaseTemplate


class Phase(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una fase: "Concept", "Feasibility", "Development".

    Una fase appartiene a un modello e a un modello solo. Due modelli che hanno
    entrambi una fase chiamata "Concept" hanno due righe distinte: sono due
    fasi diverse che si chiamano allo stesso modo. E' voluto, ed e' la
    conseguenza dell'immutabilita' dei modelli.

    "sort_order" e' l'ordine di attraversamento. Non e' detto che le fasi si
    percorrano tutte e in fila: si puo' tornare indietro, e il passaggio da una
    fase all'altra lascia una riga in "phase_transitions".

    LE DUE SPUNTE SONO LA PARTE IMPORTANTE DI QUESTA TABELLA. Le fasi sono
    dati e non codice: aggiungerne una, rinominarla o riordinarla non deve
    costare una riga di programma. Ma due fasi su sei si comportano in modo
    particolare - da una non si torna indietro, un'altra chiude il progetto -
    e quel comportamento deve stare nel dato, non in un `if` sul nome (D-055).

    "blocks_return"   da questa fase non si torna a una precedente. E' la
                      fase in cui il prodotto e' in mano ai progettisti: se
                      si e' sbagliato qualcosa non si riavvolge il progetto,
                      si apre una versione di prodotto nuova.
    "closes_project"  entrando in questa fase il progetto si chiude, cioe'
                      "projects.closed_at" viene valorizzato. E' l'ultima
                      casella del percorso.
    """

    __tablename__ = "phases"
    __table_args__ = (
        UniqueConstraint(
            "phase_template_id", "sort_order", name="uq_phases_template_order"
        ),
        UniqueConstraint("phase_template_id", "name", name="uq_phases_template_name"),
    )

    phase_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("phase_templates.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vedi la docstring: sono le due proprieta' che rendono il percorso un
    # dato e non un pezzo di programma.
    blocks_return: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    closes_project: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    template: Mapped["PhaseTemplate"] = relationship(
        "PhaseTemplate", back_populates="phases"
    )

    def __repr__(self) -> str:
        return f"<Phase {self.sort_order}. {self.name}>"
