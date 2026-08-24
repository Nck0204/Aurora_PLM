"""Tabella "users": le persone che usano Aurora."""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, pg_enum
from app.models.enums import GlobalRole


class User(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un utente del programma.

    Attenzione a una cosa sola, ma importante: "username" e' un attributo
    normale, non la chiave. Il giorno in cui una persona cambia cognome, o
    l'azienda cambia il modo di comporre i nomi utente, si aggiorna una casella
    di testo e non si spezza nessun collegamento. Chi punta a un utente punta
    sempre al suo "id".

    Non esiste nessun modo di cancellare un utente: si mette "is_active" a
    falso. Le sue firme sui documenti e le sue righe di audit devono restare
    leggibili anche dieci anni dopo che ha lasciato l'azienda.
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # L'impronta della password prodotta da argon2. Non la password: quella non
    # entra nel database in nessuna forma leggibile. 255 caratteri sono
    # abbondanti per il formato di argon2, che ne usa un centinaio.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Vero quando la password e' stata assegnata da un amministratore e va
    # cambiata al primo accesso.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    global_role: Mapped[GlobalRole] = mapped_column(
        pg_enum(GlobalRole, "global_role"),
        nullable=False,
        default=GlobalRole.UTENTE,
    )

    @property
    def full_name(self) -> str:
        """Nome e cognome, come vanno mostrati nell'interfaccia."""
        return f"{self.first_name} {self.last_name}"

    @property
    def is_creatore(self) -> bool:
        """Vero se l'utente ha il ruolo globale di creatore.

        Esiste perche' i template devono poter nascondere le voci di menu
        riservate, e "utente.is_creatore" non si puo' sbagliare mentre
        "utente.global_role.value == 'creatore'" scritto a mano in dieci
        template prima o poi diventa 'Creatore' in uno di quei dieci.

        Il controllo che conta davvero non e' questo: e' la dipendenza
        richiedi_creatore in app/dependencies.py. Nascondere un collegamento
        non protegge niente, impedisce solo di andare a sbattere.
        """
        return self.global_role is GlobalRole.CREATORE

    def __repr__(self) -> str:
        return f"<User {self.username}>"
