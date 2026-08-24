"""Tabella "products": i prodotti sviluppati per i clienti."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.product_version import ProductVersion


class Product(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un prodotto, identificato dal suo codice parlante.

    Il codice di un prodotto racconta il prodotto: in "RMS1100-24-110SW" ci
    sono la famiglia, il modello, la tensione di alimentazione, la variante.
    Le persone lo leggono e capiscono. Il programma no, e non deve provarci:
    per lui e' una stringa. La scomposizione in pezzi riconosciuti sta in
    "code_parts", che e' un dato ricavato, comodo per cercare e per filtrare,
    mai la fonte della verita'.

    Il codice e' unico e non e' la chiave primaria: vedi D-013.
    """

    __tablename__ = "products"

    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    # Ogni prodotto e' sviluppato per un cliente. Se un giorno servissero
    # prodotti a catalogo, senza committente, questa colonna andra' resa
    # facoltativa con una migrazione: vedi la nota in docs/MODELLO_DATI.md.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Il codice scomposto negli elementi riconosciuti, per esempio
    # {"famiglia": "RMS", "modello": "1100", "tensione": "110", ...}.
    # Vuoto quando il codice non segue nessuno schema noto.
    code_parts: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="products")
    versions: Mapped[list["ProductVersion"]] = relationship(
        "ProductVersion",
        back_populates="product",
        order_by="ProductVersion.version_number",
    )

    def __repr__(self) -> str:
        return f"<Product {self.code}>"
