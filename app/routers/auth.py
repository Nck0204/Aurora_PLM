"""Le pagine dell'accesso: entrare, uscire, cambiare la password.

Sei rotte in tutto:

    GET  /entra             mostra il modulo di accesso
    POST /entra             verifica le credenziali e apre la sessione
    POST /esci              chiude la sessione di questo browser
    POST /esci-ovunque      chiude tutte le sessioni dell'utente
    GET  /cambio-password   mostra il modulo del cambio password
    POST /cambio-password   verifica la password attuale e imposta la nuova

Le uscite sono POST e non GET di proposito. Un collegamento GET che fa uscire
puo' essere fatto scattare da chiunque - basta un'immagine con quell'indirizzo
in una pagina qualunque - e ci si ritroverebbe buttati fuori senza capire
perche'. Essendo POST passano dalla verifica del gettone CSRF, come tutti gli
altri moduli.

La logica non sta qui: sta in app/services/auth.py. Qui c'e' solo il giro
delle pagine, la lettura dei moduli e la consegna dei cookie.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import (
    DURATA_RICORDAMI_SECONDI,
    PERCORSO_ACCESSO,
    percorso_di_ritorno_sicuro,
    richiedi_login,
    utente_corrente,
)
from app.models import SessionKind, User
from app.services import audit, auth, etichette, passwords, setup
from app.services.cookies import (
    COOKIE_RICORDAMI,
    COOKIE_SESSIONE,
    programma_cookie,
    programma_rimozione_cookie,
)
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.accesso")

router = APIRouter(tags=["accesso"])

# Dove si finisce dopo essere entrati, se non si stava cercando altro.
PERCORSO_INIZIALE = "/"

# Il messaggio di errore dell'accesso e' **sempre questo**, sia che il nome
# utente non esista, sia che la password sia sbagliata, sia che il profilo sia
# stato disattivato. Dire "utente inesistente" significherebbe regalare a chi
# prova a entrare la meta' del lavoro: saprebbe quali nomi cercare.
MESSAGGIO_CREDENZIALI = "Credenziali non valide."

# Lunghezza minima della password che una persona sceglie per se'. Non si
# chiedono maiuscole, cifre e simboli: le regole di composizione producono
# password brutte e prevedibili ("Password1!") e spingono a scriverle su un
# foglietto. Una frase lunga vale di piu'.
LUNGHEZZA_MINIMA_PASSWORD = 10

# Dove si manda chi arriva alla pagina di accesso di un sistema che non e'
# ancora stato configurato. Vedi la spiegazione in mostra_accesso().
PERCORSO_PRIMO_AVVIO = "/primo-avvio"


def _redirect(percorso: str) -> RedirectResponse:
    """Rimanda a un'altra pagina.

    303 e non 302: dice al browser di ripetere la richiesta con GET, che e'
    quello che serve dopo un modulo inviato con POST. Con il 302 alcuni
    browser rifarebbero un POST, e ricaricando la pagina si rieseguirebbe
    l'operazione una seconda volta.
    """
    return RedirectResponse(url=percorso, status_code=303)


# --- Entrata ----------------------------------------------------------------


@router.get("/entra")
def mostra_accesso(
    request: Request,
    dopo: str | None = None,
    utente: User | None = Depends(utente_corrente),
    db: Session = Depends(get_db),
) -> Response:
    """Mostra il modulo di accesso.

    Chi e' gia' entrato non ha niente da fare qui: lo si rimanda dentro.

    **E chi arriva su un sistema che non e' ancora stato configurato viene
    mandato alla procedura guidata.** E' il punto in cui la sessione 12 si
    innesta sul resto del programma, e sta qui e non in un middleware per una
    ragione di costo: un middleware farebbe quella domanda al database a ogni
    singola richiesta, per sempre, per un caso che capita una volta nella vita
    di un'installazione. Qui la domanda si fa soltanto quando qualcuno apre la
    pagina di accesso - che e' esattamente dove finisce chiunque provi ad
    aprire qualunque pagina di un'Aurora vuota, perche' senza sessione tutte
    le rotte protette rimandano qui.
    """
    if utente is not None:
        return _redirect(PERCORSO_INIZIALE)

    if setup.sistema_da_configurare(db):
        return _redirect(PERCORSO_PRIMO_AVVIO)

    return pagina(
        request,
        "entra.html",
        dopo=percorso_di_ritorno_sicuro(dopo) or "",
    )


@router.post("/entra")
def esegui_accesso(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    ricordami: Annotated[str | None, Form()] = None,
    dopo: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
) -> Response:
    """Verifica le credenziali e, se sono buone, apre la sessione.

    La casella "Ricordami" arriva come stringa quando e' spuntata e non arriva
    affatto quando non lo e': e' cosi' che i browser inviano le caselle di
    spunta, e per questo il campo e' dichiarato facoltativo invece che come
    booleano.
    """
    esito = auth.esegui_accesso(db, username, password, request)

    if not esito.riuscito:
        # Il commit serve comunque: il tentativo fallito e la riga di audit
        # devono restare scritti, altrimenti il blocco dopo cinque tentativi
        # non conterebbe niente.
        db.commit()

        if esito.bloccato:
            messaggio = (
                "Troppi tentativi falliti. Riprova fra "
                f"{esito.minuti_rimanenti} minuti."
            )
        else:
            messaggio = MESSAGGIO_CREDENZIALI

        # Si risponde 401 e non 200: e' il codice giusto e i programmi di
        # sorveglianza lo riconoscono. La pagina mostrata e' comunque il
        # modulo, non la pagina di errore generica.
        return pagina(
            request,
            "entra.html",
            stato=401,
            errore=messaggio,
            # Il nome utente si ripropone per non farlo riscrivere; la
            # password no, mai: non si rimanda al browser una password.
            username=username,
            dopo=percorso_di_ritorno_sicuro(dopo) or "",
        )

    utente = esito.utente
    assert utente is not None  # garantito da esito.riuscito

    gettone = auth.crea_sessione(db, utente, SessionKind.SESSIONE, request)
    programma_cookie(request, COOKIE_SESSIONE, gettone)

    if ricordami:
        gettone_lungo = auth.crea_sessione(db, utente, SessionKind.RICORDAMI, request)
        programma_cookie(
            request,
            COOKIE_RICORDAMI,
            gettone_lungo,
            durata_secondi=DURATA_RICORDAMI_SECONDI,
        )
    else:
        # Se in questo browser c'era un "ricordami" di prima, va tolto: chi
        # non spunta la casella sta dicendo di non volerlo.
        if request.cookies.get(COOKIE_RICORDAMI):
            programma_rimozione_cookie(request, COOKIE_RICORDAMI)

    db.commit()

    destinazione = percorso_di_ritorno_sicuro(dopo) or PERCORSO_INIZIALE
    return _redirect(destinazione)


# --- Uscita -----------------------------------------------------------------


@router.post("/esci")
def esci(
    request: Request,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Chiude la sessione di questo browser e toglie i cookie.

    Il "ricordami" viene revocato anche lui: chi esce si aspetta di essere
    uscito, non di rientrare da solo alla prossima visita.
    """
    sessione = getattr(request.state, "sessione", None)
    if sessione is not None:
        auth.revoca_sessione(db, sessione)

    # Il gettone lungo di **questo** browser, se c'e'.
    gettone_lungo = request.cookies.get(COOKIE_RICORDAMI, "")
    trovato = auth.trova_sessione(db, gettone_lungo, SessionKind.RICORDAMI)
    if trovato is not None:
        auth.revoca_sessione(db, trovato[0])

    audit.record(
        db,
        action=audit.ACTION_LOGOUT,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=utente.id,
        request=request,
        etichetta=etichette.nome_utente(utente),
    )
    db.commit()

    programma_rimozione_cookie(request, COOKIE_SESSIONE)
    programma_rimozione_cookie(request, COOKIE_RICORDAMI)

    logger.info("'%s' e' uscito", utente.username)
    return _redirect(PERCORSO_ACCESSO)


@router.post("/esci-ovunque")
def esci_ovunque(
    request: Request,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Chiude **tutte** le sessioni dell'utente, su qualunque dispositivo.

    Serve quando si e' lasciato Aurora aperto su un calcolatore a cui non si ha
    piu' accesso, o quando si teme che qualcuno sia entrato con le proprie
    credenziali.
    """
    revocate = auth.revoca_sessioni_utente(db, utente.id)

    audit.record(
        db,
        action=audit.ACTION_LOGOUT_ALL,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=utente.id,
        request=request,
        etichetta=etichette.nome_utente(utente),
        new_value={"sessioni_revocate": revocate},
    )
    db.commit()

    programma_rimozione_cookie(request, COOKIE_SESSIONE)
    programma_rimozione_cookie(request, COOKIE_RICORDAMI)

    logger.info("'%s' e' uscito da tutti i dispositivi (%s)", utente.username, revocate)
    return _redirect(PERCORSO_ACCESSO)


# --- Cambio password --------------------------------------------------------


@router.get("/cambio-password")
def mostra_cambio_password(
    request: Request, utente: User = Depends(richiedi_login)
) -> Response:
    """Mostra il modulo per cambiare la propria password.

    La stessa pagina serve i due casi: il cambio volontario e quello
    obbligatorio del primo accesso. Cambia solo il testo di spiegazione, che
    dipende da must_change_password.
    """
    return pagina(
        request,
        "cambio_password.html",
        obbligatorio=utente.must_change_password,
    )


@router.post("/cambio-password")
def esegui_cambio_password(
    request: Request,
    password_attuale: Annotated[str, Form()],
    password_nuova: Annotated[str, Form()],
    password_ripetuta: Annotated[str, Form()],
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Verifica la password attuale e imposta quella nuova.

    Chiedere la password attuale non e' una formalita': senza, chiunque
    trovasse un calcolatore lasciato aperto potrebbe cambiare la password e
    prendersi il profilo. E' anche il motivo per cui questa pagina resta
    raggiungibile a chi deve fare il cambio obbligatorio ma non gliela salta:
    la password temporanea che ha ricevuto e' pur sempre la sua password
    attuale, e deve saperla.

    Al cambio riuscito vengono revocate tutte le altre sessioni dell'utente e
    resta aperta solo quella da cui si sta facendo il cambio.
    """
    def rimostra(messaggio: str) -> Response:
        """Ripropone il modulo con l'errore. Nessuna password torna indietro."""
        return pagina(
            request,
            "cambio_password.html",
            stato=400,
            errore=messaggio,
            obbligatorio=utente.must_change_password,
        )

    if not passwords.verify_password(utente.password_hash, password_attuale):
        logger.info(
            "Cambio password rifiutato per '%s': password attuale sbagliata",
            utente.username,
        )
        return rimostra("La password attuale non e' corretta.")

    if password_nuova != password_ripetuta:
        return rimostra("Le due password nuove non coincidono.")

    if len(password_nuova) < LUNGHEZZA_MINIMA_PASSWORD:
        return rimostra(
            f"La password nuova deve essere lunga almeno "
            f"{LUNGHEZZA_MINIMA_PASSWORD} caratteri."
        )

    if password_nuova == password_attuale:
        return rimostra("La password nuova deve essere diversa da quella attuale.")

    sessione = getattr(request.state, "sessione", None)
    auth.cambia_password(
        db,
        utente,
        password_nuova,
        sessione_da_risparmiare=sessione.id if sessione is not None else None,
        request=request,
    )
    db.commit()

    return _redirect(PERCORSO_INIZIALE + "?password_cambiata=1")
