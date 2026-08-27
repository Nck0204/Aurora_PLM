"""La configurazione guidata del primo avvio.

    GET  /primo-avvio                  l'elenco dei sei passi
    GET  /primo-avvio/{passo}          un passo, con la sua spiegazione
    POST /primo-avvio/{passo}/verifica prova il passo e risponde subito
    POST /primo-avvio/{passo}          esegue il passo (crea, salva, scrive)

**Chi puo' aprire queste pagine.** La regola sta tutta nella dipendenza
`chi_configura()` qui sotto, ed e' in due tempi: finche' il sistema e' da
configurare - nessun amministratore e nessun documento - chiunque, perche' non
c'e' nessuno a cui chiedere il permesso; appena esiste un amministratore, solo
lui, e la domanda la fa `permissions.puo()` come dappertutto (D-051).

**Perche' i passi hanno tutti la stessa forma.** Ogni passo ha una pagina che
spiega, un pulsante «Verifica» che prova e risponde senza cambiare niente, e -
quando c'e' qualcosa da fare - un pulsante che lo fa. La separazione fra
«verifica» e «esegui» e' quella che rende la procedura tranquilla da usare: si
puo' premere Verifica quante volte si vuole senza paura di rompere niente, ed
e' esattamente quello che serve a chi sta configurando un server aziendale la
prima volta.

**La procedura si puo' interrompere e riprendere** perche' il suo stato non e'
scritto da nessuna parte: si ricava dal database ogni volta (vedi
`app/services/setup.py`). Chiudere il browser e tornare domani vuol dire
ritrovarsi allo stesso punto.

**Senza JavaScript funziona lo stesso.** I pulsanti sono normali moduli POST:
la risposta e' la pagina intera, con l'esito in cima. E' la regola D-036
applicata alla pagina in cui e' piu' importante di tutte - se il primo avvio
avesse bisogno di uno script, un server appena installato con un browser
severo non si configurerebbe affatto.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import ENV_FILE, settings
from app.db import get_db
from app.dependencies import RichiedeAutenticazione, utente_corrente
from app.models import SessionKind, User
# La lunghezza minima della password e' **quella dell'accesso normale**,
# importata da li' invece che riscritta: due costanti con lo stesso nome e un
# valore diverso sono la ricetta perche' fra un anno il primo avvio ne pretenda
# dodici e il cambio password ne accetti dieci, senza che nessuno sappia dire
# quale delle due e' la regola.
from app.routers.auth import LUNGHEZZA_MINIMA_PASSWORD
from app.services import audit, auth, permissions, setup, users
from app.services.cookies import COOKIE_SESSIONE, programma_cookie
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.primo_avvio")

router = APIRouter(prefix="/primo-avvio", tags=["primo avvio"])

# Quello che si risponde a chi apre la procedura su un sistema gia' in uso
# senza esserne l'amministratore. Non dice "il sistema e' gia' configurato",
# che sarebbe un'informazione regalata a un estraneo: dice che serve entrare.
MESSAGGIO_GIA_CONFIGURATO = (
    "Aurora e' gia' configurata. Per rivedere queste impostazioni bisogna "
    "entrare con un profilo che possa amministrare il programma."
)


def chi_configura(
    request: Request,
    utente: User | None = Depends(utente_corrente),
    db: Session = Depends(get_db),
) -> User | None:
    """Chi sta facendo la configurazione: una persona, oppure nessuno.

    **Restituisce None quando il sistema e' ancora da configurare**, ed e' il
    caso normale del primo avvio: non c'e' nessun amministratore, quindi non
    c'e' nessuno da riconoscere e la procedura si apre a chi e' seduto davanti
    al server.

    Appena un amministratore esiste, la porta si chiude: chi non e' entrato
    viene mandato all'accesso, chi e' entrato senza poter amministrare riceve
    un 403. La domanda "puo' amministrare?" la fa `permissions.puo()`, che e'
    l'unico posto in cui i permessi di Aurora si decidono.
    """
    if setup.sistema_da_configurare(db):
        return None

    if utente is None:
        raise RichiedeAutenticazione(destinazione=request.url.path)

    if not permissions.puo(
        db, utente, permissions.Azione.AMMINISTRARE, permissions.AMMINISTRAZIONE
    ):
        logger.warning(
            "'%s' ha provato ad aprire la configurazione guidata", utente.username
        )
        raise HTTPException(status_code=403, detail=MESSAGGIO_GIA_CONFIGURATO)

    return utente


def _passo_o_404(chiave: str) -> tuple[int, str, str, bool]:
    """Il passo con quella chiave. 404 se non esiste.

    Si risponde 404 e non 400 perche' l'indirizzo di un passo che non esiste
    e' un indirizzo che non esiste: e' la stessa risposta di qualunque altra
    pagina scritta male.
    """
    for numero, (nome, titolo, perche, rimandabile) in enumerate(
        setup.PASSI, start=1
    ):
        if nome == chiave:
            return numero, titolo, perche, rimandabile

    raise HTTPException(status_code=404, detail="Questo passo non esiste.")


def _pagina_passo(
    request: Request,
    db: Session,
    chiave: str,
    *,
    utente: User | None,
    esito: setup.Verifica | None = None,
    fatto: str = "",
    errore: str | None = None,
    valori: dict[str, str] | None = None,
    stato: int = 200,
) -> Response:
    """Compone la pagina di un passo.

    Sta in una funzione sola perche' i momenti in cui quella pagina si disegna
    sono quattro - lettura, verifica, modulo rifiutato, azione eseguita - e
    comporla quattro volte vorrebbe dire ricordarsi quattro volte di passare
    l'elenco dei passi.
    """
    numero, titolo, perche, rimandabile = _passo_o_404(chiave)
    passi = setup.stato_dei_passi(db)

    scritti = valori or {}
    proposto = ""
    if chiave == setup.PASSO_CREATORE:
        proposto = setup.username_proposto(
            db, scritti.get("nome", ""), scritti.get("cognome", "")
        )

    return pagina(
        request,
        "primo_avvio/passo.html",
        stato=stato,
        errore=errore,
        passi=passi,
        passo_corrente=chiave,
        numero=numero,
        titolo_passo=titolo,
        perche=perche,
        rimandabile=rimandabile,
        esito=esito,
        fatto=fatto,
        valori=scritti,
        username_proposto=proposto,
        lunghezza_minima=LUNGHEZZA_MINIMA_PASSWORD,
        percorso_archivio=str(settings.STORAGE_PATH),
        file_env=ENV_FILE,
        gia_entrato=utente is not None,
        prossimo=_prossimo(passi, chiave),
        completata=setup.procedura_completata(db),
    )


def _prossimo(passi: list[setup.Passo], chiave: str) -> str:
    """La chiave del passo successivo, o vuoto se questo era l'ultimo."""
    chiavi = [passo.chiave for passo in passi]
    posizione = chiavi.index(chiave) if chiave in chiavi else -1
    if posizione < 0 or posizione + 1 >= len(chiavi):
        return ""
    return chiavi[posizione + 1]


# ---------------------------------------------------------------------------
#  L'elenco dei passi
# ---------------------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    utente: User | None = Depends(chi_configura),
    db: Session = Depends(get_db),
) -> Response:
    """I sei passi, con il segno su quelli gia' fatti."""
    passi = setup.stato_dei_passi(db)

    return pagina(
        request,
        "primo_avvio/elenco.html",
        passi=passi,
        completata=all(
            passo.fatto for passo in passi if passo.chiave != setup.PASSO_POSTA
        ),
        gia_entrato=utente is not None,
        # Il primo passo non ancora fatto: e' quello che il pulsante grande
        # propone di aprire, cosi' chi riprende la procedura domani non deve
        # cercarsi il punto in cui era rimasto.
        da_fare=next(
            (passo.chiave for passo in passi if not passo.fatto),
            "",
        ),
    )


@router.get("/{chiave}")
def mostra_passo(
    request: Request,
    chiave: str,
    utente: User | None = Depends(chi_configura),
    db: Session = Depends(get_db),
) -> Response:
    """Un passo: che cosa fa, perche', e i pulsanti per farlo."""
    return _pagina_passo(request, db, chiave, utente=utente)


# ---------------------------------------------------------------------------
#  La verifica: prova e non cambia niente
# ---------------------------------------------------------------------------


@router.post("/{chiave}/verifica")
def verifica_passo(
    request: Request,
    chiave: str,
    percorso: Annotated[str, Form()] = "",
    utente: User | None = Depends(chi_configura),
    db: Session = Depends(get_db),
) -> Response:
    """Prova il passo e risponde con l'esito. Non scrive niente.

    L'unico parametro che serve e' il percorso dell'archivio, e serve per la
    stessa ragione per cui il pulsante VERIFICA della configurazione posta
    prova il valore **scritto nel modulo**: si vuole sapere se quella cartella
    va bene *prima* di salvarla.
    """
    esito = setup.prova_passo(db, chiave, percorso=percorso)

    return _pagina_passo(
        request,
        db,
        chiave,
        utente=utente,
        esito=esito,
        valori={"percorso": percorso} if percorso else None,
    )


# ---------------------------------------------------------------------------
#  L'esecuzione: qui si scrive
# ---------------------------------------------------------------------------


@router.post("/{chiave}")
async def esegui_passo(
    request: Request,
    chiave: str,
    utente: User | None = Depends(chi_configura),
    db: Session = Depends(get_db),
) -> Response:
    """Esegue il passo: crea l'utente, salva il percorso, crea i dati iniziali.

    I quattro passi che fanno qualcosa hanno bisogno di cose diverse dal
    modulo, e per questo la lettura del modulo e' qui invece che nella firma:
    dichiarare in un colpo solo i campi di tutti e quattro produrrebbe una
    firma di quindici parametri quasi sempre vuoti.
    """
    modulo = await request.form()

    if chiave == setup.PASSO_CREATORE:
        return _crea_il_creatore(request, db, modulo)

    if chiave == setup.PASSO_ARCHIVIO:
        return _salva_l_archivio(request, db, modulo, utente=utente)

    if chiave == setup.PASSO_CLASSIFICAZIONI:
        return _crea_le_classificazioni(request, db, utente=utente)

    if chiave == setup.PASSO_FASI:
        return _crea_le_fasi(request, db, utente=utente)

    if chiave == setup.PASSO_POSTA:
        # La posta non si configura da qui: si configura nella pagina che
        # esiste gia' dalla sessione 11, con il pulsante VERIFICA su ogni
        # campo. Rifarla qui vorrebbe dire due moduli che scrivono gli stessi
        # otto parametri.
        return RedirectResponse(url="/posta/configurazione", status_code=303)

    return _pagina_passo(
        request,
        db,
        chiave,
        utente=utente,
        errore="Questo passo non ha niente da eseguire.",
        stato=400,
    )


def _crea_il_creatore(request: Request, db: Session, modulo) -> Response:
    """Il passo 2: crea la prima persona e la fa entrare subito.

    **La si fa entrare subito**, ed e' la parte che rende la procedura
    continua: senza, chi ha appena creato il proprio profilo si troverebbe
    davanti la pagina di accesso, dovrebbe riscrivere quello che ha appena
    scritto e tornare qui a mano. La sessione si apre con la stessa funzione
    dell'accesso normale - `auth.crea_sessione()` - e il cookie parte come
    parte sempre.

    **Si ricontrolla che il sistema sia da configurare** anche se la dipendenza
    lo ha gia' fatto: fra i due momenti c'e' una richiesta HTTP, e due persone
    che aprono la procedura insieme non devono poter creare due amministratori.
    """
    if not setup.sistema_da_configurare(db):
        raise HTTPException(status_code=403, detail=MESSAGGIO_GIA_CONFIGURATO)

    nome = str(modulo.get("nome") or "").strip()
    cognome = str(modulo.get("cognome") or "").strip()
    email = str(modulo.get("email") or "").strip()
    username = str(modulo.get("username") or "").strip()
    password = str(modulo.get("password") or "")
    ripetuta = str(modulo.get("password_ripetuta") or "")

    scritti = {
        "nome": nome,
        "cognome": cognome,
        "email": email,
        "username": username,
    }

    def rifiuta(messaggio: str) -> Response:
        return _pagina_passo(
            request,
            db,
            setup.PASSO_CREATORE,
            utente=None,
            errore=messaggio,
            valori=scritti,
            stato=400,
        )

    if not nome or not cognome:
        return rifiuta("Nome e cognome sono obbligatori.")

    if "@" not in email or "." not in email.split("@")[-1]:
        return rifiuta(
            "L'indirizzo di posta non sembra un indirizzo. Serve per ritrovare "
            "questa persona e per le comunicazioni del programma."
        )

    if users.email_gia_usata(db, email):
        return rifiuta("Questo indirizzo di posta e' gia' di un'altra persona.")

    if not username:
        username = users.proponi_username(db, nome, cognome)

    if len(password) < LUNGHEZZA_MINIMA_PASSWORD:
        return rifiuta(
            f"La password deve essere lunga almeno "
            f"{LUNGHEZZA_MINIMA_PASSWORD} caratteri. Una frase di quattro "
            "parole e' piu' facile da ricordare e piu' difficile da indovinare "
            "di una parola con dentro dei numeri."
        )

    if password != ripetuta:
        return rifiuta("Le due password scritte non coincidono.")

    creatore = users.crea_primo_creatore(
        db,
        first_name=nome,
        last_name=cognome,
        email=email,
        username=username,
        password=password,
        request=request,
    )

    # Una sessione normale, non un «ricordami»: chi sta configurando un server
    # e' seduto davanti a quella macchina adesso, e una sessione lunga lasciata
    # aperta su un server e' un rischio senza nessun vantaggio.
    gettone = auth.crea_sessione(db, creatore, SessionKind.SESSIONE, request)
    audit.record(
        db,
        action=audit.ACTION_LOGIN,
        entity_type=audit.ENTITY_USERS,
        entity_id=creatore.id,
        user_id=creatore.id,
        request=request,
        description=(
            "Primo accesso, subito dopo la creazione del profilo dalla "
            "configurazione guidata."
        ),
    )
    db.commit()

    programma_cookie(request, COOKIE_SESSIONE, gettone)

    logger.info(
        "Configurazione guidata: creato il primo creatore '%s'", creatore.username
    )
    return RedirectResponse(
        url=f"/primo-avvio/{setup.PASSO_ARCHIVIO}?creato=1", status_code=303
    )


def _salva_l_archivio(
    request: Request, db: Session, modulo, *, utente: User | None
) -> Response:
    """Il passo 3: verifica la cartella e la scrive nel file `.env`.

    **Si verifica prima di salvare.** E' l'unico passo in cui l'ordine conta
    davvero: un percorso sbagliato scritto nel `.env` diventa un programma che
    al riavvio non trova piu' l'archivio, e chi sta configurando non ha ancora
    idea di dove andare a guardare.
    """
    percorso = str(modulo.get("percorso") or "").strip()
    esito = setup.prova_archivio(percorso)

    if not esito.a_posto:
        return _pagina_passo(
            request,
            db,
            setup.PASSO_ARCHIVIO,
            utente=utente,
            esito=esito,
            valori={"percorso": percorso},
            stato=400,
        )

    cartella = setup.salva_archivio(percorso)

    return RedirectResponse(
        url=f"/primo-avvio/{setup.PASSO_CLASSIFICAZIONI}?archivio={cartella.name}",
        status_code=303,
    )


def _crea_le_classificazioni(
    request: Request, db: Session, *, utente: User | None
) -> Response:
    """Il passo 4: crea le classificazioni di partenza e la loro griglia."""
    autore = _autore_o_403(db, utente)

    create = setup.crea_classificazioni_di_partenza(db, autore=autore, request=request)
    db.commit()

    if not create:
        return _pagina_passo(
            request,
            db,
            setup.PASSO_CLASSIFICAZIONI,
            utente=utente,
            esito=setup.prova_passo(db, setup.PASSO_CLASSIFICAZIONI),
            fatto="C'erano gia' tutte: non e' stato creato niente di nuovo.",
        )

    return RedirectResponse(
        url=f"/primo-avvio/{setup.PASSO_FASI}?create={len(create)}",
        status_code=303,
    )


def _crea_le_fasi(request: Request, db: Session, *, utente: User | None) -> Response:
    """Il passo 5: crea il percorso di partenza con le sue sei fasi."""
    autore = _autore_o_403(db, utente)

    modello = setup.crea_percorso_di_partenza(db, autore=autore, request=request)
    db.commit()

    if modello is None:
        return _pagina_passo(
            request,
            db,
            setup.PASSO_FASI,
            utente=utente,
            esito=setup.prova_passo(db, setup.PASSO_FASI),
            fatto="C'era gia': non e' stato creato niente di nuovo.",
        )

    return RedirectResponse(
        url=f"/primo-avvio/{setup.PASSO_POSTA}?modello={modello.name}",
        status_code=303,
    )


def _autore_o_403(db: Session, utente: User | None) -> User:
    """Chi risulta autore delle righe di registro dei passi 4 e 5.

    **Deve esserci una persona.** I passi che creano classificazioni e fasi
    passano dalle funzioni dell'interfaccia, che scrivono nel registro chi ha
    fatto la cosa: senza una persona quelle righe sarebbero anonime, e un
    registro con dentro operazioni senza autore quando un autore c'era e' un
    registro meno affidabile.

    Il caso non capita nel giro normale - il passo 2 viene prima e apre la
    sessione - ma capita a chi arriva qui con un indirizzo scritto a mano
    prima di aver creato il proprio profilo, e la risposta giusta e' mandarlo
    a farlo.
    """
    if utente is not None:
        return utente

    raise HTTPException(
        status_code=403,
        detail=(
            "Prima di questo passo va creata la persona che amministrera' "
            "Aurora: e' il passo 2 della procedura."
        ),
    )
