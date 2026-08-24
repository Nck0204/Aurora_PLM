"""Attrezzi comuni ai test che toccano il database.

La fixture "db_session" consegna una sessione di SQLAlchemy che lavora dentro
una transazione **annullata sempre**, riuscito o fallito che sia il test. Il
database di sviluppo non si sporca e i test non si disturbano a vicenda: al
test successivo il database e' esattamente come prima.

Se PostgreSQL non risponde, o se le migrazioni non sono state applicate, i test
che usano questa fixture vengono **saltati** invece che falliti. Un test rosso
deve voler dire "il codice e' sbagliato", non "manca un pezzo di ambiente".
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import engine

# Tabella che si va a cercare per stabilire se le migrazioni sono passate.
# Ne basta una qualunque: o ci sono tutte o non c'e' nessuna.
SENTINEL_TABLE = "product_versions"


@pytest.fixture(scope="session")
def database_ready() -> None:
    """Verifica una volta sola che il database sia raggiungibile e migrato."""
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
            tables = inspect(connection).get_table_names()
    except SQLAlchemyError as errore:
        pytest.skip(
            "PostgreSQL non raggiungibile. Vedi scripts/setup_postgres.md. "
            f"Dettaglio: {errore}"
        )

    if SENTINEL_TABLE not in tables:
        pytest.skip(
            "Le tabelle non ci sono: eseguire prima 'alembic upgrade head'."
        )


@pytest.fixture
def db_session(database_ready: None):
    """Una sessione dentro una transazione che viene annullata alla fine.

    Il giro e' questo: si apre una connessione, ci si apre sopra una
    transazione, e la sessione viene legata a **quella** connessione. Tutto
    quello che il test scrive resta dentro la transazione; alla fine si fa
    rollback e non ne rimane traccia.

    Nel test si usa flush() e non commit(): flush manda le istruzioni al
    database - quindi i vincoli, le chiavi esterne e i valori automatici
    vengono davvero verificati - ma lascia la transazione aperta.

    "join_transaction_mode" merita una parola. Dice alla sessione di lavorare
    dentro un punto di ripristino ("savepoint") invece che sulla transazione
    esterna. Serve per i test che provocano apposta un errore di vincolo: senza,
    l'errore chiuderebbe la transazione esterna e il rollback qui sotto non
    troverebbe piu' niente da annullare.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
