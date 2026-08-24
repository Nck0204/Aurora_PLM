"""Tabella "product_versions": le versioni successive di un prodotto."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import LifecycleState

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.project import Project


class ProductVersion(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una versione di un prodotto: la 1, la 2, la 3.

    Le versioni sono il vero oggetto del lavoro. Un progetto si apre su una
    versione, non su un prodotto; i documenti e i messaggi di posta si
    attaccano a una versione. Il prodotto e' solo il filo che le tiene
    insieme.

    Una versione puo' **discendere** da un'altra: e' il caso normale quando si
    parte da una versione esistente per farne una variante o un'evoluzione.
    "derived_from_id" punta alla versione di partenza e "derivation_reason"
    spiega perche' e' stata derivata, in italiano, scritto da una persona.
    La colonna e' facoltativa perche' la prima versione non discende da niente.
    """

    __tablename__ = "product_versions"
    __table_args__ = (
        # Due volte la "versione 2" dello stesso prodotto non deve esistere.
        UniqueConstraint(
            "product_id", "version_number", name="uq_product_versions_product_number"
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )

    # Numero intero progressivo dentro il prodotto: 1, 2, 3. Non una stringa
    # tipo "1.0.2": qui la versione e' un contatore, non un numero di rilascio.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        pg_enum(LifecycleState, "lifecycle_state"),
        nullable=False,
        default=LifecycleState.IN_SVILUPPO,
        index=True,
    )

    # Autoriferimento: punta a un'altra riga di questa stessa tabella.
    derived_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_versions.id"), nullable=True, index=True
    )
    derivation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quando la versione e' passata allo stato "rilasciato". Nulla finche' e'
    # in sviluppo.
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    product: Mapped["Product"] = relationship("Product", back_populates="versions")

    # Il progetto aperto su questa versione, se e' stato aperto. Uno soltanto:
    # il vincolo di unicita' sta su projects.product_version_id.
    project: Mapped["Project | None"] = relationship(
        "Project", back_populates="product_version", uselist=False
    )

    # La versione da cui questa discende. "remote_side" serve a dire a
    # SQLAlchemy da che parte sta il "uno" e da che parte il "molti": senza,
    # non saprebbe leggere un collegamento che punta alla propria tabella.
    derived_from: Mapped["ProductVersion | None"] = relationship(
        "ProductVersion",
        remote_side="ProductVersion.id",
        back_populates="derived_versions",
    )

    # Le versioni che discendono da questa.
    derived_versions: Mapped[list["ProductVersion"]] = relationship(
        "ProductVersion",
        back_populates="derived_from",
    )

    def __repr__(self) -> str:
        return f"<ProductVersion {self.version_number} di {self.product_id}>"
