"""La pagina di diagnostica e la rotta /salute.

    GET /diagnostica          la pagina, riservata al creatore
    GET /diagnostica/errori   il dettaglio degli errori delle ultime 24 ore
    GET /salute               gli stessi dati in JSON, per la sorveglianza

**Perche' /salute e' qui e non piu' in app/main.py.** Perche' adesso risponde
con gli stessi dati della pagina, e quei dati li compone
`app/services/diagnostics.py`. Tenere la rotta in `main.py` avrebbe voluto
dire due strade verso lo stesso servizio, e la seconda volta che si aggiunge un
controllo una delle due resta indietro. La forma della risposta non e' cambiata
per chi la stesse gia' leggendo: `stato`, `applicazione`, `versione`, `ora` e
`database` sono ancora li' e vogliono dire ancora la stessa cosa.

**La pagina e' riservata al creatore, /salute no.** Sono due destinatari
diversi: la pagina la apre una persona che e' entrata, /salute la interroga un
programma di sorveglianza, che una password non ce l'ha. Se Aurora e'
raggiungibile da fuori la rete dell'ufficio tecnico, la rotta si chiude
scrivendo HEALTH_TOKEN nel file `.env` (D-089).

**Quando PostgreSQL e' spento questa pagina non si apre**, e non e' una
dimenticanza: per aprirla bisogna essere entrati, e per entrare serve il
database. Chi ci prova riceve la pagina «Il database non risponde», che porta
la stessa identica istruzione della riga rossa che vedrebbe qui - la frase e'
scritta una volta sola, in `diagnostics.CHE_FARE_DATABASE` - piu' il
collegamento a /salute, che invece risponde sempre.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.config import ENV_FILE, settings
from app.db import SessionLocal, get_db
from app.dependencies import richiedi_creatore
from app.models import User
from app.services import diagnostics
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.diagnostica")

router = APIRouter(tags=["diagnostica"])

# L'intestazione con cui una sorveglianza automatica si presenta, quando
# HEALTH_TOKEN e' stato scritto nel file .env.
INTESTAZIONE_TOKEN = "X-Aurora-Salute"


@router.get("/diagnostica")
def mostra(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Come sta Aurora: una riga per controllo, con il semaforo e che cosa fare.

    **Il contesto si chiama `diagnosi` e non `stato`**, e non e' un capriccio:
    `pagina()` ha un parametro suo che si chiama `stato` - il codice HTTP della
    risposta - e passandogli una variabile con quel nome si finisce per
    assegnarla a quello. E' la trappola descritta nella docstring di `pagina()`
    e nella sezione 4 di docs/GUIDA_STILE.md, ed e' costata mezz'ora anche
    questa volta.
    """
    diagnosi = diagnostics.stato_del_sistema(db)

    return pagina(
        request,
        "diagnostica.html",
        diagnosi=diagnosi,
        file_env=ENV_FILE,
        archivio=settings.storage_dir,
        cartella_copie=settings.backup_dir,
        # Il colore complessivo tradotto nella variante del componente
        # «avviso»: la traduzione si fa qui, non nel template.
        variante_riassunto=diagnostics.VARIANTE_DEL_COLORE[diagnosi.colore],
    )


@router.get("/diagnostica/errori")
def errori(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
) -> Response:
    """Le righe di errore delle ultime 24 ore, per esteso.

    Il registro su file lo legge il servizio; qui si passa alla pagina quello
    che ha trovato. Non c'e' nessun filtro e nessuna impaginazione, e per una
    ragione: se le righe sono tante il posto giusto in cui guardarle e'
    `logs/aurora.log` sul server, con un editore di testo. Questa pagina serve
    a rispondere alla domanda «che cosa e' andato storto stanotte?» senza
    doversi collegare al server.
    """
    righe, leggibile = diagnostics.errori_recenti()

    return pagina(
        request,
        "diagnostica_errori.html",
        righe=righe[: diagnostics.ERRORI_MOSTRATI],
        totale=len(righe),
        mostrate=min(len(righe), diagnostics.ERRORI_MOSTRATI),
        leggibile=leggibile,
        file_registro="logs/aurora.log",
    )


@router.get("/salute", tags=["servizio"])
def salute(
    token: str = "",
    intestazione: str | None = Header(default=None, alias=INTESTAZIONE_TOKEN),
) -> JSONResponse:
    """Gli stessi dati della pagina di diagnostica, in JSON.

    **Risponde sempre 200, anche quando qualcosa e' rotto.** Chi interroga
    questa rotta vuole sapere che cosa non va, e per saperlo deve poter
    leggere la risposta. Il verdetto sta in `semaforo`: "verde", "giallo" o
    "rosso".

    **Si apre la sessione del database da sola**, ed e' la terza eccezione di
    Aurora alla regola del `Depends(get_db)` - le altre due sono la
    registrazione della configurazione all'avvio e il controllo pianificato
    della posta. La ragione e' la stessa in tutti e tre i casi ma qui e' piu'
    stringente: `get_db` non fallisce mai, ma la **prima interrogazione** su
    una sessione presa da un database spento si', e sarebbe un errore 500 al
    posto della risposta che dice che il database e' spento. Aprendola qui, il
    guasto lo raccoglie il controllo che deve raccoglierlo.
    """
    if settings.HEALTH_TOKEN:
        presentato = intestazione or token
        # compare_digest e non l'uguale, per la stessa ragione scritta in
        # app/services/csrf.py: l'uguale smette di confrontare al primo
        # carattere diverso, quindi impiega piu' tempo quando i due valori
        # hanno un inizio in comune, e misurando i tempi di molte risposte la
        # parola d'ordine si indovina un carattere per volta. Qui e' un
        # rischio piu' teorico che altrove - questa rotta la interroga un
        # programma di sorveglianza, non un browser - ma due modi diversi di
        # confrontare un segreto nello stesso programma sono uno di troppo.
        if not secrets.compare_digest(presentato, settings.HEALTH_TOKEN):
            logger.warning("Richiesta a /salute senza la parola d'ordine giusta")
            raise HTTPException(
                status_code=401,
                detail=(
                    "Questa rotta e' protetta da una parola d'ordine. Va "
                    f"presentata nell'intestazione {INTESTAZIONE_TOKEN}."
                ),
            )

    db = SessionLocal()
    try:
        stato = diagnostics.stato_del_sistema(db)
    finally:
        db.close()

    return JSONResponse(diagnostics.come_json(stato), status_code=200)
