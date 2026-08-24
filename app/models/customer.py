"""Tabella "customers": i clienti per cui l'azienda sviluppa prodotti."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.product import Product


class Customer(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un cliente.

    "code" e' la sigla breve con cui il cliente viene chiamato in azienda e che
    compare dentro i codici dei prodotti. E' unica, ma resta un attributo: se
    domani va cambiata si cambia qui, senza toccare nessuna riga collegata.
    """

    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    contacts: Mapped[list["Contact"]] = relationship(
        "Contact", back_populates="customer"
    )
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="customer"
    )

    def __repr__(self) -> str:
        return f"<Customer {self.code}>"
