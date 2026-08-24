"""Tabella "contacts": le persone di riferimento presso un cliente."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class Contact(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una persona presso un cliente: chi si scrive e chi si chiama.

    L'indirizzo di posta non e' unico: la stessa casella (per esempio
    "ufficio.tecnico@cliente.it") puo' essere il riferimento di piu' persone,
    e la stessa persona puo' comparire per due clienti diversi.

    "role" e' il ruolo che la persona ha presso il cliente, scritto a mano
    ("responsabile acquisti", "progettista"): e' un'annotazione, non un valore
    su cui il programma prende decisioni.
    """

    __tablename__ = "contacts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="contacts")

    def __repr__(self) -> str:
        return f"<Contact {self.name}>"
