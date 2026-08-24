"""Configurazione dell'applicazione.

Tutti i parametri vengono letti dal file ".env" che sta nella radice del
progetto. Se un parametro obbligatorio manca, l'applicazione si rifiuta di
partire e dice quale: meglio un errore chiaro all'avvio che un comportamento
strano fra tre settimane.

La classe Settings e' costruita con pydantic-settings: elencando i campi con il
loro tipo, la libreria si occupa di leggere il file .env, convertire i valori
(le stringhe diventano numeri, percorsi, ecc.) e verificare che siano ammessi.
"""

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

    # Nome mostrato nell'interfaccia.
    APP_NAME: str = "Aurora"

    # Dettaglio dei registri: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    LOG_LEVEL: str = "INFO"

    # Come vengono spediti i messaggi di posta.
    #   "locale" -> scritti su disco come file .eml, non partono davvero
    #   "graph"  -> spediti tramite Microsoft Graph (Microsoft 365)
    # Literal impone che non siano ammessi altri valori: uno sbaglio di
    # battitura nel file .env viene scoperto all'avvio, non a runtime.
    MAIL_PROVIDER: Literal["locale", "graph"] = "locale"

    # Cartella dove finiscono i messaggi quando MAIL_PROVIDER = "locale".
    MAIL_LOCAL_PATH: Path = Path("storage/posta")

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


# Unica istanza usata da tutto il programma: la configurazione si legge una
# volta sola, all'avvio, e non cambia piu' finche' il server e' in esecuzione.
settings = Settings()
