"""La copia di sicurezza di Aurora: il database e l'archivio dei file.

A CHE COSA SERVE
----------------

I dati di Aurora sono il patrimonio dell'azienda e stanno in **due posti
diversi**, che vanno copiati tutti e due o non serve a niente copiarne uno:

  - il **database** PostgreSQL: chi ha caricato che cosa, quando, con quale
    revisione, chi puo' vederlo, tutto il registro delle operazioni;
  - l'**archivio dei file**, cioe' la cartella `STORAGE_PATH`: il contenuto
    vero dei documenti, degli allegati e dei messaggi di posta.

Un database senza archivio e' un elenco di documenti che non si scaricano. Un
archivio senza database e' una cartella piena di file dal nome esadecimale, di
cui nessuno sa piu' che cosa siano. Questo script copia tutti e due.

COME E' FATTA UNA COPIA
-----------------------

    BACKUP_PATH/
    ├── archivio/                 i file, copiati una volta sola per sempre
    │   └── 3f/9a/3f9a2c11...
    ├── aurora-2026-08-27_0300/
    │   ├── database.dump         il salvataggio di PostgreSQL
    │   ├── configurazione.env    copia del file .env di quel giorno
    │   └── informazioni.json     versione, data, conteggi, migrazione
    └── aurora-2026-08-26_0300/
        └── ...

**L'archivio dei file e' uno solo e cresce; i salvataggi del database sono
tanti e ruotano.** Non e' una scorciatoia per risparmiare spazio: e' la
conseguenza diretta di come Aurora deposita i file (D-004). Un file
nell'archivio ha per nome l'impronta SHA-256 del proprio contenuto, quindi
**non cambia mai** - se il contenuto cambiasse, cambierebbe il nome, e sarebbe
un altro file - e non viene mai cancellato (regola 5 di CLAUDE.md).

Ne discende la proprieta' che rende sensato tutto questo: la cartella
`archivio/` della copia e' un **soprainsieme** dell'archivio a qualunque data
passata. Ripristinando il database di martedi' insieme all'archivio di oggi, si
ottiene un sistema coerente: tutte le impronte che il database di martedi'
nomina sono li' dentro, piu' qualcuna in piu' che nessuno riferisce e che non
fa male a nessuno.

Copiare l'archivio per intero ogni notte, invece, vorrebbe dire riscrivere
decine di gigabyte per aggiungere i tre file caricati ieri.

CHE COSA **NON** VIENE COPIATO, E PERCHE'
------------------------------------------

  - `storage/tmp/`: i caricamenti interrotti. Non li riferisce nessuno.
  - `storage/posta/`: i messaggi ancora da leggere, quando la posta arriva da
    una cartella. Sono file in transito: quello che conta di loro e' gia'
    archiviato per impronta dentro `objects/`.
  - `storage/posta_graph.json`: il segnalibro della casella aziendale. Si
    ricostruisce da solo (D-082), e ripristinarne uno vecchio farebbe
    rileggere qualche messaggio gia' archiviato - che verrebbe riconosciuto e
    saltato.
  - `logs/`: il registro su file. E' utile per indagare, non per ripristinare,
    e ruota da solo.

ATTENZIONE A DOVE FINISCE LA COPIA
-----------------------------------

Dentro `configurazione.env` c'e' la password del database e il segreto con cui
Aurora legge la casella aziendale; dentro `database.dump` ci sono tutte le
impronte delle password e tutto il registro delle operazioni. **La cartella
delle copie va protetta come il server.** E va su un **disco diverso**: una
copia sullo stesso disco protegge dallo sbaglio di una persona e da nient'altro,
e il guasto che si teme di piu' e' proprio quello del disco.

COME SI ESEGUE
--------------

Dalla radice del progetto, con l'ambiente virtuale attivo:

    python scripts/backup.py

Opzioni:

    --destinazione PERCORSO  scrive li' invece che in BACKUP_PATH
    --tieni N                quante copie del database conservare
    --solo-database          salta l'archivio dei file
    --solo-archivio          salta il salvataggio del database
    --silenzioso             stampa solo in caso di guasto. E' la forma da
                             usare nell'operazione notturna: una procedura
                             che scrive mezza pagina ogni notte e' una
                             procedura che dopo un mese nessuno legge piu'.

CODICE DI USCITA
----------------

    0   la copia e' riuscita
    1   la copia non e' riuscita, o e' riuscita a meta'
    2   la copia non e' potuta partire (pg_dump non trovato, disco assente)

E' quello che l'Utilita' di pianificazione di Windows guarda per sapere se
l'operazione e' andata a buon fine. La procedura completa, con la
programmazione notturna e il ripristino, e' in docs/BACKUP_E_RIPRISTINO.md.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Questo script viene lanciato dalla riga di comando, quindi la radice del
# progetto non e' automaticamente fra le cartelle in cui Python cerca i moduli.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import VERSION  # noqa: E402
from app.config import ENV_FILE, settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Backup  # noqa: E402
from app.models.backup import (  # noqa: E402
    ESITO_FALLITO,
    ESITO_IN_CORSO,
    ESITO_RIUSCITO,
)

# --- Nomi delle cose dentro una copia --------------------------------------

CARTELLA_ARCHIVIO = "archivio"
PREFISSO_COPIA = "aurora-"
FILE_DUMP = "database.dump"
FILE_ENV = "configurazione.env"
FILE_INFO = "informazioni.json"

# Il formato della data nel nome della cartella: si ordina da solo in ordine
# alfabetico, che e' anche l'ordine cronologico. Con "27-08-2026" non sarebbe
# vero, e la rotazione butterebbe via la copia sbagliata.
FORMATO_DATA = "%Y-%m-%d_%H%M"

# Quanto si aspetta pg_dump prima di considerarlo bloccato. Due ore: il
# database di quest'azienda ci mette secondi, ma un salvataggio interrotto a
# meta' da un tempo massimo troppo corto sarebbe il peggiore dei danni.
TIMEOUT_SECONDI = 7200

# Che cosa **non** si copia di STORAGE_PATH. E' un elenco di esclusioni e non
# di inclusioni, ed e' voluto: cosi' una cartella che una sessione futura
# aggiungera' li' dentro finira' nelle copie da sola, invece di restarne fuori
# in silenzio finche' qualcuno non se ne accorge. Per una copia di sicurezza,
# sbagliare per eccesso e' l'unico modo sensato di sbagliare.
#
#   tmp/               i caricamenti interrotti: non li riferisce nessuno
#   posta/             i messaggi in transito. Quello che conta di loro e'
#                      gia' dentro objects/, depositato per impronta
#   posta_graph.json   il segnalibro della casella: si ricostruisce da solo
NON_SI_COPIANO = frozenset({"tmp", "posta", "posta_graph.json"})


# ---------------------------------------------------------------------------
#  1. TROVARE pg_dump
# ---------------------------------------------------------------------------


def trova_programma(nome: str) -> str | None:
    """Il percorso di un programma di PostgreSQL, o None se non si trova.

    Si guarda prima in POSTGRES_BIN_PATH, se e' stato indicato nel file `.env`,
    e poi nel PATH di sistema. L'ordine conta: su un server con due versioni di
    PostgreSQL installate, quella giusta e' quella scritta nella
    configurazione, non quella che capita per prima nel PATH.
    """
    if settings.POSTGRES_BIN_PATH:
        candidato = Path(settings.POSTGRES_BIN_PATH) / f"{nome}.exe"
        if candidato.is_file():
            return str(candidato)
        candidato = Path(settings.POSTGRES_BIN_PATH) / nome
        if candidato.is_file():
            return str(candidato)

    return shutil.which(nome)


# ---------------------------------------------------------------------------
#  2. LEGGERE LA STRINGA DI COLLEGAMENTO
# ---------------------------------------------------------------------------


class Collegamento:
    """I pezzi della stringa di collegamento, separati.

    `pg_dump` non accetta un indirizzo nella forma di SQLAlchemy
    (`postgresql+psycopg://...`): vuole host, porta, utente e nome del database
    come argomenti separati, e la password in una variabile d'ambiente.
    """

    def __init__(self, url: str) -> None:
        pezzi = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
        self.host = pezzi.hostname or "localhost"
        self.porta = str(pezzi.port or 5432)
        # unquote perche' nel file .env i caratteri speciali della password e
        # del nome utente sono codificati in percentuale.
        self.utente = unquote(pezzi.username or "")
        self.password = unquote(pezzi.password or "")
        self.database = (pezzi.path or "/").lstrip("/")

    def ambiente(self) -> dict[str, str]:
        """Le variabili d'ambiente con cui far girare pg_dump.

        La password si passa in `PGPASSWORD` e non sulla riga di comando: gli
        argomenti di un processo si leggono da Gestione attivita' e finiscono
        nei registri del sistema operativo.
        """
        ambiente = dict(os.environ)
        if self.password:
            ambiente["PGPASSWORD"] = self.password
        return ambiente

    def descrizione(self) -> str:
        """Come si scrive questo collegamento senza dire la password."""
        return f"{self.utente}@{self.host}:{self.porta}/{self.database}"


# ---------------------------------------------------------------------------
#  3. IL SALVATAGGIO DEL DATABASE
# ---------------------------------------------------------------------------


class Guasto(Exception):
    """Qualcosa e' andato storto. Il messaggio e' gia' in italiano."""


def salva_database(destinazione: Path, *, dire) -> int:
    """Esegue pg_dump e restituisce quanti byte ha scritto.

    **Il formato e' quello "custom" (-Fc) e non un file di testo.** Tre
    ragioni, e sono tutte pratiche: e' compresso, quindi occupa un quarto; si
    ripristina con `pg_restore`, che sa ricreare gli oggetti nell'ordine
    giusto anche quando ci sono dipendenze; e permette di leggerne l'indice
    senza ripristinarlo, che e' come questo script verifica di aver scritto un
    file buono invece di limitarsi a guardarne la dimensione.
    """
    pg_dump = trova_programma("pg_dump")
    if pg_dump is None:
        raise Guasto(
            "pg_dump non e' stato trovato. E' il programma con cui PostgreSQL "
            "salva un database, e sta nella cartella «bin» dell'installazione "
            "di PostgreSQL (per esempio C:\\Program Files\\PostgreSQL\\18\\bin). "
            "Scrivi quella cartella nel parametro POSTGRES_BIN_PATH del file "
            ".env, oppure aggiungila al PATH di sistema."
        )

    collegamento = Collegamento(settings.DATABASE_URL)
    dire(f"  Salvataggio di {collegamento.descrizione()} ...")

    comando = [
        pg_dump,
        "--host", collegamento.host,
        "--port", collegamento.porta,
        "--username", collegamento.utente,
        "--dbname", collegamento.database,
        # Formato compresso e ripristinabile con pg_restore.
        "--format", "custom",
        # Nessuna richiesta di password sulla console: se le credenziali sono
        # sbagliate deve fallire subito, non restare li' ad aspettare che
        # qualcuno scriva qualcosa. Un'operazione notturna bloccata su una
        # richiesta di password e' un backup che non c'e' e che nessuno sa
        # che non c'e'.
        "--no-password",
        "--file", str(destinazione),
    ]

    try:
        esito = subprocess.run(
            comando,
            env=collegamento.ambiente(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDI,
            check=False,
        )
    except subprocess.TimeoutExpired as errore:
        raise Guasto(
            f"pg_dump non ha finito entro {TIMEOUT_SECONDI // 60} minuti ed e' "
            "stato interrotto. Il database e' molto grande, oppure c'e' "
            "qualcosa che lo tiene bloccato."
        ) from errore
    except OSError as errore:
        raise Guasto(f"Non si e' riuscito a eseguire pg_dump: {errore}") from errore

    if esito.returncode != 0:
        messaggio = (esito.stderr or "").strip().splitlines()
        prima_riga = messaggio[-1] if messaggio else "nessun dettaglio"
        raise Guasto(
            f"pg_dump si e' fermato con un errore: {prima_riga}. Controlla che "
            "le credenziali scritte in DATABASE_URL siano quelle giuste e che "
            "quell'utente possa leggere tutte le tabelle."
        )

    if not destinazione.is_file() or destinazione.stat().st_size == 0:
        raise Guasto(
            "pg_dump ha dichiarato di aver finito ma il file del salvataggio "
            "e' vuoto. Non c'e' niente da ripristinare: la copia non vale."
        )

    verifica_dump(destinazione, dire=dire)
    return destinazione.stat().st_size


def verifica_dump(percorso: Path, *, dire) -> None:
    """Legge l'indice del salvataggio per accertarsi che sia leggibile.

    **Non basta guardare che il file esista e non sia vuoto.** Un file
    troncato a meta' - disco pieno, processo interrotto - esiste e non e'
    vuoto, e ci si accorge che non vale il giorno in cui serve. `pg_restore
    --list` legge l'indice interno senza ripristinare niente: se quello si
    legge, il file e' un salvataggio vero.

    Se `pg_restore` non e' installato, la verifica si salta con un avviso
    invece di far fallire la copia: un salvataggio non verificato e' meno di
    un salvataggio verificato, ma e' molto piu' di nessun salvataggio.
    """
    pg_restore = trova_programma("pg_restore")
    if pg_restore is None:
        dire(
            "  Attenzione: pg_restore non trovato, il salvataggio non e' "
            "stato verificato."
        )
        return

    try:
        esito = subprocess.run(
            [pg_restore, "--list", str(percorso)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as errore:
        raise Guasto(
            f"La verifica del salvataggio non e' riuscita a partire: {errore}"
        ) from errore

    if esito.returncode != 0:
        raise Guasto(
            "Il file del salvataggio esiste ma non si riesce a leggerlo: "
            "e' troncato o rovinato. Non ripristinerebbe niente. Controlla "
            "che sul disco di destinazione ci sia spazio."
        )

    righe = [
        riga
        for riga in esito.stdout.splitlines()
        if riga.strip() and not riga.startswith(";")
    ]
    dire(f"  Salvataggio verificato: {len(righe)} oggetti dentro.")


# ---------------------------------------------------------------------------
#  4. LA COPIA INCREMENTALE DELL'ARCHIVIO
# ---------------------------------------------------------------------------


def copia_archivio(sorgente: Path, destinazione: Path, *, dire) -> tuple[int, int, int]:
    """Copia i file che nella destinazione non ci sono ancora.

    Restituisce (copiati, gia_presenti, byte_in_tutto).

    **Il confronto e' sul nome e sulla dimensione**, non sul contenuto. Sembra
    superficiale e non lo e': il nome di un file dell'archivio **e'** l'impronta
    del suo contenuto, quindi due file con lo stesso nome hanno per costruzione
    lo stesso contenuto. La dimensione si guarda per accorgersi del caso che
    resta: una copia interrotta a meta' file, che avrebbe il nome giusto e il
    contenuto sbagliato. Quella si riscrive.

    **Non si cancella niente dalla destinazione.** Un file che c'e' nella copia
    e non c'e' piu' nell'originale e' un file che qualcuno ha tolto
    dall'archivio: e' esattamente quello che una copia di sicurezza serve a
    conservare.
    """
    if not sorgente.is_dir():
        raise Guasto(
            f"La cartella dell'archivio ({sorgente}) non esiste. Controlla il "
            "parametro STORAGE_PATH nel file .env e che il disco sia collegato."
        )

    destinazione.mkdir(parents=True, exist_ok=True)

    copiati = 0
    saltati = 0
    byte = 0

    for radice, cartelle, file in os.walk(sorgente):
        relativa = Path(radice).relative_to(sorgente)

        # Le esclusioni valgono solo al primo livello: dentro objects/ non c'e'
        # niente da escludere, e una cartella chiamata "tmp" a tre livelli di
        # profondita' sarebbe un'impronta, non una cartella temporanea.
        if relativa == Path("."):
            cartelle[:] = [nome for nome in cartelle if nome not in NON_SI_COPIANO]
            file = [nome for nome in file if nome not in NON_SI_COPIANO]

        cartella_destinazione = destinazione / relativa

        for nome in file:
            file_sorgente = Path(radice) / nome
            file_destinazione = cartella_destinazione / nome

            try:
                dimensione = file_sorgente.stat().st_size
            except OSError:
                # Un file sparito mentre si camminava sull'albero: capita, e
                # non e' un guasto della copia.
                continue

            byte += dimensione

            if (
                file_destinazione.is_file()
                and file_destinazione.stat().st_size == dimensione
            ):
                saltati += 1
                continue

            cartella_destinazione.mkdir(parents=True, exist_ok=True)
            try:
                # copy2 conserva anche le date: servono a chi guarda la
                # cartella della copia per capire quando un file e' arrivato.
                shutil.copy2(file_sorgente, file_destinazione)
                copiati += 1
            except OSError as errore:
                raise Guasto(
                    f"Non si e' riuscito a copiare {file_sorgente}: {errore}. "
                    "Controlla che sul disco di destinazione ci sia spazio e "
                    "che l'utente con cui gira la copia possa scriverci."
                ) from errore

    dire(f"  Archivio: {copiati} file copiati, {saltati} gia' presenti.")
    return copiati, saltati, byte


# ---------------------------------------------------------------------------
#  5. LA ROTAZIONE
# ---------------------------------------------------------------------------


def ruota(cartella_copie: Path, tieni: int, *, dire) -> list[str]:
    """Toglie le copie del database piu' vecchie, tenendo le ultime N.

    **Tocca solo i salvataggi del database, mai l'archivio dei file.** Sono due
    cose diverse: un salvataggio del database e' una fotografia di un momento e
    invecchia, l'archivio e' l'insieme di tutti i file mai caricati e non
    invecchia mai. Cancellare da li' vorrebbe dire perdere il contenuto di un
    documento, che e' la cosa che questa procedura esiste per impedire.

    **Le copie fallite si tolgono per prime**, indipendentemente dalla data:
    una cartella con dentro un salvataggio troncato non e' una copia, e tenerla
    al posto di una buona sarebbe il peggiore dei modi di contare fino a sette.
    """
    copie = sorted(
        (
            cartella
            for cartella in cartella_copie.iterdir()
            if cartella.is_dir() and cartella.name.startswith(PREFISSO_COPIA)
        ),
        key=lambda cartella: cartella.name,
    )

    buone = [copia for copia in copie if (copia / FILE_INFO).is_file()]
    incomplete = [copia for copia in copie if not (copia / FILE_INFO).is_file()]

    # Le incomplete si tolgono tutte tranne l'ultima, che potrebbe essere
    # quella in corso adesso.
    da_togliere = incomplete[:-1] if len(incomplete) > 1 else []
    if len(buone) > tieni:
        da_togliere += buone[: len(buone) - tieni]

    tolte: list[str] = []
    for copia in da_togliere:
        try:
            shutil.rmtree(copia)
            tolte.append(copia.name)
        except OSError as errore:
            dire(f"  Attenzione: non si e' riuscito a togliere {copia}: {errore}")

    if tolte:
        dire(f"  Rotazione: tolte {len(tolte)} copie vecchie del database.")

    return tolte


# ---------------------------------------------------------------------------
#  6. LA RIGA NEL DATABASE
# ---------------------------------------------------------------------------


def apri_riga(destinazione: Path) -> tuple[object, object]:
    """Apre la riga della tabella `backups` e la scrive subito.

    **Si scrive prima di cominciare, non dopo aver finito.** Cosi' una copia
    interrotta - il server che si spegne, il disco che si stacca - lascia
    comunque una riga, con esito "in_corso" e senza ora di fine: la
    diagnostica la vede e capisce che qualcosa e' rimasto a meta'. Scrivendo
    solo alla fine, una copia interrotta sarebbe indistinguibile da una copia
    che nessuno ha mai programmato.

    Se il database non risponde si prosegue lo stesso, senza riga: **una copia
    di sicurezza senza il suo verbale vale infinitamente piu' di nessuna copia
    di sicurezza.** Il verbale e' comodo, i dati sono i dati.
    """
    try:
        db = SessionLocal()
        riga = Backup(
            started_at=datetime.now(timezone.utc),
            outcome=ESITO_IN_CORSO,
            destination=str(destinazione),
            hostname=socket.gethostname()[:120],
        )
        db.add(riga)
        db.commit()
        return db, riga
    except Exception:
        return None, None


def chiudi_riga(db, riga, *, riuscito: bool, messaggio: str, **numeri) -> None:
    """Scrive l'esito nella riga aperta prima. Non solleva mai."""
    if db is None or riga is None:
        return

    try:
        riga.finished_at = datetime.now(timezone.utc)
        riga.outcome = ESITO_RIUSCITO if riuscito else ESITO_FALLITO
        riga.message = messaggio
        for nome, valore in numeri.items():
            setattr(riga, nome, valore)
        db.commit()
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  7. LE INFORMAZIONI SULLA COPIA
# ---------------------------------------------------------------------------


def scrivi_informazioni(cartella: Path, dati: dict) -> None:
    """Scrive `informazioni.json` dentro la cartella della copia.

    **La presenza di questo file e' la firma che dice "questa copia e'
    completa".** Viene scritto per ultimo, dopo che tutto il resto e' andato a
    buon fine: una cartella senza di lui e' una copia interrotta, e sia la
    rotazione sia il ripristino la riconoscono per tale.

    Dentro c'e' anche il numero della migrazione del database. Serve al
    ripristino: rimettere un salvataggio vecchio dentro un programma nuovo
    funziona solo se dopo si eseguono le migrazioni mancanti, e per sapere
    quali mancano bisogna sapere da dove si parte.
    """
    cartella.joinpath(FILE_INFO).write_text(
        json.dumps(dati, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def migrazione_corrente() -> str:
    """Il numero della migrazione applicata al database. Vuoto se non si sa."""
    try:
        from sqlalchemy import text

        with SessionLocal() as db:
            valore = db.execute(text("select version_num from alembic_version")).scalar()
            return str(valore or "")
    except Exception:
        return ""


def conta_le_righe() -> dict[str, int]:
    """Quante righe ci sono nelle tabelle che contano.

    Servono al ripristino, che dopo deve poter dire *«c'erano 1.482 documenti,
    adesso ce ne sono 1.482»*. Sono l'unico modo che ha una persona di sapere
    se ha ripristinato tutto o solo un pezzo.
    """
    try:
        from sqlalchemy import func, select

        from app.models import (
            AuditLog,
            Document,
            DocumentVersion,
            EmailMessage,
            Project,
            User,
        )

        with SessionLocal() as db:
            return {
                "utenti": db.scalar(select(func.count()).select_from(User)) or 0,
                "progetti": db.scalar(select(func.count()).select_from(Project)) or 0,
                "documenti": db.scalar(select(func.count()).select_from(Document)) or 0,
                "versioni": db.scalar(
                    select(func.count()).select_from(DocumentVersion)
                )
                or 0,
                "email": db.scalar(select(func.count()).select_from(EmailMessage)) or 0,
                "registro": db.scalar(select(func.count()).select_from(AuditLog)) or 0,
            }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
#  8. IL GIRO COMPLETO
# ---------------------------------------------------------------------------


def esegui(
    *,
    destinazione: Path,
    tieni: int,
    con_database: bool,
    con_archivio: bool,
    dire,
) -> int:
    """Esegue la copia. Restituisce il codice di uscita.

    L'ordine e' voluto: prima il database, poi l'archivio. Se si dovesse
    interrompere a meta', meglio avere il salvataggio del database - che senza
    i file e' un elenco incompleto ma leggibile - che i file senza il
    salvataggio, che sono una cartella di nomi esadecimali.
    """
    momento = datetime.now()
    cartella_copia = destinazione / f"{PREFISSO_COPIA}{momento.strftime(FORMATO_DATA)}"

    dire("")
    dire(f"Copia di sicurezza di Aurora - {momento.strftime('%d/%m/%Y %H:%M')}")
    dire("=" * 62)
    dire(f"  Destinazione: {destinazione}")

    try:
        destinazione.mkdir(parents=True, exist_ok=True)
        cartella_copia.mkdir(parents=True, exist_ok=True)
    except OSError as errore:
        stampa_guasto(
            f"La cartella delle copie ({destinazione}) non si riesce a creare: "
            f"{errore}. Controlla che il disco sia collegato e che l'utente "
            "con cui gira la copia possa scriverci."
        )
        return 2

    db, riga = apri_riga(cartella_copia)

    byte_database = 0
    copiati = saltati = 0
    byte_archivio = 0

    try:
        if con_database:
            byte_database = salva_database(cartella_copia / FILE_DUMP, dire=dire)

            # Il file di configurazione va nella copia perche' senza di lui un
            # ripristino su un'altra macchina e' un database senza indirizzo,
            # senza chiave dei cookie e senza i parametri della posta. E' anche
            # il file piu' delicato della copia: vedi l'avvertimento in cima.
            if ENV_FILE.is_file():
                shutil.copy2(ENV_FILE, cartella_copia / FILE_ENV)

        if con_archivio:
            copiati, saltati, byte_archivio = copia_archivio(
                settings.storage_dir,
                destinazione / CARTELLA_ARCHIVIO,
                dire=dire,
            )

        scrivi_informazioni(
            cartella_copia,
            {
                "programma": "Aurora",
                "versione": VERSION,
                "eseguita_il": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "macchina": socket.gethostname(),
                "migrazione": migrazione_corrente(),
                "archivio_di_origine": str(settings.storage_dir),
                "archivio_nella_copia": str(destinazione / CARTELLA_ARCHIVIO),
                "database_byte": byte_database,
                "archivio_byte": byte_archivio,
                "file_copiati": copiati,
                "file_gia_presenti": saltati,
                "righe": conta_le_righe(),
            },
        )

        ruota(destinazione, tieni, dire=dire)

    except Guasto as guasto:
        stampa_guasto(str(guasto))
        chiudi_riga(
            db,
            riga,
            riuscito=False,
            messaggio=str(guasto),
            database_bytes=byte_database,
            files_bytes=byte_archivio,
            files_copied=copiati,
            files_skipped=saltati,
        )
        return 1
    except Exception as errore:  # noqa: BLE001 - qui si esce comunque
        stampa_guasto(f"Errore imprevisto durante la copia: {errore}")
        chiudi_riga(
            db,
            riga,
            riuscito=False,
            messaggio=f"Errore imprevisto: {type(errore).__name__}: {errore}",
        )
        return 1

    durata = int((datetime.now() - momento).total_seconds())
    riepilogo = (
        f"Copia completata in {durata} secondi: "
        f"database {misura(byte_database)}, "
        f"archivio {copiati} file nuovi su {copiati + saltati}."
    )

    chiudi_riga(
        db,
        riga,
        riuscito=True,
        messaggio=riepilogo,
        database_bytes=byte_database,
        files_bytes=byte_archivio,
        files_copied=copiati,
        files_skipped=saltati,
    )

    dire("")
    dire(f"  {riepilogo}")
    dire(f"  Cartella: {cartella_copia}")
    dire("")
    return 0


def misura(byte: int) -> str:
    """Una quantita' di byte scritta come la scriverebbe una persona."""
    valore = float(byte)
    for unita in ("byte", "KB", "MB", "GB", "TB"):
        if valore < 1024 or unita == "TB":
            if unita == "byte":
                return f"{int(valore)} byte"
            return f"{valore:.1f} {unita}".replace(".", ",")
        valore /= 1024
    return f"{byte} byte"


def stampa_guasto(messaggio: str) -> None:
    """Scrive il guasto sull'uscita degli errori, sempre, anche in silenzio.

    Va su stderr e non su stdout apposta: l'Utilita' di pianificazione di
    Windows sa mostrare l'uscita degli errori, e un'operazione notturna che
    fallisce deve poter dire perche' anche a chi ha scelto `--silenzioso`.
    """
    print("", file=sys.stderr)
    print("  LA COPIA NON E' RIUSCITA", file=sys.stderr)
    print(f"  {messaggio}", file=sys.stderr)
    print("", file=sys.stderr)


def main() -> int:
    """Legge le opzioni ed esegue la copia."""
    # Su Windows lo standard output usa la codifica locale, e le lettere
    # accentate si romperebbero quando l'uscita viene rediretta su un file -
    # che e' esattamente quello che fa un'operazione pianificata.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    argomenti = argparse.ArgumentParser(
        description="Copia di sicurezza di Aurora: database e archivio dei file.",
    )
    argomenti.add_argument(
        "--destinazione",
        default=None,
        help="dove scrivere la copia (di partenza: BACKUP_PATH del file .env)",
    )
    argomenti.add_argument(
        "--tieni",
        type=int,
        default=None,
        help="quante copie del database conservare (di partenza: BACKUP_KEEP)",
    )
    argomenti.add_argument(
        "--solo-database", action="store_true", help="non copiare l'archivio dei file"
    )
    argomenti.add_argument(
        "--solo-archivio", action="store_true", help="non salvare il database"
    )
    argomenti.add_argument(
        "--silenzioso",
        action="store_true",
        help="stampa solo in caso di guasto",
    )
    scelte = argomenti.parse_args()

    if scelte.solo_database and scelte.solo_archivio:
        stampa_guasto(
            "--solo-database e --solo-archivio insieme vogliono dire non "
            "copiare niente."
        )
        return 2

    def dire(riga: str) -> None:
        if not scelte.silenzioso:
            print(riga)

    destinazione = (
        Path(scelte.destinazione).expanduser()
        if scelte.destinazione
        else settings.backup_dir
    )
    tieni = scelte.tieni if scelte.tieni is not None else settings.BACKUP_KEEP

    return esegui(
        destinazione=destinazione,
        tieni=max(1, tieni),
        con_database=not scelte.solo_archivio,
        con_archivio=not scelte.solo_database,
        dire=dire,
    )


if __name__ == "__main__":
    raise SystemExit(main())
