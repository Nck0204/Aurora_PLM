"""Avvio dell'applicazione Aurora.

Questo file mette insieme quattro cose:

  1. il registro (logging) su file rotativo, dentro la cartella logs/;
  2. l'applicazione FastAPI vera e propria, con i file statici e i template;
  3. il gestore globale degli errori, che scrive il dettaglio nel registro e
     mostra all'utente una pagina in italiano senza dettagli tecnici;
  4. la rotta GET /salute, che serve a verificare che il server sia vivo e che
     il database risponda.

Avvio in sviluppo:

    .venv\\Scripts\\activate
    uvicorn app.main:app --reload
"""

import http
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import VERSION
from app.config import PROJECT_ROOT, settings
from app.db import engine
from app.dependencies import (
    PARAMETRO_RITORNO,
    PERCORSO_ACCESSO,
    PERCORSO_CAMBIO_PASSWORD,
    CambioPasswordObbligatorio,
    RichiedeAutenticazione,
)
from app.routers import auth as router_auth
from app.routers import customers as router_customers
from app.routers import home as router_home
from app.routers import products as router_products
from app.routers import projects as router_projects
from app.routers import style as router_style
from app.routers import users as router_users
from app.routers import versions as router_versions
from app.services.cookies import applica_cookie
from app.services.csrf import verifica_csrf
from app.templating import templates

# ---------------------------------------------------------------------------
#  Registro (logging)
# ---------------------------------------------------------------------------

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "aurora.log"

# Quando aurora.log supera questa dimensione viene rinominato in aurora.log.1,
# aurora.log.1 diventa aurora.log.2 e cosi' via; il piu' vecchio viene buttato.
# In tutto il registro non occupa mai piu' di 5 MB x 11 file, circa 55 MB.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 10


def configure_logging() -> None:
    """Prepara la scrittura del registro su file e a schermo.

    Viene chiamata una sola volta, quando questo modulo viene importato.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # encoding="utf-8" e' indispensabile: i messaggi sono in italiano e senza
    # questa indicazione le lettere accentate romperebbero la scrittura.
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL.upper())
    # Si azzerano gli eventuali gestori gia' presenti, altrimenti con --reload
    # ogni riavvio ne aggiungerebbe un altro e ogni riga comparirebbe due,
    # tre, quattro volte.
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Uvicorn si porta dietro i propri gestori. Glieli togliamo e gli diciamo
    # di passare i messaggi al registro principale, cosi' anche le righe del
    # server finiscono in logs/aurora.log invece che solo a schermo.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


configure_logging()
logger = logging.getLogger("aurora")


# ---------------------------------------------------------------------------
#  Ciclo di vita dell'applicazione
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cosa fare all'accensione e allo spegnimento del server.

    Il codice prima di yield viene eseguito una volta all'avvio, quello dopo
    yield una volta alla chiusura.
    """
    # All'avvio: crea le cartelle di lavoro se non esistono. Meglio farlo qui
    # che scoprire a meta' giornata che l'archivio non c'e'.
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.MAIL_PROVIDER == "locale":
        settings.mail_local_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Avvio di %s versione %s", settings.APP_NAME, VERSION)
    logger.info("Archivio file: %s", settings.storage_dir)
    logger.info("Invio posta: modalita' %s", settings.MAIL_PROVIDER)

    yield

    # Alla chiusura: si restituiscono al sistema le connessioni al database.
    logger.info("Arresto di %s", settings.APP_NAME)
    engine.dispose()


# ---------------------------------------------------------------------------
#  Applicazione
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    description="Gestione progetti e documentazione tecnica",
    version=VERSION,
    lifespan=lifespan,
    # Dipendenza globale: vale per **tutte** le rotte, comprese quelle che
    # verranno aggiunte in futuro. Prepara il gettone contro la falsificazione
    # delle richieste e, sui POST, lo verifica. Dichiararla qui invece che
    # rotta per rotta e' l'unico modo per essere certi che nessuno se la
    # dimentichi: una rotta senza protezione CSRF funziona benissimo, e la
    # mancanza si nota solo il giorno in cui qualcuno ne approfitta.
    # Vedi app/services/csrf.py.
    dependencies=[Depends(verifica_csrf)],
)

# Fogli di stile, script e immagini: tutti serviti da noi, nessuna CDN.
app.mount(
    "/static",
    StaticFiles(directory=PROJECT_ROOT / "app" / "static"),
    name="static",
)


# ---------------------------------------------------------------------------
#  Consegna dei cookie
# ---------------------------------------------------------------------------


@app.middleware("http")
async def consegna_cookie(request: Request, call_next):
    """Scrive nella risposta i cookie che le dipendenze hanno programmato.

    Perche' non li impostino direttamente loro e' spiegato per esteso in
    app/services/cookies.py. In due righe: le dipendenze girano prima della
    rotta, e se la rotta finisce con un errore la risposta che parte e' quella
    del gestore degli errori, che dei cookie impostati altrove non sa niente.
    Il rinnovo del gettone "ricordami" andrebbe perso proprio mentre il gettone
    vecchio e' gia' stato revocato, e l'utente si ritroverebbe fuori.

    Applicandoli qui, in fondo a tutto, i cookie finiscono su qualunque
    risposta esca: pagina normale, rimando o pagina di errore.
    """
    response = await call_next(request)
    applica_cookie(request, response)
    return response


# ---------------------------------------------------------------------------
#  Gestione degli errori
# ---------------------------------------------------------------------------

# Testo mostrato all'utente per i codici di errore piu' frequenti. Il dettaglio
# tecnico non compare mai qui: finisce nel registro.
ERROR_MESSAGES: dict[int, tuple[str, str]] = {
    400: (
        "Richiesta non valida",
        "I dati inviati non sono stati compresi. Controlla e riprova.",
    ),
    401: (
        "Accesso richiesto",
        "Per vedere questa pagina devi prima entrare con le tue credenziali.",
    ),
    403: (
        "Accesso negato",
        "Il tuo profilo non ha i permessi necessari per questa operazione.",
    ),
    404: (
        "Pagina non trovata",
        "L'indirizzo richiesto non esiste. Forse e' stato scritto male "
        "oppure la pagina e' stata spostata.",
    ),
    405: (
        "Operazione non consentita",
        "Questa pagina non accetta il tipo di richiesta che hai inviato.",
    ),
    500: (
        "Errore interno del server",
        "Si e' verificato un problema imprevisto. L'errore e' stato "
        "registrato e sara' esaminato.",
    ),
}


def wants_html(request: Request) -> bool:
    """Dice se chi ha fatto la richiesta si aspetta una pagina o dei dati.

    Un browser che apre un indirizzo dichiara di accettare "text/html": a lui
    serve la pagina di errore. Una chiamata fatta da un programma o da HTMX in
    cerca di dati riceve invece un JSON, che e' piu' facile da trattare.
    """
    accept_header = request.headers.get("accept", "")
    return "text/html" in accept_header


def messaggio_specifico(exc: StarletteHTTPException) -> str | None:
    """Estrae il messaggio scritto da noi, se ce n'e' uno.

    Quando una rotta solleva HTTPException senza indicare "detail", Starlette
    ci mette la frase standard del protocollo ("Not Found", "Forbidden"): e'
    in inglese e non dice niente all'utente, quindi si preferisce il testo
    generico in italiano di ERROR_MESSAGES. Quando invece il detail e' stato
    scritto da noi - "Questa sezione e' riservata a chi ha il ruolo di
    creatore" - e' piu' utile di qualunque frase generica e va mostrato.
    """
    if not isinstance(exc.detail, str) or not exc.detail:
        return None

    try:
        frase_standard = http.HTTPStatus(exc.status_code).phrase
    except ValueError:
        # Un codice di stato che non sta nell'elenco standard: qualunque cosa
        # ci sia scritta nel detail, l'abbiamo scritta noi.
        return exc.detail

    return None if exc.detail == frase_standard else exc.detail


def build_error_response(
    request: Request,
    status_code: int,
    reference: str | None = None,
    message_override: str | None = None,
) -> Response:
    """Compone la risposta di errore, in HTML per il browser o in JSON."""
    title, message = ERROR_MESSAGES.get(
        status_code,
        ("Errore", "Si e' verificato un problema durante l'operazione."),
    )

    if message_override is not None:
        message = message_override

    if wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="errore.html",
            context={
                "status_code": status_code,
                "title": title,
                "message": message,
                "reference": reference,
                "app_name": settings.APP_NAME,
            },
            status_code=status_code,
        )

    body: dict[str, object] = {
        "stato": "errore",
        "codice": status_code,
        "titolo": title,
        "messaggio": message,
    }
    if reference is not None:
        body["riferimento"] = reference
    return JSONResponse(body, status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> Response:
    """Errori previsti: pagina inesistente, accesso negato, e simili.

    Sono situazioni normali, non guasti: si annotano come avvisi, senza
    riempire il registro di tracce d'errore.
    """
    logger.warning(
        "HTTP %s su %s %s - %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return build_error_response(
        request,
        exc.status_code,
        message_override=messaggio_specifico(exc),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Rete di sicurezza per tutto quello che non era previsto.

    Qualunque errore non gestito altrove arriva qui. Si genera un codice di
    riferimento breve, lo si scrive nel registro insieme alla traccia completa
    dell'errore e lo si mostra all'utente. Cosi' chi riceve la segnalazione
    "e' comparso l'errore 3f9a2c11" sa esattamente quale riga andare a
    cercare in logs/aurora.log.
    """
    reference = uuid.uuid4().hex[:8]
    logger.exception(
        "Errore non gestito [%s] su %s %s",
        reference,
        request.method,
        request.url.path,
    )
    return build_error_response(request, 500, reference=reference)


# ---------------------------------------------------------------------------
#  I due dirottamenti dell'accesso
# ---------------------------------------------------------------------------

# Le dipendenze in app/dependencies.py non possono restituire una pagina al
# posto della rotta: possono solo interrompere sollevando un'eccezione. Questi
# due gestori trasformano quelle interruzioni nei rimandi corrispondenti.


@app.exception_handler(RichiedeAutenticazione)
async def richiede_autenticazione_handler(
    request: Request, exc: RichiedeAutenticazione
) -> Response:
    """Chi non e' entrato viene mandato alla pagina di accesso.

    L'indirizzo che stava cercando di aprire viaggia nel parametro "dopo",
    cosi' dopo l'accesso ci torna invece di ritrovarsi sulla pagina iniziale.
    Nell'indirizzo finisce solo un percorso interno, gia' verificato da
    percorso_di_ritorno_sicuro: mai nessun dato dell'utente.
    """
    destinazione = f"{PERCORSO_ACCESSO}?{PARAMETRO_RITORNO}={exc.destinazione}"
    return RedirectResponse(url=destinazione, status_code=303)


@app.exception_handler(CambioPasswordObbligatorio)
async def cambio_password_handler(
    request: Request, exc: CambioPasswordObbligatorio
) -> Response:
    """Chi deve cambiare la password viene dirottato li' da qualunque pagina.

    Qui non si tiene da parte nessun indirizzo di ritorno: chi ha appena
    ricevuto la password non stava andando da nessuna parte, stava entrando.
    """
    return RedirectResponse(url=PERCORSO_CAMBIO_PASSWORD, status_code=303)


# ---------------------------------------------------------------------------
#  Rotte
# ---------------------------------------------------------------------------

# Le pagine, raggruppate per argomento. L'ordine non conta: i percorsi non si
# sovrappongono.
app.include_router(router_home.router)
app.include_router(router_auth.router)
app.include_router(router_customers.router)
app.include_router(router_products.router)
app.include_router(router_versions.router)
app.include_router(router_projects.router)
app.include_router(router_users.router)
app.include_router(router_style.router)


@app.get("/salute", tags=["servizio"])
def health_check() -> JSONResponse:
    """Verifica che il server sia in piedi e che il database risponda.

    Restituisce sempre il codice HTTP 200, anche quando il database non
    risponde: chi interroga questa rotta vuole sapere cosa non va, e per
    saperlo deve poter leggere la risposta. Il verdetto sta nel campo "stato":

        "ok"        tutto funziona
        "degradato" il server risponde ma il database non e' raggiungibile

    Questa rotta e' pensata per essere richiamata da un programma di
    sorveglianza o, semplicemente, aperta nel browser quando qualcosa non va.
    """
    database_connected = True
    database_error: str | None = None

    try:
        # Una connessione presa e restituita subito, con l'interrogazione piu'
        # semplice che esista: se questa passa, il collegamento e' buono.
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        database_connected = False
        # Solo il tipo e il messaggio dell'errore, non l'intera traccia: la
        # risposta la puo' leggere chiunque, la traccia resta nel registro.
        database_error = f"{type(error).__name__}: {error}"
        logger.error("Database non raggiungibile: %s", database_error)

    body: dict[str, object] = {
        "stato": "ok" if database_connected else "degradato",
        "applicazione": settings.APP_NAME,
        "versione": VERSION,
        # Ora locale del server, completa di fuso orario.
        "ora": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": {
            "connesso": database_connected,
            "errore": database_error,
        },
    }

    return JSONResponse(body, status_code=200)
