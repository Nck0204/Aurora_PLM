"""Le dipendenze di FastAPI usate dalle rotte protette.

Sono tre, e ogni rotta di Aurora ne usa una:

  utente_corrente     chi sta guardando la pagina, oppure None. Non pretende
                      niente: serve alle pagine che si mostrano sia a chi e'
                      entrato sia a chi non lo e'.
  richiedi_login      pretende che l'utente sia entrato. Si occupa anche di
                      dirottare al cambio password chi deve cambiarla.
  richiedi_creatore   pretende, oltre all'accesso, il permesso di
                      amministrare Aurora. Chi ce l'ha lo dice
                      permissions.puo(), come per ogni altro permesso: qui
                      non c'e' nessun confronto fra ruoli (D-051).

Sono in fila: richiedi_creatore chiama richiedi_login, che chiama
utente_corrente. FastAPI esegue ciascuna **una volta sola** per richiesta anche
quando compare piu' volte nella catena, quindi non c'e' da preoccuparsi di
interrogare il database due volte per la stessa pagina.

Come si usano:

    @router.get("/qualcosa")
    def leggi_qualcosa(utente: User = Depends(richiedi_login)):
        ...

    @router.get("/riservato")
    def leggi_riservato(utente: User = Depends(richiedi_creatore)):
        ...

**Il cookie non basta mai.** A ogni richiesta si torna al database a rileggere
la sessione e lo stato dell'utente. Un utente disattivato o a cui e' cambiato
il ruolo se ne accorge alla prima pagina che apre, non alla prossima volta che
entra: e' il requisito 11 della sessione 3, ed e' il motivo per cui qui non si
tiene niente in memoria fra una richiesta e l'altra.

I due dirottamenti - "devi entrare" e "devi cambiare la password" - non sono
risposte ma **eccezioni**, perche' una dipendenza non puo' restituire una
pagina al posto della rotta: puo' solo interrompere. Chi le trasforma in un
rimando e' il gestore registrato in app/main.py.
"""

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import SessionKind, User, UserSession
from app.services import audit, auth, permissions
from app.services.cookies import (
    COOKIE_RICORDAMI,
    COOKIE_SESSIONE,
    programma_cookie,
    programma_rimozione_cookie,
)

logger = logging.getLogger("aurora.accesso")

# Pagina a cui si manda chi non e' entrato, e nome del parametro con cui le si
# dice dove tornare dopo.
PERCORSO_ACCESSO = "/entra"
PARAMETRO_RITORNO = "dopo"

# Pagina del cambio password obbligatorio.
PERCORSO_CAMBIO_PASSWORD = "/cambio-password"

# Gli unici indirizzi che restano raggiungibili a chi deve cambiare la
# password: la pagina del cambio stessa e l'uscita. Tutto il resto lo dirotta.
# Chi deve cambiare la password deve poter fare due cose sole: cambiarla, o
# andarsene.
PERCORSI_PERMESSI_SENZA_CAMBIO = frozenset(
    {PERCORSO_CAMBIO_PASSWORD, "/esci", "/esci-ovunque"}
)

MESSAGGIO_NON_CREATORE = permissions.MESSAGGI_NEGATO[
    permissions.Azione.AMMINISTRARE
]

# Durata del cookie "ricordami" in secondi, che e' l'unita' che vuole il
# browser. Il valore in giorni sta nel file .env.
DURATA_RICORDAMI_SECONDI = settings.REMEMBER_ME_DAYS * 24 * 60 * 60


# --- Le due eccezioni di dirottamento ---------------------------------------


class RichiedeAutenticazione(Exception):
    """Sollevata quando una pagina protetta viene aperta senza essere entrati.

    Porta con se' l'indirizzo che si stava cercando di aprire, cosi' dopo
    l'accesso ci si torna invece di finire sempre sulla pagina iniziale.
    """

    def __init__(self, destinazione: str) -> None:
        super().__init__(destinazione)
        self.destinazione = destinazione


class CambioPasswordObbligatorio(Exception):
    """Sollevata quando chi ha must_change_password apre un'altra pagina."""


def percorso_di_ritorno_sicuro(valore: str | None) -> str | None:
    """Accetta un indirizzo di ritorno solo se punta dentro Aurora.

    Serve a evitare il rimando aperto: senza questo controllo si potrebbe
    mandare a qualcuno un collegamento del tipo

        /entra?dopo=https://sito-che-imita-aurora.example/

    e quella persona, dopo aver inserito le proprie credenziali in Aurora
    davvero, si ritroverebbe su una copia che gliele richiede - convinta di
    essere ancora sul programma dell'azienda.

    Si accetta quindi solo un percorso che comincia con una barra singola.
    Due barre no: "//altrosito.example/pagina" e' un indirizzo assoluto
    abbreviato, e il browser lo seguirebbe fuori da qui.
    """
    if not valore:
        return None
    if not valore.startswith("/") or valore.startswith("//"):
        return None
    # Un a capo dentro l'indirizzo permetterebbe di aggiungere righe
    # all'intestazione HTTP della risposta.
    if any(carattere in valore for carattere in "\r\n"):
        return None
    return valore


# --- Le tre dipendenze ------------------------------------------------------


def utente_corrente(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """Riconosce chi sta facendo la richiesta. None se non e' entrato.

    Guarda prima il cookie di sessione. Se non c'e' o non vale piu', prova con
    il cookie "ricordami": se quello e' buono, apre una sessione nuova e
    **ruota** il gettone lungo, cioe' ne emette uno nuovo e revoca il vecchio.

    Perche' il gettone "ricordami" ruota a ogni uso. Un gettone che dura
    trenta giorni e non cambia mai e' un gettone che, se qualcuno riesce a
    copiarlo, vale trenta giorni anche per lui. Ruotandolo, la copia rubata
    smette di funzionare al primo utilizzo del legittimo proprietario; e se e'
    il ladro a usarla per primo, e' il proprietario a ritrovarsi fuori - il
    che e' spiacevole, ma e' anche il modo in cui ci si accorge del furto.

    L'utente riconosciuto viene lasciato in request.state, dove lo trovano la
    funzione pagina() per la barra in cima e il registro di audit. Insieme a
    lui ci si lascia **il permesso di amministrare**, calcolato da
    permissions.puo(): le pagine ne hanno bisogno per sapere se disegnare le
    voci e i pulsanti delle sezioni riservate, e calcolarlo qui vuol dire
    calcolarlo una volta sola, con la funzione giusta, invece che con un
    `{% if %}` dentro ogni template (D-051).
    """
    request.state.utente = None
    request.state.sessione = None
    request.state.puo_amministrare = False

    # 1. La strada normale: il cookie di sessione.
    gettone = request.cookies.get(COOKIE_SESSIONE, "")
    trovato = auth.trova_sessione(db, gettone, SessionKind.SESSIONE)
    if trovato is not None:
        sessione, utente = trovato
        request.state.sessione = sessione
        request.state.utente = utente
        request.state.puo_amministrare = _puo_amministrare(db, utente)
        return utente

    # 2. La sessione non c'e' piu' (browser chiuso, sessione scaduta o
    #    revocata): si prova con il "ricordami".
    gettone_lungo = request.cookies.get(COOKIE_RICORDAMI, "")
    trovato = auth.trova_sessione(db, gettone_lungo, SessionKind.RICORDAMI)
    if trovato is not None:
        sessione_lunga, utente = trovato
        return _rinnova_da_ricordami(request, db, sessione_lunga, utente)

    # 3. Nessuno dei due cookie e' buono. Se il browser ne aveva, si tolgono:
    #    tenerseli non serve a niente e ogni richiesta ricomincerebbe da qui.
    if gettone:
        programma_rimozione_cookie(request, COOKIE_SESSIONE)
    if gettone_lungo:
        programma_rimozione_cookie(request, COOKIE_RICORDAMI)

    return None


def _rinnova_da_ricordami(
    request: Request,
    db: Session,
    sessione_lunga: UserSession,
    utente: User,
) -> User:
    """Apre una sessione nuova a partire da un "ricordami" valido, e lo ruota.

    Il commit qui dentro non e' una svista. Questa funzione gira **prima**
    della rotta, e i cookie nuovi partiranno comunque, anche se la rotta poi
    fallisce o risponde 403 (li applica il middleware, vedi
    app/services/cookies.py). Se la rotazione restasse appesa alla transazione
    della rotta e quella venisse annullata, il browser si ritroverebbe con due
    gettoni che nel database non esistono: l'utente sarebbe fuori senza aver
    fatto niente di sbagliato. Si scrive subito, e la rotazione e' un fatto
    compiuto per conto suo.
    """
    auth.revoca_sessione(db, sessione_lunga)

    nuovo_lungo = auth.crea_sessione(db, utente, SessionKind.RICORDAMI, request)
    nuova_sessione = auth.crea_sessione(db, utente, SessionKind.SESSIONE, request)

    audit.record(
        db,
        action=audit.ACTION_REMEMBER_ROTATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=utente.id,
        request=request,
    )

    db.commit()

    # Il cookie lungo riparte da capo con la durata piena: il "ricordami" e'
    # scorrevole, chi usa Aurora tutte le settimane non se lo vede scadere in
    # faccia. Quello di sessione non ha durata, muore con il browser.
    programma_cookie(
        request, COOKIE_RICORDAMI, nuovo_lungo, durata_secondi=DURATA_RICORDAMI_SECONDI
    )
    programma_cookie(request, COOKIE_SESSIONE, nuova_sessione)

    # Si rilegge la sessione appena creata per lasciarla in request.state:
    # serve al cambio password, che deve sapere quale sessione risparmiare.
    ricreata = auth.trova_sessione(db, nuova_sessione, SessionKind.SESSIONE)
    request.state.sessione = ricreata[0] if ricreata is not None else None
    request.state.utente = utente
    request.state.puo_amministrare = _puo_amministrare(db, utente)

    logger.info("Sessione rinnovata dal 'ricordami' per '%s'", utente.username)
    return utente


def _puo_amministrare(db: Session, utente: User) -> bool:
    """Scorciatoia per non ripetere quattro nomi lunghi in tre punti."""
    return permissions.puo(
        db, utente, permissions.Azione.AMMINISTRARE, permissions.AMMINISTRAZIONE
    )


def richiedi_login(
    request: Request, utente: User | None = Depends(utente_corrente)
) -> User:
    """Pretende che l'utente sia entrato. Altrimenti lo manda alla pagina di accesso.

    Fa anche la seconda parte del lavoro: se l'utente ha must_change_password,
    qualunque pagina apra viene dirottato al cambio password. Le uniche
    eccezioni sono la pagina del cambio stessa e le due uscite, altrimenti si
    resterebbe chiusi in un rimando senza fine.
    """
    if utente is None:
        raise RichiedeAutenticazione(destinazione=request.url.path)

    if (
        utente.must_change_password
        and request.url.path not in PERCORSI_PERMESSI_SENZA_CAMBIO
    ):
        raise CambioPasswordObbligatorio()

    return utente


def richiedi_creatore(
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> User:
    """Pretende, oltre all'accesso, il permesso di amministrare Aurora.

    La domanda la fa permissions.puo(), che e' l'unico posto in cui i permessi
    di Aurora si decidono. Qui non si confronta nessun ruolo: questa
    dipendenza traduce un "no" in un 403, e basta.

    Il permesso si ricalcola a ogni richiesta sulla riga dell'utente appena
    riletta dal database, non su qualcosa scritto nel cookie: se a una persona
    viene tolto il ruolo di creatore, lo perde alla prima pagina che apre.
    """
    if not permissions.puo(
        db, utente, permissions.Azione.AMMINISTRARE, permissions.AMMINISTRAZIONE
    ):
        logger.warning(
            "'%s' ha provato ad aprire una pagina da creatore", utente.username
        )
        raise HTTPException(status_code=403, detail=MESSAGGIO_NON_CREATORE)

    return utente
