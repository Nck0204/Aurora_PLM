"""Test del modello dati: le versioni di prodotto e la loro discendenza.

Si esegue con "pytest" dalla radice del progetto. Serve un database migrato:
se non c'e', i test si saltano da soli (vedi tests/conftest.py).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Customer, LifecycleState, Product, ProductVersion


def unique_suffix() -> str:
    """Coda casuale per i codici, cosi' due esecuzioni non si pestano i piedi.

    In teoria non servirebbe, perche' ogni test finisce con un rollback. In
    pratica costa niente ed evita di dover indagare su un fallimento oscuro il
    giorno in cui un rollback non dovesse avvenire.
    """
    return uuid.uuid4().hex[:8].upper()


def make_customer() -> Customer:
    """Un cliente di prova, gia' pronto da aggiungere alla sessione."""
    return Customer(
        name="Cliente di prova",
        code=f"TST{unique_suffix()}"[:20],
        notes="Riga creata da un test, non deve restare nel database.",
    )


def test_product_version_records_its_origin(db_session):
    """Un prodotto con due versioni, la seconda derivata dalla prima.

    E' il test che tiene ferma la scelta piu' importante del modello: le
    versioni non sono righe scollegate ma una catena, e ogni anello sa da dove
    viene e perche'.
    """
    customer = make_customer()
    product = Product(
        code=f"RMS1100-24-110SW-{unique_suffix()}",
        customer=customer,
        description="Alimentatore di prova per il test del modello dati.",
        code_parts={"famiglia": "RMS", "modello": "1100", "tensione": "110"},
    )

    first = ProductVersion(
        product=product,
        version_number=1,
        lifecycle_state=LifecycleState.RILASCIATO,
    )
    second = ProductVersion(
        product=product,
        version_number=2,
        lifecycle_state=LifecycleState.IN_SVILUPPO,
        derived_from=first,
        derivation_reason="Sostituzione del connettore, richiesta dal cliente.",
    )

    db_session.add(product)
    db_session.flush()

    # Si svuota la memoria della sessione: le verifiche qui sotto rileggono
    # davvero dal database invece di guardare gli oggetti Python appena
    # costruiti. Senza questa riga il test proverebbe solo che SQLAlchemy sa
    # tenere a mente quello che gli abbiamo detto un attimo prima.
    db_session.expire_all()

    ricaricata = db_session.scalar(
        select(ProductVersion).where(ProductVersion.id == second.id)
    )

    # Il collegamento all'indietro: la versione 2 sa da quale versione nasce.
    assert ricaricata.derived_from_id == first.id
    assert ricaricata.derived_from.version_number == 1
    assert ricaricata.derivation_reason.startswith("Sostituzione del connettore")

    # Il collegamento in avanti: dalla versione 1 si arriva alle sue derivate.
    origine = ricaricata.derived_from
    assert [v.version_number for v in origine.derived_versions] == [2]

    # La prima versione non deriva da niente: e' l'inizio della catena.
    assert origine.derived_from_id is None
    assert origine.derived_from is None

    # Entrambe appartengono allo stesso prodotto, in ordine di numero.
    assert [v.version_number for v in ricaricata.product.versions] == [1, 2]
    assert ricaricata.product.code.startswith("RMS1100-24-110SW")

    # I valori automatici li ha messi il database, non il codice del test.
    assert ricaricata.created_at is not None
    assert ricaricata.created_at.tzinfo is not None, "le date devono avere il fuso"
    assert ricaricata.lifecycle_state is LifecycleState.IN_SVILUPPO


def test_version_number_cannot_repeat_within_a_product(db_session):
    """Due volte la "versione 2" dello stesso prodotto non devono esistere.

    Il vincolo lo impone il database, non il programma: e' l'unico posto in cui
    imporlo serva davvero, perche' vale anche per chi scrive da fuori.
    """
    customer = make_customer()
    product = Product(
        code=f"TEST-DUPLICATO-{unique_suffix()}",
        customer=customer,
        description="Prodotto usato per provare il vincolo di unicita'.",
    )
    db_session.add(product)
    db_session.add(ProductVersion(product=product, version_number=1))
    db_session.flush()

    db_session.add(ProductVersion(product=product, version_number=1))

    with pytest.raises(IntegrityError):
        db_session.flush()
