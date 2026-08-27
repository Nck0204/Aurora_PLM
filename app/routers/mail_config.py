"""La pagina di configurazione della posta, riservata al creatore.

    GET  /posta/configurazione           il modulo con i parametri e lo stato
    POST /posta/configurazione           salva i parametri nel file .env
    POST /posta/configurazione/verifica  prova un parametro, o tutto il giro

**Perche' e' un file suo e non una rotta in piu' dentro `routers/emails.py`.**
Perche' l'ordine di registrazione conta. `routers/emails.py` dichiara
`GET /posta/{message_id}`, e FastAPI prova le rotte nell'ordine in cui sono
state registrate: se questo router venisse dopo, l'indirizzo
`/posta/configurazione` finirebbe in quella rotta, che aspetta un
identificativo e risponderebbe "non e' un identificativo valido". In
`app/main.py` questo router e' registrato **prima**, con il commento che lo
spiega.

**Le tre rotte sono riservate al creatore** e il lucchetto e' la dipendenza
dichiarata, come dappertutto. Qui non c'e' nessuna decisione di permesso
scritta a mano: chi puo' amministrare Aurora lo ha gia' deciso
`permissions.puo()`, richiamato da `richiedi_creatore`.

**La pagina funziona anche senza JavaScript.** I pulsanti VERIFICA sono
normali pulsanti di invio con `formaction`: senza HTMX ricaricano la pagina
intera con l'esito in cima, con HTMX sostituiscono il solo riquadro
dell'esito. E' la stessa forma dell'anteprima del codice prodotto
(`routers/products.py`), ed e' la regola D-036: quello che deve funzionare per
forza non dipende da uno script.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import ENV_FILE
from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import User
from app.services import mail_config, mail_scheduler
from app.templating import pagina, templates

logger = logging.getLogger("aurora.rotte.posta.configurazione")

router = APIRouter(prefix="/posta/configurazione", tags=["posta"])

# Il valore che il campo nascosto porta quando si e' premuto il pulsante in
# fondo, quello che prova tutto il giro invece di un parametro solo.
PROVA_TUTTO = "tutto"


def _valori(
    provider: str,
    tenant: str,
    client: str,
    segreto: str,
    casella: str,
    scadenza: str,
    minuti: str,
    automatico: str,
) -> dict[str, str]:
    """Gli otto campi del modulo, con i nomi che hanno nel file `.env`.

    La corrispondenza si scrive qui e in nessun altro posto: il modulo la
    dichiara con gli alias, la pagina compone i campi leggendo
    `mail_config.PARAMETRI`, e in mezzo c'e' questa funzione sola.
    """
    return {
        "MAIL_PROVIDER": provider,
        "MAIL_TENANT_ID": tenant,
        "MAIL_CLIENT_ID": client,
        "MAIL_CLIENT_SECRET": segreto,
        "MAIL_MAILBOX_ADDRESS": casella,
        "MAIL_SECRET_EXPIRES_ON": scadenza,
        "MAIL_POLL_MINUTES": minuti,
        "MAIL_SCHEDULER_ENABLED": automatico,
    }


def _pagina(
    request: Request,
    *,
    valori: dict[str, str] | None = None,
    esito: mail_config.Esito | None = None,
    provato: str = "",
    errori: dict[str, str] | None = None,
    stato: int = 200,
) -> Response:
    """Compone la pagina, con o senza l'esito di una verifica.

    Serve alla lettura, al modulo rifiutato e alla verifica fatta senza
    JavaScript: sono tre momenti diversi della stessa pagina, e comporla in tre
    posti vorrebbe dire ricordarsi tre volte di passare la diagnostica.
    """
    return pagina(
        request,
        "posta/configurazione.html",
        stato=stato,
        parametri=mail_config.PARAMETRI,
        valori=valori if valori is not None else mail_config.valori_correnti(),
        errori=errori or {},
        esito=esito,
        provato=provato,
        segreto_impostato=mail_config.segreto_impostato(),
        diagnostica=mail_config.diagnostica(),
        mancanti=mail_config.mancanti_per_il_collegamento(),
        ultimo=mail_scheduler.ultimo_controllo(),
        file_env=ENV_FILE,
        prova_tutto=PROVA_TUTTO,
    )


@router.get("")
def mostra(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
) -> Response:
    """Il modulo con i parametri di adesso e lo stato del collegamento."""
    return _pagina(request)


@router.post("")
def salva(
    request: Request,
    provider: Annotated[str, Form(alias="MAIL_PROVIDER")] = "locale",
    tenant: Annotated[str, Form(alias="MAIL_TENANT_ID")] = "",
    client: Annotated[str, Form(alias="MAIL_CLIENT_ID")] = "",
    segreto: Annotated[str, Form(alias="MAIL_CLIENT_SECRET")] = "",
    casella: Annotated[str, Form(alias="MAIL_MAILBOX_ADDRESS")] = "",
    scadenza: Annotated[str, Form(alias="MAIL_SECRET_EXPIRES_ON")] = "",
    minuti: Annotated[str, Form(alias="MAIL_POLL_MINUTES")] = "5",
    automatico: Annotated[str, Form(alias="MAIL_SCHEDULER_ENABLED")] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Scrive i parametri nel file `.env` e li applica subito.

    **Non si prova il collegamento prima di salvare**, ed e' voluto: i quattro
    parametri si scrivono in momenti diversi - l'ufficio informatico manda
    prima la registrazione applicativa e il segreto arriva dopo - e una pagina
    che rifiutasse di salvare finche' tutto non funziona costringerebbe a
    tenere i valori su un foglietto. Quello che manca lo dice la diagnostica, e
    il pulsante VERIFICA c'e' apposta.
    """
    valori = _valori(
        provider, tenant, client, segreto, casella, scadenza, minuti, automatico
    )

    problemi = mail_config.problemi_di_forma(valori)
    if problemi:
        return _pagina(request, valori=valori, errori=problemi, stato=400)

    cambiati = mail_config.salva(db, valori, autore=creatore, request=request)
    db.commit()

    return RedirectResponse(
        url=f"/posta/configurazione?salvati={len(cambiati)}", status_code=303
    )


@router.post("/verifica")
def verifica(
    request: Request,
    parametro: Annotated[str, Form()] = "",
    provider: Annotated[str, Form(alias="MAIL_PROVIDER")] = "locale",
    tenant: Annotated[str, Form(alias="MAIL_TENANT_ID")] = "",
    client: Annotated[str, Form(alias="MAIL_CLIENT_ID")] = "",
    segreto: Annotated[str, Form(alias="MAIL_CLIENT_SECRET")] = "",
    casella: Annotated[str, Form(alias="MAIL_MAILBOX_ADDRESS")] = "",
    scadenza: Annotated[str, Form(alias="MAIL_SECRET_EXPIRES_ON")] = "",
    minuti: Annotated[str, Form(alias="MAIL_POLL_MINUTES")] = "5",
    automatico: Annotated[str, Form(alias="MAIL_SCHEDULER_ENABLED")] = "",
    creatore: User = Depends(richiedi_creatore),
) -> Response:
    """Prova un parametro - o tutto il giro - e risponde con l'esito.

    **Prova i valori scritti nel modulo, non quelli salvati.** E' il punto di
    tutta la pagina: si incolla il valore che l'ufficio informatico ha appena
    mandato, si preme VERIFICA e si sa subito se e' quello giusto, senza aver
    salvato niente e senza aver riavviato niente.

    L'unica eccezione e' il segreto lasciato vuoto, che vuol dire "quello di
    prima": vedi `mail_config.con_i_valori_veri()`.

    **Non scrive niente e non tocca il database.** E' una domanda, come
    l'anteprima del codice prodotto: per questo non c'e' nessuna sessione fra
    gli argomenti.
    """
    valori = _valori(
        provider, tenant, client, segreto, casella, scadenza, minuti, automatico
    )

    if parametro == PROVA_TUTTO or not parametro:
        esito = mail_config.prova_completa(valori)
        provato = PROVA_TUTTO
    else:
        esito = mail_config.prova_parametro(parametro, valori)
        provato = parametro

    # Con HTMX si risponde con il solo riquadro dell'esito; senza, con la
    # pagina intera. La differenza la dice l'intestazione che manda HTMX: e'
    # l'unico posto di Aurora in cui si guarda, e sta qui perche' e' anche
    # l'unica pagina in cui una stessa rotta serve tutti e due i casi.
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="posta/verifica.html",
            context={"esito": esito, "provato": provato},
        )

    return _pagina(request, valori=valori, esito=esito, provato=provato)
