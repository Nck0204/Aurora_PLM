"""Le pagine dei prodotti.

    GET  /prodotti                      elenco, con ricerca e filtri
    GET  /prodotti/nuovo                modulo di creazione
    POST /prodotti/nuovo                crea il prodotto e la sua versione 1
    POST /prodotti/anteprima-codice     il pezzo di pagina con la scomposizione
    GET  /prodotti/{id}                 scheda: dati, elementi, versioni
    POST /prodotti/{id}                 salva i dati modificati
    POST /prodotti/{id}/disattiva       toglie il prodotto dagli elenchi

I prodotti li **legge** chiunque sia entrato: sapere che cosa fa l'azienda non
e' un'informazione riservata, e chi lavora su un progetto ha bisogno di
arrivare al prodotto da cui e' nato. Li **crea e li modifica** il creatore.
Per questo la dipendenza non sta sul router ma sulle singole rotte che
scrivono: e' l'unico punto del programma in cui le due cose si separano, e il
motivo e' scritto qui.

L'anteprima della scomposizione e' l'unica rotta che risponde con un pezzo di
pagina invece che con una pagina intera. La usa HTMX mentre si scrive il
codice; il modulo funziona lo stesso senza (D-036).
"""

import logging
import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import Product, User
from app.services import customers, product_codes, products
from app.templating import pagina, templates

logger = logging.getLogger("aurora.rotte.prodotti")

router = APIRouter(prefix="/prodotti", tags=["prodotti"])

MESSAGGIO_PRODOTTO_INESISTENTE = "Il prodotto richiesto non esiste."

# L'avviso che compare quando un codice non corrisponde alla regola. Sta qui,
# scritto una volta sola, perche' compare in tre posti: nell'anteprima, nella
# pagina di creazione dopo il salvataggio e nella scheda del prodotto.
AVVISO_CODICE_NON_RICONOSCIUTO = (
    "Questo codice non corrisponde alla regola di scomposizione in uso: "
    "viene accettato lo stesso, ma non sara' cercabile per modello, potenza o "
    "tensione finche' la regola non verra' aggiornata."
)


def _prodotto_o_404(db: Session, product_id: uuid.UUID) -> Product:
    """Cerca il prodotto e, se non c'e', si ferma con un 404 in italiano."""
    prodotto = products.trova_prodotto(db, product_id)
    if prodotto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_PRODOTTO_INESISTENTE)
    return prodotto


def _opzioni_clienti(db: Session) -> list[tuple[str, str]]:
    """I clienti attivi come coppie (identificatore, nome), per la tendina.

    Le coppie si compongono qui e non nel template: comporre un elenco di
    scelte e' lavoro del codice, e un template che lo fa e' un template che
    contiene una regola.
    """
    return [
        (str(cliente.id), cliente.name)
        for cliente in customers.elenco_clienti(db, solo_attivi=True)
    ]


def _filtri_ricerca(
    db: Session, cliente: str, elementi_scelti: dict[str, str]
) -> list[dict]:
    """Le tendine della barra di ricerca: il cliente, piu' una per elemento.

    Le tendine degli elementi **non sono scritte da nessuna parte**: nascono
    dalla regola di scomposizione. Se domani il file di configurazione avra'
    un gruppo in piu', qui comparira' una tendina in piu' senza che nessuno
    tocchi ne' questo file ne' il template.

    Un elemento che nessun prodotto ha ancora non diventa una tendina: una
    tendina vuota e' una domanda a cui non si puo' rispondere.
    """
    valori = products.valori_degli_elementi(db)

    filtri: list[dict] = [
        {
            "nome": "cliente",
            "etichetta": "Cliente",
            "opzioni": _opzioni_clienti(db),
            "scelto": cliente,
            "vuoto": "Tutti i clienti",
        }
    ]

    for elemento in product_codes.elementi():
        possibili = valori.get(elemento.chiave, [])
        if not possibili:
            continue
        filtri.append(
            {
                "nome": elemento.chiave,
                "etichetta": elemento.etichetta,
                "opzioni": [(valore, valore) for valore in possibili],
                "scelto": elementi_scelti.get(elemento.chiave, ""),
                "vuoto": f"Qualunque {elemento.etichetta.lower()}",
            }
        )

    return filtri


def _filtri_degli_elementi(request: Request) -> dict[str, str]:
    """Legge dall'indirizzo un filtro per ciascun elemento del codice.

    I nomi dei parametri non si possono dichiarare nella firma della rotta,
    perche' dipendono dal file di configurazione: se domani la regola avra' un
    elemento in piu', il filtro corrispondente deve comparire senza che
    nessuno tocchi il codice. Si leggono quindi dai parametri della richiesta,
    e si tengono solo quelli previsti dalla regola: un parametro inventato non
    diventa un filtro.
    """
    trovati: dict[str, str] = {}
    for elemento in product_codes.elementi():
        valore = (request.query_params.get(elemento.chiave) or "").strip()
        if valore:
            trovati[elemento.chiave] = valore
    return trovati


# --- Elenco -----------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    q: str = "",
    cliente: str = "",
    ordina: str = products.ORDINAMENTO_PREDEFINITO,
    verso: str = "asc",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """L'elenco dei prodotti, con ricerca per codice, cliente ed elementi.

    Il numero di pagina si legge dai parametri della richiesta e non dalla
    firma: nell'indirizzo si chiama "pagina", che in questo file e' gia' il
    nome della funzione che compone le risposte HTML. Due cose con lo stesso
    nome nello stesso file sono un errore che si scopre tardi.
    """
    pagina_numero = max(1, _intero(request.query_params.get("pagina"), 1))

    cliente_id: uuid.UUID | None = None
    if cliente:
        try:
            cliente_id = uuid.UUID(cliente)
        except ValueError:
            # Un identificatore scritto male nell'indirizzo non e' un guasto:
            # si ignora il filtro e si mostra tutto.
            cliente_id = None

    elementi_scelti = _filtri_degli_elementi(request)

    trovati, totale = products.cerca_prodotti(
        db,
        testo=q,
        cliente_id=cliente_id,
        elementi=elementi_scelti,
        ordina=ordina,
        verso=verso,
        pagina=pagina_numero,
        per_pagina=settings.PAGE_SIZE,
    )

    # I parametri da conservare quando si cambia pagina o si riordina: senza,
    # il secondo clic azzererebbe la ricerca appena fatta.
    parametri: dict[str, str] = {}
    if q:
        parametri["q"] = q
    if cliente:
        parametri["cliente"] = cliente
    parametri.update(elementi_scelti)
    if ordina != products.ORDINAMENTO_PREDEFINITO:
        parametri["ordina"] = ordina
    if verso != "asc":
        parametri["verso"] = verso

    return pagina(
        request,
        "prodotti/elenco.html",
        prodotti=trovati,
        totale=totale,
        pagina_corrente=pagina_numero,
        totale_pagine=math.ceil(totale / settings.PAGE_SIZE) if totale else 0,
        parametri=parametri,
        q=q,
        cliente=cliente,
        filtri=_filtri_ricerca(db, cliente, elementi_scelti),
        elementi_scelti=elementi_scelti,
        regola=product_codes.regola(),
        ordina=ordina,
        verso=verso,
    )


def _intero(valore: str | None, predefinito: int) -> int:
    """Legge un numero da un parametro dell'indirizzo, senza fidarsene.

    Un indirizzo puo' essere scritto a mano, o restare in un preferito dopo
    che la pagina e' cambiata: "?pagina=abc" non deve produrre un errore
    tecnico ma comportarsi come se il parametro non ci fosse.
    """
    try:
        return int(valore) if valore is not None else predefinito
    except ValueError:
        return predefinito


# --- Creazione --------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Mostra il modulo di creazione di un prodotto."""
    return pagina(
        request,
        "prodotti/nuovo.html",
        clienti=_opzioni_clienti(db),
        regola=product_codes.regola(),
    )


@router.post("/anteprima-codice")
def anteprima_codice(
    request: Request,
    codice: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
) -> Response:
    """Il pezzo di pagina che mostra come viene letto un codice mentre si scrive.

    Risponde con un frammento, non con una pagina: lo chiede HTMX a ogni pausa
    della battitura e lo infila nel riquadro dell'anteprima. **Non tocca il
    database e non scrive niente**: e' una domanda, non un cambiamento.

    Se lo script non arriva, questa rotta non viene mai chiamata e non manca
    niente: il modulo di creazione funziona lo stesso, e la scomposizione si
    vede dopo il salvataggio, nella scheda del prodotto (D-036).
    """
    return templates.TemplateResponse(
        request=request,
        name="prodotti/anteprima.html",
        context={
            "codice": codice.strip(),
            "coppie": product_codes.scomposizione_leggibile(
                product_codes.scomponi(codice)
            ),
            "regola": product_codes.regola(),
            "avviso_non_riconosciuto": AVVISO_CODICE_NON_RICONOSCIUTO,
        },
    )


@router.post("/nuovo")
def crea(
    request: Request,
    codice: Annotated[str, Form()] = "",
    cliente: Annotated[str, Form()] = "",
    descrizione: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Crea il prodotto e, insieme, la sua versione 1.

    Un codice che non si scompone **viene accettato**: il prodotto si crea con
    code_parts vuoto e chi lo ha inserito trova l'avviso sulla scheda. E' la
    regola che l'azienda ha chiesto per prima, e il posto in cui viene
    rispettata e' questo: qui non c'e' nessun controllo sulla forma del codice
    perche' non deve essercene nessuno.
    """

    def rimostra(messaggio: str) -> Response:
        """Ripropone il modulo con l'errore e i valori gia' scritti."""
        return pagina(
            request,
            "prodotti/nuovo.html",
            stato=400,
            errore=messaggio,
            clienti=_opzioni_clienti(db),
            regola=product_codes.regola(),
            codice=codice,
            cliente=cliente,
            descrizione=descrizione,
            coppie=product_codes.scomposizione_leggibile(
                product_codes.scomponi(codice)
            ),
        )

    if not codice.strip():
        return rimostra("Il codice del prodotto e' obbligatorio.")

    if products.codice_gia_usato(db, codice):
        return rimostra(f"Il codice «{codice.strip()}» e' gia' di un altro prodotto.")

    try:
        cliente_id = uuid.UUID(cliente)
    except (ValueError, AttributeError):
        return rimostra("Scegli il cliente per cui e' sviluppato il prodotto.")

    cliente_scelto = customers.trova_cliente(db, cliente_id)
    if cliente_scelto is None:
        return rimostra("Il cliente scelto non esiste piu'.")

    prodotto, _prima_versione = products.crea_prodotto(
        db,
        codice=codice,
        cliente=cliente_scelto,
        descrizione=descrizione,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/prodotti/{prodotto.id}?creato=1", status_code=303)


# --- Scheda -----------------------------------------------------------------


@router.get("/{product_id}")
def scheda(
    request: Request,
    product_id: uuid.UUID,
    creato: int = 0,
    salvato: int = 0,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di un prodotto: dati, codice scomposto, tutte le versioni.

    Le versioni sono in ordine cronologico, dalla prima all'ultima: e' l'ordine
    in cui la storia si racconta.
    """
    prodotto = _prodotto_o_404(db, product_id)
    versioni = products.versioni_di(db, prodotto.id)

    return pagina(
        request,
        "prodotti/scheda.html",
        prodotto=prodotto,
        versioni=versioni,
        coppie=product_codes.scomposizione_leggibile(prodotto.code_parts),
        regola=product_codes.regola(),
        avviso_non_riconosciuto=AVVISO_CODICE_NON_RICONOSCIUTO,
        creato=bool(creato),
        salvato=bool(salvato),
        clienti=_opzioni_clienti(db),
    )


@router.post("/{product_id}")
def salva(
    request: Request,
    product_id: uuid.UUID,
    codice: Annotated[str, Form()] = "",
    cliente: Annotated[str, Form()] = "",
    descrizione: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Salva i dati modificati di un prodotto e riscompone il codice."""
    prodotto = _prodotto_o_404(db, product_id)

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "prodotti/scheda.html",
            stato=400,
            errore=messaggio,
            prodotto=prodotto,
            versioni=products.versioni_di(db, prodotto.id),
            coppie=product_codes.scomposizione_leggibile(prodotto.code_parts),
            regola=product_codes.regola(),
            avviso_non_riconosciuto=AVVISO_CODICE_NON_RICONOSCIUTO,
                clienti=_opzioni_clienti(db),
        )

    if not codice.strip():
        return rimostra("Il codice del prodotto e' obbligatorio.")

    if products.codice_gia_usato(db, codice, escluso=prodotto.id):
        return rimostra(f"Il codice «{codice.strip()}» e' gia' di un altro prodotto.")

    try:
        cliente_scelto = customers.trova_cliente(db, uuid.UUID(cliente))
    except (ValueError, AttributeError):
        cliente_scelto = None

    if cliente_scelto is None:
        return rimostra("Il cliente scelto non esiste piu'.")

    products.modifica_prodotto(
        db,
        prodotto,
        codice=codice,
        cliente=cliente_scelto,
        descrizione=descrizione,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/prodotti/{prodotto.id}?salvato=1", status_code=303)


@router.post("/{product_id}/disattiva")
def disattiva(
    request: Request,
    product_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie un prodotto dagli elenchi. Le sue versioni restano leggibili."""
    prodotto = _prodotto_o_404(db, product_id)

    products.disattiva_prodotto(db, prodotto, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/prodotti/{prodotto.id}", status_code=303)


@router.post("/{product_id}/riattiva")
def riattiva(
    request: Request,
    product_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette un prodotto negli elenchi."""
    prodotto = _prodotto_o_404(db, product_id)

    products.riattiva_prodotto(db, prodotto, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/prodotti/{prodotto.id}", status_code=303)
