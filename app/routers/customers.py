"""Le pagine dei clienti e dei loro contatti.

    GET  /clienti                       elenco
    GET  /clienti/nuovo                 modulo di creazione
    POST /clienti/nuovo                 crea il cliente
    GET  /clienti/{id}                  scheda: dati, contatti, prodotti
    POST /clienti/{id}                  salva i dati modificati
    POST /clienti/{id}/disattiva        toglie il cliente dagli elenchi
    POST /clienti/{id}/riattiva         lo rimette
    POST /clienti/{id}/contatti         aggiunge una persona di riferimento
    POST /contatti/{id}/disattiva       toglie un contatto
    POST /contatti/{id}/riattiva        lo rimette

Come per gli utenti, **non c'e' nessuna rotta per cancellare** e non va
aggiunta: regola 5 di CLAUDE.md.

L'anagrafica dei clienti la tiene il creatore. Non e' un dato che cambia
spesso, e un cliente sbagliato si porta dietro i prodotti sbagliati: e' il
tipo di tabella che conviene lasciare in poche mani. Chi non e' creatore i
clienti li **legge** dalle schede dei prodotti, dove compaiono comunque.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import Contact, Customer, User
from app.services import customers, products
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.clienti")

router = APIRouter(tags=["clienti"], dependencies=[Depends(richiedi_creatore)])

MESSAGGIO_CLIENTE_INESISTENTE = "Il cliente richiesto non esiste."
MESSAGGIO_CONTATTO_INESISTENTE = "Il contatto richiesto non esiste."


def _cliente_o_404(db: Session, customer_id: uuid.UUID) -> Customer:
    """Cerca il cliente e, se non c'e', si ferma con un 404 in italiano."""
    cliente = customers.trova_cliente(db, customer_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_CLIENTE_INESISTENTE)
    return cliente


def _contatto_o_404(db: Session, contact_id: uuid.UUID) -> Contact:
    """Cerca il contatto e, se non c'e', si ferma con un 404 in italiano."""
    contatto = customers.trova_contatto(db, contact_id)
    if contatto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_CONTATTO_INESISTENTE)
    return contatto


# --- Elenco -----------------------------------------------------------------


@router.get("/clienti")
def elenco(request: Request, db: Session = Depends(get_db)) -> Response:
    """Tutti i clienti, disattivati compresi.

    I disattivati si vedono perche' questa e' la pagina da cui si riattivano,
    come per gli utenti. La colonna dello stato li distingue.
    """
    elencati = customers.elenco_clienti(db)
    prodotti = {
        cliente.id: customers.conta_prodotti(db, cliente.id) for cliente in elencati
    }

    return pagina(request, "clienti/elenco.html", clienti=elencati, prodotti=prodotti)


# --- Creazione --------------------------------------------------------------


@router.get("/clienti/nuovo")
def mostra_nuovo(request: Request) -> Response:
    """Mostra il modulo di creazione di un cliente."""
    return pagina(request, "clienti/nuovo.html")


@router.post("/clienti/nuovo")
def crea(
    request: Request,
    nome: Annotated[str, Form()] = "",
    codice: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Crea un cliente nuovo."""

    def rimostra(messaggio: str) -> Response:
        """Ripropone il modulo con l'errore e i valori gia' scritti.

        Il valore torna al template come "nome_cliente" e non come "nome":
        "nome" e' gia' il secondo parametro di pagina(), che e' il nome del
        template, e passarglielo come contesto lo coprirebbe. Vedi la nota in
        app/templating.py.
        """
        return pagina(
            request,
            "clienti/nuovo.html",
            stato=400,
            errore=messaggio,
            nome_cliente=nome,
            codice=codice,
            note=note,
        )

    if not nome.strip():
        return rimostra("Il nome del cliente e' obbligatorio.")

    if not codice.strip():
        return rimostra("La sigla del cliente e' obbligatoria.")

    if customers.codice_gia_usato(db, codice):
        return rimostra(f"La sigla «{codice.strip()}» e' gia' di un altro cliente.")

    cliente = customers.crea_cliente(
        db,
        nome=nome,
        codice=codice,
        note=note,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/clienti/{cliente.id}?creato=1", status_code=303)


# --- Scheda -----------------------------------------------------------------


@router.get("/clienti/{customer_id}")
def scheda(
    request: Request,
    customer_id: uuid.UUID,
    creato: int = 0,
    salvato: int = 0,
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di un cliente: dati modificabili, contatti e prodotti."""
    cliente = _cliente_o_404(db, customer_id)

    suoi_prodotti, _totale = products.cerca_prodotti(
        db, cliente_id=cliente.id, solo_attivi=False, per_pagina=200
    )

    return pagina(
        request,
        "clienti/scheda.html",
        cliente=cliente,
        contatti=customers.contatti_di(db, cliente.id),
        prodotti=suoi_prodotti,
        creato=bool(creato),
        salvato=bool(salvato),
    )


@router.post("/clienti/{customer_id}")
def salva(
    request: Request,
    customer_id: uuid.UUID,
    nome: Annotated[str, Form()] = "",
    codice: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Salva i dati modificati di un cliente."""
    cliente = _cliente_o_404(db, customer_id)

    def rimostra(messaggio: str) -> Response:
        suoi_prodotti, _totale = products.cerca_prodotti(
            db, cliente_id=cliente.id, solo_attivi=False, per_pagina=200
        )
        return pagina(
            request,
            "clienti/scheda.html",
            stato=400,
            errore=messaggio,
            cliente=cliente,
            contatti=customers.contatti_di(db, cliente.id),
            prodotti=suoi_prodotti,
        )

    if not nome.strip():
        return rimostra("Il nome del cliente e' obbligatorio.")

    if not codice.strip():
        return rimostra("La sigla del cliente e' obbligatoria.")

    if customers.codice_gia_usato(db, codice, escluso=cliente.id):
        return rimostra(f"La sigla «{codice.strip()}» e' gia' di un altro cliente.")

    customers.modifica_cliente(
        db,
        cliente,
        nome=nome,
        codice=codice,
        note=note,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/clienti/{cliente.id}?salvato=1", status_code=303)


# --- Disattivazione e riattivazione -----------------------------------------


@router.post("/clienti/{customer_id}/disattiva")
def disattiva(
    request: Request,
    customer_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie il cliente dagli elenchi. I suoi prodotti restano dove sono."""
    cliente = _cliente_o_404(db, customer_id)

    customers.disattiva_cliente(db, cliente, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/clienti/{cliente.id}", status_code=303)


@router.post("/clienti/{customer_id}/riattiva")
def riattiva(
    request: Request,
    customer_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette il cliente negli elenchi."""
    cliente = _cliente_o_404(db, customer_id)

    customers.riattiva_cliente(db, cliente, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/clienti/{cliente.id}", status_code=303)


# --- Contatti ---------------------------------------------------------------


@router.post("/clienti/{customer_id}/contatti")
def aggiungi_contatto(
    request: Request,
    customer_id: uuid.UUID,
    nome_contatto: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    ruolo: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Aggiunge una persona di riferimento al cliente.

    Il campo si chiama "nome_contatto" e non "nome" perche' nella stessa
    pagina c'e' anche il modulo dei dati del cliente, che ha gia' un campo
    "nome": due moduli diversi con lo stesso nome di campo sono la premessa
    di una svista il giorno in cui qualcuno li unira'.
    """
    cliente = _cliente_o_404(db, customer_id)

    if not nome_contatto.strip():
        suoi_prodotti, _totale = products.cerca_prodotti(
            db, cliente_id=cliente.id, solo_attivi=False, per_pagina=200
        )
        return pagina(
            request,
            "clienti/scheda.html",
            stato=400,
            errore="Il nome della persona di riferimento e' obbligatorio.",
            cliente=cliente,
            contatti=customers.contatti_di(db, cliente.id),
            prodotti=suoi_prodotti,
        )

    customers.aggiungi_contatto(
        db,
        cliente,
        nome=nome_contatto,
        email=email,
        ruolo=ruolo,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/clienti/{cliente.id}", status_code=303)


@router.post("/contatti/{contact_id}/disattiva")
def disattiva_contatto(
    request: Request,
    contact_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie un contatto dagli elenchi del suo cliente."""
    contatto = _contatto_o_404(db, contact_id)

    customers.disattiva_contatto(db, contatto, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/clienti/{contatto.customer_id}", status_code=303)


@router.post("/contatti/{contact_id}/riattiva")
def riattiva_contatto(
    request: Request,
    contact_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette un contatto negli elenchi del suo cliente."""
    contatto = _contatto_o_404(db, contact_id)

    customers.riattiva_contatto(db, contatto, creatore, request)
    db.commit()

    return RedirectResponse(url=f"/clienti/{contatto.customer_id}", status_code=303)
