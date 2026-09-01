"""Avvio dell'applicazione Aurora.

Questo file mette insieme quattro cose:

  1. il registro (logging) su file rotativo, dentro la cartella logs/;
  2. l'applicazione FastAPI vera e propria, con i file statici e i template;
  3. il gestore globale degli errori, che scrive il dettaglio nel registro e
     mostra all'utente una pagina in italiano senza dettagli tecnici - fra cui
     quello del database irraggiungibile, che merita una pagina sua perche' e'
     il guasto piu' prevedibile di tutti (sessione 12);
  4. la registrazione dei router, cioe' l'elenco delle pagine di Aurora.

La rotta GET /salute stava qui fino alla sessione 11. Adesso sta in
app/routers/diagnostics.py, insieme alla pagina che mostra gli stessi dati.

Avvio in sviluppo:

    .venv\\Scripts\\activate
    uvicorn app.main:app --reload
"""

import http
import logging
import re
import uuid
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import VERSION
from app.config import PROJECT_ROOT, settings
from app.db import SessionLocal, engine
from app.dependencies import (
    PARAMETRO_RITORNO,
    PERCORSO_ACCESSO,
    PERCORSO_CAMBIO_PASSWORD,
    CambioPasswordObbligatorio,
    RichiedeAutenticazione,
)
from app.routers import audit as router_audit
from app.routers import auth as router_auth
from app.routers import customers as router_customers
from app.routers import diagnostics as router_diagnostics
from app.routers import documents as router_documents
from app.routers import emails as router_emails
from app.routers import help as router_help
from app.routers import home as router_home
from app.routers import mail_config as router_mail_config
from app.routers import permissions as router_permissions
from app.routers import phases as router_phases
from app.routers import products as router_products
from app.routers import projects as router_projects
from app.routers import setup as router_setup
from app.routers import storico as router_storico
from app.routers import style as router_style
from app.routers import users as router_users
from app.routers import versions as router_versions
from app.services import diagnostics, mail_scheduler
from app.services.configuration import registra_configurazione
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


# I parametri dell'indirizzo il cui **valore** non deve finire nel registro.
# Ce n'e' uno solo e basta cosi': la parola d'ordine di /salute, che D-089
# permette di presentare anche come "?token=..." perche' non tutti i programmi
# di sorveglianza sanno aggiungere un'intestazione.
#
# Uvicorn scrive nel registro degli accessi la riga di richiesta per intero,
# query compresa: senza questa sostituzione, la parola d'ordine finirebbe in
# chiaro dentro logs/aurora.log a ogni interrogazione, cioe' in un file che si
# manda per posta quando si chiede aiuto.
_PARAMETRI_DA_NASCONDERE = re.compile(
    r"\b(token)=[^&\s\"]*", re.IGNORECASE
)


class NascondiSegretiNegliIndirizzi(logging.Filter):
    """Sostituisce con *** il valore dei parametri riservati nelle righe.

    E' un filtro del registro e non una modifica alle rotte perche' la riga la
    scrive uvicorn, dentro di se', prima che il nostro programma la veda. Si
    applica a tutti i gestori: una riga che passa dal registro degli accessi e
    una che passa dal nostro sono la stessa riga per chi la legge.

    Non solleva mai: un filtro del registro che fallisce fa sparire la riga che
    stava ripulendo, ed e' esattamente il momento in cui quella riga serviva.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            messaggio = record.getMessage()
            if "token=" in messaggio.lower():
                record.msg = _PARAMETRI_DA_NASCONDERE.sub(r"\1=***", messaggio)
                record.args = ()
        except Exception:  # noqa: BLE001 - vedi la docstring
            pass
        return True


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

    # Il filtro sta sui gestori e non sul registro principale: cosi' vale
    # anche per le righe che arrivano dai registri di uvicorn, che hanno un
    # nome diverso ma finiscono in questi stessi due gestori.
    nascondi = NascondiSegretiNegliIndirizzi()
    file_handler.addFilter(nascondi)
    console_handler.addFilter(nascondi)

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


def _registra_la_configurazione() -> None:
    """Scrive nel registro se la configurazione e' cambiata dall'avvio scorso.

    E' l'unico modo che ha Aurora di registrare "le modifiche alla
    configurazione": i parametri stanno nel file .env e nei file di config/, e
    si cambiano sul server con un editore di testo, senza passare da nessuna
    pagina. La spiegazione per esteso e' in cima ad
    app/services/configuration.py.

    **Una sessione creata a mano, e questa e' l'eccezione che conferma la
    regola.** Le sessioni si prendono con Depends(get_db), ma qui non c'e'
    nessuna richiesta HTTP: il server sta partendo. Si apre, si scrive, si
    chiude.

    **Un guasto qui non impedisce al server di partire.** Se il database non
    risponde ancora - capita quando i due servizi si avviano insieme al
    riavvio del server aziendale - l'errore finisce nel registro su file e
    Aurora parte lo stesso: senza database non funzionerebbe comunque niente,
    e la rotta /salute lo dice gia' meglio di quanto lo direbbe un errore di
    avvio.
    """
    db = SessionLocal()
    try:
        azione = registra_configurazione(db)
        if azione is not None:
            db.commit()
    except SQLAlchemyError as errore:
        db.rollback()
        logger.error(
            "Non e' stato possibile registrare la configurazione all'avvio: "
            "%s. Il server parte lo stesso; vedere /salute per lo stato del "
            "database",
            errore,
        )
    finally:
        db.close()


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
    logger.info("Lettura della posta: modalita' %s", settings.MAIL_PROVIDER)

    _registra_la_configurazione()

    # Il controllo periodico della posta. Parte solo con MAIL_PROVIDER=graph e
    # solo se MAIL_SCHEDULER_ENABLED e' vero: la decisione e le sue ragioni
    # stanno tutte in app/services/mail_scheduler.py, qui c'e' solo
    # l'accensione.
    mail_scheduler.avvia()

    yield

    # Alla chiusura: si spegne l'orologio e si restituiscono al sistema le
    # connessioni al database.
    mail_scheduler.ferma()
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


# ---------------------------------------------------------------------------
#  Le intestazioni di sicurezza
# ---------------------------------------------------------------------------

# Le intestazioni che accompagnano **ogni** risposta di Aurora. Sono cinque e
# ciascuna chiude una porta che, senza di lei, resta aperta.
#
# Content-Security-Policy e' la piu' importante, e in Aurora si puo' scrivere
# stretta come non si potrebbe scrivere quasi da nessun'altra parte: la regola
# 1 di CLAUDE.md dice che non esiste nessuna risorsa caricata da un indirizzo
# esterno, quindi "default-src 'self'" e' la descrizione esatta di come il
# programma e' fatto, non un compromesso. Se un giorno qualcuno aggiungesse un
# collegamento a una CDN, la pagina si romperebbe subito e in modo evidente -
# che e' precisamente quello che si vuole.
#
#   'unsafe-inline' su style-src perche' i componenti scrivono qualche
#   attributo style= per le larghezze calcolate (la barra di caricamento, la
#   barra dell'avanzamento). Su script-src invece non c'e', ed e' la meta' che
#   conta: nessuno script scritto dentro la pagina viene eseguito.
#
#   form-action 'self' vieta a un modulo di questa pagina di inviare i propri
#   dati altrove; frame-ancestors 'none' vieta di mettere Aurora dentro la
#   cornice di un'altra pagina, che e' il modo con cui si fa premere a
#   qualcuno un pulsante che non sta vedendo.
#
# X-Content-Type-Options impedisce al browser di indovinare il tipo di un file
# scaricato dall'archivio: un .txt caricato da qualcuno non deve poter essere
# interpretato come HTML e finire eseguito.
#
# Referrer-Policy fa si' che, seguendo un collegamento, l'indirizzo della
# pagina di partenza non viaggi verso l'esterno. Gli indirizzi di Aurora
# contengono UUID di documenti e progetti: non sono segreti, ma non hanno
# ragione di uscire.
#
# Strict-Transport-Security si aggiunge **solo con COOKIE_SECURE acceso**,
# cioe' solo quando Aurora sta dietro a https. Mandarla su http sarebbe
# inutile; mandarla da un server di prova raggiunto per nome finirebbe per
# impedire di aprirlo in http per i mesi successivi, perche' il browser se la
# ricorda.
INTESTAZIONI_DI_SICUREZZA = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Sei mesi. Dice al browser: da qui in avanti questo indirizzo si apre solo in
# https, anche se qualcuno scrive http a mano. Non c'e' "includeSubDomains"
# perche' Aurora sta su un nome solo del dominio aziendale e non ha nessun
# titolo per decidere degli altri.
HSTS = "max-age=15552000"


@app.middleware("http")
async def intestazioni_di_sicurezza(request: Request, call_next):
    """Aggiunge a ogni risposta le intestazioni che il browser deve rispettare.

    E' un middleware e non una cosa scritta rotta per rotta per la stessa
    ragione per cui la protezione CSRF e' una dipendenza globale (D-028): una
    rotta a cui mancassero funzionerebbe benissimo, e la mancanza si
    scoprirebbe il giorno in cui qualcuno ne approfitta.

    Le intestazioni gia' scritte da chi ha composto la risposta non si
    sovrascrivono: se un giorno una rotta avesse bisogno di una politica sua,
    la scrive e questa la rispetta.
    """
    response = await call_next(request)

    for nome, valore in INTESTAZIONI_DI_SICUREZZA.items():
        if nome not in response.headers:
            response.headers[nome] = valore

    if settings.COOKIE_SECURE and "Strict-Transport-Security" not in response.headers:
        response.headers["Strict-Transport-Security"] = HSTS

    return response


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


# Il messaggio del 404 quando un identificativo nell'indirizzo non e' scritto
# come un UUID. E' **la stessa frase** che riceve chi chiede un identificativo
# ben scritto che non esiste: e' la regola di D-052 portata fino in fondo. Un
# messaggio diverso direbbe a chi prova gli indirizzi che la forma era quella
# giusta, che e' meta' dell'informazione che D-052 vuole non dare.
MESSAGGIO_INDIRIZZO_NON_VALIDO = ERROR_MESSAGES[404][1]


@app.exception_handler(RequestValidationError)
async def validazione_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """Un parametro che FastAPI non riesce a leggere non e' un errore tecnico.

    **Che cosa succedeva senza questo gestore.** Aprendo un indirizzo con
    dentro un identificativo storto - un preferito di sei mesi fa, un
    collegamento tagliato a meta' da un programma di posta, un indirizzo
    ribattuto a mano - FastAPI rispondeva da solo con un 422 e un JSON come
    questo, anche a un browser:

        {"detail":[{"type":"uuid_parsing","loc":["path","product_id"],
                    "msg":"Input should be a valid UUID, ..."}]}

    Sono tre cose sbagliate insieme: e' in inglese (regola 3 di CLAUDE.md), e'
    un dettaglio tecnico interno mostrato a chi usa il programma, e dice il
    nome del parametro della rotta, che a chi guarda non serve e a chi prova
    gli indirizzi serve.

    **Adesso ci sono due risposte, e la distinzione conta.** Se quello che non
    si e' letto sta nel **percorso**, la risposta e' un 404 con la stessa
    identica frase di un identificativo inesistente: perche' e' esattamente
    quello che e' - un indirizzo che non porta da nessuna parte - e perche' due
    frasi diverse per la stessa domanda sono il buco che D-052 e' andato a
    chiudere. Per tutto il resto - un campo di modulo mancante, un parametro di
    ricerca che non si converte - e' un 400: la richiesta e' malfatta, e chi
    l'ha inviata la puo' correggere.

    Il dettaglio vero finisce nel registro su file, dove chi indaga lo trova.
    """
    posizioni = [
        errore.get("loc", ()) for errore in exc.errors()
    ]
    solo_percorso = bool(posizioni) and all(
        posizione and posizione[0] == "path" for posizione in posizioni
    )

    logger.warning(
        "Parametri non validi su %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )

    if solo_percorso:
        return build_error_response(
            request, 404, message_override=MESSAGGIO_INDIRIZZO_NON_VALIDO
        )

    return build_error_response(request, 400)


def database_irraggiungibile() -> bool:
    """Dice se in questo momento PostgreSQL non risponde proprio.

    Serve a distinguere due guasti che arrivano tutti e due come
    `SQLAlchemyError` e che non si somigliano per niente: il servizio spento -
    che si risolve avviandolo, e capita - e l'interrogazione scritta male, che
    e' un difetto del programma. Si prende una connessione nuova apposta: la
    sessione della richiesta, dopo un errore, e' inutilizzabile.
    """
    try:
        with engine.connect() as connessione:
            connessione.execute(text("SELECT 1"))
        return False
    except Exception:
        return True


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> Response:
    """Quando cade il database, si dice che e' caduto il database.

    **Perche' questo gestore esiste.** Senza, un PostgreSQL spento produce
    l'errore 500 generico - «si e' verificato un problema imprevisto, l'errore
    e' stato registrato» - che e' vero e non serve a nessuno: quel problema
    non e' imprevisto, e' il piu' prevedibile di tutti, e chi lo incontra deve
    sapere che si risolve avviando un servizio di Windows.

    **La pagina /diagnostica non e' raggiungibile in quel momento**, perche'
    per aprirla bisogna essere entrati e per entrare serve il database. Quindi
    l'istruzione la porta questa pagina, ed e' **la stessa frase** che si
    leggerebbe li': `diagnostics.CHE_FARE_DATABASE`, scritta una volta sola.

    **Un errore SQL che non e' un database spento resta un 500.** Una
    interrogazione scritta male e' un difetto del programma, e mostrarla come
    "il database non risponde" manderebbe chi indaga a riavviare un servizio
    che sta benissimo.
    """
    if not database_irraggiungibile():
        return await unhandled_exception_handler(request, exc)

    riferimento = uuid.uuid4().hex[:8]
    logger.error(
        "Database non raggiungibile [%s] su %s %s: %s",
        riferimento,
        request.method,
        request.url.path,
        exc,
    )

    if not wants_html(request):
        return JSONResponse(
            {
                "stato": "degradato",
                "codice": 503,
                "titolo": "Il database non risponde",
                "messaggio": diagnostics.CHE_FARE_DATABASE,
                "riferimento": riferimento,
            },
            status_code=503,
        )

    return templates.TemplateResponse(
        request=request,
        name="errore_database.html",
        context={
            "app_name": settings.APP_NAME,
            "che_fare": diagnostics.CHE_FARE_DATABASE,
            "percorso": request.url.path,
            "reference": riferimento,
        },
        status_code=503,
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
app.include_router(router_documents.router)
# La configurazione della posta va registrata **prima** delle pagine della
# posta, e non e' un dettaglio: routers/emails.py dichiara `/posta/{message_id}`,
# e FastAPI prova le rotte nell'ordine in cui sono state registrate. Al
# contrario, l'indirizzo `/posta/configurazione` finirebbe in quella rotta, che
# aspetta un identificativo e risponderebbe che non e' valido.
app.include_router(router_mail_config.router)
app.include_router(router_emails.router)
app.include_router(router_products.router)
app.include_router(router_versions.router)
app.include_router(router_projects.router)
app.include_router(router_permissions.router)
app.include_router(router_phases.router)
app.include_router(router_users.router)
app.include_router(router_audit.router)
app.include_router(router_storico.router)
app.include_router(router_diagnostics.router)
app.include_router(router_help.router)
app.include_router(router_setup.router)
app.include_router(router_style.router)


# La rotta /salute non e' piu' qui: sta in app/routers/diagnostics.py insieme
# alla pagina che mostra gli stessi dati. Fino alla sessione 11 rispondeva a una
# domanda sola - "il database c'e'?" - e stava bene in questo file; adesso
# risponde con dieci controlli, e quei controlli li compone un servizio.
# Tenerne una copia qui avrebbe voluto dire due strade verso lo stesso servizio,
# e la seconda volta che si aggiunge un controllo una delle due resta indietro.
# La forma della risposta non e' cambiata per chi la stesse gia' leggendo.
