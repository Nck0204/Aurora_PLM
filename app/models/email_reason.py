"""Tabella "email_reasons": i motivi ammessi nell'oggetto di un messaggio."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class EmailReason(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Un motivo fra quelli ammessi nella terza parentesi dell'oggetto.

    La convenzione aziendale vuole che l'oggetto di un messaggio cominci con
    tre parentesi quadre: `[RMS1100-24-110SW][V2][SPECS]`. La terza dice
    **perche'** si scrive - una richiesta di specifiche, un'offerta, una
    modifica - e serve a chi legge la posta archiviata mesi dopo.

    L'elenco dei motivi ammessi e' una riga di tabella e non una costante nel
    programma per la stessa ragione per cui le fasi sono dati (D-055):
    l'azienda ne aggiungera' e ne toglera', e farlo non deve costare una
    modifica al codice. Si amministra da `/posta/motivi`.

    **Il motivo non decide niente.** Un oggetto con un motivo sconosciuto non
    viene rifiutato: il messaggio si attribuisce lo stesso al prodotto, e il
    motivo non riconosciuto resta scritto in `subject_parsed` perche' chi
    amministra possa accorgersi che ne serve uno nuovo. Fermarsi su un motivo
    fuori elenco vorrebbe dire mettere in quarantena della posta che sappiamo
    benissimo a chi appartiene.

    Come tutto il resto in Aurora non si cancella: si disattiva (regola 5 di
    CLAUDE.md). Un motivo disattivato smette di essere proponibile ma i
    messaggi che ce l'hanno addosso continuano a mostrarlo.
    """

    __tablename__ = "email_reasons"

    # Il codice come si scrive nell'oggetto: SPECS, RFQ, QUOTE. Sempre in
    # maiuscolo - lo normalizza il servizio - perche' il confronto con quello
    # che arriva nell'oggetto deve essere una uguaglianza e non un indovinello.
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ordine con cui compaiono nella pagina che li amministra e nei filtri.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<EmailReason {self.code}>"
