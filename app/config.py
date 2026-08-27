"""Configurazione dell'applicazione.

Tutti i parametri vengono letti dal file ".env" che sta nella radice del
progetto. Se un parametro obbligatorio manca, l'applicazione si rifiuta di
partire e dice quale: meglio un errore chiaro all'avvio che un comportamento
strano fra tre settimane.

La classe Settings e' costruita con pydantic-settings: elencando i campi con il
loro tipo, la libreria si occupa di leggere il file .env, convertire i valori
(le stringhe diventano numeri, percorsi, ecc.) e verificare che siano ammessi.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Radice del progetto. Questo file sta in  <radice>/app/config.py,
# quindi due livelli sopra c'e' la cartella "aurora".
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Percorso del file di configurazione locale.
ENV_FILE = PROJECT_ROOT / ".env"


def _absolute(path: Path) -> Path:
    """Restituisce il percorso in forma assoluta.

    I percorsi scritti nel file .env possono essere relativi (comodi in
    sviluppo) oppure assoluti (necessari in produzione, dove l'archivio sta
    su un disco dedicato). Quelli relativi vengono agganciati alla radice del
    progetto, cosi' il programma funziona da qualunque cartella lo si avvii.
    """
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


class Settings(BaseSettings):
    """I parametri di funzionamento di Aurora.

    I nomi dei campi sono scritti in maiuscolo perche' coincidono, lettera per
    lettera, con i nomi delle variabili nel file .env.
    """

    # Stringa di connessione a PostgreSQL.
    # Esempio: postgresql+psycopg://aurora_app:password@localhost:5432/aurora
    DATABASE_URL: str

    # Cartella dell'archivio file (documenti caricati dagli utenti).
    STORAGE_PATH: Path = Path("storage")

    # Chiave segreta per la firma dei cookie di sessione.
    SECRET_KEY: str

    # Se vero, i cookie vengono consegnati al browser con l'attributo "Secure",
    # che vuol dire "rimandameli solo su una connessione cifrata". In sviluppo
    # deve stare falso, altrimenti il browser non li rimanda mai su http e non
    # si riesce a entrare; in produzione, dove Aurora sta dietro a https, deve
    # stare vero. Vedi docs/DECISIONI.md, D-023.
    COOKIE_SECURE: bool = False

    # Durata di una sessione normale, quella senza "ricordami". Il cookie
    # muore comunque alla chiusura del browser: questo e' il limite che vale
    # dalla parte del server, e serve a non lasciare aperte per sempre le
    # sessioni di un browser rimasto acceso.
    SESSION_HOURS: int = 12

    # Durata della sessione lunga emessa dalla casella "Ricordami".
    REMEMBER_ME_DAYS: int = 30

    # Blocco dei tentativi di accesso: dopo LOGIN_MAX_ATTEMPTS tentativi
    # falliti sullo stesso nome utente nell'arco di LOGIN_WINDOW_MINUTES
    # minuti, quel nome utente non viene piu' accettato finche' la finestra
    # non si e' svuotata.
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_WINDOW_MINUTES: int = 15

    # File che dice come si scompone il codice parlante di un prodotto
    # (RMS1100-24-110SW). E' un file TOML con l'espressione regolare e le
    # etichette in italiano dei suoi gruppi. Sta fuori dal codice perche' la
    # regola non e' ancora stata confermata dall'azienda: quando arrivera' la
    # conferma si cambia il file, non il programma. Vedi D-038.
    PRODUCT_CODE_CONFIG: Path = Path("config/codice_prodotto.toml")

    # Quante righe per pagina negli elenchi lunghi (prodotti, progetti).
    PAGE_SIZE: int = 25

    # File che elenca i tipi di documento proponibili al caricamento (schema
    # elettrico, PCB, firmware...). Sta fuori dal codice per la stessa ragione
    # della scomposizione dei codici: e' un elenco che l'azienda cambiera',
    # e cambiarlo non deve voler dire modificare il programma. Se il file
    # manca o e' scritto male, Aurora usa l'elenco di ripiego di
    # app/services/doc_types.py e non si ferma.
    DOCUMENT_TYPES_CONFIG: Path = Path("config/tipi_documento.toml")

    # Dimensione massima di un file caricato, in megabyte. Il valore di
    # partenza e' 2 GB: gli schemi meccanici e i firmware compilati di
    # quest'azienda ci stanno dentro con margine. Il limite si verifica
    # **mentre** il file arriva (app/services/storage.py), non dopo: un file
    # da 8 GB non deve poter riempire il disco prima che qualcuno se ne
    # accorga.
    MAX_UPLOAD_MB: int = 2048

    # Nome mostrato nell'interfaccia.
    APP_NAME: str = "Aurora"

    # Dettaglio dei registri: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    LOG_LEVEL: str = "INFO"

    # Da dove Aurora prende i messaggi da archiviare.
    #   "locale" -> file .eml letti da una cartella (MAIL_LOCAL_PATH)
    #   "graph"  -> la casella aziendale, letta con Microsoft Graph
    # Literal impone che non siano ammessi altri valori: uno sbaglio di
    # battitura nel file .env viene scoperto all'avvio, non a runtime.
    MAIL_PROVIDER: Literal["locale", "graph"] = "locale"

    # Cartella dove finiscono i messaggi quando MAIL_PROVIDER = "locale".
    MAIL_LOCAL_PATH: Path = Path("storage/posta")

    # --- I parametri della casella aziendale (MAIL_PROVIDER = "graph") -----
    #
    # Sono quattro e sono tutti obbligatori quando il provider e' "graph".
    # Partono vuoti apposta: Aurora deve poter partire su una macchina in cui
    # la registrazione applicativa non e' ancora stata fatta, e dirlo nella
    # pagina di configurazione invece di rifiutarsi di accendersi. Chi li
    # scrive non e' obbligato a toccare questo file: la pagina
    # /posta/configurazione li salva nel .env da sola (D-081).
    #
    #   MAIL_TENANT_ID        l'organizzazione Microsoft 365 dell'azienda
    #   MAIL_CLIENT_ID        la registrazione applicativa creata per Aurora
    #   MAIL_CLIENT_SECRET    il segreto di quella registrazione
    #   MAIL_MAILBOX_ADDRESS  l'indirizzo della casella da leggere
    MAIL_TENANT_ID: str = ""
    MAIL_CLIENT_ID: str = ""
    MAIL_CLIENT_SECRET: str = ""
    MAIL_MAILBOX_ADDRESS: str = ""

    # Data di scadenza del segreto applicativo, scritta come 2027-03-15.
    #
    # E' una stringa e non una data perche' deve poter essere vuota e perche'
    # un valore scritto storto non deve impedire ad Aurora di partire: la
    # conversione la fa scadenza_segreto(), che davanti a una data illeggibile
    # restituisce None e lo segnala nella diagnostica. Un programma che non si
    # accende perche' qualcuno ha scritto "15/03/2027" e' un programma che ha
    # scelto la lite invece del servizio.
    MAIL_SECRET_EXPIRES_ON: str = ""

    # Ogni quanti minuti Aurora va a vedere se nella casella c'e' posta nuova.
    # Sotto il minuto non si scende: un controllo che parte piu' spesso di
    # quanto duri si accavallerebbe con se stesso, e Microsoft comincerebbe a
    # rispondere "troppe richieste".
    MAIL_POLL_MINUTES: int = 5

    # Se falso, il controllo periodico non parte: la posta si legge soltanto
    # con il pulsante "Controlla adesso". Serve sulle macchine di collaudo e
    # nei test, dove un lavoro che parte da solo mentre si sta guardando
    # un'altra cosa e' solo un modo di non capire piu' niente.
    MAIL_SCHEDULER_ENABLED: bool = True

    # File in cui la fonte Graph tiene il segno di dove era arrivata: il
    # gettone delta e l'ultimo istante elaborato. Non e' configurazione ed e'
    # ricostruibile da solo (D-082); sta in un file e non in una tabella
    # perche' e' un segnalibro, non un dato dell'azienda.
    MAIL_GRAPH_STATE_PATH: Path = Path("storage/posta_graph.json")

    # Istruzioni per pydantic-settings: dove leggere e come comportarsi.
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Variabili d'ambiente sconosciute vengono ignorate invece di far
        # fallire l'avvio: su un server Windows ce ne sono a decine.
        extra="ignore",
    )

    @property
    def storage_dir(self) -> Path:
        """Percorso assoluto dell'archivio file."""
        return _absolute(self.STORAGE_PATH)

    @property
    def mail_local_dir(self) -> Path:
        """Percorso assoluto della cartella dei messaggi scritti su disco."""
        return _absolute(self.MAIL_LOCAL_PATH)

    @property
    def mail_graph_state_file(self) -> Path:
        """Percorso assoluto del segnalibro della fonte Graph."""
        return _absolute(self.MAIL_GRAPH_STATE_PATH)

    @property
    def mail_poll_seconds(self) -> int:
        """Ogni quanti secondi parte il controllo periodico della posta.

        Il minimo e' un minuto: sotto, il controllo si accavallerebbe con se
        stesso e Microsoft comincerebbe a rispondere "troppe richieste".
        """
        return max(60, self.MAIL_POLL_MINUTES * 60)

    def scadenza_segreto(self) -> date | None:
        """La data di scadenza del segreto applicativo, se e' leggibile.

        None quando il parametro e' vuoto **oppure** quando e' scritto in un
        modo che non si riesce a leggere. La differenza fra i due casi la dice
        `mail_config`, che e' il posto in cui si compone il messaggio per chi
        guarda: qui si risponde alla sola domanda "che data e'?".
        """
        testo = (self.MAIL_SECRET_EXPIRES_ON or "").strip()
        if not testo:
            return None
        try:
            return date.fromisoformat(testo)
        except ValueError:
            return None

    @property
    def product_code_config(self) -> Path:
        """Percorso assoluto del file di scomposizione dei codici prodotto."""
        return _absolute(self.PRODUCT_CODE_CONFIG)

    @property
    def document_types_config(self) -> Path:
        """Percorso assoluto del file con l'elenco dei tipi di documento."""
        return _absolute(self.DOCUMENT_TYPES_CONFIG)

    @property
    def max_upload_bytes(self) -> int:
        """Dimensione massima di un file caricato, in byte.

        Nel file .env il limite si scrive in megabyte perche' e' l'unita' in
        cui lo pensa una persona; il programma lavora in byte perche' e'
        l'unita' in cui li conta mentre arrivano.
        """
        return self.MAX_UPLOAD_MB * 1024 * 1024


# Unica istanza usata da tutto il programma: la configurazione si legge una
# volta sola, all'avvio, e non cambia piu' finche' il server e' in esecuzione.
settings = Settings()
