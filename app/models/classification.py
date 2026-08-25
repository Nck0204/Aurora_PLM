"""Tabella "classifications": le classi di riservatezza dei documenti."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class Classification(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una classificazione: Tecnico, Commerciale, Qualita', Amministrativo.

    Non e' una semplice etichetta di comodo: e' l'asse su cui girano i
    permessi. Chi puo' vedere un documento non dipende dal documento ma dalla
    coppia (ruolo nel progetto, classificazione del documento), scritta nella
    tabella "permission_rules". Un ingegnere non vede i documenti commerciali
    del progetto su cui lavora, e questa e' la riga di codice che lo decide.

    Le classificazioni sono poche e stabili: si aggiungono, non si cancellano.
    Quella che non serve piu' si **disattiva** (is_active): sparisce dai menu a
    tendina e dai filtri, ma la riga resta con le sue caselle della matrice.
    Cancellarla vorrebbe dire lasciare senza regola i documenti che ce
    l'hanno addosso, ed e' il motivo per cui la pagina che le amministra si
    rifiuta di disattivare una classificazione ancora in uso.
    """

    __tablename__ = "classifications"

    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ordine con cui compaiono negli elenchi e nei menu a tendina.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Falso per le classificazioni messe da parte. Non si cancella niente:
    # regola 5 di CLAUDE.md.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<Classification {self.name}>"
