"""Tabella "projects": il lavoro aperto su una versione di prodotto."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.document import Document
    from app.models.phase import Phase
    from app.models.phase_template import PhaseTemplate
    from app.models.product_version import ProductVersion
    from app.models.user import User


class Project(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un progetto: il lavoro che si fa su **una** versione di prodotto.

    Il legame con la versione di prodotto e' uno a uno, imposto dal vincolo di
    unicita' su "product_version_id". Non "un progetto per prodotto": un
    progetto per versione. La versione 2 di un prodotto e' un lavoro nuovo, con
    la sua squadra, i suoi documenti e le sue fasi.

    Un progetto non si cancella e non si archivia: si chiude, valorizzando
    "closed_at".
    """

    __tablename__ = "projects"

    # Unico: una versione di prodotto ha al massimo un progetto.
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_versions.id"), nullable=False, unique=True
    )

    project_manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Il modello di fasi scelto alla nascita del progetto. Resta quello per
    # tutta la vita del progetto anche se nel frattempo il modello viene
    # sostituito da una versione piu' recente: i modelli sono immutabili.
    phase_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("phase_templates.id"), nullable=False, index=True
    )

    # La fase in cui il progetto si trova adesso. Puo' essere nulla nel breve
    # intervallo fra la creazione del progetto e l'ingresso nella prima fase.
    current_phase_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phases.id"), nullable=True, index=True
    )

    # Le norme applicabili a questo progetto, per esempio
    # ["EN 50155", "EN 45545-2"]. Partono da quelle del modello di fasi e
    # possono essere allargate o ristrette sul singolo progetto: per questo
    # sono scritte anche qui e non solo sul modello.
    standards: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    product_version: Mapped["ProductVersion"] = relationship(
        "ProductVersion", back_populates="project"
    )
    project_manager: Mapped["User"] = relationship("User")
    phase_template: Mapped["PhaseTemplate"] = relationship("PhaseTemplate")
    current_phase: Mapped["Phase | None"] = relationship("Phase")

    assignments: Mapped[list["Assignment"]] = relationship(
        "Assignment", back_populates="project"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="project"
    )

    def __repr__(self) -> str:
        return f"<Project su versione {self.product_version_id}>"
