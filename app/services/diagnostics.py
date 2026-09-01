"""La diagnostica: come sta Aurora, detto a chi non l'ha scritta.

Questo file risponde a una domanda sola - *«funziona tutto?»* - e la risposta
deve poterla leggere una persona che di Aurora sa quello che le hanno
raccontato in mezz'ora. Da qui discendono tre regole che valgono per ogni
controllo scritto qui dentro, e da cui non si deroga.

**1. Un semaforo, e solo tre colori.** Verde vuol dire che non c'e' niente da
fare. Giallo vuol dire che c'e' qualcosa da programmare, ma non oggi. Rosso
vuol dire che qualcosa e' gia' rotto e qualcuno se ne sta accorgendo. Non
esiste il quarto colore per i casi incerti: un controllo che non sa rispondere
e' giallo, perche' *non saperlo* e' un problema da guardare.

**2. Ogni riga che non e' verde dice che cosa fare.** Non "che cosa e'
successo": *che cosa fare*. «Il servizio postgresql-x64-18 non risponde» e'
una diagnosi; «Apri Servizi di Windows, cerca postgresql-x64-18 e premi Avvia»
e' un'istruzione. La riga verde l'istruzione non ce l'ha, perche' non c'e'
niente da fare.

**3. Nessun controllo solleva mai.** Se il disco non si legge, se il database
non risponde, se una cartella non esiste, la riga diventa rossa e lo dice. Una
pagina di diagnostica che si rompe quando c'e' un guasto e' una pagina che si
rompe esattamente il giorno in cui serve. Ogni funzione `_controllo_*` qui
sotto ha il suo `try`, e chi le mette in fila (`stato_del_sistema`) ne ha un
altro attorno per quello che non si era previsto.

**Perche' i controlli sono funzioni separate e non un metodo unico.** Perche'
la pagina li mostra tutti, `/salute` li serve tutti in JSON, e i test ne
provano uno per volta. Una funzione che li facesse tutti insieme non si
potrebbe provare a pezzi, e un controllo che non si prova a pezzi e' un
controllo che si scopre sbagliato il giorno del guasto.

**Dove sta il resto della diagnostica.** Quella della posta sta in
`app/services/mail_config.py` dalla sessione 11, in cima alla pagina di
configurazione: chi ha un problema con la posta apre quella. Qui la posta
c'e' lo stesso, ma ridotta alle tre righe che interessano a chi guarda tutto
il sistema, e con il collegamento a quella pagina.
"""

import logging
import os
import re
import shutil
import socket
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import VERSION
from app.config import PROJECT_ROOT, settings
from app.models import (
    AuditLog,
    Backup,
    Document,
    DocumentVersion,
    EmailAttachment,
    EmailAssignmentState,
    EmailMessage,
    User,
)
from app.models.backup import ESITO_RIUSCITO
from app.services import mail_config, mail_scheduler, storage

logger = logging.getLogger("aurora.diagnostica")


# ---------------------------------------------------------------------------
#  1. IL SEMAFORO
# ---------------------------------------------------------------------------

VERDE = "verde"
GIALLO = "giallo"
ROSSO = "rosso"

# I tre colori in ordine di gravita'. Serve a calcolare il colore complessivo
# della pagina: il peggiore fra quelli delle righe.
GRAVITA = {VERDE: 0, GIALLO: 1, ROSSO: 2}

# Il colore del semaforo tradotto nella variante del componente «etichetta»,
# che di colori ne conosce altri nomi. La corrispondenza si scrive qui e in
# nessun altro posto: il template disegna quello che riceve.
VARIANTE_DEL_COLORE = {
    VERDE: "successo",
    GIALLO: "attenzione",
    ROSSO: "errore",
}

# La frase complessiva, per chi guarda la pagina un secondo e va via.
RIASSUNTO = {
    VERDE: "Va tutto bene.",
    GIALLO: "C'e' qualcosa da programmare, ma niente di rotto.",
    ROSSO: "C'e' qualcosa che non funziona: le voci in rosso qui sotto.",
}


@dataclass(frozen=True)
class Voce:
    """Una riga della diagnostica.

    titolo     di che cosa si sta parlando, in italiano e senza gergo.
    colore     verde, giallo o rosso.
    valore     la misura, gia' scritta per essere letta: «412 MB liberi su
               1,8 GB», non un numero grezzo da formattare nel template.
    che_fare   l'istruzione, e solo quando serve. Sulle righe verdi e' vuota.
    dettagli   le coppie (etichetta, valore) di contorno, che si guardano solo
               quando la riga non e' verde.
    dove       l'indirizzo di una pagina di Aurora che approfondisce, se c'e'.
    dati       le stesse informazioni in forma di numeri, per /salute. Il JSON
               non deve rileggere una frase per ricavarne una cifra.
    """

    chiave: str
    titolo: str
    colore: str
    valore: str
    che_fare: str = ""
    dettagli: tuple[tuple[str, str], ...] = ()
    dove: str = ""
    dati: dict[str, Any] = field(default_factory=dict)

    @property
    def variante(self) -> str:
        """Il colore tradotto nella variante del componente «etichetta»."""
        return VARIANTE_DEL_COLORE[self.colore]


@dataclass(frozen=True)
class Stato:
    """Come sta Aurora: il colore complessivo e tutte le righe."""

    colore: str
    riassunto: str
    voci: tuple[Voce, ...]
    momento: datetime

    def voce(self, chiave: str) -> Voce | None:
        """La riga con quella chiave, se c'e'. Serve ai test e alla pagina."""
        for riga in self.voci:
            if riga.chiave == chiave:
                return riga
        return None


def _peggiore(colori: list[str]) -> str:
    """Il colore piu' grave fra quelli passati. Verde se non ce n'e' nessuno."""
    if not colori:
        return VERDE
    return max(colori, key=lambda colore: GRAVITA[colore])


# ---------------------------------------------------------------------------
#  2. COME SI SCRIVONO I NUMERI PERCHE' SI LEGGANO
# ---------------------------------------------------------------------------
#
# Sono tre funzioni piccole e stanno qui invece che in un filtro Jinja per la
# regola della sezione 5 di docs/GUIDA_STILE.md: il valore arriva al template
# gia' scritto. Un template che sa trasformare 1932735283 in "1,8 GB" contiene
# una regola, e le regole dentro l'HTML non si provano.

MISURE = ("byte", "KB", "MB", "GB", "TB", "PB")


def misura(byte: float | int | None) -> str:
    """Una quantita' di byte scritta come la scriverebbe una persona.

    Si sale di unita' ogni 1024 e si tengono al massimo due cifre dopo la
    virgola, che diventano una sola sopra i dieci: "1,84 GB" si legge, "1,8
    GB" si legge meglio, "1837,29 MB" non si legge affatto.
    """
    if byte is None:
        return "non disponibile"

    valore = float(byte)
    for unita in MISURE:
        if valore < 1024 or unita == MISURE[-1]:
            if unita == "byte":
                return f"{int(valore)} byte"
            cifre = 1 if valore >= 10 else 2
            testo = f"{valore:.{cifre}f}".replace(".", ",")
            return f"{testo} {unita}"
        valore /= 1024

    return f"{byte} byte"


def quando(momento: datetime | None, *, mai: str = "mai") -> str:
    """Una data e un'ora scritte in italiano, nell'ora locale del server.

    Le date nel database hanno tutte il fuso orario (CLAUDE.md, sezione 5) e
    di solito sono in UTC. Chi guarda la pagina sta davanti al server e
    ragiona nell'ora dell'orologio appeso al muro: si converte qui, una volta
    sola, invece di lasciare che ogni pagina se lo ricordi.
    """
    if momento is None:
        return mai
    return momento.astimezone().strftime("%d/%m/%Y alle %H:%M")


def da_quanto(momento: datetime | None) -> str:
    """Quanto tempo e' passato, detto come lo direbbe una persona.

    "tre ore fa" e non "10847 secondi". Sopra le quarantotto ore si passa ai
    giorni: nessuno conta le ore di una settimana.
    """
    if momento is None:
        return ""

    passati = datetime.now(timezone.utc) - momento
    secondi = int(passati.total_seconds())

    if secondi < 0:
        return "fra poco"
    if secondi < 60:
        return "meno di un minuto fa"
    if secondi < 3600:
        minuti = secondi // 60
        return "un minuto fa" if minuti == 1 else f"{minuti} minuti fa"
    if secondi < 48 * 3600:
        ore = secondi // 3600
        return "un'ora fa" if ore == 1 else f"{ore} ore fa"

    giorni = secondi // 86400
    return f"{giorni} giorni fa"


# ---------------------------------------------------------------------------
#  3. IL DATABASE
# ---------------------------------------------------------------------------

# Sopra questi millisecondi la risposta del database diventa gialla. Mezzo
# secondo per un "SELECT 1" in rete locale vuol dire che qualcosa non va:
# il disco, la rete, o un'altra interrogazione che sta tenendo occupato tutto.
SOGLIA_LENTEZZA_MS = 500

# La frase che si legge quando PostgreSQL non risponde. E' scritta una volta
# sola e la usano tutte e tre le strade: la pagina di diagnostica, /salute e
# la pagina di errore che compare quando il database cade mentre qualcuno sta
# lavorando (app/main.py). Che siano la stessa frase non e' un dettaglio: chi
# la legge la prima volta la riconosce la seconda.
CHE_FARE_DATABASE = (
    "Aurora non riesce a parlare con PostgreSQL, e senza database non "
    "funziona niente. Sul server: apri «Servizi» di Windows, cerca il "
    "servizio che comincia per «postgresql» e guarda se e' avviato; se non lo "
    "e', premi «Avvia». Se e' avviato, controlla che l'indirizzo scritto in "
    "DATABASE_URL nel file .env sia quello giusto e che il servizio risponda "
    "sulla porta indicata."
)


def _controllo_database(db: Session) -> Voce:
    """Il database risponde? E quanto ci mette?

    L'interrogazione e' la piu' semplice che esista, apposta: quello che si
    misura e' il giro completo - rete, autenticazione, motore - non la
    bravura di PostgreSQL a eseguire una query.
    """
    inizio = perf_counter()
    try:
        db.execute(select(1)).scalar()
        millisecondi = int((perf_counter() - inizio) * 1000)
    except Exception as errore:
        logger.error("Diagnostica: il database non risponde (%s)", errore)
        return Voce(
            chiave="database",
            titolo="Collegamento al database",
            colore=ROSSO,
            valore="Non risponde",
            che_fare=CHE_FARE_DATABASE,
            dati={"connesso": False, "millisecondi": None},
        )

    if millisecondi > SOGLIA_LENTEZZA_MS:
        return Voce(
            chiave="database",
            titolo="Collegamento al database",
            colore=GIALLO,
            valore=f"Risponde, ma lentamente: {millisecondi} millisecondi",
            che_fare=(
                "Il database risponde piu' lentamente del normale (sopra il "
                f"mezzo secondo per la domanda piu' semplice che esista). "
                "Guarda se sul server c'e' un'altra cosa che sta occupando il "
                "disco - una copia di sicurezza, un antivirus a meta' "
                "scansione - e riprova fra qualche minuto. Se resta cosi', "
                "conviene farlo vedere a chi amministra PostgreSQL."
            ),
            dati={"connesso": True, "millisecondi": millisecondi},
        )

    return Voce(
        chiave="database",
        titolo="Collegamento al database",
        colore=VERDE,
        # In rete locale il giro dura spesso meno di un millisecondo, e
        # "risponde in 0 millisecondi" e' vero e sembra un guasto. Il numero
        # resta esatto in `dati`, per chi sorveglia.
        valore=(
            "Risponde in meno di un millisecondo"
            if millisecondi < 1
            else f"Risponde in {millisecondi} millisecondi"
        ),
        dati={"connesso": True, "millisecondi": millisecondi},
    )


# ---------------------------------------------------------------------------
#  4. LA POSTA
# ---------------------------------------------------------------------------

# Dopo quante ore senza un controllo riuscito la posta diventa gialla. Il
# controllo periodico gira ogni cinque minuti: sei ore senza nemmeno uno
# riuscito vuol dire che qualcosa si e' fermato.
ORE_SENZA_POSTA = 6


def _controllo_posta(db: Session) -> Voce:
    """La casella si legge? Quando e' andata bene l'ultima volta?

    **L'ultimo controllo riuscito sta in memoria e si perde al riavvio**
    (`mail_scheduler`, sessione 11): dopo un riavvio del server questa riga
    dice "nessuno da quando il programma e' acceso", e non e' un guasto. Per
    non far sembrare rotto un server appena riacceso, quel caso e' giallo solo
    se la fonte e' la casella aziendale, dove qualcuno *dovrebbe* aver
    controllato entro cinque minuti.
    """
    graph = settings.MAIL_PROVIDER == "graph"
    origine = (
        f"casella aziendale {settings.MAIL_MAILBOX_ADDRESS or '(non indicata)'}"
        if graph
        else f"cartella del server {settings.mail_local_dir}"
    )

    if graph:
        mancanti = mail_config.mancanti_per_il_collegamento()
        if mancanti:
            return Voce(
                chiave="posta",
                titolo="Collegamento alla casella di posta",
                colore=ROSSO,
                valore="Parametri incompleti: la posta non viene letta",
                che_fare=(
                    "Mancano dei parametri della casella aziendale. Aprili "
                    "nella pagina «Configurazione posta»: accanto a ogni "
                    "campo c'e' un pulsante che prova il valore e dice subito "
                    "se e' quello giusto."
                ),
                dove="/posta/configurazione",
                dati={"provider": "graph", "parametri_mancanti": mancanti},
            )

    ultimo = mail_scheduler.ultimo_controllo()
    elaborati = _messaggi_nelle_24_ore(db)

    dettagli = (
        ("Da dove arriva", origine),
        ("Messaggi elaborati nelle ultime 24 ore", str(elaborati)),
    )
    dati = {
        "provider": settings.MAIL_PROVIDER,
        "origine": origine,
        "elaborati_24_ore": elaborati,
        "ultimo_controllo": None,
        "ultimo_controllo_riuscito": None,
    }

    if ultimo is None:
        colore = GIALLO if graph else VERDE
        return Voce(
            chiave="posta",
            titolo="Collegamento alla casella di posta",
            colore=colore,
            valore="Nessun controllo da quando il programma e' stato acceso",
            che_fare=(
                "Se Aurora e' stata riavviata da poco, e' normale e fra "
                "cinque minuti questa riga diventera' verde da sola. Se e' "
                "accesa da ore, apri la pagina «Configurazione posta» e premi "
                "«Controlla adesso»: la risposta dira' che cosa non va."
                if graph
                else ""
            ),
            dove="/posta/configurazione" if graph else "",
            dettagli=dettagli,
            dati=dati,
        )

    dati["ultimo_controllo"] = ultimo.quando.isoformat()
    dati["ultimo_controllo_riuscito"] = ultimo.riuscito

    if not ultimo.riuscito:
        return Voce(
            chiave="posta",
            titolo="Collegamento alla casella di posta",
            colore=ROSSO,
            valore=f"L'ultimo controllo, {da_quanto(ultimo.quando)}, non e' riuscito",
            che_fare=(
                f"{ultimo.messaggio} Il dettaglio tecnico e' nel registro su "
                "file. La pagina «Configurazione posta» ha un pulsante che "
                "prova il collegamento e dice quale parametro e' sbagliato."
            ),
            dove="/posta/configurazione",
            dettagli=dettagli + (("Ultimo controllo", quando(ultimo.quando)),),
            dati=dati,
        )

    vecchio = datetime.now(timezone.utc) - ultimo.quando > timedelta(
        hours=ORE_SENZA_POSTA
    )
    if vecchio and graph:
        return Voce(
            chiave="posta",
            titolo="Collegamento alla casella di posta",
            colore=GIALLO,
            valore=f"L'ultimo controllo riuscito e' di {da_quanto(ultimo.quando)}",
            che_fare=(
                "Il controllo automatico dovrebbe girare ogni "
                f"{settings.MAIL_POLL_MINUTES} minuti e non lo sta facendo. "
                "Riavvia Aurora: l'orologio si accende all'avvio del "
                "programma. Se dopo il riavvio non riparte, guarda la pagina "
                "«Configurazione posta»."
            ),
            dove="/posta/configurazione",
            dettagli=dettagli + (("Ultimo controllo", quando(ultimo.quando)),),
            dati=dati,
        )

    return Voce(
        chiave="posta",
        titolo="Collegamento alla casella di posta",
        colore=VERDE,
        valore=f"Ultimo controllo riuscito {da_quanto(ultimo.quando)}",
        dove="/posta/configurazione",
        dettagli=dettagli + (("Ultimo controllo", quando(ultimo.quando)),),
        dati=dati,
    )


def _messaggi_nelle_24_ore(db: Session) -> int:
    """Quanti messaggi sono stati archiviati nell'ultimo giorno.

    Si conta su `created_at`, che e' il momento in cui Aurora ha archiviato il
    messaggio, non su `received_at`, che e' quando e' arrivato nella casella:
    la domanda a cui questa riga risponde e' "il programma sta lavorando?",
    non "quanta posta riceve l'azienda?".
    """
    da = datetime.now(timezone.utc) - timedelta(hours=24)
    return (
        db.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(EmailMessage.created_at >= da)
        )
        or 0
    )


# ---------------------------------------------------------------------------
#  5. LA QUARANTENA
# ---------------------------------------------------------------------------

# Da quanti messaggi in quarantena la riga diventa gialla. Non e' un guasto -
# la quarantena e' il funzionamento normale, non l'eccezione - ma una coda che
# cresce vuol dire che nessuno la sta smaltendo.
QUARANTENA_DA_GUARDARE = 20


def _controllo_quarantena(db: Session) -> Voce:
    """Quanti messaggi aspettano che una persona dica a chi appartengono."""
    quanti = (
        db.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(EmailMessage.assignment_state == EmailAssignmentState.QUARANTENA)
        )
        or 0
    )

    if quanti == 0:
        return Voce(
            chiave="quarantena",
            titolo="Messaggi in quarantena",
            colore=VERDE,
            valore="Nessuno in attesa",
            dove="/posta/quarantena",
            dati={"in_attesa": 0},
        )

    parola = "messaggio" if quanti == 1 else "messaggi"
    colore = GIALLO if quanti >= QUARANTENA_DA_GUARDARE else VERDE

    return Voce(
        chiave="quarantena",
        titolo="Messaggi in quarantena",
        colore=colore,
        valore=f"{quanti} {parola} in attesa di assegnazione",
        che_fare=(
            "Sono messaggi che Aurora ha archiviato ma non e' riuscita ad "
            "attribuire a una versione di prodotto: aspettano che una persona "
            "dica a quale progetto appartengono. Non si perdono e non c'e' "
            "fretta, ma se la coda cresce nessuno li sta smistando: aprila e "
            "assegnali dalla pagina «Quarantena»."
            if colore == GIALLO
            else ""
        ),
        dove="/posta/quarantena",
        dati={"in_attesa": quanti},
    )


# ---------------------------------------------------------------------------
#  6. LA SCADENZA DEL SEGRETO
# ---------------------------------------------------------------------------


def _controllo_segreto(*, oggi: date | None = None) -> Voce:
    """Fra quanti giorni scade il segreto con cui si legge la casella.

    Il calcolo e le soglie sono quelli della sessione 11 e stanno in
    `mail_config`: qui si traducono nei tre colori del semaforo. Averne una
    copia vorrebbe dire due tabelle di soglie che il giorno in cui una cambia
    cominciano a dire cose diverse.
    """
    if settings.MAIL_PROVIDER != "graph":
        return Voce(
            chiave="segreto",
            titolo="Scadenza del segreto applicativo",
            colore=VERDE,
            valore="Non serve: la posta arriva da una cartella del server",
            dati={"applicabile": False},
        )

    scadenza = mail_config.scadenza_segreto(oggi=oggi)

    if scadenza is None:
        scritta = (settings.MAIL_SECRET_EXPIRES_ON or "").strip()
        return Voce(
            chiave="segreto",
            titolo="Scadenza del segreto applicativo",
            colore=GIALLO,
            valore=(
                "Non indicata"
                if not scritta
                else f"Scritta in un modo che non si riesce a leggere: «{scritta}»"
            ),
            che_fare=(
                "Il segreto con cui Aurora legge la casella aziendale scade, "
                "e quando scade la posta smette di arrivare senza che nessuno "
                "avvisi. Chiedi la data all'ufficio informatico e scrivila "
                "nella pagina «Configurazione posta», con l'anno davanti "
                "(2027-03-15): da quel momento Aurora comincia a segnalarla "
                "trenta giorni prima."
            ),
            dove="/posta/configurazione",
            dati={"applicabile": True, "scadenza": None},
        )

    mancanti = scadenza.giorni_mancanti
    dati = {
        "applicabile": True,
        "scadenza": scadenza.giorno.isoformat(),
        "giorni_mancanti": mancanti,
    }

    if mancanti < 0:
        return Voce(
            chiave="segreto",
            titolo="Scadenza del segreto applicativo",
            colore=ROSSO,
            valore=f"Scaduto il {scadenza.giorno.strftime('%d/%m/%Y')}",
            che_fare=(
                "Da quel giorno Aurora non riesce piu' a leggere la posta. "
                "Chiedi all'ufficio informatico un segreto nuovo per la "
                "registrazione applicativa di Aurora e scrivilo nella pagina "
                "«Configurazione posta», insieme alla nuova data di scadenza."
            ),
            dove="/posta/configurazione",
            dati=dati,
        )

    if mancanti <= 14:
        colore = ROSSO if mancanti <= 7 else GIALLO
        return Voce(
            chiave="segreto",
            titolo="Scadenza del segreto applicativo",
            colore=colore,
            valore=(
                "Scade oggi"
                if mancanti == 0
                else f"Fra {mancanti} giorni "
                f"({scadenza.giorno.strftime('%d/%m/%Y')})"
            ),
            che_fare=(
                "Quando il segreto scade, la posta smette di arrivare e "
                "Microsoft non avvisa nessuno. Chiedi adesso all'ufficio "
                "informatico un segreto nuovo: si scrive nella pagina "
                "«Configurazione posta» e ha effetto subito."
            ),
            dove="/posta/configurazione",
            dati=dati,
        )

    if mancanti <= 30:
        return Voce(
            chiave="segreto",
            titolo="Scadenza del segreto applicativo",
            colore=GIALLO,
            valore=f"Fra {mancanti} giorni ({scadenza.giorno.strftime('%d/%m/%Y')})",
            che_fare=(
                "Non c'e' ancora fretta, ma conviene chiedere ora all'ufficio "
                "informatico di preparare il segreto nuovo: il giorno in cui "
                "scade, la posta smette di arrivare."
            ),
            dove="/posta/configurazione",
            dati=dati,
        )

    return Voce(
        chiave="segreto",
        titolo="Scadenza del segreto applicativo",
        colore=VERDE,
        valore=f"Fra {mancanti} giorni ({scadenza.giorno.strftime('%d/%m/%Y')})",
        dove="/posta/configurazione",
        dati=dati,
    )


# ---------------------------------------------------------------------------
#  7. LA COPIA DI SICUREZZA
# ---------------------------------------------------------------------------

# Dopo quante ore l'ultima copia riuscita e' troppo vecchia. Trenta e non
# ventiquattro: la copia notturna gira a orari leggermente diversi, e una
# diagnostica che diventa gialla ogni mattina alle 3:05 e' una diagnostica che
# si impara a ignorare.
ORE_COPIA_VECCHIA = 30


def _controllo_backup(db: Session) -> Voce:
    """L'ultima copia di sicurezza: quando, e com'e' andata."""
    ultima = db.scalars(
        select(Backup).order_by(Backup.started_at.desc()).limit(1)
    ).first()

    if ultima is None:
        return Voce(
            chiave="backup",
            titolo="Copia di sicurezza",
            colore=ROSSO,
            valore="Non ne e' mai stata eseguita nessuna",
            che_fare=(
                "I dati di Aurora - i documenti, le revisioni, la "
                "corrispondenza - sono il patrimonio dell'azienda, e senza "
                "copia di sicurezza un guasto al disco li porta via tutti. La "
                "procedura per programmare la copia notturna e' in "
                "docs/BACKUP_E_RIPRISTINO.md: sono dieci minuti di lavoro, "
                "una volta sola."
            ),
            dati={"mai_eseguita": True},
        )

    dati = {
        "mai_eseguita": False,
        "quando": ultima.started_at.isoformat(),
        "esito": ultima.outcome,
        "destinazione": ultima.destination,
        "byte_database": ultima.database_bytes,
        "byte_archivio": ultima.files_bytes,
    }
    dettagli = (
        ("Dove", ultima.destination),
        ("Database", misura(ultima.database_bytes)),
        (
            "Archivio",
            f"{misura(ultima.files_bytes)} "
            f"({ultima.files_copied} file copiati, "
            f"{ultima.files_skipped} gia' presenti)",
        ),
    )

    if not ultima.riuscito:
        return Voce(
            chiave="backup",
            titolo="Copia di sicurezza",
            colore=ROSSO,
            valore=f"L'ultimo tentativo, {da_quanto(ultima.started_at)}, e' fallito",
            che_fare=(
                (ultima.message or "Il motivo non e' stato registrato.")
                + " Prova a eseguire la copia a mano dal server, con "
                "«python scripts/backup.py»: lo script scrive per esteso che "
                "cosa non e' andato. La procedura completa e' in "
                "docs/BACKUP_E_RIPRISTINO.md."
            ),
            dettagli=dettagli + (("Quando", quando(ultima.started_at)),),
            dati=dati,
        )

    vecchia = datetime.now(timezone.utc) - ultima.started_at > timedelta(
        hours=ORE_COPIA_VECCHIA
    )
    if vecchia:
        return Voce(
            chiave="backup",
            titolo="Copia di sicurezza",
            colore=GIALLO,
            valore=f"L'ultima e' riuscita, ma e' di {da_quanto(ultima.started_at)}",
            che_fare=(
                "La copia dovrebbe essere ogni notte. Sul server, apri "
                "l'«Utilita' di pianificazione» di Windows e controlla che "
                "l'operazione «Aurora - copia di sicurezza» ci sia, sia "
                "attiva e non stia segnalando errori. La procedura e' in "
                "docs/BACKUP_E_RIPRISTINO.md."
            ),
            dettagli=dettagli + (("Quando", quando(ultima.started_at)),),
            dati=dati,
        )

    return Voce(
        chiave="backup",
        titolo="Copia di sicurezza",
        colore=VERDE,
        valore=f"Riuscita {da_quanto(ultima.started_at)}, {quando(ultima.started_at)}",
        dettagli=dettagli,
        dati=dati,
    )


# ---------------------------------------------------------------------------
#  8. IL DISCO
# ---------------------------------------------------------------------------

# Sotto queste percentuali di spazio libero il disco diventa giallo e poi
# rosso. Sotto il 5% Windows stesso comincia a comportarsi male, e un
# PostgreSQL che non riesce a scrivere il proprio registro delle transazioni
# si ferma: quello e' rosso, non "quasi".
LIBERO_GIALLO = 15.0
LIBERO_ROSSO = 5.0

# Sotto quanti mesi di autonomia la stima diventa un avviso. Sei mesi sono il
# tempo che ci vuole per far comprare un disco a un'azienda.
MESI_GIALLI = 6
MESI_ROSSI = 2

# Su quanti giorni si misura la crescita per stimare quanto durera' il disco.
# Trenta: meno sarebbe rumore (una settimana con due progetti grossi darebbe
# una stima catastrofica), di piu' sarebbe una fotografia vecchia.
GIORNI_DI_CRESCITA = 30


def _controllo_disco(db: Session) -> Voce:
    """Quanto spazio c'e', e per quanti mesi bastera' al ritmo attuale.

    La stima dei mesi e' la parte che serve davvero: sapere che restano 400 GB
    non dice niente a nessuno, sapere che al ritmo di quest'anno finiscono
    fra cinque mesi fa comprare il disco *prima* che finiscano.

    Si misura la crescita dell'**archivio dei file**, non del disco intero:
    l'archivio e' l'unica cosa che cresce per colpa di Aurora, ed e' l'unica
    di cui il database sappia dire quanto e' cresciuta e quando.
    """
    percorso = settings.storage_dir
    try:
        uso = shutil.disk_usage(percorso if percorso.exists() else PROJECT_ROOT)
    except OSError as errore:
        logger.error("Diagnostica: non si riesce a misurare il disco (%s)", errore)
        return Voce(
            chiave="disco",
            titolo="Spazio sul disco",
            colore=GIALLO,
            valore="Non si riesce a misurare",
            che_fare=(
                f"Aurora non riesce a leggere lo spazio del disco su cui sta "
                f"l'archivio ({percorso}). Controlla che quella cartella "
                "esista e che l'utente con cui gira Aurora possa leggerla."
            ),
            dati={"misurabile": False, "percorso": str(percorso)},
        )

    libero_percento = (uso.free / uso.total * 100) if uso.total else 0.0
    crescita = _crescita_al_mese(db)
    mesi = (uso.free / crescita) if crescita > 0 else None

    dettagli = [
        ("Disco", str(percorso.anchor or percorso)),
        ("Usato", f"{misura(uso.used)} su {misura(uso.total)}"),
        ("Libero", f"{misura(uso.free)} ({libero_percento:.0f}%)"),
        (
            "Crescita dell'archivio",
            f"{misura(crescita)} al mese"
            if crescita > 0
            else f"nessuna negli ultimi {GIORNI_DI_CRESCITA} giorni",
        ),
    ]
    if mesi is not None:
        dettagli.append(("Autonomia stimata", _mesi_scritti(mesi)))

    dati = {
        "misurabile": True,
        "percorso": str(percorso),
        "totale_byte": uso.total,
        "usato_byte": uso.used,
        "libero_byte": uso.free,
        "libero_percento": round(libero_percento, 1),
        "crescita_mensile_byte": int(crescita),
        "mesi_rimanenti": round(mesi, 1) if mesi is not None else None,
    }

    valore = (
        f"{misura(uso.free)} liberi su {misura(uso.total)} "
        f"({libero_percento:.0f}% libero)"
    )
    if mesi is not None:
        valore += f" - bastano ancora {_mesi_scritti(mesi)}"

    colore = VERDE
    che_fare = ""

    if libero_percento < LIBERO_ROSSO:
        colore = ROSSO
        che_fare = (
            "Il disco e' quasi pieno. Quando finisce, Aurora non riesce piu' "
            "a ricevere documenti e PostgreSQL puo' fermarsi del tutto. "
            "Libera spazio adesso - le copie di sicurezza vecchie e i file "
            "temporanei di Windows sono il primo posto dove guardare - e "
            "programma l'acquisto di un disco piu' grande."
        )
    elif libero_percento < LIBERO_GIALLO:
        colore = GIALLO
        che_fare = (
            "Lo spazio libero sta scendendo. Non e' urgente oggi, ma conviene "
            "guardare che cosa occupa il disco e programmare l'ampliamento "
            "prima di arrivare al limite."
        )

    if mesi is not None and colore != ROSSO:
        if mesi < MESI_ROSSI:
            colore = ROSSO
            che_fare = (
                f"Al ritmo con cui l'archivio e' cresciuto negli ultimi "
                f"{GIORNI_DI_CRESCITA} giorni, lo spazio finisce fra "
                f"{_mesi_scritti(mesi)}. Serve un disco piu' grande, e serve "
                "adesso: quando lo spazio finisce non si riesce piu' a "
                "caricare niente."
            )
        elif mesi < MESI_GIALLI and colore == VERDE:
            colore = GIALLO
            che_fare = (
                f"Al ritmo di crescita degli ultimi {GIORNI_DI_CRESCITA} "
                f"giorni, lo spazio finisce fra {_mesi_scritti(mesi)}. E' il "
                "momento di programmare l'ampliamento del disco: farlo con "
                "calma costa molto meno che farlo di corsa."
            )

    return Voce(
        chiave="disco",
        titolo="Spazio sul disco",
        colore=colore,
        valore=valore,
        che_fare=che_fare,
        dettagli=tuple(dettagli),
        dati=dati,
    )


def _mesi_scritti(mesi: float) -> str:
    """La stima dei mesi, scritta come si dice a voce.

    Sopra i due anni si smette di contare: "bastano ancora 74 mesi" e' una
    precisione finta, e chi la legge lo sa.
    """
    if mesi >= 24:
        return "piu' di due anni"
    if mesi < 1:
        giorni = int(mesi * 30)
        return "meno di un mese" if giorni >= 1 else "pochi giorni"
    if mesi < 2:
        return "circa un mese"
    return f"circa {int(mesi)} mesi"


def _crescita_al_mese(db: Session) -> float:
    """Di quanti byte al mese sta crescendo l'archivio.

    Si sommano i byte delle versioni di documento e degli allegati caricati
    negli ultimi trenta giorni e si riporta la somma a un mese di trenta
    giorni. E' una stima, e va letta come tale: un mese con due progetti
    grossi ne da' una alta, un mese di ferie una bassa.

    Non si contano i **messaggi** di posta perche' il loro `.eml` e' piccolo e
    quello che pesa - gli allegati - e' gia' contato.
    """
    da = datetime.now(timezone.utc) - timedelta(days=GIORNI_DI_CRESCITA)

    documenti = (
        db.scalar(
            select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0)).where(
                DocumentVersion.created_at >= da
            )
        )
        or 0
    )
    allegati = (
        db.scalar(
            select(func.coalesce(func.sum(EmailAttachment.size_bytes), 0)).where(
                EmailAttachment.created_at >= da
            )
        )
        or 0
    )

    return float(documenti + allegati) * (30.0 / GIORNI_DI_CRESCITA)


# ---------------------------------------------------------------------------
#  9. QUANTO C'E' DENTRO
# ---------------------------------------------------------------------------


def _controllo_contenuto(db: Session) -> Voce:
    """Quanti documenti, versioni, messaggi e persone ci sono.

    Non e' un controllo: e' sempre verde, e serve a un'altra cosa. Chi ripristina
    una copia di sicurezza deve poter dire *«c'erano 1.482 documenti, adesso ce
    ne sono 1.482»*, e questa e' la riga che glielo dice. E' anche il primo posto
    in cui si guarda quando qualcuno dice "mi sembra che manchi roba".

    I documenti ritirati non si contano fra quelli attivi ma si contano a
    parte: sono righe che ci sono ancora (regola 5 di CLAUDE.md), e chi
    confronta due numeri deve sapere quale sta guardando.
    """
    documenti = (
        db.scalar(
            select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
        )
        or 0
    )
    ritirati = (
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_not(None))
        )
        or 0
    )
    versioni = db.scalar(select(func.count()).select_from(DocumentVersion)) or 0
    messaggi = db.scalar(select(func.count()).select_from(EmailMessage)) or 0
    allegati = db.scalar(select(func.count()).select_from(EmailAttachment)) or 0
    persone = (
        db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        or 0
    )

    return Voce(
        chiave="contenuto",
        titolo="Quanto c'e' dentro Aurora",
        colore=VERDE,
        valore=(
            f"{documenti} documenti, {versioni} versioni, "
            f"{messaggi} messaggi archiviati, {persone} persone attive"
        ),
        dettagli=(
            ("Documenti attivi", str(documenti)),
            ("Documenti ritirati", str(ritirati)),
            ("Versioni di documento", str(versioni)),
            ("Messaggi di posta archiviati", str(messaggi)),
            ("Allegati", str(allegati)),
            ("Persone che possono entrare", str(persone)),
        ),
        dati={
            "documenti": documenti,
            "documenti_ritirati": ritirati,
            "versioni": versioni,
            "email": messaggi,
            "allegati": allegati,
            "utenti_attivi": persone,
        },
    )


# ---------------------------------------------------------------------------
#  10. GLI ERRORI DELLE ULTIME 24 ORE
# ---------------------------------------------------------------------------

# Quante righe di errore nelle ultime 24 ore prima di diventare gialli. Zero
# errori e' l'obiettivo, ma un paio di 404 di qualcuno che ha sbagliato a
# scrivere un indirizzo non sono un guasto.
ERRORI_DA_GUARDARE = 10

# Come si riconosce una riga di errore nel registro su file. Il formato lo
# stabilisce app/main.py: data, ora, due spazi, il livello.
RIGA_DI_REGISTRO = re.compile(
    r"^(?P<quando>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<livello>[A-Z]+)\s+(?P<resto>.*)$"
)

LIVELLI_DI_ERRORE = ("ERROR", "CRITICAL")

# Quante righe di registro si leggono al massimo. Il file arriva a 5 MB prima
# di essere ruotato: leggerlo per intero a ogni caricamento di pagina sarebbe
# uno spreco, e le righe che interessano sono in fondo.
RIGHE_DA_LEGGERE = 4000

# Quanti errori si mostrano nella pagina. Chi ne ha trecento non li legge
# tutti: legge i primi e va a cercare il registro su file.
ERRORI_MOSTRATI = 20


@dataclass(frozen=True)
class RigaDiErrore:
    """Una riga di errore del registro su file, gia' pronta da mostrare."""

    quando: str
    livello: str
    testo: str


def errori_recenti(*, ore: int = 24) -> tuple[list[RigaDiErrore], bool]:
    """Gli errori scritti nel registro su file nelle ultime ore.

    Restituisce le righe e un booleano che dice se il file si e' potuto
    leggere: sono due informazioni diverse, e "nessun errore" e "non riesco a
    leggere il registro" non vanno confuse. Un registro illeggibile e' esso
    stesso un problema.

    Si legge solo la coda del file: gli errori di ieri stanno in fondo, e il
    file puo' arrivare a cinque megabyte.
    """
    percorso = PROJECT_ROOT / "logs" / "aurora.log"
    if not percorso.is_file():
        return [], False

    limite = datetime.now().astimezone() - timedelta(hours=ore)
    trovate: list[RigaDiErrore] = []

    try:
        with percorso.open("r", encoding="utf-8", errors="replace") as file:
            righe = file.readlines()[-RIGHE_DA_LEGGERE:]
    except OSError as errore:
        logger.error("Diagnostica: registro su file illeggibile (%s)", errore)
        return [], False

    for riga in righe:
        trovata = RIGA_DI_REGISTRO.match(riga.rstrip("\n"))
        if trovata is None or trovata.group("livello") not in LIVELLI_DI_ERRORE:
            continue

        try:
            momento = datetime.strptime(
                trovata.group("quando"), "%Y-%m-%d %H:%M:%S"
            ).astimezone()
        except ValueError:
            continue

        if momento < limite:
            continue

        trovate.append(
            RigaDiErrore(
                quando=momento.strftime("%d/%m %H:%M"),
                livello=trovata.group("livello"),
                testo=trovata.group("resto").strip(),
            )
        )

    # I piu' recenti per primi: chi apre la pagina vuole sapere che cosa e'
    # appena successo, non che cosa succedeva ieri sera.
    trovate.reverse()
    return trovate, True


def _controllo_errori() -> Voce:
    """Quante righe di errore ha scritto Aurora nelle ultime 24 ore."""
    righe, leggibile = errori_recenti()

    if not leggibile:
        return Voce(
            chiave="errori",
            titolo="Errori nelle ultime 24 ore",
            colore=GIALLO,
            valore="Il registro su file non si riesce a leggere",
            che_fare=(
                "Aurora scrive quello che le succede in logs/aurora.log, e "
                "quel file adesso non si legge: o non e' mai stato scritto - "
                "il programma e' appena stato installato - o l'utente con cui "
                "gira Aurora non ha il permesso di leggere quella cartella. "
                "Senza registro, di un guasto non resta niente."
            ),
            dati={"leggibile": False, "quanti": None},
        )

    quanti = len(righe)

    if quanti == 0:
        return Voce(
            chiave="errori",
            titolo="Errori nelle ultime 24 ore",
            colore=VERDE,
            valore="Nessuno",
            dove="/diagnostica/errori",
            dati={"leggibile": True, "quanti": 0},
        )

    parola = "errore" if quanti == 1 else "errori"
    colore = GIALLO if quanti >= ERRORI_DA_GUARDARE else VERDE

    return Voce(
        chiave="errori",
        titolo="Errori nelle ultime 24 ore",
        colore=colore,
        valore=f"{quanti} {parola} registrati",
        che_fare=(
            "Sono piu' del normale. Aprili con il collegamento qui accanto: "
            "la prima riga di solito dice gia' di che si tratta. Se si "
            "ripetono sempre uguali, il dettaglio completo - con la traccia "
            "dell'errore - e' nel file logs/aurora.log sul server."
            if colore == GIALLO
            else ""
        ),
        dove="/diagnostica/errori",
        dettagli=tuple(
            (riga.quando, riga.testo[:160]) for riga in righe[:3]
        ),
        dati={"leggibile": True, "quanti": quanti},
    )


# ---------------------------------------------------------------------------
#  11. L'INTEGRITA' DELL'ARCHIVIO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Integrita:
    """Il confronto fra quello che c'e' sul disco e quello che dice il database.

    orfani_su_disco    file dentro storage/objects che nessuna riga riferisce.
                       Non sono un guasto: sono quello che resta di un
                       documento ritirato o di un caricamento annullato, e non
                       si cancellano (regola 5 di CLAUDE.md).
    mancanti_su_disco  righe del database il cui file **non c'e' piu'**.
                       Questo si' che e' un guasto, ed e' il piu' grave che
                       Aurora possa avere: qualcuno ha cancellato dei file
                       dall'archivio, o l'archivio collegato non e' quello
                       giusto.
    """

    oggetti_su_disco: int
    impronte_nel_database: int
    orfani_su_disco: int
    mancanti_su_disco: int
    temporanei_rimasti: int
    esempi_mancanti: tuple[str, ...] = ()
    leggibile: bool = True


def _nomi_nell_archivio(cartella: Path) -> set[str]:
    """I nomi dei file dell'archivio, letti con os.scandir.

    **Perche' non `rglob("*")`.** L'archivio ha una forma fissa e conosciuta:
    `objects/<due caratteri>/<due caratteri>/<impronta>` (D-004). Sono fino a
    65.536 cartelle, quasi tutte con dentro pochi file, e il costo di questa
    funzione non e' leggere i file - e' aprire le cartelle.

    `Path.rglob()` costruisce un oggetto `Path` per ogni voce trovata e poi
    `is_file()` chiede al sistema operativo, una per una, se sia un file: e'
    una chiamata di sistema in piu' per ogni voce. `os.scandir` restituisce
    invece voci che il tipo se lo portano gia' dietro, perche' Windows lo
    fornisce insieme al nome quando legge la cartella.

    Su un archivio di seimila file la differenza misurata e' fra 2,3 secondi e
    0,6: la pagina di diagnostica passa da «lenta» a «pronta», e cresce piu'
    piano quando l'archivio crescera'.

    Una cartella che non si legge - permessi, disco staccato a meta' giro - non
    ferma la lettura delle altre: si salta e si annota. Un archivio letto per
    tre quarti darebbe pero' un conto di file mancanti che non vuol dire
    niente, ed e' per questo che chi chiama distingue i due casi guardando se
    e' stato sollevato un OSError sulla cartella di partenza.
    """
    trovati: set[str] = set()
    da_visitare = [cartella]

    while da_visitare:
        corrente = da_visitare.pop()
        try:
            with os.scandir(corrente) as voci:
                for voce in voci:
                    if voce.is_dir():
                        da_visitare.append(Path(voce.path))
                    else:
                        trovati.add(voce.name.lower())
        except OSError as errore:
            if corrente == cartella:
                # La cartella di partenza: senza di lei non c'e' niente da
                # confrontare, e il chiamante deve saperlo.
                raise
            logger.warning(
                "Diagnostica: sottocartella dell'archivio illeggibile "
                "(%s): %s",
                corrente,
                errore,
            )

    return trovati


def verifica_archivio(db: Session, *, esempi: int = 5) -> Integrita:
    """Confronta i file sul disco con le impronte scritte nel database.

    Il confronto e' in due sensi e sono due domande diverse:

      - *quali file ci sono sul disco che nessuno riferisce?* Sono innocui, e
        contarli serve a spiegare perche' l'archivio e' piu' grande di quanto
        i documenti facciano pensare;
      - *quali file il database si aspetta di trovare e non ci sono?* Questo
        e' il guasto vero. Un documento che c'e' nell'elenco e non si scarica
        e' il modo peggiore di scoprire di aver perso qualcosa.

    Le impronte si contano una volta sola anche quando due documenti hanno lo
    stesso contenuto: sul disco quel file e' uno solo, ed e' il punto della
    deduplicazione (D-004).
    """
    nel_database: set[str] = set()
    for impronta in db.scalars(select(DocumentVersion.storage_hash)).all():
        nel_database.add(impronta.lower())
    for impronta in db.scalars(select(EmailMessage.storage_hash)).all():
        nel_database.add(impronta.lower())
    for impronta in db.scalars(select(EmailAttachment.storage_hash)).all():
        nel_database.add(impronta.lower())

    cartella = storage.cartella_oggetti()
    sul_disco: set[str] = set()
    leggibile = True

    if cartella.is_dir():
        try:
            sul_disco = _nomi_nell_archivio(cartella)
        except OSError as errore:
            logger.error("Diagnostica: archivio illeggibile (%s)", errore)
            leggibile = False
    else:
        leggibile = False

    mancanti = sorted(nel_database - sul_disco) if leggibile else []

    return Integrita(
        oggetti_su_disco=len(sul_disco),
        impronte_nel_database=len(nel_database),
        orfani_su_disco=len(sul_disco - nel_database) if leggibile else 0,
        mancanti_su_disco=len(mancanti),
        temporanei_rimasti=len(storage.temporanei_rimasti()),
        esempi_mancanti=tuple(mancanti[:esempi]),
        leggibile=leggibile,
    )


# Per quanti secondi vale la verifica dell'archivio gia' fatta.
#
# **Perche' questo controllo si tiene da parte e gli altri no.** Tutti gli
# altri sono interrogazioni al database su tabelle indicizzate e costano
# millisecondi. Questo apre una per una tutte le cartelle dell'archivio, e il
# suo costo cresce con l'archivio: con seimila file sono sei decimi di
# secondo, con centomila saranno parecchi secondi. La pagina /diagnostica la
# apre una persona ogni tanto e potrebbe anche aspettare; **/salute la
# interroga un programma di sorveglianza**, che la chiama ogni minuto per
# sempre - e un minuto di lavoro su disco ogni minuto e' una macchina che si
# tiene occupata da sola.
#
# Cinque minuti sono la misura giusta perche' il guasto che questo controllo
# scopre - dei file spariti dall'archivio - non e' un guasto che si risolve
# in cinque minuti: chi lo vede deve fermarsi e ripristinare una copia. Un
# ritardo di cinque minuti nell'accorgersene non cambia niente; una pagina di
# diagnostica che ci mette dieci secondi ad aprirsi, si'.
SECONDI_VALIDITA_ARCHIVIO = 300

# Quello che la verifica ha trovato l'ultima volta, e quando. Sta in una
# variabile di modulo e non in una tabella perche' non e' un dato
# dell'azienda: e' il risultato di una misura, si rifa' da solo, e perderlo al
# riavvio del server non costa niente (e' la stessa ragione di D-082).
_archivio_gia_verificato: tuple[float, Integrita] | None = None


def archivio_verificato(db: Session, *, forza: bool = False) -> Integrita:
    """La verifica dell'archivio, rifatta al massimo ogni cinque minuti.

    Con `forza=True` si rifa' comunque: e' quello che serve a chi ha appena
    ripristinato una copia di sicurezza e vuole sapere **adesso** se i file
    ci sono tutti, non che cosa si era misurato cinque minuti fa.

    `verifica_archivio()` resta esatta e senza memoria: la usano
    `scripts/ripristino.py` e i test, che non devono mai vedere una risposta
    vecchia.
    """
    global _archivio_gia_verificato

    if not forza and _archivio_gia_verificato is not None:
        quando, esito = _archivio_gia_verificato
        if perf_counter() - quando < SECONDI_VALIDITA_ARCHIVIO:
            return esito

    esito = verifica_archivio(db)
    _archivio_gia_verificato = (perf_counter(), esito)
    return esito


def dimentica_archivio_verificato() -> None:
    """Butta via la verifica tenuta da parte.

    Serve ai test, che devono poter cambiare l'archivio e vedere subito la
    riga cambiare: senza, il secondo test di fila leggerebbe la misura del
    primo e verificherebbe la memoria invece del programma.
    """
    global _archivio_gia_verificato
    _archivio_gia_verificato = None


def _controllo_archivio(db: Session) -> Voce:
    """La riga che riassume il confronto fra disco e database."""
    try:
        esito = archivio_verificato(db)
    except Exception as errore:  # noqa: BLE001 - qui non si solleva mai
        logger.exception("Diagnostica: la verifica dell'archivio e' fallita")
        return Voce(
            chiave="archivio",
            titolo="Integrita' dell'archivio dei file",
            colore=GIALLO,
            valore="Non si e' riuscito a verificarla",
            che_fare=(
                "Aurora non e' riuscita a confrontare i file sul disco con "
                "quelli che si aspetta di trovare. Il dettaglio e' nel "
                f"registro su file. Errore: {type(errore).__name__}."
            ),
            dati={"verificabile": False},
        )

    dati = {
        "verificabile": esito.leggibile,
        "oggetti_su_disco": esito.oggetti_su_disco,
        "impronte_nel_database": esito.impronte_nel_database,
        "orfani_su_disco": esito.orfani_su_disco,
        "mancanti_su_disco": esito.mancanti_su_disco,
        "temporanei_rimasti": esito.temporanei_rimasti,
    }
    dettagli = (
        ("File nell'archivio", str(esito.oggetti_su_disco)),
        ("File attesi dal database", str(esito.impronte_nel_database)),
        ("Sul disco e non riferiti da nessuno", str(esito.orfani_su_disco)),
        ("Attesi dal database e non sul disco", str(esito.mancanti_su_disco)),
        ("Caricamenti interrotti (cartella tmp)", str(esito.temporanei_rimasti)),
    )

    if not esito.leggibile:
        return Voce(
            chiave="archivio",
            titolo="Integrita' dell'archivio dei file",
            colore=ROSSO,
            valore="L'archivio non si legge",
            che_fare=(
                f"La cartella dell'archivio ({storage.cartella_oggetti()}) non "
                "esiste oppure non si riesce ad aprirla. Controlla che il "
                "disco sia collegato, che il percorso scritto in STORAGE_PATH "
                "nel file .env sia quello giusto e che l'utente con cui gira "
                "Aurora possa leggerlo e scriverci."
            ),
            dettagli=dettagli,
            dati=dati,
        )

    if esito.mancanti_su_disco:
        elenco = ", ".join(impronta[:12] for impronta in esito.esempi_mancanti)
        return Voce(
            chiave="archivio",
            titolo="Integrita' dell'archivio dei file",
            colore=ROSSO,
            valore=(
                f"{esito.mancanti_su_disco} file risultano nel database ma non "
                "sono sul disco"
            ),
            che_fare=(
                "Sono documenti che compaiono negli elenchi e che non si "
                "riesce piu' a scaricare: qualcuno ha tolto dei file "
                "dall'archivio, oppure Aurora sta guardando un archivio che "
                "non e' il suo. Controlla per prima cosa che STORAGE_PATH nel "
                "file .env punti alla cartella giusta. Se il percorso e' "
                "quello e i file non ci sono, vanno ripresi dall'ultima copia "
                "di sicurezza: la procedura e' in docs/BACKUP_E_RIPRISTINO.md. "
                f"Prime impronte mancanti: {elenco}."
            ),
            dettagli=dettagli,
            dati=dati,
        )

    if esito.temporanei_rimasti:
        return Voce(
            chiave="archivio",
            titolo="Integrita' dell'archivio dei file",
            colore=GIALLO,
            valore=(
                f"Tutti i {esito.impronte_nel_database} file attesi ci sono, ma "
                f"{esito.temporanei_rimasti} caricamenti sono rimasti a meta'"
            ),
            che_fare=(
                "Nella cartella storage/tmp sono rimasti dei file di "
                "caricamenti interrotti. Non sono riferiti da nessuna riga del "
                "database e non servono a niente: si possono togliere a mano "
                "in tutta sicurezza, e nel frattempo non fanno danni oltre a "
                "occupare spazio."
            ),
            dettagli=dettagli,
            dati=dati,
        )

    return Voce(
        chiave="archivio",
        titolo="Integrita' dell'archivio dei file",
        colore=VERDE,
        valore=(
            f"Tutti i {esito.impronte_nel_database} file attesi sono al loro posto"
        ),
        dettagli=dettagli,
        dati=dati,
    )


# ---------------------------------------------------------------------------
#  12. IL REGISTRO DELLE OPERAZIONI
# ---------------------------------------------------------------------------


def _controllo_registro(db: Session) -> Voce:
    """Il registro delle operazioni: quante voci, e a quando risale l'ultima.

    Non ricalcola la catena delle impronte, e non e' una svista: con
    centomila voci quel controllo dura minuti, e una pagina che ci mette
    minuti a caricarsi non la apre nessuno. Lo fa `scripts/verifica_audit.py`,
    che gira quando serve. Qui si risponde alla domanda piu' semplice e piu'
    utile: *il registro sta ancora ricevendo righe?*
    """
    quante = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    ultima = db.scalars(
        select(AuditLog.occurred_at).order_by(AuditLog.seq.desc()).limit(1)
    ).first()

    dati = {
        "voci": quante,
        "ultima": ultima.isoformat() if ultima is not None else None,
    }

    if quante == 0:
        return Voce(
            chiave="registro",
            titolo="Registro delle operazioni",
            colore=GIALLO,
            valore="Vuoto",
            che_fare=(
                "Il registro non ha nemmeno una voce. Su un'installazione "
                "appena fatta e' normale e si riempira' al primo accesso; su "
                "un'installazione in uso vuol dire che qualcosa non sta "
                "scrivendo, ed e' da guardare subito."
            ),
            dove="/registro",
            dati=dati,
        )

    return Voce(
        chiave="registro",
        titolo="Registro delle operazioni",
        colore=VERDE,
        valore=f"{quante} voci, l'ultima {da_quanto(ultima)}",
        dettagli=(
            ("Voci in tutto", str(quante)),
            ("Ultima voce", quando(ultima)),
            (
                "Verifica della catena",
                "si esegue con «python scripts/verifica_audit.py»",
            ),
        ),
        dove="/registro",
        dati=dati,
    )


# ---------------------------------------------------------------------------
#  13. TUTTI INSIEME
# ---------------------------------------------------------------------------

# L'ordine in cui i controlli compaiono nella pagina, ed e' l'ordine in cui
# ---------------------------------------------------------------------------
#  13. LA CONNESSIONE E' CIFRATA?
# ---------------------------------------------------------------------------

# L'istruzione per accendere https, scritta una volta sola. La citano la riga
# rossa e la riga gialla, che parlano dello stesso rimedio visto da due parti.
CHE_FARE_HTTPS = (
    "Apri il file .env sul server, scrivi il percorso del certificato in "
    "HTTPS_CERT_FILE e quello della sua chiave in HTTPS_KEY_FILE, metti "
    "COOKIE_SECURE=true, e riavvia il servizio «Aurora» da Servizi di "
    "Windows. La procedura completa, certificato compreso, e' in "
    "docs/INSTALLAZIONE.md, sezione 6."
)


def _controllo_sicurezza() -> Voce:
    """La sessione di chi usa Aurora viaggia cifrata, oppure no.

    **Perche' questo controllo esiste.** E' il difetto piu' probabile di
    un'installazione nuova, ed e' anche quello che non si vede: Aurora
    funziona perfettamente in http, le pagine si aprono, nessuno si lamenta -
    e intanto il gettone di sessione di ogni persona attraversa la rete
    aziendale in chiaro, dove chiunque abbia accesso a uno switch lo puo'
    leggere e riusare.

    **Sono due parametri e vanno d'accordo o non vanno.** Il certificato dice
    come parla il server; `COOKIE_SECURE` dice al browser di non rimandare il
    cookie su una connessione in chiaro. Con il primo e senza il secondo la
    cifratura c'e' ma non protegge la sessione; con il secondo e senza il
    primo **non si riesce a entrare**, ed e' un guasto che sembra qualunque
    altra cosa - il modulo di accesso accetta la password e rimanda al modulo
    di accesso.

    Il caso «COOKIE_SECURE acceso e nessun certificato» resta **giallo** e non
    rosso, ed e' voluto: e' anche la configurazione giusta di chi ha messo
    davanti ad Aurora un altro server che parla in https. Aurora non ha modo
    di saperlo, e dare del rosso a una configurazione corretta insegna a
    ignorare i rossi.

    Non riceve la sessione del database: la risposta sta tutta nel file `.env`.
    """
    dati = {
        "https": settings.https_acceso,
        "cookie_secure": settings.COOKIE_SECURE,
    }
    dettagli = (
        ("Certificato", settings.HTTPS_CERT_FILE or "(nessuno)"),
        ("Chiave privata", settings.HTTPS_KEY_FILE or "(nessuna)"),
        ("Cookie con l'attributo Secure", "si" if settings.COOKIE_SECURE else "no"),
    )

    if settings.https_acceso and settings.COOKIE_SECURE:
        return Voce(
            chiave="sicurezza",
            titolo="Connessione cifrata",
            colore=VERDE,
            valore="Aurora parla in https e i cookie viaggiano solo cifrati",
            dettagli=dettagli,
            dati=dati,
        )

    if settings.https_acceso and not settings.COOKIE_SECURE:
        return Voce(
            chiave="sicurezza",
            titolo="Connessione cifrata",
            colore=ROSSO,
            valore="Aurora parla in https, ma i cookie non lo pretendono",
            che_fare=(
                "Il certificato c'e' e la connessione e' cifrata, ma "
                "COOKIE_SECURE nel file .env e' falso: il browser rimanderebbe "
                "il gettone di sessione anche su una connessione in chiaro, e "
                "chiunque sulla rete lo potrebbe leggere. Scrivi "
                "COOKIE_SECURE=true nel file .env e riavvia il servizio "
                "«Aurora» da Servizi di Windows."
            ),
            dettagli=dettagli,
            dati=dati,
        )

    if settings.COOKIE_SECURE and not settings.https_acceso:
        return Voce(
            chiave="sicurezza",
            titolo="Connessione cifrata",
            colore=GIALLO,
            valore="I cookie pretendono https, ma Aurora non ha un certificato",
            che_fare=(
                "COOKIE_SECURE e' vero e Aurora non ha nessun certificato. Se "
                "davanti c'e' gia' un altro server che parla in https, va "
                "bene cosi' e questa riga si puo' ignorare. Se non c'e', "
                "nessuno riuscira' a entrare: il browser accetta la password "
                "e non rimanda mai il cookie. " + CHE_FARE_HTTPS
            ),
            dettagli=dettagli,
            dati=dati,
        )

    return Voce(
        chiave="sicurezza",
        titolo="Connessione cifrata",
        colore=ROSSO,
        valore="Aurora parla in chiaro: le password attraversano la rete cosi'",
        che_fare=(
            "Ogni password scritta nel modulo di accesso e ogni gettone di "
            "sessione attraversano la rete aziendale in chiaro, dove chi ha "
            "accesso a uno switch li puo' leggere e riusare. In sviluppo va "
            "bene; su un server in esercizio no. " + CHE_FARE_HTTPS
        ),
        dettagli=dettagli,
        dati=dati,
    )


# conviene guardarli: prima quello senza il quale non funziona niente, poi
# quelli che dicono se qualcosa si e' fermato, poi quelli che parlano del
# futuro, e per ultimo il conteggio, che non e' un controllo.
_CONTROLLI_CON_DATABASE: tuple[tuple[str, Callable[[Session], Voce]], ...] = (
    ("posta", _controllo_posta),
    ("quarantena", _controllo_quarantena),
    ("backup", _controllo_backup),
    ("disco", _controllo_disco),
    ("archivio", _controllo_archivio),
    ("registro", _controllo_registro),
    ("contenuto", _controllo_contenuto),
)


def stato_del_sistema(db: Session, *, oggi: date | None = None) -> Stato:
    """Tutti i controlli, in fila, con il colore complessivo.

    **Se il database non risponde si ferma alla prima riga**, e ha ragione a
    farlo: tutti gli altri controlli lo interrogherebbero e diventerebbero
    rossi uno dopo l'altro, dicendo sette volte la stessa cosa. Una riga rossa
    che dice "PostgreSQL non risponde" con l'istruzione per riavviarlo e' piu'
    utile di sette righe rosse fra cui cercarla.

    **Nessun controllo puo' far fallire la pagina.** Ognuno ha il suo `try`
    dentro; questo qui e' la rete sotto la rete, per l'errore che non si era
    previsto.
    """
    momento = datetime.now(timezone.utc)
    voci: list[Voce] = [_controllo_database(db)]

    if voci[0].colore == ROSSO:
        return Stato(
            colore=ROSSO,
            riassunto=RIASSUNTO[ROSSO],
            voci=tuple(voci),
            momento=momento,
        )

    for chiave, controllo in _CONTROLLI_CON_DATABASE:
        voci.append(_al_riparo(chiave, lambda: controllo(db)))

    voci.append(_al_riparo("sicurezza", _controllo_sicurezza))
    voci.append(_al_riparo("segreto", lambda: _controllo_segreto(oggi=oggi)))
    voci.append(_al_riparo("errori", _controllo_errori))

    colore = _peggiore([riga.colore for riga in voci])
    return Stato(
        colore=colore,
        riassunto=RIASSUNTO[colore],
        voci=tuple(voci),
        momento=momento,
    )


def _al_riparo(chiave: str, controllo: Callable[[], Voce]) -> Voce:
    """Esegue un controllo trasformando in una riga gialla qualunque guasto."""
    try:
        return controllo()
    except Exception as errore:  # noqa: BLE001 - e' proprio il punto
        logger.exception("Diagnostica: il controllo «%s» e' fallito", chiave)
        return Voce(
            chiave=chiave,
            titolo=f"Controllo «{chiave}»",
            colore=GIALLO,
            valore="Non si e' riuscito a eseguirlo",
            che_fare=(
                "Questo controllo si e' interrotto per un errore imprevisto. "
                "Gli altri sono validi. Il dettaglio, con la traccia "
                "completa, e' in logs/aurora.log. Errore: "
                f"{type(errore).__name__}."
            ),
            dati={"eseguito": False},
        )


# ---------------------------------------------------------------------------
#  14. LA RISPOSTA IN JSON
# ---------------------------------------------------------------------------


def come_json(stato: Stato) -> dict[str, Any]:
    """Lo stesso stato, in una forma che un programma sa leggere.

    Le chiavi sono in italiano perche' e' testo destinato a chi guarda, non
    codice (CLAUDE.md, regola 4): e' la stessa scelta che /salute faceva gia'
    dalla sessione 1, e cambiarla adesso romperebbe qualunque cosa la stia
    gia' interrogando.

    **`stato` e `semaforo` rispondono a due domande diverse, e vanno tenute
    distinte.** `stato` vale "ok" o "degradato" e parla solo del database: e'
    quello che c'era dalla sessione 1 e vuol dire *«il programma e' in
    piedi?»*. `semaforo` e' il verdetto complessivo della sessione 12 e vuol
    dire *«c'e' qualcosa da fare?»*: un'installazione senza copia di sicurezza
    e' rossa di semaforo e "ok" di stato, e sono tutte e due vere.

    Chi programma una sorveglianza automatica guarda `semaforo`. Chi voleva
    solo sapere se il server e' vivo continua a guardare `stato` e trova
    quello che trovava prima.
    """
    database = stato.voce("database")
    connesso = bool(database and database.dati.get("connesso"))

    return {
        "stato": "ok" if connesso else "degradato",
        "semaforo": stato.colore,
        "riassunto": stato.riassunto,
        "applicazione": settings.APP_NAME,
        "versione": VERSION,
        "macchina": socket.gethostname(),
        "ora": stato.momento.astimezone().isoformat(timespec="seconds"),
        # La forma vecchia di /salute, tenuta per chi la stesse gia' leggendo.
        "database": {
            "connesso": connesso,
            "errore": None if connesso else "Il database non risponde.",
        },
        "controlli": [
            {
                "nome": voce.chiave,
                "titolo": voce.titolo,
                "semaforo": voce.colore,
                "valore": voce.valore,
                "che_fare": voce.che_fare,
                "dati": voce.dati,
            }
            for voce in stato.voci
        ],
    }


# ---------------------------------------------------------------------------
#  15. LO SPAZIO CHE OCCUPA UNA CARTELLA
# ---------------------------------------------------------------------------


def spazio_occupato(cartella: Path) -> tuple[int, int]:
    """Quanti byte e quanti file ci sono dentro una cartella, ricorsivamente.

    Serve alla copia di sicurezza (per dire quanto ha copiato) e alla pagina
    di diagnostica. Un file che sparisce mentre si conta non e' un errore:
    capita, e viene semplicemente saltato.
    """
    byte = 0
    quanti = 0

    if not cartella.is_dir():
        return 0, 0

    for radice, _cartelle, file in os.walk(cartella):
        for nome in file:
            try:
                byte += (Path(radice) / nome).stat().st_size
                quanti += 1
            except OSError:
                continue

    return byte, quanti
