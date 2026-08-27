"""Tabella "backups": l'esito di ogni copia di sicurezza eseguita."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class Backup(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Una copia di sicurezza tentata: quando, dove, com'e' andata.

    **Perche' e' una tabella e non una riga nel registro su file.** Perche' la
    domanda a cui deve rispondere e' "l'ultima copia e' andata bene?", e quella
    domanda la fa la pagina di diagnostica ogni volta che qualcuno la apre. Un
    file di testo da rileggere e interpretare a ogni caricamento di pagina
    sarebbe la risposta sbagliata a una domanda facile.

    **Ci scrive uno script, non il programma.** `scripts/backup.py` gira dalla
    riga di comando - di notte, dall'Utilita' di pianificazione di Windows - e
    apre la sua sessione del database da solo. Aurora questa tabella la legge
    e basta.

    **Anche la copia fallita lascia la sua riga.** E' il punto: una copia che
    non e' partita e non ha lasciato traccia e' indistinguibile da una copia
    che nessuno ha mai programmato, e sono due guasti diversi con due rimedi
    diversi. Per questo `outcome` ha tre valori e non due:

        "riuscito"   il file c'e' ed e' stato verificato
        "fallito"    il tentativo c'e' stato e non e' andato a buon fine
        "in_corso"   la riga e' stata aperta e non ancora chiusa: se resta
                     cosi', la copia e' stata interrotta a meta'

    Non e' un tipo enumerato di PostgreSQL come gli altri (D-014) e la ragione
    e' che questi tre valori non sono uno stato del lavoro dell'azienda: sono
    l'esito di una procedura di manutenzione, che va letta anche da fuori
    Aurora con un `SELECT` scritto a mano. Una colonna di testo la legge
    chiunque; un tipo enumerato costringe chi indaga a scoprire prima come si
    chiama.
    """

    __tablename__ = "backups"

    # Quando il tentativo e' cominciato e quando e' finito. La seconda resta
    # vuota finche' la copia e' in corso: una riga con started_at valorizzato
    # e finished_at vuoto, vecchia di ore, e' una copia interrotta.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # La cartella della copia, per intero. Serve al ripristino, che deve
    # sapere che cosa rimettere a posto, e alla diagnostica, che la mostra.
    destination: Mapped[str] = mapped_column(String(500), nullable=False)

    # Quanto occupa il salvataggio del database e quanto l'archivio copiato.
    # Separati perche' crescono in modo diverso: il dump del database e'
    # piccolo e costante, l'archivio cresce con i documenti caricati.
    database_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    files_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Quanti file dell'archivio sono stati copiati questa volta, e quanti
    # c'erano gia' nella copia precedente e non sono stati riscritti. La
    # seconda e' la misura di quanto lavoro risparmia la copia incrementale:
    # senza, non si saprebbe se sta funzionando.
    files_copied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # La frase in italiano che la diagnostica mostra: "Copia completata in 3
    # minuti" oppure "pg_dump non e' stato trovato".
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Il nome della macchina su cui la copia e' stata eseguita. Con due server
    # - quello vero e quello di collaudo - che scrivono sullo stesso database
    # per sbaglio, e' l'unica riga che lo rivela.
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)

    @property
    def riuscito(self) -> bool:
        """Vero quando la copia e' finita bene."""
        return self.outcome == ESITO_RIUSCITO

    @property
    def durata_secondi(self) -> int | None:
        """Quanto e' durata, se e' finita."""
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at).total_seconds())


# I tre valori ammessi in "outcome". Stanno qui, accanto alla colonna, e non in
# enums.py: quello raccoglie gli stati del lavoro dell'azienda, questi sono
# l'esito di una procedura di manutenzione.
ESITO_IN_CORSO = "in_corso"
ESITO_RIUSCITO = "riuscito"
ESITO_FALLITO = "fallito"

ESITI = (ESITO_IN_CORSO, ESITO_RIUSCITO, ESITO_FALLITO)
