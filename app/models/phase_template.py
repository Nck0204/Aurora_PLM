"""Tabella "phase_templates": i modelli di percorso a fasi."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.phase import Phase


class PhaseTemplate(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un modello di percorso: l'elenco ordinato delle fasi di un progetto.

    Un modello e' **immutabile**. Non si corregge un modello gia' usato: se ne
    crea una nuova versione, con lo stesso nome e "version" aumentato di uno.

    La ragione e' semplice. Un progetto aperto due anni fa e' passato per le
    fasi di allora. Se si potesse modificare il modello a posteriori, la storia
    di quel progetto racconterebbe fasi che al tempo non esistevano, e le
    approvazioni registrate sarebbero riferite a passaggi mai avvenuti. In un
    archivio di documentazione tecnica una storia che si riscrive da sola non
    e' un archivio.

    "is_active" dice se il modello e' proponibile per un progetto nuovo. I
    modelli vecchi restano nel database, disattivati: servono a leggere i
    progetti che li usano.
    """

    __tablename__ = "phase_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_phase_templates_name_version"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Elenco delle norme che il percorso fa rispettare, per esempio
    # ["EN 50155", "ISO 9001"]. E' un elenco di stringhe.
    standards: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Numero di versione del modello: 1, 2, 3. Vedi la docstring sopra.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    phases: Mapped[list["Phase"]] = relationship(
        "Phase",
        back_populates="template",
        order_by="Phase.sort_order",
    )

    def __repr__(self) -> str:
        return f"<PhaseTemplate {self.name} v{self.version}>"
