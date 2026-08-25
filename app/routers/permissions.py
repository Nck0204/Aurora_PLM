"""Le pagine che amministrano i permessi. Riservate al creatore.

    GET  /permessi                                 la griglia ruolo x classe
    POST /permessi                                 la conferma di che cosa cambia
    POST /permessi/applica                         scrive i cambiamenti
    GET  /permessi/classificazioni                 l'elenco delle classi
    POST /permessi/classificazioni                 ne crea una
    POST /permessi/classificazioni/{id}/rinomina   cambia nome e descrizione
    POST /permessi/classificazioni/{id}/sposta     su o giu' di un posto
    POST /permessi/classificazioni/{id}/disattiva  la toglie dai menu
    POST /permessi/classificazioni/{id}/riattiva   la rimette

**Il salvataggio della matrice e' in due passi**, e non e' un vezzo. Cambiando
una casella si cambiano i permessi di tutte le persone che hanno quel ruolo su
tutti i progetti in corso, subito, senza che nessuno se ne accorga: e' la
pagina di Aurora in cui un clic distratto fa piu' danni. La prima richiesta
non scrive niente e mostra l'elenco di quello che cambierebbe, casella per
casella, com'era e come diventa; la seconda scrive.

E' una pagina di conferma e non una finestra modale, per la ragione di D-042:
una finestra ha bisogno di JavaScript per aprirsi, e se non si aprisse
l'operazione partirebbe senza che nessuno abbia letto niente.

**Qui non c'e' nessuna regola di permesso scritta.** Il lucchetto e' la
dipendenza richiedi_creatore dichiarata sul router, che chiede a
permissions.puo() come ogni altra parte del programma (D-051). Le funzioni che
leggono e scrivono la matrice stanno in app/services/permissions.py, insieme
alla regola che la matrice serve a governare: chi corregge una casella vede
sopra di se' che cosa quella casella decide.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import Classification, ProjectRole, User
from app.services import permissions
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.permessi")

# La dipendenza sta sul router e non sulle singole rotte: cosi' una rotta
# aggiunta domani da qualcun altro nasce gia' protetta.
router = APIRouter(
    prefix="/permessi",
    tags=["permessi"],
    dependencies=[Depends(richiedi_creatore)],
)

MESSAGGIO_CLASSE_INESISTENTE = "La classificazione richiesta non esiste."

# I nomi in italiano dei tre ruoli di progetto, per le intestazioni della
# griglia. Stanno qui e non nel template per la regola di CLAUDE.md: un
# template che trasforma un valore in un'etichetta contiene una regola.
NOMI_RUOLI: dict[ProjectRole, str] = {
    ProjectRole.PROJECT_MANAGER: "Project manager",
    ProjectRole.INGEGNERE: "Ingegnere",
    ProjectRole.LETTORE: "Lettore",
}

# La spiegazione di che cosa vuol dire ciascun permesso, sotto la griglia.
# Sono le stesse parole di docs/MODELLO_DATI.md, 4.5.
SIGNIFICATO_PERMESSI: tuple[tuple[str, str], ...] = (
    ("visualizza", "Sapere che il documento esiste, aprirlo e scaricarlo."),
    ("carica", "Caricare un documento nuovo o una versione nuova."),
    ("modifica", "Cambiare lo stato del documento e ritirarlo."),
)


def _classe_o_404(db: Session, classification_id: uuid.UUID) -> Classification:
    """Cerca la classificazione e, se non c'e', si ferma con un 404."""
    classe = permissions.trova_classificazione(db, classification_id)
    if classe is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_CLASSE_INESISTENTE)
    return classe


def _scelte_dal_modulo(modulo) -> dict[str, bool]:
    """Traduce le caselle spuntate del modulo in un dizionario di verita'.

    Il browser invia una casella di spunta **solo quando e' spuntata**: da un
    modulo con dodici caselle di cui tre spuntate arrivano tre campi, non
    dodici. Quindi non si puo' leggere "quello che e' arrivato" e assumere che
    il resto sia falso senza sapere quali caselle esistevano: per questo la
    griglia mette accanto a ogni spunta un campo nascosto con lo stesso nome e
    il suffisso ".c" ("c" come "casella"), che arriva sempre.

    Il campo nascosto dice "questa casella era nella pagina"; la spunta dice
    "ed era segnata". Senza il primo, una casella tolta dalla griglia da
    qualcuno che modifica il modulo a mano risulterebbe "non nominata" e
    resterebbe com'era.
    """
    scelte: dict[str, bool] = {}

    for chiave, valore in modulo.multi_items():
        if chiave.endswith(".c"):
            # Il campo nascosto: la casella c'era. Falsa finche' non si trova
            # la spunta corrispondente.
            scelte.setdefault(chiave[:-2], False)
        elif valore == "si":
            scelte[chiave] = True

    return scelte


# ---------------------------------------------------------------------------
#  La matrice
# ---------------------------------------------------------------------------


@router.get("")
def griglia(
    request: Request,
    salvate: int = 0,
    db: Session = Depends(get_db),
) -> Response:
    """La griglia dei permessi: una riga per ruolo, tre spunte per classe.

    Le classificazioni disattivate non compaiono: sono vuote per costruzione
    (si disattiva solo quello che non e' in uso, e da li' in poi non accetta
    documenti nuovi), quindi le loro caselle non governano piu' niente.
    """
    return pagina(
        request,
        "permessi/matrice.html",
        caselle=permissions.matrice(db),
        classificazioni=permissions.elenco_classificazioni(db),
        ruoli=list(ProjectRole),
        nomi_ruoli=NOMI_RUOLI,
        colonne_permessi=permissions.PERMESSI_DELLA_MATRICE,
        significato=SIGNIFICATO_PERMESSI,
        salvate=int(salvate),
    )


@router.post("")
async def conferma(request: Request, db: Session = Depends(get_db)) -> Response:
    """Mostra che cosa cambierebbe. **Non scrive niente.**

    Se non cambia niente si torna alla griglia senza far leggere una pagina di
    conferma vuota: chi ha premuto Salva senza aver toccato nulla non ha
    bisogno di confermare il nulla.

    I cambiamenti viaggiano verso il passo successivo dentro campi nascosti,
    non in una variabile di sessione: cosi' quello che viene scritto e'
    esattamente quello che e' stato mostrato, anche se nel frattempo qualcun
    altro ha corretto la matrice da un altro calcolatore.
    """
    modulo = await request.form()
    scelte = _scelte_dal_modulo(modulo)
    cambiamenti = permissions.confronta_matrice(db, scelte)

    if not cambiamenti:
        return RedirectResponse(url="/permessi", status_code=303)

    return pagina(
        request,
        "permessi/conferma.html",
        cambiamenti=cambiamenti,
        nomi_ruoli=NOMI_RUOLI,
        colonne_permessi=permissions.PERMESSI_DELLA_MATRICE,
        # Quello che si rimanda avanti: una riga per casella cambiata, nella
        # forma "ruolo:classificazione:colonna=si|no".
        nascosti=[
            f"{cambiamento.project_role.value}:{cambiamento.classificazione.id}:"
            f"{colonna}={'si' if cambiamento.dopo[colonna] else 'no'}"
            for cambiamento in cambiamenti
            for colonna, _ in permissions.PERMESSI_DELLA_MATRICE
        ],
    )


@router.post("/applica")
async def applica(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Scrive i cambiamenti confermati, e ne registra ciascuno.

    Si riparte dai valori arrivati nei campi nascosti e si ricalcola il
    confronto con la matrice di adesso: se nel frattempo un'altra persona
    avesse gia' fatto la stessa correzione, quella casella semplicemente non
    compare piu' fra i cambiamenti e non viene registrata due volte.
    """
    modulo = await request.form()

    scelte: dict[str, bool] = {}
    for riga in modulo.getlist("cambiamento"):
        chiave, _, valore = str(riga).rpartition("=")
        if chiave:
            scelte[chiave] = valore == "si"

    cambiamenti = permissions.confronta_matrice(db, scelte)
    quante = permissions.salva_matrice(db, cambiamenti, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/permessi?salvate={quante}", status_code=303)


# ---------------------------------------------------------------------------
#  Le classificazioni
# ---------------------------------------------------------------------------


def _pagina_classificazioni(
    request: Request,
    db: Session,
    *,
    stato: int = 200,
    errore: str | None = None,
    nome_scritto: str = "",
    descrizione_scritta: str = "",
) -> Response:
    """Compone l'elenco delle classificazioni.

    Sta in una funzione perche' le rotte che la mostrano sono cinque - una
    normale e quattro che la rimostrano con un errore - e cinque copie dello
    stesso contesto divergono alla prima aggiunta.
    """
    classificazioni = permissions.elenco_classificazioni(
        db, comprese_disattivate=True
    )

    return pagina(
        request,
        "permessi/classificazioni.html",
        stato=stato,
        errore=errore,
        classificazioni=classificazioni,
        # Quanti documenti ha ciascuna: e' il numero che decide se si puo'
        # disattivare, e la pagina lo mostra invece di limitarsi a rifiutare.
        usi={
            classe.id: permissions.documenti_con_classificazione(db, classe.id)
            for classe in classificazioni
        },
        nome_scritto=nome_scritto,
        descrizione_scritta=descrizione_scritta,
    )


@router.get("/classificazioni")
def classificazioni(request: Request, db: Session = Depends(get_db)) -> Response:
    """L'elenco delle classificazioni, con creazione, rinomina e ordinamento."""
    return _pagina_classificazioni(request, db)


@router.post("/classificazioni")
def crea_classificazione(
    request: Request,
    nome: Annotated[str, Form()] = "",
    descrizione: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Crea una classificazione nuova, con le sue caselle a permessi chiusi.

    Nasce chiusa a tutti: e' il servizio a scrivere le tre caselle a falso, e
    il motivo e' che una classificazione senza caselle sarebbe una
    classificazione i cui permessi non ha deciso nessuno.
    """
    if not nome.strip():
        return _pagina_classificazioni(
            request,
            db,
            stato=400,
            errore="Il nome della classificazione e' obbligatorio.",
            descrizione_scritta=descrizione,
        )

    if permissions.nome_gia_usato(db, nome):
        return _pagina_classificazioni(
            request,
            db,
            stato=400,
            errore="Esiste gia' una classificazione con questo nome.",
            nome_scritto=nome,
            descrizione_scritta=descrizione,
        )

    classe = permissions.crea_classificazione(
        db,
        nome=nome,
        descrizione=descrizione,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url=f"/permessi/classificazioni?creata={classe.id}", status_code=303
    )


@router.post("/classificazioni/{classification_id}/rinomina")
def rinomina(
    request: Request,
    classification_id: uuid.UUID,
    nome: Annotated[str, Form()] = "",
    descrizione: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Cambia nome e descrizione di una classificazione.

    I documenti non si toccano: puntano all'identificativo, non al nome.
    """
    classe = _classe_o_404(db, classification_id)

    if not nome.strip():
        return _pagina_classificazioni(
            request,
            db,
            stato=400,
            errore="Il nome della classificazione e' obbligatorio.",
        )

    if permissions.nome_gia_usato(db, nome, escludi=classe.id):
        return _pagina_classificazioni(
            request,
            db,
            stato=400,
            errore="Esiste gia' un'altra classificazione con questo nome.",
        )

    permissions.rinomina_classificazione(
        db,
        classe,
        nome=nome,
        descrizione=descrizione,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url="/permessi/classificazioni", status_code=303)


@router.post("/classificazioni/{classification_id}/sposta")
def sposta(
    request: Request,
    classification_id: uuid.UUID,
    verso: Annotated[str, Form()] = "su",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Sposta una classificazione di un posto in su o in giu' nell'elenco.

    Due pulsanti e non un campo con il numero d'ordine: chi riordina quattro
    voci vuole spostarne una, non ricalcolare i numeri di tutte.
    """
    classe = _classe_o_404(db, classification_id)

    permissions.sposta_classificazione(
        db, classe, verso=verso, autore=creatore, request=request
    )
    db.commit()

    return RedirectResponse(url="/permessi/classificazioni", status_code=303)


@router.post("/classificazioni/{classification_id}/disattiva")
def disattiva(
    request: Request,
    classification_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie una classificazione dai menu, **se non e' in uso**.

    "In uso" vuol dire che almeno un documento ce l'ha addosso, ritirati
    compresi. Non si tratta di prudenza formale: la classificazione e' la meta'
    della coppia che decide chi vede quel documento, e toglierla vorrebbe dire
    lasciarlo senza la riga che risponde a quella domanda.
    """
    classe = _classe_o_404(db, classification_id)

    quanti = permissions.documenti_con_classificazione(db, classe.id)
    if quanti:
        return _pagina_classificazioni(
            request,
            db,
            stato=400,
            errore=(
                f"«{classe.name}» e' addosso a {quanti} "
                f"document{'o' if quanti == 1 else 'i'} e non si puo' "
                "togliere: senza la sua riga non ci sarebbe piu' modo di "
                "dire chi li puo' vedere."
            ),
        )

    permissions.disattiva_classificazione(
        db, classe, autore=creatore, request=request
    )
    db.commit()

    return RedirectResponse(url="/permessi/classificazioni", status_code=303)


@router.post("/classificazioni/{classification_id}/riattiva")
def riattiva(
    request: Request,
    classification_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette una classificazione nei menu, con le caselle che aveva."""
    classe = _classe_o_404(db, classification_id)

    permissions.riattiva_classificazione(
        db, classe, autore=creatore, request=request
    )
    db.commit()

    return RedirectResponse(url="/permessi/classificazioni", status_code=303)
