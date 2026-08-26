"""Anagrafica dei clienti e delle persone di riferimento presso di loro.

Le tabelle esistono dalla sessione 2 (`customers`, `contacts`): qui c'e' il
comportamento. Come per gli utenti, **niente si cancella**: un cliente e un
contatto si disattivano, perche' i prodotti, i progetti e la corrispondenza
che li nominano devono restare leggibili anche dopo che il rapporto e'
finito.

Le funzioni non sanno niente di HTTP: si possono richiamare da una rotta, da
uno script di caricamento iniziale o da un test.
"""

import logging
import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Contact, Customer, Product, User
from app.services import audit, etichette

logger = logging.getLogger("aurora.clienti")

# Azioni registrate nel registro delle operazioni.
ACTION_CUSTOMER_CREATED = "customer.created"
ACTION_CUSTOMER_UPDATED = "customer.updated"
ACTION_CUSTOMER_DEACTIVATED = "customer.deactivated"
ACTION_CUSTOMER_REACTIVATED = "customer.reactivated"
ACTION_CONTACT_CREATED = "contact.created"
ACTION_CONTACT_UPDATED = "contact.updated"
ACTION_CONTACT_DEACTIVATED = "contact.deactivated"

ENTITY_CUSTOMERS = "customers"
ENTITY_CONTACTS = "contacts"


# --- Lettura ----------------------------------------------------------------


def elenco_clienti(db: Session, solo_attivi: bool = False) -> list[Customer]:
    """Tutti i clienti in ordine di nome.

    Di partenza si mostrano anche i disattivati: l'elenco dei clienti e' la
    pagina da cui si riattiva un cliente, quindi nasconderli renderebbe
    l'operazione impossibile. Chi deve **proporre** un cliente da scegliere -
    il modulo di creazione di un prodotto - chiede invece solo_attivi=True.
    """
    interrogazione = select(Customer)
    if solo_attivi:
        interrogazione = interrogazione.where(Customer.is_active.is_(True))
    return list(db.scalars(interrogazione.order_by(Customer.name)).all())


def trova_cliente(db: Session, customer_id: uuid.UUID) -> Customer | None:
    """Cerca un cliente dal suo identificatore."""
    return db.get(Customer, customer_id)


def codice_gia_usato(
    db: Session, codice: str, escluso: uuid.UUID | None = None
) -> bool:
    """Dice se un altro cliente ha gia' quella sigla.

    Il confronto non guarda maiuscole e minuscole: "acme" e "ACME" sono la
    stessa sigla scritta in due modi, e lasciarle convivere vorrebbe dire due
    schede per lo stesso cliente. Il vincolo del database e' invece
    letterale: questo controllo esiste per dare un messaggio comprensibile
    prima che sia il database a rifiutare la scrittura.
    """
    interrogazione = select(Customer.id).where(
        func.lower(Customer.code) == codice.strip().lower()
    )
    if escluso is not None:
        interrogazione = interrogazione.where(Customer.id != escluso)
    return db.scalars(interrogazione).first() is not None


def contatti_di(db: Session, customer_id: uuid.UUID) -> list[Contact]:
    """Le persone di riferimento di un cliente, disattivate comprese."""
    return list(
        db.scalars(
            select(Contact)
            .where(Contact.customer_id == customer_id)
            .order_by(Contact.is_active.desc(), Contact.name)
        ).all()
    )


def trova_contatto(db: Session, contact_id: uuid.UUID) -> Contact | None:
    """Cerca un contatto dal suo identificatore."""
    return db.get(Contact, contact_id)


def conta_prodotti(db: Session, customer_id: uuid.UUID) -> int:
    """Quanti prodotti attivi ha questo cliente.

    Serve all'elenco, per far vedere a colpo d'occhio quali clienti sono
    davvero in uso, e alla disattivazione, che avverte quando il cliente che
    si sta togliendo ha ancora prodotti attivi.
    """
    return (
        db.scalar(
            select(func.count(Product.id)).where(
                Product.customer_id == customer_id,
                Product.is_active.is_(True),
            )
        )
        or 0
    )


# --- Scrittura --------------------------------------------------------------


def crea_cliente(
    db: Session,
    *,
    nome: str,
    codice: str,
    note: str | None,
    autore: User,
    request: Request | None = None,
) -> Customer:
    """Aggiunge un cliente. Chi chiama ha gia' verificato che la sigla sia libera."""
    cliente = Customer(
        name=nome.strip(),
        code=codice.strip(),
        notes=(note or "").strip() or None,
    )
    db.add(cliente)
    db.flush()

    audit.record(
        db,
        action=ACTION_CUSTOMER_CREATED,
        entity_type=ENTITY_CUSTOMERS,
        entity_id=cliente.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_cliente(cliente),
        new_value={"name": cliente.name, "code": cliente.code},
    )

    logger.info(
        "Cliente '%s' (%s) creato da '%s'",
        cliente.name,
        cliente.code,
        autore.username,
    )
    return cliente


def modifica_cliente(
    db: Session,
    cliente: Customer,
    *,
    nome: str,
    codice: str,
    note: str | None,
    autore: User,
    request: Request | None = None,
) -> Customer:
    """Cambia i dati di un cliente e registra **solo quello che e' cambiato**.

    Nel registro non finisce la riga intera ma le sole colonne toccate: e' la
    regola di app/services/audit.py, e serve a rendere leggibile la storia di
    un oggetto. Una riga che dice "sono cambiati nome e sigla" si legge; venti
    righe che ripetono tutti i campi, no.
    """
    prima = {"name": cliente.name, "code": cliente.code, "notes": cliente.notes}

    cliente.name = nome.strip()
    cliente.code = codice.strip()
    cliente.notes = (note or "").strip() or None

    dopo = {"name": cliente.name, "code": cliente.code, "notes": cliente.notes}
    cambiati = {chiave for chiave in dopo if dopo[chiave] != prima[chiave]}

    if cambiati:
        audit.record(
            db,
            action=ACTION_CUSTOMER_UPDATED,
            entity_type=ENTITY_CUSTOMERS,
            entity_id=cliente.id,
            user_id=autore.id,
            request=request,
            etichetta=etichette.nome_cliente(cliente),
            old_value={chiave: prima[chiave] for chiave in cambiati},
            new_value={chiave: dopo[chiave] for chiave in cambiati},
        )

    return cliente


def disattiva_cliente(
    db: Session,
    cliente: Customer,
    autore: User,
    request: Request | None = None,
) -> Customer:
    """Toglie un cliente dagli elenchi. Non cancella niente.

    I prodotti del cliente restano dove sono e continuano a funzionare: un
    cliente disattivato e' un cliente con cui non si aprono lavori nuovi, non
    un cliente che non e' mai esistito.
    """
    cliente.is_active = False

    audit.record(
        db,
        action=ACTION_CUSTOMER_DEACTIVATED,
        entity_type=ENTITY_CUSTOMERS,
        entity_id=cliente.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_cliente(cliente),
        old_value={"is_active": True},
        new_value={"is_active": False},
    )

    logger.info("Cliente '%s' disattivato da '%s'", cliente.code, autore.username)
    return cliente


def riattiva_cliente(
    db: Session,
    cliente: Customer,
    autore: User,
    request: Request | None = None,
) -> Customer:
    """Rimette un cliente negli elenchi."""
    cliente.is_active = True

    audit.record(
        db,
        action=ACTION_CUSTOMER_REACTIVATED,
        entity_type=ENTITY_CUSTOMERS,
        entity_id=cliente.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_cliente(cliente),
        old_value={"is_active": False},
        new_value={"is_active": True},
    )

    return cliente


def aggiungi_contatto(
    db: Session,
    cliente: Customer,
    *,
    nome: str,
    email: str | None,
    ruolo: str | None,
    autore: User,
    request: Request | None = None,
) -> Contact:
    """Aggiunge una persona di riferimento al cliente.

    L'indirizzo di posta non e' obbligatorio e non e' unico: la stessa casella
    (ufficio.tecnico@cliente.it) puo' essere il riferimento di piu' persone, e
    la stessa persona puo' comparire per due clienti diversi. Vedi
    docs/MODELLO_DATI.md, 4.2.
    """
    contatto = Contact(
        customer_id=cliente.id,
        name=nome.strip(),
        email=(email or "").strip() or None,
        role=(ruolo or "").strip() or None,
    )
    db.add(contatto)
    db.flush()

    audit.record(
        db,
        action=ACTION_CONTACT_CREATED,
        entity_type=ENTITY_CONTACTS,
        entity_id=contatto.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_contatto(contatto),
        new_value={"name": contatto.name, "email": contatto.email},
    )

    return contatto


def disattiva_contatto(
    db: Session,
    contatto: Contact,
    autore: User,
    request: Request | None = None,
) -> Contact:
    """Toglie un contatto dagli elenchi, senza cancellarlo.

    Serve per la persona che ha cambiato lavoro: i messaggi che le sono stati
    scritti restano, ma il suo nome non viene piu' proposto.
    """
    contatto.is_active = False

    audit.record(
        db,
        action=ACTION_CONTACT_DEACTIVATED,
        entity_type=ENTITY_CONTACTS,
        entity_id=contatto.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_contatto(contatto),
        old_value={"is_active": True},
        new_value={"is_active": False},
    )

    return contatto


def riattiva_contatto(
    db: Session,
    contatto: Contact,
    autore: User,
    request: Request | None = None,
) -> Contact:
    """Rimette un contatto negli elenchi."""
    contatto.is_active = True

    audit.record(
        db,
        action=ACTION_CONTACT_UPDATED,
        entity_type=ENTITY_CONTACTS,
        entity_id=contatto.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_contatto(contatto),
        old_value={"is_active": False},
        new_value={"is_active": True},
    )

    return contatto
