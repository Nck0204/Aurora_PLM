"""Le pagine dei progetti.

    GET  /progetti                      elenco completo dei progetti visibili
    GET  /progetti/nuovo?versione={id}  modulo di apertura su una versione
    POST /progetti/nuovo                apre il progetto e compone la squadra
    GET  /progetti/{id}                 scheda del progetto

**Un progetto si apre su una versione di prodotto, mai da solo.** Per questo
il modulo di creazione vuole per forza il parametro "versione": non esiste una
pagina "nuovo progetto" da cui scegliere il prodotto dopo. Il legame e' uno a
uno e nasce insieme al progetto.

Chi non e' assegnato a un progetto non lo vede nell'elenco e non ne apre la
scheda: il controllo e' lo stesso nei due punti (projects.puo_vedere), perche'
un elenco che nasconde una riga che poi si apre scrivendone l'indirizzo non e'
una protezione, e' una tenda.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import PhaseTemplate, Project, User
from app.services import documents, lifecycle, permissions, projects, users
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.progetti")

router = APIRouter(prefix="/progetti", tags=["progetti"])

MESSAGGIO_PROGETTO_INESISTENTE = "Il progetto richiesto non esiste."
MESSAGGIO_PROGETTO_NON_VISIBILE = (
    "Questo progetto non e' fra quelli a cui sei assegnato."
)


def _progetto_visibile_o_errore(
    db: Session, project_id: uuid.UUID, utente: User
) -> Project:
    """Cerca il progetto e verifica che questa persona lo possa vedere.

    Il 404 e il 403 dicono due cose diverse e vanno tenuti distinti: "non
    esiste" e "esiste ma non e' tuo". Nascondere la seconda dietro la prima
    sembra piu' prudente, ma manda chi ha davvero bisogno di quel progetto a
    cercare un guasto che non c'e', invece che a chiedere l'assegnazione.
    """
    progetto = projects.trova_progetto(db, project_id)
    if progetto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_PROGETTO_INESISTENTE)

    if not projects.puo_vedere(db, progetto, utente):
        raise HTTPException(status_code=403, detail=MESSAGGIO_PROGETTO_NON_VISIBILE)

    return progetto


# --- Elenco -----------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    q: str = "",
    stato: str = "",
    fase: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """L'elenco dei progetti visibili, con gli stessi filtri del cruscotto.

    E' la stessa interrogazione della pagina iniziale: la voce di menu
    "Progetti" porta qui, e chi ci arriva deve trovare quello che ha appena
    visto sul cruscotto, non un elenco costruito con altre regole.
    """
    return pagina(
        request,
        "progetti/elenco.html",
        progetti=projects.cruscotto(
            db, utente, testo=q or None, stato=stato or None, fase=fase or None
        ),
        filtri=projects.filtri_cruscotto(db, utente, stato, fase),
        q=q,
        stato_scelto=stato,
        fase_scelta=fase,
    )


# --- Apertura ---------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(
    request: Request,
    versione: str = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Mostra il modulo di apertura di un progetto su una versione.

    Lo apre il creatore. Non e' una scelta di comodo: aprire un progetto vuol
    dire assegnare delle persone, e chi assegna le persone e' chi gestisce
    l'anagrafica, non chi lavora dentro un progetto.
    """
    scelta = _versione_per_progetto(db, versione)

    return pagina(
        request,
        "progetti/nuovo.html",
        versione=scelta,
        prodotto=scelta.product,
        modelli=_opzioni_modelli(db),
        persone=_opzioni_persone(db),
    )


def _opzioni_persone(db: Session) -> list[tuple[str, str]]:
    """Le persone attive come coppie (identificatore, nome e cognome)."""
    return [
        (str(persona.id), persona.full_name)
        for persona in users.elenco_utenti(db, solo_attivi=True)
    ]


def _opzioni_modelli(db: Session) -> list[tuple[str, str]]:
    """I modelli di fasi attivi come coppie (identificatore, nome e versione).

    Il numero di versione compare nel testo perche' i modelli sono immutabili
    e ne convivono piu' versioni: "Standard v1" e "Standard v2" sono due
    percorsi diversi, e scegliere quello sbagliato si vedrebbe solo mesi dopo.
    """
    return [
        (str(modello.id), f"{modello.name} v{modello.version}")
        for modello in projects.modelli_di_fasi(db)
    ]


def _versione_per_progetto(db: Session, versione: str):
    """Cerca la versione su cui si vuole aprire il progetto e la controlla.

    Due rifiuti possibili, tutti e due con una frase italiana: la versione non
    esiste, oppure ci ha gia' un progetto sopra. Il secondo caso lo
    impedirebbe comunque il vincolo di unicita' del database, ma l'errore che
    ne verrebbe fuori sarebbe tecnico e in inglese.
    """
    try:
        trovata = lifecycle.trova_versione(db, uuid.UUID(versione))
    except (ValueError, AttributeError):
        trovata = None

    if trovata is None:
        raise HTTPException(
            status_code=404,
            detail="La versione di prodotto su cui aprire il progetto non esiste.",
        )

    if trovata.project is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Su questa versione c'e' gia' un progetto: una versione ne ha "
                "al massimo uno."
            ),
        )

    return trovata


@router.post("/nuovo")
def crea(
    request: Request,
    versione: Annotated[str, Form()] = "",
    project_manager: Annotated[str, Form()] = "",
    modello: Annotated[str, Form()] = "",
    norme: Annotated[str, Form()] = "",
    ingegneri: Annotated[list[str], Form()] = [],
    lettori: Annotated[list[str], Form()] = [],
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Apre il progetto, congela il modello di fasi e compone la squadra."""
    scelta = _versione_per_progetto(db, versione)

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "progetti/nuovo.html",
            stato=400,
            errore=messaggio,
            versione=scelta,
            prodotto=scelta.product,
            modelli=_opzioni_modelli(db),
            persone=_opzioni_persone(db),
            norme=norme,
        )

    responsabile = _utente_scelto(db, project_manager)
    if responsabile is None:
        return rimostra("Scegli il project manager del progetto.")

    modello_scelto = _modello_scelto(db, modello)
    if modello_scelto is None:
        return rimostra("Scegli il modello di fasi da seguire.")

    progetto = projects.apri_progetto(
        db,
        versione=scelta,
        project_manager=responsabile,
        modello=modello_scelto,
        norme=_norme_scritte(norme, modello_scelto),
        ingegneri=_utenti_scelti(db, ingegneri),
        lettori=_utenti_scelti(db, lettori),
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/progetti/{progetto.id}?aperto=1", status_code=303)


def _utente_scelto(db: Session, valore: str) -> User | None:
    """Cerca una persona dal suo identificatore, senza fidarsi del modulo."""
    try:
        return users.trova_utente(db, uuid.UUID(valore))
    except (ValueError, AttributeError):
        return None


def _utenti_scelti(db: Session, valori: list[str]) -> list[User]:
    """Le persone scelte in una casella a scelta multipla, quelle valide."""
    trovate: list[User] = []
    for valore in valori:
        persona = _utente_scelto(db, valore)
        if persona is not None and persona.is_active:
            trovate.append(persona)
    return trovate


def _modello_scelto(db: Session, valore: str) -> PhaseTemplate | None:
    """Cerca il modello di fasi scelto."""
    try:
        return db.scalars(
            select(PhaseTemplate).where(PhaseTemplate.id == uuid.UUID(valore))
        ).first()
    except (ValueError, AttributeError):
        return None


def _norme_scritte(testo: str, modello: PhaseTemplate) -> list[str]:
    """Le norme applicabili, una per riga, ripulite.

    Se la casella e' vuota si parte da quelle del modello: sono il punto di
    partenza ragionevole, e chi apre il progetto puo' toglierne o aggiungerne.
    Una volta scritte nel progetto non cambiano piu' da sole, nemmeno se il
    modello venisse sostituito (D-041).
    """
    righe = [riga.strip() for riga in testo.splitlines() if riga.strip()]
    if righe:
        return righe
    return list(modello.standards or [])


# --- Scheda -----------------------------------------------------------------


@router.get("/{project_id}")
def scheda(
    request: Request,
    project_id: uuid.UUID,
    aperto: int = 0,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di un progetto: versione, squadra, fasi, norme."""
    progetto = _progetto_visibile_o_errore(db, project_id, utente)

    fasi = projects.fasi_del_modello(db, progetto.phase_template_id)

    # Le fasi come le vuole il componente dell'avanzamento: conclusa quella
    # gia' attraversata, corrente quella di adesso, niente per le prossime.
    # L'ordine di attraversamento e' sort_order, quindi "gia' attraversata"
    # vuol dire "prima di quella corrente".
    posizione_corrente = next(
        (
            indice
            for indice, fase in enumerate(fasi)
            if fase.id == progetto.current_phase_id
        ),
        None,
    )

    avanzamento = [
        {
            "nome": fase.name,
            "stato": (
                "conclusa"
                if posizione_corrente is not None and indice < posizione_corrente
                else "corrente"
                if indice == posizione_corrente
                else ""
            ),
        }
        for indice, fase in enumerate(fasi)
    ]

    return pagina(
        request,
        "progetti/scheda.html",
        progetto=progetto,
        versione=progetto.product_version,
        prodotto=progetto.product_version.product,
        squadra=projects.assegnazioni_attive(db, progetto.id),
        avanzamento=avanzamento,
        aperto=bool(aperto),
        # Il riquadro dei documenti dice quanti se ne vedono e porta al loro
        # elenco. Il conteggio passa dallo stesso filtro dell'elenco, quindi
        # non puo' dire "tre documenti" a chi poi ne trova due.
        documenti_del_progetto=documents.conta_documenti(
            db, utente, progetto.id
        ),
        puo_caricare=bool(
            permissions.classificazioni_caricabili(db, progetto, utente)
        ),
    )
