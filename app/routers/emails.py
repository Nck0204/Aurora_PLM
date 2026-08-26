"""Le pagine della posta archiviata.

    GET  /posta                            elenco con ricerca, filtri, date
    POST /posta/elabora                    legge la cartella e archivia
    GET  /posta/quarantena                 i messaggi non attribuiti (creatore)
    GET  /posta/motivi                     i motivi ammessi (creatore)
    POST /posta/motivi                     crea o corregge un motivo
    POST /posta/motivi/{id}/proponibilita  mette o toglie dai proponibili
    GET  /posta/{id}                       la scheda di un messaggio
    GET  /posta/{id}/assegna               il modulo di assegnazione
    POST /posta/{id}/assegna               esegue l'assegnazione
    GET  /posta/{id}/scarica               il file .eml originale
    GET  /posta/{id}/allegati/{aid}        un allegato

**Chi vede che cosa lo decide permissions.puo()**, e in questo file non c'e'
nemmeno una riga che lo stabilisca. Un messaggio e' trattato come un documento
di classificazione "Corrispondenza" nel progetto della versione a cui e'
attaccato (D-069): l'elenco passa da `filtro_email()`, la scheda da
`pretendi()`, e le due strade dicono per forza la stessa cosa perche' sono la
stessa regola scritta due volte, una in Python e una in SQL.

**La quarantena e i motivi sono riservati al creatore.** Non e' una scelta di
comodo: un messaggio in quarantena non e' attaccato a nessuna versione, quindi
non esiste nessun progetto su cui la matrice possa dire qualcosa, e l'unica
regola scrivibile e' "lo vede chi amministra Aurora". Il lucchetto e' la
dipendenza dichiarata sulla rotta.

**L'elenco e' una pagina sola per due usi**: tutta la posta che si puo'
vedere, e quella di un progetto (`?progetto={id}`), che e' la "sezione Posta"
di cui parla il punto 1 della sessione. Due pagine separate avrebbero voluto
dire due interrogazioni da tenere allineate e, prima o poi, due elenchi che
dicono cose diverse - e' la stessa scelta dell'elenco dei documenti.
"""

import logging
import math
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import EmailAssignmentState, EmailMessage, Project, User
from app.services import (
    documents,
    email_reasons,
    emails,
    mail_source,
    permissions,
    projects,
    storage,
)
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.posta")

router = APIRouter(prefix="/posta", tags=["posta"])

# I messaggi dei dinieghi stanno in permissions.py, perche' quello del 404
# deve essere identico alla parola per quello di un messaggio che davvero non
# esiste: se ogni rotta se lo scrivesse per conto suo, la differenza fra due
# risposte finirebbe per dire che il messaggio c'e'.
MESSAGGIO_INESISTENTE = permissions.MESSAGGI_INESISTENTE[EmailMessage]
MESSAGGIO_PROGETTO_INESISTENTE = permissions.MESSAGGI_INESISTENTE[Project]

# Quante versioni di prodotto propone il modulo di assegnazione. Venti stanno
# in una tendina senza doverla scorrere per mezzo minuto; chi non trova quella
# che cerca scrive due lettere del codice nella casella e l'elenco si stringe.
VERSIONI_PROPOSTE = 20


# ---------------------------------------------------------------------------
#  Aiuti comuni
# ---------------------------------------------------------------------------


def _intero(valore: str | None, predefinito: int) -> int:
    """Legge un numero da un parametro dell'indirizzo, senza fidarsene."""
    try:
        return int(valore) if valore is not None else predefinito
    except ValueError:
        return predefinito


def _messaggio_o_errore(
    db: Session, message_id: uuid.UUID, utente: User, azione=None
) -> EmailMessage:
    """Cerca il messaggio e pretende il permesso di farci quello che si vuole.

    Chi non lo puo' vedere riceve un 404 con lo stesso messaggio di uno che non
    esiste - compresi tutti i messaggi in quarantena, che per chi non e'
    creatore e' come se non ci fossero. Chi lo vede ma non puo' fare quella
    operazione riceve un 403 che gliela spiega. La differenza la fa
    `permissions.pretendi()`, qui non c'e' nessuna regola scritta.
    """
    messaggio = emails.trova_messaggio(db, message_id)
    if messaggio is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_INESISTENTE)

    permissions.pretendi(
        db, utente, azione or permissions.Azione.VEDERE, messaggio
    )
    return messaggio


def _progetto_o_errore(db: Session, valore: str, utente: User) -> Project:
    """Cerca il progetto del filtro e verifica che lo si possa vedere."""
    try:
        progetto = projects.trova_progetto(db, uuid.UUID(valore))
    except (ValueError, AttributeError):
        progetto = None

    if progetto is None:
        raise HTTPException(
            status_code=404, detail=MESSAGGIO_PROGETTO_INESISTENTE
        )

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, progetto)
    return progetto


def _disposizione(nome_file: str) -> str:
    """L'intestazione che dice al browser di salvare il file con quel nome.

    E' la stessa di app/routers/documents.py, e per la stessa ragione: i nomi
    degli allegati hanno accenti, e un'intestazione HTTP no. Se ne scrivono
    due versioni, una ripulita che capiscono tutti e una in UTF-8 percentuale
    che i browser preferiscono quando c'e'.
    """
    ripulito = nome_file.encode("ascii", "ignore").decode("ascii")
    ripulito = ripulito.replace('"', "").replace("\\", "").strip()
    if not ripulito:
        ripulito = "allegato"

    return (
        f'attachment; filename="{ripulito}"; '
        f"filename*=UTF-8''{quote(nome_file, safe='')}"
    )


def _consegna(impronta: str, *, nome_file: str, mime_type: str) -> Response:
    """Manda al browser un file dell'archivio, un pezzo per volta.

    Il file non passa mai per la memoria del server: un `.eml` con dentro un
    firmware da 300 MB uscirebbe altrimenti caricandolo tutto.
    """
    try:
        percorso = storage.percorso_di(impronta)
    except ValueError as errore:
        logger.error("Impronta illeggibile: %s", impronta)
        raise HTTPException(
            status_code=500,
            detail="Il file non e' leggibile dall'archivio.",
        ) from errore

    if not percorso.is_file():
        logger.error("Il file %s manca dall'archivio", impronta)
        raise HTTPException(
            status_code=404,
            detail=(
                "Il file non si trova nell'archivio. Segnala il problema a "
                "chi amministra Aurora."
            ),
        )

    return FileResponse(
        path=percorso,
        media_type=mime_type,
        headers={"content-disposition": _disposizione(nome_file)},
    )


# ---------------------------------------------------------------------------
#  Elenco
# ---------------------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    q: str = "",
    progetto: str = "",
    stato: str = "",
    dal: str = "",
    al: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """I messaggi che questa persona puo' vedere, dal piu' recente.

    Il numero di pagina si legge dai parametri della richiesta e non dalla
    firma: nell'indirizzo si chiama "pagina", che in questo file e' gia' il
    nome della funzione che compone le pagine.
    """
    pagina_numero = max(1, _intero(request.query_params.get("pagina"), 1))

    progetto_scelto: Project | None = None
    if progetto:
        progetto_scelto = _progetto_o_errore(db, progetto, utente)

    dal_giorno = emails.data_scritta(dal)
    al_giorno = emails.data_scritta(al)

    trovati, totale = emails.cerca_messaggi(
        db,
        utente,
        project_id=progetto_scelto.id if progetto_scelto else None,
        stato=stato or None,
        testo=q or None,
        dal=dal_giorno,
        al=al_giorno,
        pagina=pagina_numero,
        per_pagina=settings.PAGE_SIZE,
    )

    parametri = {
        nome: valore
        for nome, valore in (
            ("q", q),
            ("progetto", progetto),
            ("stato", stato),
            ("dal", dal),
            ("al", al),
        )
        if valore
    }

    return pagina(
        request,
        "posta/elenco.html",
        messaggi=trovati,
        totale=totale,
        q=q,
        progetto_scelto=progetto_scelto,
        stato_scelto=stato,
        dal=dal,
        al=al,
        filtri=emails.filtri_elenco(stato),
        parametri=parametri,
        pagina_corrente=pagina_numero,
        totale_pagine=(
            math.ceil(totale / settings.PAGE_SIZE) if totale else 0
        ),
        come_attribuito=emails.come_attribuito,
        nome_stato=emails.nome_stato,
    )


# ---------------------------------------------------------------------------
#  L'acquisizione
# ---------------------------------------------------------------------------


@router.post("/elabora")
def elabora(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Legge la cartella della posta e archivia quello che trova.

    E' un POST e non un GET perche' cambia qualcosa nel programma: un
    collegamento lo puo' far scattare chiunque, anche una pagina ostile
    (docs/GUIDA_STILE.md, sezione 5).

    **La rotta non commette niente e non annulla niente**, ed e' l'unica di
    Aurora fatta cosi'. Ogni messaggio ha la sua transazione dentro
    `emails.acquisisci()`, perche' un messaggio storto non deve portarsi via
    quelli gia' archiviati (D-070).

    Dalla sessione 11 la stessa funzione la chiamera' un lavoro pianificato,
    senza nessuna persona davanti: e' il motivo per cui `acquisisci()` prende
    l'autore come argomento facoltativo invece di andarselo a cercare.
    """
    try:
        fonte = mail_source.fonte_configurata()
        riepilogo = emails.acquisisci(
            db, fonte, autore=creatore, request=request
        )
    except mail_source.FonteNonDisponibile as errore:
        logger.error("Acquisizione non avviata: %s", errore)
        return RedirectResponse(
            url=f"/posta?problema={quote(str(errore), safe='')}",
            status_code=303,
        )

    # I numeri viaggiano nell'indirizzo e non in una variabile di sessione:
    # cosi' la pagina si puo' ricaricare senza rispedire il modulo, e chi
    # copia l'indirizzo copia anche l'esito che sta guardando.
    parametri = (
        f"letti={riepilogo.letti}"
        f"&archiviati={riepilogo.archiviati}"
        f"&quarantena={riepilogo.in_quarantena}"
        f"&gia={riepilogo.gia_presenti}"
        f"&errori={riepilogo.errori}"
    )
    return RedirectResponse(url=f"/posta?{parametri}", status_code=303)


# ---------------------------------------------------------------------------
#  Quarantena
# ---------------------------------------------------------------------------


@router.get("/quarantena")
def quarantena(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """I messaggi che aspettano di essere assegnati a mano.

    Riservata al creatore, e la spiegazione sta in cima al file: un messaggio
    non attribuito non appartiene a nessun progetto, quindi non c'e' nessuna
    matrice da consultare.
    """
    pagina_numero = max(1, _intero(request.query_params.get("pagina"), 1))

    messaggi, totale = emails.in_quarantena(
        db, pagina=pagina_numero, per_pagina=settings.PAGE_SIZE
    )

    return pagina(
        request,
        "posta/quarantena.html",
        messaggi=messaggi,
        totale=totale,
        pagina_corrente=pagina_numero,
        totale_pagine=(
            math.ceil(totale / settings.PAGE_SIZE) if totale else 0
        ),
    )


# ---------------------------------------------------------------------------
#  I motivi ammessi
# ---------------------------------------------------------------------------


@router.get("/motivi")
def motivi(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """L'elenco dei motivi ammessi nella terza parentesi dell'oggetto."""
    return _pagina_motivi(request, db)


def _pagina_motivi(
    request: Request,
    db: Session,
    *,
    errore: str | None = None,
    codice_scritto: str = "",
    descrizione_scritta: str = "",
) -> Response:
    """Compone la pagina dei motivi. Serve alla lettura e al modulo rifiutato."""
    return pagina(
        request,
        "posta/motivi.html",
        stato=400 if errore else 200,
        errore=errore,
        motivi=email_reasons.elenco(db, solo_attivi=False),
        codice_scritto=codice_scritto,
        descrizione_scritta=descrizione_scritta,
    )


@router.post("/motivi")
def salva_motivo(
    request: Request,
    codice: Annotated[str, Form()] = "",
    descrizione: Annotated[str, Form()] = "",
    motivo_id: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Aggiunge un motivo, oppure ne corregge uno che c'e' gia'.

    Un modulo solo per le due operazioni perche' sono la stessa: due campi da
    scrivere e un elenco su cui finiscono. Il campo nascosto `motivo_id` dice
    quale delle due si sta facendo, ed e' vuoto quando se ne aggiunge uno.
    """
    esistente = None
    if motivo_id:
        try:
            esistente = email_reasons.trova(db, uuid.UUID(motivo_id))
        except (ValueError, AttributeError):
            esistente = None
        if esistente is None:
            raise HTTPException(
                status_code=404, detail="Il motivo richiesto non esiste."
            )

    try:
        pulito = email_reasons.verifica_codice(codice)
    except email_reasons.CodiceNonValido as problema:
        return _pagina_motivi(
            request,
            db,
            errore=str(problema),
            codice_scritto=codice,
            descrizione_scritta=descrizione,
        )

    if email_reasons.codice_gia_usato(
        db, pulito, escludi=esistente.id if esistente else None
    ):
        return _pagina_motivi(
            request,
            db,
            errore=f"Il motivo «{pulito}» c'e' gia' nell'elenco.",
            codice_scritto=codice,
            descrizione_scritta=descrizione,
        )

    if esistente is None:
        email_reasons.crea(
            db,
            codice=pulito,
            descrizione=descrizione,
            autore=creatore,
            request=request,
        )
    else:
        email_reasons.modifica(
            db,
            esistente,
            codice=pulito,
            descrizione=descrizione,
            autore=creatore,
            request=request,
        )

    db.commit()
    return RedirectResponse(url="/posta/motivi?salvato=1", status_code=303)


@router.post("/motivi/{reason_id}/proponibilita")
def proponibilita_motivo(
    request: Request,
    reason_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Mette o toglie un motivo dall'elenco di quelli riconosciuti.

    Un pulsante solo che fa e disfa: lo stato di adesso lo si vede nella riga,
    e due pulsanti - uno attivo e uno spento - direbbero la stessa cosa
    occupando il doppio.
    """
    motivo = email_reasons.trova(db, reason_id)
    if motivo is None:
        raise HTTPException(
            status_code=404, detail="Il motivo richiesto non esiste."
        )

    if motivo.is_active:
        email_reasons.disattiva(db, motivo, autore=creatore, request=request)
        esito = "disattivato"
    else:
        email_reasons.riattiva(db, motivo, autore=creatore, request=request)
        esito = "riattivato"

    db.commit()
    return RedirectResponse(url=f"/posta/motivi?{esito}=1", status_code=303)


# ---------------------------------------------------------------------------
#  La scheda di un messaggio
# ---------------------------------------------------------------------------


@router.get("/{message_id}")
def scheda(
    request: Request,
    message_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Il messaggio con il corpo leggibile e gli allegati scaricabili."""
    messaggio = _messaggio_o_errore(db, message_id, utente)

    motivo, riconosciuto = emails.motivo_riconosciuto(messaggio)

    return pagina(
        request,
        "posta/messaggio.html",
        messaggio=messaggio,
        destinatari=emails.destinatari_di(messaggio, "a"),
        copia=emails.destinatari_di(messaggio, "cc"),
        copia_nascosta=emails.destinatari_di(messaggio, "ccn"),
        attribuzione=emails.come_attribuito(messaggio),
        nome_stato=emails.nome_stato(messaggio.assignment_state),
        motivo=motivo,
        motivo_riconosciuto=riconosciuto,
        difetti=(messaggio.subject_parsed or {}).get("difetti") or [],
        peso=documents.peso_leggibile,
        puo_assegnare=permissions.puo(
            db, utente, permissions.Azione.MODIFICARE, messaggio
        ),
    )


@router.get("/{message_id}/scarica")
def scarica_messaggio(
    request: Request,
    message_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Consegna il file `.eml` originale, e registra chi lo ha preso.

    Il nome con cui esce e' composto qui: sul disco il file si chiama con la
    sua impronta (D-004), e "3f9a2c11....eml" non e' un nome che si ritrova
    fra i download di lunedi'.
    """
    messaggio = _messaggio_o_errore(db, message_id, utente)

    nome = _nome_del_file(messaggio)
    emails.registra_scarico(
        db, messaggio, che_cosa=nome, utente=utente, request=request
    )
    db.commit()

    return _consegna(
        messaggio.storage_hash, nome_file=nome, mime_type="message/rfc822"
    )


def _nome_del_file(messaggio: EmailMessage) -> str:
    """Il nome con cui esce il `.eml` di un messaggio.

    La data e l'oggetto, ripuliti dei caratteri che nei nomi di file non ci
    stanno. L'oggetto si taglia a sessanta caratteri: sommato al percorso in
    cui il browser lo salvera', un oggetto lungo sfonderebbe il limite dei 260
    caratteri di Windows.
    """
    quando = messaggio.sent_at or messaggio.received_at
    oggetto = (messaggio.subject or "messaggio").strip()

    for carattere in '\\/:*?"<>|\r\n\t':
        oggetto = oggetto.replace(carattere, "-")

    return f"{quando.date().isoformat()} {oggetto[:60].strip()}.eml"


@router.get("/{message_id}/allegati/{attachment_id}")
def scarica_allegato(
    request: Request,
    message_id: uuid.UUID,
    attachment_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Consegna un allegato, verificando che sia di quel messaggio."""
    messaggio = _messaggio_o_errore(db, message_id, utente)

    allegato = emails.allegato_di(db, messaggio, attachment_id)
    if allegato is None:
        raise HTTPException(
            status_code=404, detail="L'allegato richiesto non esiste."
        )

    emails.registra_scarico(
        db,
        messaggio,
        che_cosa=allegato.filename,
        utente=utente,
        request=request,
    )
    db.commit()

    return _consegna(
        allegato.storage_hash,
        nome_file=allegato.filename,
        mime_type=allegato.mime_type,
    )


# ---------------------------------------------------------------------------
#  L'assegnazione a mano
# ---------------------------------------------------------------------------


@router.get("/{message_id}/assegna")
def mostra_assegna(
    request: Request,
    message_id: uuid.UUID,
    cerca: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Il modulo con cui si attacca un messaggio a una versione di prodotto.

    La ricerca del prodotto e' un modulo GET dentro la pagina: chi smista la
    quarantena conosce il codice, non l'identificatore della versione, e una
    tendina con dentro tutte le versioni dell'azienda non si scorre.
    """
    messaggio = _messaggio_o_errore(
        db, message_id, utente, permissions.Azione.MODIFICARE
    )

    return _pagina_assegna(request, db, messaggio, cerca=cerca)


def _pagina_assegna(
    request: Request,
    db: Session,
    messaggio: EmailMessage,
    *,
    cerca: str = "",
    errore: str | None = None,
) -> Response:
    """Compone il modulo di assegnazione, con l'elenco delle versioni."""
    filo = emails.messaggi_del_filo(db, messaggio)
    in_quarantena = [
        altro
        for altro in filo
        if altro.assignment_state == EmailAssignmentState.QUARANTENA
    ]

    return pagina(
        request,
        "posta/assegna.html",
        stato=400 if errore else 200,
        errore=errore,
        messaggio=messaggio,
        versioni=emails.cerca_versioni(db, cerca, VERSIONI_PROPOSTE),
        cerca=cerca,
        quanti_nel_filo=len(in_quarantena),
        nel_filo=in_quarantena,
    )


@router.post("/{message_id}/assegna")
def assegna(
    request: Request,
    message_id: uuid.UUID,
    versione: Annotated[str, Form()] = "",
    tutto_il_filo: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Attacca il messaggio - e, se richiesto, tutta la sua conversazione.

    La proposta di assegnare anche gli altri messaggi del filo e' una spunta
    del modulo e non una domanda dopo: una conversazione appartiene tutta allo
    stesso prodotto, e assegnarne dodici uno per volta e' il modo piu' sicuro
    di smettere di usare la quarantena. La spunta e' segnata di partenza,
    perche' e' quasi sempre quello che si vuole; chi non lo vuole la toglie.
    """
    messaggio = _messaggio_o_errore(
        db, message_id, utente, permissions.Azione.MODIFICARE
    )

    scelta = emails.trova_versione(db, versione)
    if scelta is None:
        return _pagina_assegna(
            request,
            db,
            messaggio,
            errore="Scegli la versione di prodotto a cui attaccare il messaggio.",
        )

    # La tendina propone solo versioni esistenti, ma la richiesta puo' arrivare
    # scritta a mano: il permesso si chiede sulla versione scelta davvero.
    permissions.pretendi(db, utente, permissions.Azione.VEDERE, scelta)

    emails.assegna(
        db, messaggio, versione=scelta, autore=utente, request=request
    )

    assegnati = 0
    if tutto_il_filo == "si":
        assegnati = len(
            emails.assegna_il_filo(
                db, messaggio, versione=scelta, autore=utente, request=request
            )
        )

    db.commit()

    return RedirectResponse(
        url=f"/posta/{messaggio.id}?assegnato=1&filo={assegnati}",
        status_code=303,
    )
