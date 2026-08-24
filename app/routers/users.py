"""Le pagine della gestione utenti. Riservate al ruolo creatore.

    GET  /utenti                       elenco degli utenti, con stato e ruolo
    GET  /utenti/nuovo                 modulo di creazione
    POST /utenti/nuovo                 crea l'utente e mostra la sua password
    POST /utenti/{id}/reimposta        assegna una password nuova
    POST /utenti/{id}/disattiva        toglie l'utente dal servizio
    POST /utenti/{id}/riattiva         lo rimette in servizio

**Non c'e' nessuna rotta per cancellare un utente, e non va aggiunta.** E' la
regola 5 di CLAUDE.md: le firme sui documenti e le righe del registro di una
persona restano leggibili anche dieci anni dopo che ha lasciato l'azienda. Chi
non deve piu' entrare si disattiva.

Il ruolo si controlla in un punto solo, la dipendenza richiedi_creatore
dichiarata sul router: vale per tutte le rotte qui dentro, comprese quelle che
verranno aggiunte in seguito.

La password generata compare **una volta sola**, nella pagina che segue la
creazione o la riassegnazione. Non viene rimostrata, non finisce in nessun
indirizzo, non finisce nel registro. Se si chiude quella pagina senza averla
annotata, se ne assegna un'altra: e' l'unica cosa che si puo' fare, e va bene
cosi'.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import GlobalRole, User
from app.services import auth, users
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.utenti")

# La dipendenza sta sul router e non sulle singole rotte: cosi' una rotta
# aggiunta domani da qualcun altro nasce gia' protetta.
router = APIRouter(
    prefix="/utenti",
    tags=["utenti"],
    dependencies=[Depends(richiedi_creatore)],
)

MESSAGGIO_UTENTE_INESISTENTE = "L'utente richiesto non esiste."


def _utente_o_404(db: Session, user_id: uuid.UUID) -> User:
    """Cerca l'utente e, se non c'e', ferma tutto con un 404 in italiano."""
    utente = users.trova_utente(db, user_id)
    if utente is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_UTENTE_INESISTENTE)
    return utente


# --- Elenco -----------------------------------------------------------------


@router.get("")
def elenco(request: Request, db: Session = Depends(get_db)) -> Response:
    """Elenco di tutti gli utenti, con stato, ruolo e sessioni aperte.

    Qui i disattivati si vedono: e' la pagina in cui si va per riattivarne uno.
    """
    elencati = users.elenco_utenti(db)

    # Quante sessioni aperte ha ciascuno: e' l'unico modo, dall'interfaccia, di
    # accorgersi che una persona e' entrata da qualche parte e non e' uscita.
    sessioni = {u.id: auth.conta_sessioni_attive(db, u.id) for u in elencati}

    return pagina(request, "utenti/elenco.html", utenti=elencati, sessioni=sessioni)


# --- Creazione --------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(request: Request) -> Response:
    """Mostra il modulo di creazione di un utente."""
    return pagina(request, "utenti/nuovo.html", ruoli=list(GlobalRole))


@router.post("/nuovo")
def crea_nuovo(
    request: Request,
    first_name: Annotated[str, Form()],
    last_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    ruolo: Annotated[str, Form()] = GlobalRole.UTENTE.value,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Crea l'utente e mostra la sua password, una volta sola.

    Lo username non arriva dal modulo: lo propone il programma a partire da
    nome e cognome (nome.cognome, minuscolo, senza accenti, con un numero
    progressivo in caso di omonimia). E' voluto: se lo scrivesse la persona
    che crea l'utente, dopo sei mesi ci sarebbero tre convenzioni diverse
    convissute nella stessa tabella.
    """

    def rimostra(messaggio: str) -> Response:
        """Ripropone il modulo con l'errore e i valori gia' scritti."""
        return pagina(
            request,
            "utenti/nuovo.html",
            stato=400,
            errore=messaggio,
            ruoli=list(GlobalRole),
            first_name=first_name,
            last_name=last_name,
            email=email,
            ruolo=ruolo,
        )

    if not first_name.strip() or not last_name.strip():
        return rimostra("Nome e cognome sono obbligatori.")

    if not email.strip():
        return rimostra("L'indirizzo di posta e' obbligatorio.")

    if users.email_gia_usata(db, email):
        return rimostra("Questo indirizzo di posta e' gia' di un altro utente.")

    try:
        ruolo_scelto = GlobalRole(ruolo)
    except ValueError:
        # Puo' succedere solo se qualcuno costruisce la richiesta a mano: il
        # modulo propone un elenco chiuso.
        return rimostra("Il ruolo indicato non esiste.")

    username = users.proponi_username(db, first_name, last_name)

    utente, password = users.crea_utente(
        db,
        first_name=first_name,
        last_name=last_name,
        email=email,
        username=username,
        ruolo=ruolo_scelto,
        creato_da=creatore,
        request=request,
    )
    db.commit()

    return pagina(
        request,
        "utenti/password.html",
        utente_creato=utente,
        password=password,
        appena_creato=True,
    )


# --- Password, disattivazione, riattivazione --------------------------------


@router.post("/{user_id}/reimposta")
def reimposta(
    request: Request,
    user_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Assegna una password temporanea nuova e butta fuori l'utente da ovunque.

    Si usa quando una persona ha perso la password. Non esiste nessun modo di
    recuperare quella vecchia: l'impronta argon2 non e' reversibile, ed e'
    esattamente la ragione per cui la si usa.
    """
    utente = _utente_o_404(db, user_id)

    password = users.reimposta_password(db, utente, creatore, request)
    db.commit()

    return pagina(
        request,
        "utenti/password.html",
        utente_creato=utente,
        password=password,
        appena_creato=False,
    )


@router.post("/{user_id}/disattiva")
def disattiva(
    request: Request,
    user_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie un utente dal servizio e chiude tutte le sue sessioni.

    Non ci si puo' disattivare da soli. Non e' una regola morale: se l'unico
    creatore si disattivasse, non resterebbe nessuno che possa riattivarlo e
    l'unico modo di rientrare sarebbe un intervento a mano sul database.
    """
    utente = _utente_o_404(db, user_id)

    if utente.id == creatore.id:
        return _elenco_con_errore(
            request, db, "Non puoi disattivare il tuo stesso profilo."
        )

    revocate = users.disattiva(db, utente, creatore, request)
    db.commit()

    logger.info(
        "'%s' disattivato: %s sessioni chiuse", utente.username, revocate
    )
    return _redirect_elenco()


@router.post("/{user_id}/riattiva")
def riattiva(
    request: Request,
    user_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette in servizio un utente disattivato."""
    utente = _utente_o_404(db, user_id)

    users.riattiva(db, utente, creatore, request)
    db.commit()

    return _redirect_elenco()


# --- Aiuti ------------------------------------------------------------------


def _redirect_elenco() -> Response:
    """Torna all'elenco. 303 perche' si arriva sempre da un POST."""
    return RedirectResponse(url="/utenti", status_code=303)


def _elenco_con_errore(request: Request, db: Session, messaggio: str) -> Response:
    """Rimostra l'elenco con un messaggio di errore in cima."""
    elencati = users.elenco_utenti(db)
    sessioni = {u.id: auth.conta_sessioni_attive(db, u.id) for u in elencati}

    return pagina(
        request,
        "utenti/elenco.html",
        stato=400,
        errore=messaggio,
        utenti=elencati,
        sessioni=sessioni,
    )
