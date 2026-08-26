"""La scheda "Storico" di un oggetto: le voci del registro che lo riguardano.

    GET /prodotti/{id}/storico
    GET /versioni/{id}/storico
    GET /progetti/{id}/storico
    GET /documenti/{id}/storico
    GET /utenti/{id}/storico

**Cinque rotte in un file solo, e non una in ciascun router.** La pagina e' la
stessa per tutti e cinque: cambia soltanto quale oggetto si cerca e quali
identificatori compongono la sua storia. Sparpagliarle nei cinque router
avrebbe voluto dire cinque copie della stessa funzione, e alla prima modifica
tre copie aggiornate e due no.

Gli indirizzi restano pero' **sotto l'oggetto** e non sotto una sezione
"storico" tutta sua: `/progetti/{id}/storico` e non `/storico/progetti/{id}`.
Cosi' la barra laterale continua a segnare la sezione giusta (vedi
sezione_corrente in app/navigation.py), e l'indirizzo dice da solo di che cosa
si sta guardando la storia.

**Chi vede la storia di un oggetto e' chi vede l'oggetto.** Non e' una regola
scritta qui: ogni rotta chiama permissions.pretendi(..., VEDERE, oggetto), che
risponde 404 a chi l'oggetto non lo puo' nemmeno vedere - con lo stesso
messaggio di uno che non esiste (D-052). Per i prodotti e le versioni vuol
dire "chiunque sia entrato", per i progetti e i documenti vuol dire la
squadra. Per le persone la domanda e' la stessa ma la fa la dipendenza
`richiedi_creatore`, che risponde **403** come tutte le altre pagine della
sezione utenti: la spiegazione sta sulla rotta. In ogni caso e' D-051
applicato a una pagina nuova - la domanda si fa a permissions.puo(), non a un
`if` scritto qui.

**Non e' la stessa cosa di /registro.** Li' c'e' tutto il registro e lo vede
il solo creatore; qui c'e' la storia di un oggetto solo, e la vede chi ha a
che fare con quell'oggetto. Un ingegnere deve poter rispondere alla domanda
"chi ha cambiato lo stato di questo documento venerdi'" senza chiedere il
permesso a nessuno.
"""

import logging
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import Assignment, Document, PhaseTransition, User
from app.services import audit, documents, lifecycle, permissions, products
from app.services import projects as servizio_progetti
from app.services import registro
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.storico")

router = APIRouter(tags=["storico"])

MESSAGGIO_INESISTENTE = "L'oggetto richiesto non esiste."


def _numero_di_pagina(request: Request) -> int:
    """Il numero di pagina scritto nell'indirizzo, senza fidarsene."""
    try:
        return max(1, int(request.query_params.get("pagina") or 1))
    except ValueError:
        return 1


def _voci_per_la_pagina(voci) -> list[dict]:
    """Le righe gia' tradotte per il template.

    E' la stessa forma che compone app/routers/audit.py per la pagina
    /registro, e la compongono tutte e due perche' il componente che le
    disegna e' lo stesso (components/storico.html).
    """
    return [
        {
            "seq": voce.seq,
            "quando": voce.occurred_at.astimezone(),
            "autore": registro.nome_autore(voce),
            "azione": audit.etichetta_azione(voce.action),
            "codice_azione": voce.action,
            "entita": registro.etichetta_entita(voce.entity_type),
            "entity_id": voce.entity_id,
            "indirizzo": registro.indirizzo_entita(voce.entity_type, voce.entity_id),
            "descrizione": voce.description,
            "prima": voce.old_value or {},
            "dopo": voce.new_value or {},
            "ip": voce.ip,
            "impronta": voce.entry_hash,
        }
        for voce in voci
    ]


def _pagina_storico(
    request: Request,
    db: Session,
    *,
    titolo: str,
    sezione: str,
    indirizzo_oggetto: str,
    etichetta_ritorno: str,
    altre_schede: list[dict] | None,
    entity_ids: list[uuid.UUID],
    autore_id: uuid.UUID | None = None,
    spiegazione: str,
) -> Response:
    """Compone la pagina. E' l'unica funzione che disegna, per tutti e cinque.

    "altre_schede" sono le linguette **in mezzo** fra la scheda dell'oggetto e
    il suo storico: le prime due le mette il macro schede_oggetto, che le
    disegna uguali in tutta Aurora. Oggi ne ha una sola tipo di oggetto - una
    persona, che ha anche la pagina degli accessi.
    """
    numero = _numero_di_pagina(request)

    voci, totale = registro.voci_collegate(
        db,
        entity_ids=entity_ids,
        autore_id=autore_id,
        pagina=numero,
        per_pagina=settings.PAGE_SIZE,
    )

    return pagina(
        request,
        "storico.html",
        titolo_oggetto=titolo,
        sezione_menu=sezione,
        indirizzo_oggetto=indirizzo_oggetto,
        etichetta_ritorno=etichetta_ritorno,
        altre_schede=altre_schede or [],
        indirizzo_storico=request.url.path,
        spiegazione=spiegazione,
        voci=_voci_per_la_pagina(voci),
        totale=totale,
        pagina_corrente=numero,
        totale_pagine=math.ceil(totale / settings.PAGE_SIZE) if totale else 0,
    )


# ---------------------------------------------------------------------------
#  Prodotto
# ---------------------------------------------------------------------------


@router.get("/prodotti/{product_id}/storico")
def storico_prodotto(
    request: Request,
    product_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La storia di un prodotto: il prodotto e tutte le sue versioni.

    Le versioni ci sono dentro apposta. "Quando e' stata rilasciata la
    versione 2" e' una domanda sul prodotto, e chi la fa non ha voglia di
    aprire le versioni una per una per scoprire quale.
    """
    prodotto = products.trova_prodotto(db, product_id)
    if prodotto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, prodotto)

    identificatori = [prodotto.id] + [
        versione.id for versione in products.versioni_di(db, prodotto.id)
    ]

    return _pagina_storico(
        request,
        db,
        titolo=prodotto.code,
        sezione="Prodotti",
        indirizzo_oggetto=f"/prodotti/{prodotto.id}",
        etichetta_ritorno="Il prodotto",
        altre_schede=None,
        entity_ids=identificatori,
        spiegazione=(
            "Tutto quello che e' successo a questo prodotto e alle sue "
            "versioni, dalla creazione a oggi."
        ),
    )


# ---------------------------------------------------------------------------
#  Versione di prodotto
# ---------------------------------------------------------------------------


@router.get("/versioni/{version_id}/storico")
def storico_versione(
    request: Request,
    version_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La storia di una versione: creazione, derivazione, ciclo di vita."""
    versione = lifecycle.trova_versione(db, version_id)
    if versione is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, versione)

    return _pagina_storico(
        request,
        db,
        titolo=f"{versione.product.code} versione {versione.version_number}",
        sezione="Prodotti",
        indirizzo_oggetto=f"/versioni/{versione.id}",
        etichetta_ritorno="La versione",
        altre_schede=None,
        entity_ids=[versione.id],
        spiegazione=(
            "Tutto quello che e' successo a questa versione: come e' nata, "
            "come si e' mosso il suo ciclo di vita, chi l'ha corretta."
        ),
    )


# ---------------------------------------------------------------------------
#  Progetto
# ---------------------------------------------------------------------------


@router.get("/progetti/{project_id}/storico")
def storico_progetto(
    request: Request,
    project_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La storia di un progetto: fasi, squadra, apertura e chiusura.

    Le assegnazioni e i passaggi di fase sono voci con un **tipo di entita'
    diverso** - "assignments", "phase_transitions" - e senza i loro
    identificatori qui non comparirebbero. Sono pero' la meta' della storia di
    un progetto: chi e' entrato nella squadra, chi ne e' uscito, chi ha
    chiesto un avanzamento e chi l'ha respinto.
    """
    progetto = servizio_progetti.trova_progetto(db, project_id)
    if progetto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, progetto)

    assegnazioni = db.scalars(
        select(Assignment.id).where(Assignment.project_id == progetto.id)
    ).all()
    passaggi = db.scalars(
        select(PhaseTransition.id).where(PhaseTransition.project_id == progetto.id)
    ).all()

    return _pagina_storico(
        request,
        db,
        titolo=(
            f"{progetto.product_version.product.code} "
            f"v{progetto.product_version.version_number}"
        ),
        sezione="Progetti",
        indirizzo_oggetto=f"/progetti/{progetto.id}",
        etichetta_ritorno="Il progetto",
        altre_schede=None,
        entity_ids=[progetto.id, *assegnazioni, *passaggi],
        spiegazione=(
            "Tutto quello che e' successo a questo progetto: l'apertura, i "
            "passaggi di fase con chi li ha chiesti e chi li ha decisi, le "
            "persone entrate e uscite dalla squadra."
        ),
    )


# ---------------------------------------------------------------------------
#  Documento
# ---------------------------------------------------------------------------


@router.get("/documenti/{document_id}/storico")
def storico_documento(
    request: Request,
    document_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La storia di un documento: caricamenti, stati, ritiro, scarichi.

    Gli scarichi ci sono, ed e' il motivo principale per cui questa pagina
    esiste: "chi ha scaricato l'offerta prima che la mandassimo" e' la domanda
    che, il giorno in cui viene fatta, deve avere una risposta.
    """
    documento = db.get(Document, document_id)
    if documento is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, documento)

    versioni = documents.versioni_di(db, documento.id)

    return _pagina_storico(
        request,
        db,
        titolo=documento.title,
        sezione="Documenti",
        indirizzo_oggetto=f"/documenti/{documento.id}",
        etichetta_ritorno="Il documento",
        altre_schede=None,
        entity_ids=[documento.id] + [versione.id for versione in versioni],
        spiegazione=(
            "Tutto quello che e' successo a questo documento: chi lo ha "
            "caricato, chi ne ha cambiato lo stato, chi lo ha scaricato e "
            "quando."
        ),
    )


# ---------------------------------------------------------------------------
#  Persona
# ---------------------------------------------------------------------------


@router.get("/utenti/{user_id}/storico")
def storico_utente(
    request: Request,
    user_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """La storia di una persona: quello che le hanno fatto e quello che ha fatto.

    **E' l'unica delle cinque che dichiara Depends(richiedi_creatore)**
    invece di chiamare permissions.pretendi(). La domanda e' la stessa e la
    decide sempre permissions.puo() - richiedi_creatore non fa altro che
    chiedergliela - ma la risposta negativa e' un **403** invece di un 404, ed
    e' quello che rispondono gia' tutte le altre pagine della sezione utenti.
    Due pagine vicine che rispondono in due modi diversi alla stessa domanda
    mandano chi indaga a cercare un guasto che non c'e'.

    Le due meta' ci sono tutte e due, ed e' la differenza fra questa pagina e
    tutte le altre. "Che cosa e' stato fatto a questo utente" - creato,
    disattivato, password riassegnata - risponde a una domanda di
    amministrazione; "che cosa ha fatto questo utente" risponde alla domanda
    per cui esiste un audit trail. Separarle in due pagine vorrebbe dire
    costringere chi indaga ad aprirle tutte e due e a rimettere in ordine due
    elenchi a mano.
    """
    persona = db.get(User, user_id)
    if persona is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    return _pagina_storico(
        request,
        db,
        titolo=persona.username,
        sezione="Utenti",
        indirizzo_oggetto=f"/utenti/{persona.id}",
        etichetta_ritorno="La scheda",
        altre_schede=[
            {
                "etichetta": "Accessi",
                "indirizzo": f"/utenti/{persona.id}/accessi",
            }
        ],
        entity_ids=[persona.id],
        autore_id=persona.id,
        spiegazione=(
            "Quello che e' stato fatto a questa persona e quello che questa "
            "persona ha fatto, in un elenco solo e in ordine di tempo."
        ),
    )
