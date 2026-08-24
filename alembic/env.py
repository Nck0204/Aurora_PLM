"""Configurazione di Alembic, lo strumento che tiene allineato il database.

Alembic esegue questo file ogni volta che si lancia un comando "alembic ...".
Il suo compito e' rispondere a due domande:

  1. a quale database mi collego?      -> lo legge da app/config.py, cioe' dal
                                          file .env, non da alembic.ini: cosi'
                                          l'indirizzo del database e la sua
                                          password stanno scritti in un posto
                                          solo in tutto il progetto;

  2. quali tabelle dovrebbero esistere? -> le legge da Base.metadata, cioe'
                                          dai modelli in app/models/.

Comandi che si usano piu' spesso (dalla radice del progetto):

    alembic revision --autogenerate -m "descrizione"   crea una migrazione
    alembic upgrade head                               applica le migrazioni
    alembic downgrade -1                               torna indietro di una
    alembic current                                    a che punto e' il db
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Alembic viene lanciato dalla riga di comando, quindi la cartella del progetto
# non e' automaticamente fra quelle in cui Python cerca i moduli. Gliela
# aggiungiamo a mano, altrimenti "import app.config" qui sotto fallirebbe.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Questi import devono stare dopo la riga qui sopra, non prima.
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402

# Importare app.models serve a registrare le tabelle in Base.metadata: una
# classe che nessuno importa e' invisibile ad Alembic, che genererebbe una
# migrazione vuota senza dire niente. Per ora il pacchetto non contiene
# ancora nessun modello.
import app.models  # noqa: E402, F401

# Oggetto di configurazione di Alembic, corrispondente ad alembic.ini.
config = context.config

# Imposta il registro di Alembic secondo quanto scritto in alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La fotografia di come dovrebbe essere il database secondo il nostro codice.
# Alembic la confronta con il database vero per capire cosa manca.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modalita' "senza collegamento": genera lo script SQL invece di eseguirlo.

    Serve quando le migrazioni devono essere passate a un amministratore di
    database che le applichera' a mano.
    """
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Accorgersi anche quando cambia solo il tipo di una colonna.
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modalita' normale: si collega al database ed esegue le migrazioni."""
    # Si costruisce il collegamento direttamente dalla configurazione, senza
    # passare da alembic.ini. Motivo pratico: alembic.ini viene letto da
    # configparser, che tratta il segno "%" come carattere speciale, e le
    # password codificate in percentuale (%40 al posto di @) verrebbero
    # interpretate male.
    connectable = create_engine(
        settings.DATABASE_URL,
        # NullPool: Alembic fa un lavoro breve e poi esce, non ha senso che
        # tenga in caldo delle connessioni.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
