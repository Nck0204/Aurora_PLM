"""Anagrafica dei prodotti e delle loro versioni.

Il prodotto e' il filo; le versioni sono il lavoro. Un prodotto nasce sempre
**con la sua versione 1**: un prodotto senza nessuna versione non e' niente
su cui si possa lavorare, e lasciarlo creare vorrebbe dire ammettere righe a
meta' nel database (D-040).

Le versioni successive nascono per **derivazione**: si sceglie da quale
versione si parte e si scrive perche'. La nuova parte da "in sviluppo", che
e' l'unico stato in cui un lavoro appena cominciato possa essere.

Il cambio di stato non sta qui: sta in app/services/lifecycle.py, insieme al
grafo delle transizioni e alla regola del superamento automatico.
"""

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, LifecycleState, Product, ProductVersion, User
from app.services import audit, product_codes

logger = logging.getLogger("aurora.prodotti")

ACTION_PRODUCT_CREATED = "product.created"
ACTION_PRODUCT_UPDATED = "product.updated"
ACTION_PRODUCT_DEACTIVATED = "product.deactivated"
ACTION_PRODUCT_REACTIVATED = "product.reactivated"
ACTION_VERSION_CREATED = "product_version.created"

ENTITY_PRODUCTS = "products"
ENTITY_VERSIONS = "product_versions"

# Le colonne su cui l'elenco dei prodotti si puo' ordinare. La chiave e' quella
# che viaggia nell'indirizzo (?ordina=codice), il valore la colonna vera. Un
# valore che non sta in questo dizionario viene ignorato: cosi' un indirizzo
# scritto a mano non puo' far ordinare per una colonna a cui non si e' pensato.
ORDINAMENTI = {
    "codice": Product.code,
    "cliente": Customer.name,
    "aggiornato": Product.updated_at,
}
ORDINAMENTO_PREDEFINITO = "codice"


# --- Lettura ----------------------------------------------------------------


def trova_prodotto(db: Session, product_id: uuid.UUID) -> Product | None:
    """Cerca un prodotto dal suo identificatore."""
    return db.get(Product, product_id)


def trova_per_codice(db: Session, codice: str) -> Product | None:
    """Cerca un prodotto dal suo codice, senza guardare maiuscole e minuscole."""
    return db.scalars(
        select(Product).where(func.lower(Product.code) == codice.strip().lower())
    ).first()


def codice_gia_usato(
    db: Session, codice: str, escluso: uuid.UUID | None = None
) -> bool:
    """Dice se il codice e' gia' di un altro prodotto.

    Il confronto ignora maiuscole e minuscole: "rms1100-24-110sw" e
    "RMS1100-24-110SW" sono lo stesso prodotto scritto in due modi, e il
    vincolo di unicita' del database, che invece e' letterale, li lascerebbe
    convivere.
    """
    interrogazione = select(Product.id).where(
        func.lower(Product.code) == codice.strip().lower()
    )
    if escluso is not None:
        interrogazione = interrogazione.where(Product.id != escluso)
    return db.scalars(interrogazione).first() is not None


def _filtra(
    interrogazione: Select[Any],
    *,
    testo: str | None,
    cliente_id: uuid.UUID | None,
    elementi: dict[str, str] | None,
    solo_attivi: bool,
) -> Select[Any]:
    """Aggiunge all'interrogazione i filtri della barra di ricerca.

    Sta in una funzione sua perche' serve due volte: una per contare le righe
    e una per prenderne una pagina. Se i due elenchi di filtri fossero scritti
    due volte, prima o poi direbbero cose diverse e l'impaginazione mostrerebbe
    "37 risultati" su tre pagine che ne contengono altri.

    **I pezzi del codice si cercano dentro code_parts**, che e' una colonna
    jsonb: `Product.code_parts["modello"].astext == "RMS"` diventa in SQL
    l'operatore ->> di PostgreSQL. E' il motivo per cui la scomposizione viene
    salvata invece di essere ricalcolata ogni volta che serve.
    """
    if solo_attivi:
        interrogazione = interrogazione.where(Product.is_active.is_(True))

    if testo:
        parola = f"%{testo.strip()}%"
        interrogazione = interrogazione.where(
            or_(
                Product.code.ilike(parola),
                Product.description.ilike(parola),
            )
        )

    if cliente_id is not None:
        interrogazione = interrogazione.where(Product.customer_id == cliente_id)

    for chiave, valore in (elementi or {}).items():
        if valore:
            interrogazione = interrogazione.where(
                Product.code_parts[chiave].astext == valore
            )

    return interrogazione


def cerca_prodotti(
    db: Session,
    *,
    testo: str | None = None,
    cliente_id: uuid.UUID | None = None,
    elementi: dict[str, str] | None = None,
    solo_attivi: bool = True,
    ordina: str = ORDINAMENTO_PREDEFINITO,
    verso: str = "asc",
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[Product], int]:
    """Cerca i prodotti e ne restituisce una pagina, piu' il totale trovato.

    Il totale serve all'impaginazione e alla riga di riepilogo: e' quanti ne
    ha trovati la ricerca, non quanti ne sono stati mostrati.

    L'unione con i clienti c'e' sempre - anche quando non si sta filtrando per
    cliente - perche' l'elenco mostra comunque il nome del cliente e perche'
    l'ordinamento per cliente ne ha bisogno.
    """
    colonna = ORDINAMENTI.get(ordina, ORDINAMENTI[ORDINAMENTO_PREDEFINITO])
    verso_sql = colonna.desc() if verso == "desc" else colonna.asc()

    conteggio = _filtra(
        select(func.count(Product.id)).join(
            Customer, Product.customer_id == Customer.id
        ),
        testo=testo,
        cliente_id=cliente_id,
        elementi=elementi,
        solo_attivi=solo_attivi,
    )
    totale = db.scalar(conteggio) or 0

    righe = _filtra(
        select(Product)
        .join(Customer, Product.customer_id == Customer.id)
        .options(selectinload(Product.customer), selectinload(Product.versions)),
        testo=testo,
        cliente_id=cliente_id,
        elementi=elementi,
        solo_attivi=solo_attivi,
    )

    pagina = max(1, pagina)
    righe = (
        righe.order_by(verso_sql, Product.code)
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
    )

    return list(db.scalars(righe).all()), totale


def valori_degli_elementi(db: Session) -> dict[str, list[str]]:
    """I valori che ogni elemento del codice assume davvero, per i filtri.

    Restituisce per esempio {"modello": ["RMS", "TPS"], "potenza": ["600",
    "1100"]}. Le tendine della ricerca si costruiscono da qui, quindi
    contengono sempre e solo valori che qualche prodotto ha per davvero: un
    filtro che non trova mai niente e' peggio di un filtro che non c'e'.

    Si legge tutta la colonna code_parts dei prodotti attivi e si contano i
    valori in Python. Con qualche migliaio di prodotti - il caso di
    quest'azienda - e' un'interrogazione da una colonna sola e non si nota;
    se un giorno i prodotti diventassero centomila, questa e' la funzione da
    riscrivere con una interrogazione per elemento.
    """
    valori: dict[str, set[str]] = {}

    for parti in db.scalars(
        select(Product.code_parts).where(Product.is_active.is_(True))
    ).all():
        for chiave, valore in (parti or {}).items():
            if valore:
                valori.setdefault(chiave, set()).add(str(valore))

    return {chiave: sorted(insieme) for chiave, insieme in valori.items()}


def versioni_di(db: Session, product_id: uuid.UUID) -> list[ProductVersion]:
    """Le versioni di un prodotto in ordine cronologico, dalla prima all'ultima.

    L'ordine e' quello del numero di versione, che e' un contatore crescente:
    ordinare per data di creazione darebbe lo stesso risultato in tutti i casi
    normali e uno diverso il giorno in cui due versioni nascono nello stesso
    secondo. Il numero, invece, e' unico per costruzione.
    """
    return list(
        db.scalars(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .options(selectinload(ProductVersion.project))
            .order_by(ProductVersion.version_number)
        ).all()
    )


def versione_piu_recente(
    db: Session, product_id: uuid.UUID
) -> ProductVersion | None:
    """L'ultima versione di un prodotto: quella con il numero piu' alto.

    Serve all'avviso in cima alla scheda di una versione vecchia: "esiste una
    versione piu' recente, e' la 3". Senza quell'avviso capita che qualcuno
    lavori per mezza giornata sulla versione sbagliata, ed e' proprio il tipo
    di errore che un programma deve rendere difficile.
    """
    return db.scalars(
        select(ProductVersion)
        .where(ProductVersion.product_id == product_id)
        .order_by(ProductVersion.version_number.desc())
        .limit(1)
    ).first()


def prossimo_numero_versione(db: Session, product_id: uuid.UUID) -> int:
    """Il numero che avra' la prossima versione di questo prodotto.

    E' il massimo esistente piu' uno, non il conteggio delle versioni: se un
    giorno una versione venisse tolta di mezzo, il conteggio riuserebbe un
    numero gia' stato, e il vincolo di unicita' su (product_id,
    version_number) rifiuterebbe la scrittura.
    """
    massimo = db.scalar(
        select(func.max(ProductVersion.version_number)).where(
            ProductVersion.product_id == product_id
        )
    )
    return (massimo or 0) + 1


# --- Scrittura --------------------------------------------------------------


def crea_prodotto(
    db: Session,
    *,
    codice: str,
    cliente: Customer,
    descrizione: str | None,
    autore: User,
    request: Request | None = None,
) -> tuple[Product, ProductVersion]:
    """Crea il prodotto **e la sua versione 1**, in un colpo solo.

    Restituisce tutti e due. La versione 1 non e' derivata da niente
    (derived_from_id resta nullo) e parte da "in sviluppo".

    Il codice viene scomposto adesso e il risultato salvato in code_parts. Se
    non corrisponde alla regola, code_parts resta vuoto **e il prodotto si
    crea lo stesso**: e' la regola che l'azienda ha chiesto per prima, e vale
    anche qui dentro, non solo nelle pagine. Chi chiama puo' accorgersene
    guardando `prodotto.code_parts`.
    """
    parti = product_codes.scomponi(codice)

    prodotto = Product(
        code=codice.strip(),
        customer_id=cliente.id,
        description=(descrizione or "").strip() or None,
        code_parts=parti,
    )
    db.add(prodotto)
    db.flush()

    audit.record(
        db,
        action=ACTION_PRODUCT_CREATED,
        entity_type=ENTITY_PRODUCTS,
        entity_id=prodotto.id,
        user_id=autore.id,
        request=request,
        new_value={
            "code": prodotto.code,
            "customer": cliente.code,
            "code_parts": parti,
        },
    )

    prima_versione = _aggiungi_versione(
        db,
        prodotto=prodotto,
        numero=1,
        derivata_da=None,
        motivazione=None,
        autore=autore,
        request=request,
    )

    if not parti:
        logger.warning(
            "Prodotto '%s' creato senza scomposizione: il codice non "
            "corrisponde alla regola in uso",
            prodotto.code,
        )
    logger.info(
        "Prodotto '%s' creato da '%s' con %s elementi riconosciuti",
        prodotto.code,
        autore.username,
        len(parti),
    )

    return prodotto, prima_versione


def modifica_prodotto(
    db: Session,
    prodotto: Product,
    *,
    codice: str,
    cliente: Customer,
    descrizione: str | None,
    autore: User,
    request: Request | None = None,
) -> Product:
    """Cambia i dati di un prodotto e **riscompone il codice** se e' cambiato.

    code_parts e' un dato ricavato: quando cambia la fonte si ricalcola, sempre
    e subito. Lasciarlo indietro vorrebbe dire una ricerca che trova un
    prodotto sotto un modello che non ha piu'.
    """
    prima = {
        "code": prodotto.code,
        "customer_id": str(prodotto.customer_id),
        "description": prodotto.description,
    }

    prodotto.code = codice.strip()
    prodotto.customer_id = cliente.id
    prodotto.description = (descrizione or "").strip() or None

    if prodotto.code != prima["code"]:
        prodotto.code_parts = product_codes.scomponi(prodotto.code)

    dopo = {
        "code": prodotto.code,
        "customer_id": str(prodotto.customer_id),
        "description": prodotto.description,
    }
    cambiati = {chiave for chiave in dopo if dopo[chiave] != prima[chiave]}

    if cambiati:
        audit.record(
            db,
            action=ACTION_PRODUCT_UPDATED,
            entity_type=ENTITY_PRODUCTS,
            entity_id=prodotto.id,
            user_id=autore.id,
            request=request,
            old_value={chiave: prima[chiave] for chiave in cambiati},
            new_value={chiave: dopo[chiave] for chiave in cambiati},
        )

    return prodotto


def riscomponi(db: Session, prodotto: Product) -> Product:
    """Ricalcola code_parts con la regola in uso adesso.

    Serve il giorno in cui l'azienda confermera' la regola vera e il file di
    configurazione cambiera': i prodotti gia' inseriti conservano la
    scomposizione di prima finche' non passano di qui. Non e' ancora
    richiamata da nessuna pagina - lo sara' quando ci sara' la pagina di
    diagnostica, sessione 11 - ma esiste perche' la strada sia gia' aperta e
    perche' i test possano verificarla.
    """
    prodotto.code_parts = product_codes.scomponi(prodotto.code)
    return prodotto


def disattiva_prodotto(
    db: Session,
    prodotto: Product,
    autore: User,
    request: Request | None = None,
) -> Product:
    """Toglie un prodotto dagli elenchi. Le sue versioni restano dove sono."""
    prodotto.is_active = False

    audit.record(
        db,
        action=ACTION_PRODUCT_DEACTIVATED,
        entity_type=ENTITY_PRODUCTS,
        entity_id=prodotto.id,
        user_id=autore.id,
        request=request,
        old_value={"is_active": True},
        new_value={"is_active": False},
    )

    return prodotto


def riattiva_prodotto(
    db: Session,
    prodotto: Product,
    autore: User,
    request: Request | None = None,
) -> Product:
    """Rimette un prodotto negli elenchi."""
    prodotto.is_active = True

    audit.record(
        db,
        action=ACTION_PRODUCT_REACTIVATED,
        entity_type=ENTITY_PRODUCTS,
        entity_id=prodotto.id,
        user_id=autore.id,
        request=request,
        old_value={"is_active": False},
        new_value={"is_active": True},
    )

    return prodotto


def deriva_versione(
    db: Session,
    *,
    origine: ProductVersion,
    motivazione: str,
    autore: User,
    request: Request | None = None,
) -> ProductVersion:
    """Crea una versione nuova a partire da un'altra.

    La versione nuova appartiene allo stesso prodotto dell'origine, prende il
    numero successivo e parte da "in sviluppo". La motivazione la scrive una
    persona ed e' obbligatoria: "perche' esiste la versione 3" e' la domanda
    che qualcuno si fara' fra due anni, e la risposta va scritta adesso che si
    sa.
    """
    prodotto = origine.product

    return _aggiungi_versione(
        db,
        prodotto=prodotto,
        numero=prossimo_numero_versione(db, prodotto.id),
        derivata_da=origine,
        motivazione=motivazione,
        autore=autore,
        request=request,
    )


def _aggiungi_versione(
    db: Session,
    *,
    prodotto: Product,
    numero: int,
    derivata_da: ProductVersion | None,
    motivazione: str | None,
    autore: User,
    request: Request | None,
) -> ProductVersion:
    """Il pezzo comune fra la versione 1 e le versioni derivate.

    E' privata perche' dall'esterno si entra da una delle due porte -
    crea_prodotto() o deriva_versione() - e nessuna delle due lascia scegliere
    il numero di versione: quello lo decide il programma, ed e' l'unico modo
    perche' il vincolo di unicita' su (product_id, version_number) non venga
    mai messo alla prova da una svista.
    """
    versione = ProductVersion(
        product_id=prodotto.id,
        version_number=numero,
        lifecycle_state=LifecycleState.IN_SVILUPPO,
        derived_from_id=derivata_da.id if derivata_da is not None else None,
        derivation_reason=(motivazione or "").strip() or None,
    )
    db.add(versione)
    db.flush()

    audit.record(
        db,
        action=ACTION_VERSION_CREATED,
        entity_type=ENTITY_VERSIONS,
        entity_id=versione.id,
        user_id=autore.id,
        request=request,
        new_value={
            "product": prodotto.code,
            "version_number": numero,
            "derived_from": (
                derivata_da.version_number if derivata_da is not None else None
            ),
            "derivation_reason": versione.derivation_reason,
        },
    )

    logger.info(
        "Versione %s di '%s' creata da '%s'%s",
        numero,
        prodotto.code,
        autore.username,
        (
            f" per derivazione dalla {derivata_da.version_number}"
            if derivata_da is not None
            else ""
        ),
    )

    return versione
