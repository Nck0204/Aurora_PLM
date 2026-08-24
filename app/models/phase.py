"""Tabella "phases": le singole fasi dentro un modello di percorso."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
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

    template: Mapped["PhaseTemplate"] = relationship(
        "PhaseTemplate", back_populates="phases"
    )

    def __repr__(self) -> str:
        return f"<Phase {self.sort_order}. {self.name}>"
