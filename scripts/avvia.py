"""Accende Aurora in produzione.

E' il programma che il servizio di Windows esegue, e l'unica cosa che fa e'
avviare uvicorn con quello che trova scritto nel file `.env`:

    SERVER_HOST       su quali schede di rete rispondere (0.0.0.0 = tutte)
    SERVER_PORT       su quale porta
    HTTPS_CERT_FILE   il certificato, se Aurora deve parlare in https
    HTTPS_KEY_FILE    la sua chiave privata

Come si esegue a mano, per provare prima di installare il servizio:

    .venv\\Scripts\\activate
    python scripts/avvia.py


PERCHE' ESISTE, INVECE DI SCRIVERE LA RIGA DI UVICORN NEL SERVIZIO
------------------------------------------------------------------

Perche' altrimenti la porta, l'indirizzo e i due percorsi del certificato
finirebbero **dentro la configurazione del servizio di Windows**, che e' un
posto in cui la configurazione di Aurora non sta e non deve stare (regola 8 di
CLAUDE.md): non e' in git, non e' commentata, non si legge senza aprire uno
strumento di amministrazione, e chi cambia il certificato l'anno prossimo non
saprebbe dove andare a cercarla.

Cosi' invece **la configurazione resta tutta in un file solo**, quello che chi
amministra il server ha gia' aperto per tutto il resto. Il servizio esegue una
riga che non cambia mai.

Ci guadagna anche l'installazione: `nssm install` vuole un programma e i suoi
argomenti, e «python scripts\\avvia.py» e' molto piu' difficile da sbagliare
di una riga di uvicorn con sei opzioni.


CHE COSA CONTROLLA PRIMA DI ACCENDERE
--------------------------------------

Tre cose, e tutte e tre sono errori che altrimenti si scoprirebbero tardi e
male:

  1. **il certificato indicato esiste davvero.** Senza questo controllo
     uvicorn parte, prova ad aprire il file, non lo trova e muore: il servizio
     di Windows risulta «avviato e poi arrestato», che non dice niente a
     nessuno. Qui invece si legge una riga che dice quale file manca;

  2. **https e i cookie sono d'accordo.** Con il certificato indicato e
     `COOKIE_SECURE=false` la sessione viaggerebbe anche in chiaro; con
     `COOKIE_SECURE=true` e nessun certificato **non si riesce piu' a
     entrare**, perche' il browser non rimanda mai un cookie Secure su http, e
     la causa non e' facile da indovinare. Sono i due guasti piu' probabili
     della messa in esercizio, e sono anche i due che si riconoscono peggio;

  3. **si dice a voce alta come si sta accendendo**, con l'indirizzo per
     esteso. La prima riga del registro di ogni avvio risponde alla domanda
     «ma questo server e' quello di produzione o quello di prova?».

Il primo caso ferma l'avvio; il secondo lo lascia proseguire scrivendo un
avviso, perche' un server che non si accende e' peggio di un server che si
accende male e lo dice - la pagina di diagnostica lo ripete in rosso, e resta
raggiungibile proprio perche' il server e' acceso.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402

from app import VERSION  # noqa: E402
from app.config import ENV_FILE, settings  # noqa: E402

logger = logging.getLogger("aurora.avvio")


def verifica_i_certificati() -> list[str]:
    """I file di certificato indicati e non trovati. Vuota se va tutto bene."""
    mancanti = []
    for nome, valore in (
        ("HTTPS_CERT_FILE", settings.HTTPS_CERT_FILE),
        ("HTTPS_KEY_FILE", settings.HTTPS_KEY_FILE),
    ):
        percorso = (valore or "").strip()
        if percorso and not Path(percorso).is_file():
            mancanti.append(f"{nome} = {percorso}")
    return mancanti


def avvisi_sulla_sicurezza() -> list[str]:
    """Le incoerenze fra https e i cookie, scritte come le legge una persona."""
    avvisi = []

    if settings.https_acceso and not settings.COOKIE_SECURE:
        avvisi.append(
            "Aurora sta partendo in https ma COOKIE_SECURE e' falso: i cookie "
            "di sessione verrebbero rimandati anche su una connessione in "
            "chiaro. Scrivi COOKIE_SECURE=true nel file .env e riavvia il "
            "servizio."
        )

    if settings.COOKIE_SECURE and not settings.https_acceso:
        avvisi.append(
            "COOKIE_SECURE e' vero ma non c'e' nessun certificato "
            "(HTTPS_CERT_FILE e HTTPS_KEY_FILE sono vuoti): se davanti ad "
            "Aurora non c'e' gia' un altro server che parla in https, nessuno "
            "riuscira' a entrare, perche' il browser non rimanda mai un "
            "cookie Secure su http."
        )

    return avvisi


def indirizzo() -> str:
    """L'indirizzo con cui Aurora si apre, scritto per esteso.

    Con SERVER_HOST a 0.0.0.0 si scrive il nome della macchina invece dello
    zero: «https://0.0.0.0:8000» non e' un indirizzo che qualcuno possa
    aprire, e chi legge questa riga la legge proprio per sapere dove andare.
    """
    import socket

    schema = "https" if settings.https_acceso else "http"
    ospite = settings.SERVER_HOST
    if ospite in ("0.0.0.0", "::"):
        ospite = socket.gethostname()
    return f"{schema}://{ospite}:{settings.SERVER_PORT}/"


def main() -> int:
    """Accende il server. Restituisce il codice di uscita del processo.

    **Ogni riga si scrive con flush=True**, e non e' pignoleria: quando questo
    programma gira come servizio di Windows, la sua uscita finisce dentro un
    file (`logs\\servizio.log`), e uno stdout diretto a un file e' bufferizzato
    - le righe resterebbero in memoria fino alla chiusura del processo. Cioe':
    proprio le righe che dicono perche' il server non e' partito comparirebbero
    solo se il server parte.
    """
    def riga(testo: str = "") -> None:
        print(testo, flush=True)

    riga(f"Aurora {VERSION}")
    riga(f"  configurazione: {ENV_FILE}")
    riga(f"  database:       {settings.DATABASE_URL.split('@')[-1]}")
    riga(f"  archivio:       {settings.storage_dir}")
    riga(f"  indirizzo:      {indirizzo()}")
    riga()

    mancanti = verifica_i_certificati()
    if mancanti:
        riga("  ERRORE: il certificato indicato nel file .env non esiste.")
        for testo in mancanti:
            riga(f"    {testo}")
        riga()
        riga("  Controlla i percorsi, oppure lasciali vuoti per partire in")
        riga("  http. La procedura e' in docs/INSTALLAZIONE.md, sezione 6.")
        return 2

    for avviso in avvisi_sulla_sicurezza():
        riga(f"  ATTENZIONE: {avviso}")
        riga()

    opzioni: dict[str, object] = {
        "host": settings.SERVER_HOST,
        "port": settings.SERVER_PORT,
        # Il registro lo configura app/main.py quando viene importato: si dice
        # a uvicorn di non rifarselo suo, altrimenti le sue righe smetterebbero
        # di finire in logs/aurora.log.
        "log_config": None,
        # Un processo solo, ed e' una scelta: il blocco che impedisce due
        # controlli della posta insieme sta nel processo (D-080), e con piu'
        # processi non varrebbe piu'. Per qualche decina di utenti in rete
        # locale un processo basta e avanza.
        "workers": 1,
        # Niente ricaricamento automatico: quella e' roba da sviluppo, e in
        # produzione vorrebbe dire un processo che sorveglia i file per
        # sempre, senza nessuna ragione.
        "reload": False,
    }

    if settings.https_acceso:
        opzioni["ssl_certfile"] = settings.HTTPS_CERT_FILE.strip()
        opzioni["ssl_keyfile"] = settings.HTTPS_KEY_FILE.strip()

    uvicorn.run("app.main:app", **opzioni)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
