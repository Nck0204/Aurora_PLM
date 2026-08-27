"""Il controllo periodico della posta, e il pulsante che lo fa partire adesso.

Fino alla sessione 10 l'acquisizione la avviava una persona, dalla pagina della
posta. Con la casella aziendale collegata non ha piu' senso: i messaggi
arrivano quando arrivano, e nessuno sta seduto a premere un pulsante ogni
cinque minuti. Questo file mette `emails.acquisisci()` su un orologio.

    APScheduler ogni MAIL_POLL_MINUTES  -->
                                             controlla()  -->  emails.acquisisci()
    il pulsante "Controlla adesso"      -->

**Le due strade sono la stessa strada.** Il lavoro pianificato e il pulsante
chiamano la stessa funzione, e la differenza sta in due sole cose: chi e'
l'autore da scrivere nel registro (una persona, oppure nessuno) e da dove
arriva la sessione del database. Se fossero due funzioni, la seconda
comincerebbe a differire dalla prima al primo pezzetto aggiunto in fretta.

**Un controllo per volta, sempre.** Il blocco e' un `threading.Lock` preso
senza aspettare: chi arriva mentre un controllo e' in corso non si mette in
coda, riceve una risposta che dice "e' gia' in corso" e se ne va. Due
acquisizioni sovrapposte proverebbero a scrivere lo stesso messaggio due volte
- il `Message-ID` e' unico, quindi la seconda fallirebbe - e a spostare due
volte lo stesso messaggio nella casella. Nessuna delle due cose e' un guasto
grave, e tutte e due riempiono il registro di errori che non raccontano niente.

Il blocco vale **dentro un processo**. Aurora gira come un processo solo su un
server solo (CLAUDE.md, sezione 1): non serve un blocco nel database, e
metterne uno vorrebbe dire scrivere e mantenere una tabella per un problema che
questa installazione non ha.

**Lo stato di quello che succede sta in memoria e non nel database.** L'ora
dell'ultimo controllo, com'e' andato e quanto e' durato servono alla
diagnostica di adesso: al riavvio del server ripartono da zero, e va bene cosi'.
Quello che deve restare - i messaggi archiviati, chi li ha archiviati e quando -
sta nelle tabelle della posta e nel registro delle operazioni da prima.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.services import emails, mail_source

logger = logging.getLogger("aurora.posta.pianificazione")

# Da dove e' partito un controllo. Sono due parole mostrate nella diagnostica,
# non due comportamenti: quello che cambia e' solo chi risulta averlo avviato.
ORIGINE_MANUALE = "manuale"
ORIGINE_PIANIFICATA = "pianificata"

# Il nome del lavoro dentro APScheduler. Serve a ritrovarlo per sapere quando
# tocchera' di nuovo a lui.
LAVORO_POSTA = "controllo_posta"


@dataclass(frozen=True)
class Controllo:
    """Com'e' andato un controllo della posta.

    `riuscito` distingue il controllo che ha parlato con la fonte da quello che
    non ci e' nemmeno riuscito; `sovrapposto` distingue il caso in cui non e'
    partito perche' ce n'era gia' uno in corso, che non e' un guasto e non va
    mostrato in rosso.
    """

    quando: datetime
    origine: str
    riuscito: bool
    messaggio: str
    letti: int = 0
    archiviati: int = 0
    in_quarantena: int = 0
    gia_presenti: int = 0
    errori: int = 0
    sovrapposto: bool = False
    dettagli: tuple[str, ...] = field(default_factory=tuple)

    @property
    def variante(self) -> str:
        """Con quale colore mostrarlo: e' testo per il componente «avviso»."""
        if self.sovrapposto:
            return "informazione"
        if not self.riuscito:
            return "errore"
        if self.errori:
            return "attenzione"
        return "successo"


# Lo stato del processo: il blocco, l'ultimo esito e l'orologio.
_blocco = threading.Lock()
_ultimo: Controllo | None = None
_pianificatore: BackgroundScheduler | None = None


def ultimo_controllo() -> Controllo | None:
    """L'esito dell'ultimo controllo da quando il server e' acceso."""
    return _ultimo


def in_corso() -> bool:
    """Vero se un controllo sta girando proprio adesso."""
    return _blocco.locked()


# ---------------------------------------------------------------------------
#  1. IL CONTROLLO
# ---------------------------------------------------------------------------


def controlla(
    db: Session,
    *,
    autore: User | None = None,
    request: Request | None = None,
    origine: str = ORIGINE_MANUALE,
) -> Controllo:
    """Legge la posta dalla fonte configurata e archivia quello che trova.

    E' la sola funzione che avvia un'acquisizione, e la chiamano tutti e due:
    il pulsante «Controlla adesso» e il lavoro pianificato.

    **Non solleva mai.** Qualunque cosa vada storta esce come un `Controllo`
    con `riuscito=False` e una frase in italiano: chi ha premuto il pulsante
    vede una pagina che spiega, e il lavoro pianificato scrive nel registro e
    aspetta il turno successivo invece di morire e non ripartire piu'.
    """
    if not _blocco.acquire(blocking=False):
        logger.info("Controllo della posta saltato: ce n'e' gia' uno in corso")
        return _annota(
            Controllo(
                quando=datetime.now(timezone.utc),
                origine=origine,
                riuscito=False,
                sovrapposto=True,
                messaggio=(
                    "Un controllo della posta e' gia' in corso. Aspetta che "
                    "finisca: i messaggi non si perdono."
                ),
            ),
            memorizza=False,
        )

    fonte = None
    try:
        try:
            fonte = mail_source.fonte_configurata()
            riepilogo = emails.acquisisci(
                db, fonte, autore=autore, request=request
            )
        except mail_source.FonteNonDisponibile as errore:
            logger.error("Controllo della posta non riuscito: %s", errore)
            return _annota(
                Controllo(
                    quando=datetime.now(timezone.utc),
                    origine=origine,
                    riuscito=False,
                    messaggio=str(errore),
                )
            )
        except SQLAlchemyError:
            # Il database non risponde: si annulla quello che c'e' in sospeso e
            # si aspetta il turno successivo. Senza il rollback la sessione
            # resterebbe rotta e ogni controllo successivo fallirebbe subito.
            db.rollback()
            logger.exception("Controllo della posta interrotto dal database")
            return _annota(
                Controllo(
                    quando=datetime.now(timezone.utc),
                    origine=origine,
                    riuscito=False,
                    messaggio=(
                        "Il database non ha risposto durante la lettura della "
                        "posta. Il dettaglio e' nel registro su file; il "
                        "controllo successivo riprovera' da solo."
                    ),
                )
            )

        return _annota(
            Controllo(
                quando=datetime.now(timezone.utc),
                origine=origine,
                riuscito=True,
                messaggio=_riassunto(riepilogo),
                letti=riepilogo.letti,
                archiviati=riepilogo.archiviati,
                in_quarantena=riepilogo.in_quarantena,
                gia_presenti=riepilogo.gia_presenti,
                errori=riepilogo.errori,
                dettagli=tuple(riepilogo.messaggi_di_errore),
            )
        )
    finally:
        _chiudi(fonte)
        _blocco.release()


def _riassunto(riepilogo: emails.Riepilogo) -> str:
    """La frase che riassume un giro, per la pagina e per il registro."""
    if riepilogo.letti == 0:
        return "Nessun messaggio nuovo da leggere."

    pezzi = [
        f"letti {riepilogo.letti}",
        f"attribuiti {riepilogo.archiviati}",
        f"in quarantena {riepilogo.in_quarantena}",
    ]
    if riepilogo.gia_presenti:
        pezzi.append(f"gia' archiviati {riepilogo.gia_presenti}")
    if riepilogo.errori:
        pezzi.append(f"con problemi {riepilogo.errori}")

    return "Messaggi " + ", ".join(pezzi) + "."


def _chiudi(fonte: object | None) -> None:
    """Restituisce il collegamento alla casella, se la fonte ne aveva uno.

    La fonte locale non ha niente da chiudere e infatti non ha l'attributo:
    si guarda se c'e' invece di chiedere di che classe si tratta, cosi' la
    terza fonte che verra' non dovra' toccare questa riga.
    """
    cliente = getattr(fonte, "cliente", None)
    chiudi = getattr(cliente, "chiudi", None)
    if callable(chiudi):
        chiudi()


def _annota(controllo: Controllo, *, memorizza: bool = True) -> Controllo:
    """Scrive l'esito nel registro su file e lo tiene da parte per la pagina.

    Il controllo che non e' partito perche' ce n'era gia' uno in corso non
    sostituisce l'ultimo esito buono: chi guarda la diagnostica vuole sapere
    com'e' andata l'ultima lettura vera, non che due pulsanti si sono pestati i
    piedi.
    """
    global _ultimo

    if controllo.riuscito:
        logger.info(
            "Controllo della posta (%s): %s", controllo.origine, controllo.messaggio
        )
    elif not controllo.sovrapposto:
        logger.error(
            "Controllo della posta (%s) non riuscito: %s",
            controllo.origine,
            controllo.messaggio,
        )

    if memorizza:
        _ultimo = controllo
    return controllo


# ---------------------------------------------------------------------------
#  2. L'OROLOGIO
# ---------------------------------------------------------------------------


def _lavoro_pianificato() -> None:
    """Quello che APScheduler esegue a ogni scadenza.

    **Si apre la sessione del database da sola**, ed e' una delle due eccezioni
    di Aurora alla regola del `Depends(get_db)` (l'altra e' la registrazione
    della configurazione all'avvio): qui non c'e' nessuna richiesta HTTP, c'e'
    un orologio che suona.

    L'autore e' nullo, cioe' "sistema", e le voci che finiscono nel registro
    non hanno una persona: non c'e', e scriverne una finta sarebbe la peggiore
    delle bugie da mettere in un audit trail (e' la stessa scelta di
    `app/services/configuration.py`).
    """
    db = SessionLocal()
    try:
        controlla(db, origine=ORIGINE_PIANIFICATA)
    except Exception:
        # Rete di sicurezza: se qui uscisse un'eccezione, APScheduler
        # spegnerebbe il lavoro e la posta smetterebbe di arrivare in silenzio.
        logger.exception("Il controllo pianificato della posta e' fallito")
    finally:
        db.close()


def avvia() -> bool:
    """Accende il controllo periodico. Restituisce se e' stato acceso davvero.

    Non parte in due casi, e tutti e due sono voluti:

      - `MAIL_SCHEDULER_ENABLED=false`, che e' come si spegne sulle macchine di
        collaudo e durante i test;
      - `MAIL_PROVIDER=locale`, perche' la cartella dei `.eml` non si riempie da
        sola: i file ce li mette una persona, e quella persona puo' premere
        «Controlla adesso» subito dopo invece di aspettare cinque minuti.
    """
    global _pianificatore

    if _pianificatore is not None:
        return True

    if not settings.MAIL_SCHEDULER_ENABLED:
        logger.info(
            "Controllo periodico della posta spento (MAIL_SCHEDULER_ENABLED=false)"
        )
        return False

    if settings.MAIL_PROVIDER != "graph":
        logger.info(
            "Controllo periodico della posta non avviato: con "
            "MAIL_PROVIDER=%s i messaggi li porta una persona",
            settings.MAIL_PROVIDER,
        )
        return False

    _pianificatore = BackgroundScheduler(timezone="UTC")
    _pianificatore.add_job(
        _lavoro_pianificato,
        trigger="interval",
        seconds=settings.mail_poll_seconds,
        id=LAVORO_POSTA,
        name="Controllo della posta",
        # Se un controllo dura piu' dell'intervallo, il successivo non parte:
        # e' la stessa protezione del blocco, detta a chi tiene l'orologio.
        max_instances=1,
        # Se il server e' stato fermo per un po', al ritorno si fa un controllo
        # solo e non uno per ogni scadenza saltata.
        coalesce=True,
        # Il primo controllo non parte all'accensione ma dopo un intervallo:
        # all'avvio il server ha gia' da fare, e la posta puo' aspettare cinque
        # minuti.
        misfire_grace_time=60,
    )
    _pianificatore.start()

    logger.info(
        "Controllo periodico della posta acceso: ogni %s minuti",
        settings.MAIL_POLL_MINUTES,
    )
    return True


def ferma() -> None:
    """Spegne il controllo periodico. Si puo' chiamare anche se non era acceso."""
    global _pianificatore

    if _pianificatore is None:
        return

    _pianificatore.shutdown(wait=False)
    _pianificatore = None
    logger.info("Controllo periodico della posta spento")


def acceso() -> bool:
    """Vero se il controllo periodico sta girando."""
    return _pianificatore is not None


def prossimo_controllo() -> datetime | None:
    """Quando tocchera' di nuovo al controllo periodico, se e' acceso."""
    if _pianificatore is None:
        return None

    lavoro = _pianificatore.get_job(LAVORO_POSTA)
    return getattr(lavoro, "next_run_time", None) if lavoro else None
