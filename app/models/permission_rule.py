"""Tabella "permission_rules": chi puo' fare che cosa, per classificazione."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import ProjectRole

if TYPE_CHECKING:
    from app.models.classification import Classification


class PermissionRule(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una casella della matrice dei permessi.

    La matrice ha una riga per ogni coppia (ruolo nel progetto,
    classificazione) e tre caselle: vedere, caricare, modificare. Con tre ruoli
    e quattro classificazioni sono dodici righe in tutto, e ci sono **tutte**,
    anche quelle con tutti i permessi a falso.

    Averle tutte scritte e' voluto: cosi' la risposta a "l'ingegnere puo'
    vedere i documenti commerciali?" e' una riga che dice no, non una riga che
    manca. Una riga che manca si puo' sempre leggere come una dimenticanza.

    I permessi valgono **dentro un progetto**: chi non e' assegnato a un
    progetto non ha nessun ruolo su quel progetto, quindi nessun permesso.
    """

    __tablename__ = "permission_rules"
    __table_args__ = (
        UniqueConstraint(
            "project_role",
            "classification_id",
            name="uq_permission_rules_role_classification",
        ),
    )

    project_role: Mapped[ProjectRole] = mapped_column(
        pg_enum(ProjectRole, "project_role"), nullable=False
    )

    classification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classifications.id"), nullable=False, index=True
    )

    # Vedere che il documento esiste e scaricarlo.
    can_view: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Caricare una nuova versione di un documento esistente, o un documento
    # nuovo con questa classificazione.
    can_upload: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Cambiare i dati del documento (titolo, tipo, stato) e ritirarlo.
    can_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    classification: Mapped["Classification"] = relationship("Classification")

    def __repr__(self) -> str:
        return f"<PermissionRule {self.project_role.value} su {self.classification_id}>"
