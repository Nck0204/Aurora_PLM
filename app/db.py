"""Collegamento al database PostgreSQL.

In questo file ci sono quattro cose, e nient'altro:

  Base          la classe da cui discendono tutti i modelli (le tabelle).
                Alembic guarda Base.metadata per capire quali tabelle
                dovrebbero esistere e generare le migrazioni.

  engine        il gestore delle connessioni verso PostgreSQL. Ne esiste uno
                solo per tutto il programma: tiene aperto un piccolo insieme
                di connessioni (un "pool") e le presta a chi ne ha bisogno.

  SessionLocal  la fabbrica delle sessioni. Una sessione e' il quaderno degli
                appunti di una singola operazione: raccoglie le modifiche e le
                scrive tutte insieme quando si chiama commit().

  get_db        la funzione che FastAPI usa per consegnare una sessione a chi
                gestisce una richiesta HTTP, e per richiuderla alla fine.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Classe madre di tutti i modelli di Aurora.

    Ogni tabella del database sara' una classe che eredita da questa. Per ora
    non ce n'e' nessuna: le tabelle arrivano dalla sessione 2 in avanti.
    """


# create_engine NON apre nessuna connessione: si limita a preparare gli
# strumenti. La prima connessione vera parte al primo uso.
engine = create_engine(
    settings.DATABASE_URL,
    # Prima di prestare una connessione tenuta in cassetto, verifica che sia
    # ancora viva. Costa un giro a vuoto ma evita gli errori che capitano
    # quando il server di rete chiude le connessioni inattive di notte.
    pool_pre_ping=True,
    # Numero di connessioni tenute aperte, piu' quelle extra concesse nei
    # momenti di punta. Per una ventina di utenti in rete locale bastano.
    pool_size=5,
    max_overflow=10,
    # Mettere True per vedere a schermo ogni istruzione SQL: utilissimo
    # quando si indaga su un problema, rumorosissimo tutto il resto del tempo.
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    # Non spedire le modifiche al database prima di ogni interrogazione:
    # preferiamo che sia il codice a decidere quando, chiamando commit().
    autoflush=False,
    autocommit=False,
    # Dopo commit() gli oggetti restano leggibili senza dover ritornare al
    # database. Serve perche' le pagine HTML vengono composte dopo il commit.
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """Consegna una sessione del database e la richiude a lavoro finito.

    Si usa cosi' dentro una rotta di FastAPI:

        @router.get("/esempio")
        def read_example(db: Session = Depends(get_db)):
            ...

    FastAPI chiama questa funzione, prende il valore restituito da yield e lo
    passa alla rotta. Quando la rotta ha finito - anche se e' finita male, per
    un errore - l'esecuzione riprende dopo lo yield ed esegue il blocco
    finally, che chiude la sessione e restituisce la connessione al pool.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
