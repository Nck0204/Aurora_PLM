"""Attrezzi comuni ai test che toccano il database.

La fixture "db_session" consegna una sessione di SQLAlchemy che lavora dentro
una transazione **annullata sempre**, riuscito o fallito che sia il test. Il
database di sviluppo non si sporca e i test non si disturbano a vicenda: al
test successivo il database e' esattamente come prima.

Se PostgreSQL non risponde, o se le migrazioni non sono state applicate, i test
che usano questa fixture vengono **saltati** invece che falliti. Un test rosso
deve voler dire "il codice e' sbagliato", non "manca un pezzo di ambiente".

La fixture "client" aggiunge a quella un finto browser che parla con
l'applicazione vera - rotte, dipendenze, middleware, template - ma appoggiata
alla stessa transazione, cosi' anche le pagine si provano senza lasciare
tracce.
"""

import html
import random
import re
import string
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.models import GlobalRole, User
from app.services import passwords

# Tabella che si va a cercare per stabilire se le migrazioni sono passate.
# Ne basta una qualunque: o ci sono tutte o non c'e' nessuna.
SENTINEL_TABLE = "product_versions"

# Password usate dai test. Sono qui in chiaro perche' sono finte e vivono solo
# dentro una transazione annullata: nel database vero non arrivano mai.
PASSWORD_DI_PROVA = "password-di-prova-1"
PASSWORD_NUOVA = "una-password-nuova-lunga"


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
    esterna. Serve per due cose: per i test che provocano apposta un errore di
    vincolo, perche' senza savepoint l'errore chiuderebbe la transazione
    esterna e il rollback qui sotto non troverebbe piu' niente da annullare; e
    per le rotte vere, che chiamano commit() - con il savepoint quel commit
    chiude il punto di ripristino e non la transazione del test.
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


@pytest.fixture
def client(db_session: Session):
    """Un finto browser che parla con l'applicazione vera.

    L'applicazione e' quella di app/main.py senza nessuna modifica: stesse
    rotte, stesse dipendenze, stesso middleware, stessi template. L'unica cosa
    sostituita e' la sorgente delle sessioni del database, che diventa quella
    del test: cosi' anche quello che le rotte scrivono viene annullato alla
    fine, comprese le righe che loro stesse mandano con commit().

    Il finto browser conserva i cookie fra una richiesta e l'altra, come farebbe
    un browser vero: e' quello che permette di provare per davvero l'accesso, il
    "ricordami" e la protezione dei moduli.
    """

    def sessione_di_prova():
        # Non si chiude: la chiude la fixture db_session, dopo il rollback.
        yield db_session

    app.dependency_overrides[get_db] = sessione_di_prova
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def secondo_browser(client: TestClient):
    """Un secondo finto browser, con i suoi cookie, sullo stesso database.

    Serve ai test che devono verificare che cosa succede alle **altre**
    sessioni di una persona: quelle su un altro calcolatore, che devono
    chiudersi quando la password cambia o quando l'utente viene disattivato.

    Dipende da "client" perche' e' quella fixture a dirottare le sessioni del
    database su quella del test: senza, questo browser parlerebbe con il
    database vero.
    """
    with TestClient(app) as altro:
        yield altro


# --- Aiuti per scrivere i test ----------------------------------------------


def cognome_irripetibile() -> str:
    """Un cognome inventato che non puo' gia' essere nel database.

    Serve ai test che verificano il nome utente **proposto** dal programma:
    quelli devono confrontare il risultato con un valore esatto, e il valore
    esatto cambierebbe se un utente con quel nome esistesse gia' - il programma
    aggiungerebbe il numero progressivo dell'omonimia.

    Non e' una precauzione teorica: e' successo davvero. La verifica a mano
    della sessione 3 ha creato dall'interfaccia un utente "Nicolo' D'Angelo"
    sul database di sviluppo, e il test che si aspettava "nicolo.dangelo" si e'
    trovato davanti "nicolo.dangelo2".

    Gli altri test, quelli che il nome utente se lo scelgono, usano invece nomi
    con **due punti** ("prova.mario.rossi"): proponi_username() ne produce al
    massimo uno, quindi quello spazio di nomi il programma non lo raggiunge e
    non ci puo' essere collisione.
    """
    return "Diprova" + uuid.uuid4().hex[:8]


def crea_utente(
    db: Session,
    username: str = "mario.rossi",
    password: str = PASSWORD_DI_PROVA,
    ruolo: GlobalRole = GlobalRole.UTENTE,
    deve_cambiare: bool = False,
    attivo: bool = True,
) -> User:
    """Mette nel database un utente con una password nota.

    Serve ai test che devono provare a entrare: la password vera non si puo'
    rileggere da nessuna parte, quindi il test deve essere lui a stabilirla.

    **I nomi utente passati qui hanno due punti** ("prova.mario.rossi"). Non e'
    un vezzo: proponi_username() ne produce al massimo uno ("nome.cognome"),
    quindi quello e' uno spazio di nomi che il programma non raggiunge mai, e
    un utente vero creato a mano sul database di sviluppo non puo' collidere
    con quelli dei test. Vedi cognome_irripetibile() per l'altra meta' della
    stessa precauzione.
    """
    utente = User(
        username=username,
        first_name="Mario",
        last_name="Rossi",
        email=f"{username}@esempio.local",
        password_hash=passwords.hash_password(password),
        must_change_password=deve_cambiare,
        is_active=attivo,
        global_role=ruolo,
    )
    db.add(utente)
    db.flush()
    return utente


def contenuto_leggibile(risposta) -> str:
    """Il testo di una pagina con le entita' HTML riportate ai caratteri veri.

    Il nome non comincia per "test": pytest raccoglie come test qualunque
    funzione il cui nome cominci cosi', compresi gli aiuti importati dentro un
    file di test, e proverebbe a passargli le fixture che non ha.

    Jinja2 protegge l'HTML trasformando gli apostrofi in &#39;, quindi cercare
    "non e' corretta" dentro risposta.text non trova mai niente. Serve nei test
    che verificano un messaggio in italiano, che di apostrofi ne ha sempre.
    """
    return html.unescape(risposta.text)


# Il campo nascosto che ogni modulo di Aurora deve contenere. Il test lo legge
# dalla pagina invece di inventarselo: cosi' verifica anche che i template lo
# mettano davvero, e che il gettone nel campo coincida con quello nel cookie.
_CAMPO_CSRF = re.compile(r'name="csrf"\s+value="([^"]+)"')


def gettone_csrf(client: TestClient, percorso: str = "/entra") -> str:
    """Apre una pagina e ne estrae il gettone del modulo.

    Il cookie corrispondente resta nel finto browser, che lo rimandera' da solo
    con il POST successivo.
    """
    risposta = client.get(percorso)
    trovato = _CAMPO_CSRF.search(risposta.text)

    assert trovato is not None, (
        f"la pagina {percorso} non contiene il campo nascosto csrf: "
        "senza, il modulo verrebbe rifiutato"
    )
    return trovato.group(1)


def entra(
    client: TestClient,
    username: str,
    password: str,
    ricordami: bool = False,
) -> object:
    """Fa il giro completo dell'accesso: apre il modulo e lo invia.

    Restituisce la risposta al POST, senza seguire il rimando: cosi' il test
    puo' guardare il codice di stato e i cookie consegnati.
    """
    dati = {
        "username": username,
        "password": password,
        "csrf": gettone_csrf(client, "/entra"),
    }
    if ricordami:
        dati["ricordami"] = "si"

    return client.post("/entra", data=dati, follow_redirects=False)


# --- Aiuti per i test dei prodotti, delle versioni e dei progetti -----------
#
# Servono a tutti i file della sessione 5 e stanno qui per la stessa ragione
# per cui ci sta crea_utente(): un aiuto copiato in tre file di test diventa
# tre aiuti diversi alla prima modifica.
#
# I codici e le sigle inventati qui portano una coda casuale, come i cognomi
# di cognome_irripetibile(): il database di sviluppo contiene dati veri
# lasciati dalle verifiche a mano, e "customers.code" e "products.code" hanno
# tutti e due un vincolo di unicita'.


def sigla_irripetibile(prefisso: str = "PRV") -> str:
    """Una sigla cliente che nel database non puo' gia' esserci."""
    return prefisso + uuid.uuid4().hex[:6].upper()


def modello_irripetibile() -> str:
    """Una sigla di modello che nel listino dell'azienda non ci puo' essere.

    Sono otto lettere casuali dopo "PRV". Serve a costruire codici prodotto
    che non collidano con quelli veri: **e' successo davvero**. La verifica a
    mano della sessione 5 ha creato dall'interfaccia il prodotto
    "RMS1100-24-110SW", che i test usavano come codice di comodo, e da quel
    momento quarantasei test sono diventati rossi tutti insieme - non perche'
    il programma fosse sbagliato, ma perche' "products.code" e' unico.

    E' la stessa lezione di cognome_irripetibile() e la stessa medicina: i
    test si scelgono i propri dati dentro uno spazio di nomi che il programma
    vero non raggiunge.

    Solo lettere, niente cifre: nell'espressione di scomposizione il modello
    e' il gruppo delle lettere iniziali, e una cifra in mezzo finirebbe nella
    potenza cambiando la scomposizione.
    """
    return "PRV" + "".join(random.choices(string.ascii_uppercase, k=8))


def codice_irripetibile(
    potenza: str = "1100",
    ingresso: str = "24",
    uscita: str = "110",
    variante: str = "SW",
) -> str:
    """Un codice prodotto che non puo' gia' esserci, e che si scompone.

    Il modello e' l'unica parte casuale: tutto il resto e' fisso, cosi' un
    test puo' affermare che la potenza vale 1100 e la tensione di uscita 110
    senza dover prima chiedere al programma che cosa ha capito - il che
    sarebbe verificare una funzione con se stessa.
    """
    return f"{modello_irripetibile()}{potenza}-{ingresso}-{uscita}{variante}"


def crea_cliente(db: Session, nome: str = "Cliente di prova"):
    """Mette nel database un cliente attivo, con una sigla libera."""
    from app.models import Customer

    cliente = Customer(name=nome, code=sigla_irripetibile(), is_active=True)
    db.add(cliente)
    db.flush()
    return cliente


def crea_prodotto(
    db: Session,
    cliente=None,
    codice: str | None = None,
    autore=None,
):
    """Un prodotto con la sua versione 1, creato passando dal servizio vero.

    Passa dal servizio e non costruisce le righe a mano di proposito: cosi' i
    test lavorano sugli stessi dati che produce l'interfaccia, scomposizione
    del codice e riga di audit comprese.
    """
    from app.services import products

    if codice is None:
        codice = codice_irripetibile()
    if cliente is None:
        cliente = crea_cliente(db)
    if autore is None:
        autore = crea_utente(
            db,
            username=f"prova.autore.{uuid.uuid4().hex[:8]}",
            ruolo=GlobalRole.CREATORE,
        )

    prodotto, versione = products.crea_prodotto(
        db,
        codice=codice,
        cliente=cliente,
        descrizione="Prodotto creato da un test.",
        autore=autore,
    )
    db.flush()
    return prodotto, versione


def crea_progetto(db: Session, versione, project_manager, autore=None, squadra=()):
    """Apre un progetto su una versione, con il modello di fasi disponibile.

    Se nel database non c'e' nessun modello di fasi attivo - succede su un
    database appena migrato, senza scripts/seed.py - ne crea uno con due fasi:
    il test deve poter girare comunque.
    """
    from app.models import Phase, PhaseTemplate
    from app.services import projects

    if autore is None:
        autore = project_manager

    modello = projects.modelli_di_fasi(db)
    if modello:
        scelto = modello[0]
    else:
        scelto = PhaseTemplate(
            name=f"Modello di prova {uuid.uuid4().hex[:6]}",
            description="Creato da un test.",
            standards=["EN 50155"],
            is_active=True,
            version=1,
        )
        db.add(scelto)
        db.flush()
        for ordine, nome in enumerate(("Concept", "Sviluppo"), start=1):
            db.add(
                Phase(
                    phase_template_id=scelto.id,
                    name=nome,
                    sort_order=ordine,
                )
            )
        db.flush()

    progetto = projects.apri_progetto(
        db,
        versione=versione,
        project_manager=project_manager,
        modello=scelto,
        norme=["EN 50155"],
        ingegneri=list(squadra),
        lettori=[],
        autore=autore,
    )
    db.flush()
    return progetto
