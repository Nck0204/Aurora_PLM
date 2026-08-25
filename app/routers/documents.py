"""Le pagine dei documenti.

    GET  /documenti                                elenco, con filtri e ricerca
    GET  /documenti/nuovo?progetto={id}            modulo di caricamento
    POST /documenti/nuovo                          carica uno o piu' file
    GET  /documenti/ritirati                       i documenti tolti (creatore)
    GET  /documenti/{id}                           scheda con lo storico
    GET  /documenti/{id}/versione                  modulo della versione nuova
    POST /documenti/{id}/versione                  carica la versione nuova
    GET  /documenti/{id}/stato?nuovo={stato}       conferma del cambio di stato
    POST /documenti/{id}/stato                     esegue il cambio
    POST /documenti/{id}/ritira                    ritiro logico
    POST /documenti/{id}/ripristina                ritorno negli elenchi
    GET  /documenti/{id}/versioni/{vid}/scarica    il file
    GET  /documenti/{id}/versioni/{vid}/avviso     l'avviso prima dello scarico

**Chi vede che cosa lo decide permissions.puo()**, e in questo file non c'e'
nemmeno una riga che lo stabilisca: si chiede con `permissions.pretendi()`,
che risponde da sola con il codice giusto. Le due strade - l'elenco e la
scheda - passano dalla stessa regola, perche' un elenco che nasconde una riga
che poi si apre scrivendone l'indirizzo non e' una protezione (D-051).

**Un identificativo che non si puo' vedere riceve un 404**, con lo stesso
messaggio di uno che non esiste. Il 403 resta per le operazioni: chi il
documento lo vede gia' e prova a cambiarne lo stato senza averne il permesso
riceve una spiegazione, non un vicolo cieco.

**Lo scarico di un file che non e' piu' valido passa da un avviso.** Se la
versione di prodotto e' superata o obsoleta e il file non e' un PDF - dove la
filigrana si stampa e basta - la rotta dello scarico dirotta su una pagina che
lo dice, e il file si prende da li'. Il controllo sta nella rotta dello
scarico e non nei collegamenti: cosi' vale per tutti i modi in cui ci si
arriva, compreso un indirizzo copiato e incollato.
"""

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import (
    Classification,
    Document,
    DocumentState,
    DocumentVersion,
    Project,
    User,
)
from app.services import (
    doc_types,
    documents,
    lifecycle,
    permissions,
    projects,
    storage,
    watermark,
)
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.documenti")

router = APIRouter(prefix="/documenti", tags=["documenti"])

# I messaggi dei dinieghi stanno in permissions.py, perche' quello del 404
# deve essere identico alla parola per quello di un documento che davvero non
# esiste: se ogni rotta se lo scrivesse per conto suo, la differenza fra due
# risposte finirebbe per dire che il documento c'e'.
MESSAGGIO_DOCUMENTO_INESISTENTE = permissions.MESSAGGI_INESISTENTE[Document]
MESSAGGIO_PROGETTO_INESISTENTE = permissions.MESSAGGI_INESISTENTE[Project]

# Il parametro con cui la pagina dell'avviso dice "l'utente ha letto, procedi".
PARAMETRO_AVVISATO = "avvisato"


# ---------------------------------------------------------------------------
#  Aiuti comuni
# ---------------------------------------------------------------------------


def _progetto_o_errore(db: Session, valore: str, utente: User) -> Project:
    """Cerca il progetto e verifica che questa persona lo possa vedere.

    Le due risposte negative sono la stessa: 404 sia quando il progetto non
    esiste sia quando esiste e non lo si vede. Chi provasse gli indirizzi uno
    per uno non riuscirebbe a distinguere i due casi, che e' esattamente lo
    scopo.
    """
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


def _documento_o_errore(
    db: Session, document_id: uuid.UUID, utente: User, azione=None
) -> Document:
    """Cerca il documento e pretende il permesso di fare quello che si vuole.

    "azione" e' quello che la rotta sta per fare: vedere se non si dice
    niente, caricare per la versione nuova, modificare per il cambio di stato
    e il ritiro. Chiedere il permesso **dell'operazione vera** invece che
    del solo "vedere" e' quello che permette di scriverne uno per rotta e di
    non doverne ricordare due.

    Chi non lo puo' vedere riceve un 404 con lo stesso messaggio di un
    documento che non esiste - compreso il caso del documento ritirato, che
    resta in tabella ma per chi non e' creatore e' come se non ci fosse. Chi
    lo vede ma non puo' fare quell'operazione riceve un 403 che gliela
    spiega. La differenza la fa permissions.pretendi(), qui non c'e' nessuna
    regola scritta.
    """
    documento = documents.trova_documento(db, document_id)
    if documento is None:
        raise HTTPException(
            status_code=404, detail=MESSAGGIO_DOCUMENTO_INESISTENTE
        )

    permissions.pretendi(
        db, utente, azione or permissions.Azione.VEDERE, documento
    )
    return documento


def _classificazione_scelta(
    db: Session, valore: str
) -> Classification | None:
    """Cerca la classificazione scelta nel modulo, senza fidarsi del modulo."""
    try:
        return db.get(Classification, uuid.UUID(valore))
    except (ValueError, AttributeError):
        return None


def _opzioni_classificazioni(
    classificazioni: list[Classification],
) -> list[tuple[str, str]]:
    """Le classificazioni come coppie (identificatore, nome), per la tendina."""
    return [
        (str(classificazione.id), classificazione.name)
        for classificazione in classificazioni
    ]


def _caricamento_da(file: UploadFile) -> documents.Caricamento:
    """Trasforma il file dell'upload in quello che si aspetta il servizio."""
    return documents.Caricamento(
        sorgente=file.file,
        nome_file=file.filename or "documento",
        mime_type=file.content_type or documents.MIME_SCONOSCIUTO,
    )


def _file_veri(file: list[UploadFile]) -> list[UploadFile]:
    """I file scelti davvero.

    Un campo file lasciato vuoto arriva comunque, con nome vuoto e dimensione
    zero: senza questo filtro un modulo inviato senza scegliere niente
    creerebbe un documento vuoto invece di dire "scegli un file".
    """
    return [singolo for singolo in file if singolo and singolo.filename]


def _peso_massimo_leggibile() -> str:
    """Il limite di dimensione come si scrive in una pagina."""
    return documents.peso_leggibile(settings.max_upload_bytes)


def _intero(valore: str | None, predefinito: int) -> int:
    """Legge un numero da un parametro dell'indirizzo, senza fidarsene.

    Un indirizzo puo' essere scritto a mano, o restare in un preferito dopo
    che la pagina e' cambiata: "?pagina=abc" non deve produrre un errore
    tecnico ma comportarsi come se il parametro non ci fosse.
    """
    try:
        return int(valore) if valore is not None else predefinito
    except ValueError:
        return predefinito


# ---------------------------------------------------------------------------
#  Elenco
# ---------------------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    q: str = "",
    progetto: str = "",
    tipo: str = "",
    stato: str = "",
    ordina: str = documents.ORDINAMENTO_PREDEFINITO,
    verso: str = "desc",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """I documenti che questa persona puo' vedere, con filtri e ricerca.

    E' un elenco solo per due usi: la voce di menu "Documenti", che li mostra
    tutti, e il collegamento dalla scheda di un progetto, che aggiunge il
    parametro "progetto" e li restringe a quello. Due pagine separate avrebbero
    voluto dire due interrogazioni da tenere allineate e, prima o poi, due
    elenchi che dicono cose diverse.

    Il numero di pagina si legge dai parametri della richiesta e non dalla
    firma: nell'indirizzo si chiama "pagina", che in questo file e' gia' il
    nome della funzione che compone le pagine.
    """
    pagina_numero = max(1, _intero(request.query_params.get("pagina"), 1))

    progetto_scelto: Project | None = None
    if progetto:
        progetto_scelto = _progetto_o_errore(db, progetto, utente)

    trovati, totale = documents.cerca_documenti(
        db,
        utente,
        project_id=progetto_scelto.id if progetto_scelto else None,
        tipo=tipo or None,
        stato=stato or None,
        testo=q or None,
        ordina=ordina,
        verso=verso,
        pagina=pagina_numero,
        per_pagina=settings.PAGE_SIZE,
    )

    # I parametri da tenersi passando da una pagina all'altra: senza,
    # cambiando pagina si perderebbero i filtri.
    parametri = {
        nome: valore
        for nome, valore in (
            ("q", q),
            ("progetto", progetto),
            ("tipo", tipo),
            ("stato", stato),
            ("ordina", ordina),
            ("verso", verso),
        )
        if valore
    }

    totale_pagine = math.ceil(totale / settings.PAGE_SIZE) if totale else 0

    return pagina(
        request,
        "documenti/elenco.html",
        documenti=trovati,
        totale=totale,
        filtri=documents.filtri_elenco(db, utente, tipo, stato),
        q=q,
        progetto_scelto=progetto_scelto,
        tipo_scelto=tipo,
        stato_scelto=stato,
        ordina=ordina,
        verso=verso,
        parametri=parametri,
        pagina_corrente=pagina_numero,
        totale_pagine=totale_pagine,
        nome_stato=lifecycle.nome_stato_documento,
        peso=documents.peso_leggibile,
        versione_corrente=documents.versione_corrente,
    )


@router.get("/ritirati")
def ritirati(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """I documenti ritirati, con il pulsante per rimetterli a posto.

    E' la sezione dedicata di cui parla la regola 5 della sessione. La
    dipendenza sulla rotta e' il lucchetto: nascondere la voce di menu non
    proteggerebbe niente.
    """
    return pagina(
        request,
        "documenti/ritirati.html",
        documenti=documents.documenti_ritirati(db),
        nome_stato=lifecycle.nome_stato_documento,
        versione_corrente=documents.versione_corrente,
    )


# ---------------------------------------------------------------------------
#  Caricamento di un documento nuovo
# ---------------------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(
    request: Request,
    progetto: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Il modulo di caricamento, sempre dentro un progetto.

    Un documento sta in un progetto, quindi il progetto si sceglie prima: non
    esiste una pagina "carica un documento" da cui decidere dopo dove finisce.
    """
    progetto_scelto = _progetto_o_errore(db, progetto, utente)
    caricabili = permissions.classificazioni_caricabili(
        db, progetto_scelto, utente
    )

    return pagina(
        request,
        "documenti/nuovo.html",
        progetto=progetto_scelto,
        prodotto=progetto_scelto.product_version.product,
        versione=progetto_scelto.product_version,
        tipi=doc_types.opzioni(),
        problema_tipi=doc_types.elenco().problema,
        classificazioni=_opzioni_classificazioni(caricabili),
        peso_massimo=_peso_massimo_leggibile(),
    )


@router.post("/nuovo")
def carica(
    request: Request,
    progetto: Annotated[str, Form()] = "",
    titolo: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = "",
    classificazione: Annotated[str, Form()] = "",
    file: Annotated[list[UploadFile], File()] = [],
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Carica uno o piu' file, e ne fa un documento ciascuno.

    **Un file, un documento.** Con piu' file scelti insieme non ci sarebbe un
    titolo solo che vada bene per tutti: cosi' il titolo scritto nel modulo
    vale quando il file e' uno, e negli altri casi ogni documento prende come
    titolo il nome del proprio file, senza estensione. Tipo e classificazione
    valgono per tutti, perche' chi carica dieci schemi insieme li sta
    caricando tutti come schemi.

    L'ordine delle operazioni conta: i file finiscono nell'archivio prima che
    venga scritta qualunque riga. Se uno supera il limite non e' stato creato
    niente da annullare.
    """
    progetto_scelto = _progetto_o_errore(db, progetto, utente)
    caricabili = permissions.classificazioni_caricabili(
        db, progetto_scelto, utente
    )

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "documenti/nuovo.html",
            stato=400,
            errore=messaggio,
            progetto=progetto_scelto,
            prodotto=progetto_scelto.product_version.product,
            versione=progetto_scelto.product_version,
            tipi=doc_types.opzioni(),
            problema_tipi=doc_types.elenco().problema,
            classificazioni=_opzioni_classificazioni(caricabili),
            peso_massimo=_peso_massimo_leggibile(),
            titolo_scritto=titolo,
            tipo_scelto=tipo,
            classificazione_scelta=classificazione,
        )

    scelti = _file_veri(file)
    if not scelti:
        return rimostra("Scegli almeno un file da caricare.")

    if not tipo.strip():
        return rimostra("Scegli il tipo di documento.")

    classe = _classificazione_scelta(db, classificazione)
    if classe is None:
        return rimostra("Scegli la classificazione del documento.")

    # Il menu a tendina propone gia' solo le classificazioni consentite, ma
    # la richiesta puo' arrivare scritta a mano: si chiede il permesso sulla
    # coppia (progetto, classificazione) scelta davvero.
    permissions.pretendi(
        db,
        utente,
        permissions.Azione.CARICARE,
        permissions.BersaglioCaricamento(
            progetto=progetto_scelto, classification_id=classe.id
        ),
    )

    creati: list[Document] = []
    for singolo in scelti:
        caricamento = _caricamento_da(singolo)

        try:
            deposito = documents.deposita_file(
                caricamento, settings.max_upload_bytes
            )
        except storage.FileTroppoGrande as errore:
            db.rollback()
            return rimostra(f"«{caricamento.nome_file}»: {errore}")

        documento, _ = documents.crea_documento(
            db,
            progetto=progetto_scelto,
            # Con piu' di un file il titolo scritto nel modulo non puo' valere
            # per tutti: si passa vuoto, e il servizio prende il nome del file.
            titolo=titolo if len(scelti) == 1 else "",
            tipo=tipo,
            classificazione=classe,
            caricamento=caricamento,
            deposito=deposito,
            autore=utente,
            request=request,
        )
        creati.append(documento)

    db.commit()

    # Con un file solo si va sulla sua scheda, che e' quello che chi ha
    # caricato vuole vedere. Con piu' file si torna all'elenco del progetto,
    # perche' non ce n'e' uno solo da mostrare.
    if len(creati) == 1:
        return RedirectResponse(
            url=f"/documenti/{creati[0].id}?caricato=1", status_code=303
        )

    return RedirectResponse(
        url=f"/documenti?progetto={progetto_scelto.id}&caricati={len(creati)}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
#  Scheda
# ---------------------------------------------------------------------------


@router.get("/{document_id}")
def scheda(
    request: Request,
    document_id: uuid.UUID,
    caricato: int = 0,
    versione_nuova: int = 0,
    cambiato: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di un documento: i dati, lo storico, gli scarichi.

    Lo storico delle versioni e' l'unica cosa che questa pagina deve fare
    bene: chi la apre vuole sapere che cosa e' cambiato e da chi, e poter
    scaricare qualunque versione, non solo l'ultima.
    """
    documento = _documento_o_errore(db, document_id, utente)

    versione_prodotto = documents.versione_di_prodotto_di(documento)
    da_marchiare = watermark.serve_filigrana(versione_prodotto.lifecycle_state)

    return pagina(
        request,
        "documenti/scheda.html",
        documento=documento,
        progetto=documento.project,
        prodotto=versione_prodotto.product,
        versione_prodotto=versione_prodotto,
        versioni=documents.versioni_di(db, documento.id),
        corrente=documents.versione_corrente(documento),
        # I pulsanti della scheda: i tre permessi arrivano gia' decisi, il
        # template li disegna e basta (D-051).
        permessi=permissions.Permessi(
            vedere=True,
            caricare=permissions.puo(
                db, utente, permissions.Azione.CARICARE, documento
            ),
            modificare=permissions.puo(
                db, utente, permissions.Azione.MODIFICARE, documento
            ),
        ),
        stati_possibili=lifecycle.stati_documento_raggiungibili(documento.state),
        stato_definitivo=lifecycle.STATO_DOCUMENTO_DEFINITIVO,
        nome_stato=lifecycle.nome_stato_documento,
        peso=documents.peso_leggibile,
        rilascio=documents.ultimo_rilascio(db, documento.id),
        scarichi=documents.scarichi_di(db, documento.id),
        da_marchiare=da_marchiare,
        caricato=bool(caricato),
        versione_nuova=bool(versione_nuova),
        cambiato=cambiato,
    )


# ---------------------------------------------------------------------------
#  Versione nuova
# ---------------------------------------------------------------------------


@router.get("/{document_id}/versione")
def mostra_versione(
    request: Request,
    document_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Il modulo con cui si carica una versione nuova.

    Quando il documento e' rilasciato, la pagina lo dice in cima: il file
    rilasciato non verra' toccato, quello nuovo sara' la versione dopo e
    ripartira' da bozza. E' il punto in cui la regola dell'immutabilita' del
    rilasciato si spiega, invece di limitarsi a impedire qualcosa.
    """
    documento = _documento_o_errore(
        db, document_id, utente, permissions.Azione.CARICARE
    )

    return pagina(
        request,
        "documenti/versione.html",
        documento=documento,
        progetto=documento.project,
        corrente=documents.versione_corrente(documento),
        prossimo_numero=documents.prossimo_numero_versione(db, documento.id),
        era_rilasciato=documento.state is DocumentState.RILASCIATO,
        nome_stato=lifecycle.nome_stato_documento,
        peso_massimo=_peso_massimo_leggibile(),
    )


@router.post("/{document_id}/versione")
def aggiungi_versione(
    request: Request,
    document_id: uuid.UUID,
    nota: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Carica la versione successiva di un documento gia' esistente.

    La versione precedente non viene toccata in nessun modo: resta la sua riga
    con la sua impronta, e il file nell'archivio e' lo stesso di prima. E'
    quello che rende vero il criterio di accettazione "la precedente resta
    scaricabile e identica all'originale".
    """
    documento = _documento_o_errore(
        db, document_id, utente, permissions.Azione.CARICARE
    )

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "documenti/versione.html",
            stato=400,
            errore=messaggio,
            documento=documento,
            progetto=documento.project,
            corrente=documents.versione_corrente(documento),
            prossimo_numero=documents.prossimo_numero_versione(
                db, documento.id
            ),
            era_rilasciato=documento.state is DocumentState.RILASCIATO,
            nome_stato=lifecycle.nome_stato_documento,
            peso_massimo=_peso_massimo_leggibile(),
            nota_scritta=nota,
        )

    if file is None or not file.filename:
        return rimostra("Scegli il file della versione nuova.")

    if not nota.strip():
        return rimostra(
            "Scrivi che cosa cambia rispetto alla versione precedente: e' la "
            "sola informazione che nessuno potra' ricostruire dopo."
        )

    caricamento = _caricamento_da(file)

    try:
        deposito = documents.deposita_file(caricamento, settings.max_upload_bytes)
    except storage.FileTroppoGrande as errore:
        db.rollback()
        return rimostra(str(errore))

    try:
        versione = documents.aggiungi_versione(
            db,
            documento=documento,
            caricamento=caricamento,
            deposito=deposito,
            nota=nota,
            autore=utente,
            request=request,
        )
    except (documents.NotaObbligatoria, documents.DocumentoEliminato) as errore:
        db.rollback()
        return rimostra(str(errore))

    db.commit()

    return RedirectResponse(
        url=f"/documenti/{documento.id}?versione_nuova={versione.version_number}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
#  Stato
# ---------------------------------------------------------------------------


@router.get("/{document_id}/stato")
def mostra_stato(
    request: Request,
    document_id: uuid.UUID,
    nuovo: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La pagina di conferma del cambio di stato.

    E' una pagina e non una finestra modale, per la stessa ragione del
    rilascio di una versione di prodotto (D-042): una finestra ha bisogno di
    JavaScript per aprirsi, e se non si aprisse l'operazione partirebbe senza
    che nessuno abbia letto niente.

    La conferma del **rilascio** e' quella che conta: da li' in poi il file non
    si sostituisce piu'. La pagina lo scrive per esteso.
    """
    documento = _documento_o_errore(
        db, document_id, utente, permissions.Azione.MODIFICARE
    )

    stato_nuovo = _stato_scelto(nuovo)
    if stato_nuovo is None:
        raise HTTPException(
            status_code=400,
            detail="Lo stato richiesto non esiste fra quelli di un documento.",
        )

    try:
        lifecycle.verifica_transizione_documento(documento.state, stato_nuovo)
    except lifecycle.TransizioneNonAmmessa as errore:
        raise HTTPException(status_code=400, detail=str(errore)) from errore

    return pagina(
        request,
        "documenti/conferma_stato.html",
        documento=documento,
        progetto=documento.project,
        nuovo_stato=stato_nuovo,
        e_il_rilascio=stato_nuovo is lifecycle.STATO_DOCUMENTO_DEFINITIVO,
        corrente=documents.versione_corrente(documento),
        nome_stato=lifecycle.nome_stato_documento,
    )


@router.post("/{document_id}/stato")
def cambia_stato(
    request: Request,
    document_id: uuid.UUID,
    nuovo: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Esegue il cambio di stato, dopo che la conferma e' stata letta."""
    documento = _documento_o_errore(
        db, document_id, utente, permissions.Azione.MODIFICARE
    )

    stato_nuovo = _stato_scelto(nuovo)
    if stato_nuovo is None:
        raise HTTPException(
            status_code=400,
            detail="Lo stato richiesto non esiste fra quelli di un documento.",
        )

    try:
        documents.cambia_stato(
            db,
            documento=documento,
            nuovo_stato=stato_nuovo,
            autore=utente,
            request=request,
        )
    except (
        lifecycle.TransizioneNonAmmessa,
        documents.DocumentoEliminato,
    ) as errore:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(errore)) from errore

    db.commit()

    return RedirectResponse(
        url=f"/documenti/{documento.id}?cambiato={stato_nuovo.value}",
        status_code=303,
    )


def _stato_scelto(valore: str) -> DocumentState | None:
    """Trasforma il parametro dell'indirizzo in uno stato, o in None.

    Il valore arriva da un indirizzo, e gli indirizzi si scrivono a mano: uno
    stato che non esiste deve diventare una frase italiana, non un errore di
    conversione con la traccia dello stack.
    """
    for stato in DocumentState:
        if stato.value == valore:
            return stato
    return None


# ---------------------------------------------------------------------------
#  Ritiro e ripristino
# ---------------------------------------------------------------------------


@router.post("/{document_id}/ritira")
def ritira(
    request: Request,
    document_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Toglie il documento dagli elenchi. Non cancella niente."""
    documento = _documento_o_errore(
        db, document_id, utente, permissions.Azione.MODIFICARE
    )

    progetto_id = documento.project_id
    documents.elimina(db, documento=documento, autore=utente, request=request)
    db.commit()

    return RedirectResponse(
        url=f"/documenti?progetto={progetto_id}&ritirato=1", status_code=303
    )


@router.post("/{document_id}/ripristina")
def ripristina(
    request: Request,
    document_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Rimette un documento ritirato negli elenchi ordinari.

    Lo fa il creatore, perche' e' lui l'unico che i documenti ritirati li
    vede: la sezione da cui si ripristina e' la sua.
    """
    documento = documents.trova_documento(db, document_id)
    if documento is None:
        raise HTTPException(
            status_code=404, detail=MESSAGGIO_DOCUMENTO_INESISTENTE
        )

    documents.ripristina(
        db, documento=documento, autore=creatore, request=request
    )
    db.commit()

    return RedirectResponse(
        url=f"/documenti/{documento.id}?ripristinato=1", status_code=303
    )


# ---------------------------------------------------------------------------
#  Scarico
# ---------------------------------------------------------------------------


def _versione_o_errore(
    db: Session, documento: Document, version_id: uuid.UUID
) -> DocumentVersion:
    """Cerca la versione e verifica che appartenga a quel documento.

    Il controllo sull'appartenenza non e' formale: senza, chiunque possa
    vedere un documento qualunque potrebbe scaricare la versione di un altro
    scrivendone l'identificatore, e i permessi sarebbero stati verificati sul
    documento sbagliato.
    """
    versione = documents.trova_versione(db, version_id)
    if versione is None or versione.document_id != documento.id:
        raise HTTPException(
            status_code=404,
            detail="Questa versione non esiste, o non appartiene a questo documento.",
        )
    return versione


@router.get("/{document_id}/versioni/{version_id}/avviso")
def avviso_scarico(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """L'avviso mostrato prima di scaricare un file non piu' valido.

    Serve per i formati su cui la filigrana non si puo' stampare: un DWG, uno
    ZIP, un foglio di calcolo. La filigrana esiste perche' l'avvertenza
    viaggi insieme al file anche fuori da Aurora; dove non si puo' stampare,
    le uniche due cose che restano sono questa pagina e il nome del file, e si
    fanno tutte e due.
    """
    documento = _documento_o_errore(db, document_id, utente)
    versione = _versione_o_errore(db, documento, version_id)
    versione_prodotto = documents.versione_di_prodotto_di(documento)

    return pagina(
        request,
        "documenti/avviso_scarico.html",
        documento=documento,
        versione=versione,
        prodotto=versione_prodotto.product,
        versione_prodotto=versione_prodotto,
        nome_scaricato=watermark.nome_con_avvertenza(
            versione.original_filename
        ),
        peso=documents.peso_leggibile,
    )


@router.get("/{document_id}/versioni/{version_id}/scarica")
def scarica(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    avvisato: int = 0,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Consegna il file di una versione, e registra chi lo ha preso.

    Tre strade, e la scelta fra loro sta tutta qui dentro:

      1. la versione di prodotto e' buona -> il file esce com'e';
      2. la versione di prodotto e' superata o obsoleta e il file e' un PDF ->
         esce con la filigrana stampata sopra, calcolata adesso;
      3. la versione di prodotto e' superata o obsoleta e il file non e' un
         PDF -> si passa prima dalla pagina dell'avviso, e il file esce con
         l'avvertenza dentro il nome.

    Il dirottamento del terzo caso sta nella rotta e non nei collegamenti,
    cosi' vale per tutti i modi in cui ci si arriva: il pulsante, un indirizzo
    copiato, un preferito salvato sei mesi fa.
    """
    documento = _documento_o_errore(db, document_id, utente)
    versione = _versione_o_errore(db, documento, version_id)

    versione_prodotto = documents.versione_di_prodotto_di(documento)
    non_piu_valida = watermark.serve_filigrana(
        versione_prodotto.lifecycle_state
    )
    e_pdf = watermark.e_un_pdf(versione.mime_type, versione.original_filename)

    if non_piu_valida and not e_pdf and not avvisato:
        return RedirectResponse(
            url=(
                f"/documenti/{documento.id}/versioni/{versione.id}/avviso"
            ),
            status_code=303,
        )

    nome_consegnato = versione.original_filename
    con_filigrana = False
    contenuto: bytes | None = None

    if non_piu_valida:
        nome_consegnato = watermark.nome_con_avvertenza(nome_consegnato)

        if e_pdf:
            try:
                contenuto = watermark.applica(
                    storage.leggi(versione.storage_hash),
                    stato=versione_prodotto.lifecycle_state,
                    momento=datetime.now(timezone.utc).astimezone(),
                )
                con_filigrana = True
            except watermark.FiligranaNonApplicata:
                # Gia' scritto nel registro con la sua traccia. Il file esce
                # com'e': togliere a una persona un documento che ha il
                # diritto di avere, per un guasto che non la riguarda, sarebbe
                # il modo peggiore di sbagliare. L'avvertenza resta nel nome.
                contenuto = None

    documents.registra_scarico(
        db,
        documento=documento,
        versione=versione,
        utente=utente,
        con_filigrana=con_filigrana,
        request=request,
    )
    db.commit()

    if contenuto is not None:
        return Response(
            content=contenuto,
            media_type=watermark.MIME_PDF,
            headers={"content-disposition": _disposizione(nome_consegnato)},
        )

    try:
        percorso = storage.percorso_di(versione.storage_hash)
    except ValueError as errore:
        logger.error("Impronta illeggibile sulla versione %s", versione.id)
        raise HTTPException(
            status_code=500,
            detail="Il file di questa versione non e' leggibile dall'archivio.",
        ) from errore

    if not percorso.is_file():
        logger.error(
            "Il file %s della versione %s manca dall'archivio",
            versione.storage_hash,
            versione.id,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                "Il file di questa versione non si trova nell'archivio. "
                "Segnala il problema a chi amministra Aurora."
            ),
        )

    # FileResponse manda il file un pezzo per volta: un DWG da 800 MB non
    # passa mai per la memoria del server.
    return FileResponse(
        path=percorso,
        media_type=versione.mime_type or documents.MIME_SCONOSCIUTO,
        headers={"content-disposition": _disposizione(nome_consegnato)},
    )


def _disposizione(nome_file: str) -> str:
    """L'intestazione che dice al browser di salvare il file con quel nome.

    I nomi dei file di quest'azienda hanno accenti e lettere che non stanno
    nell'ASCII, e l'intestazione HTTP invece ci sta. Per questo se ne
    scrivono due versioni: una ripulita, che capiscono tutti, e una in
    UTF-8 percentuale, che i browser preferiscono quando c'e'. E' il modo
    previsto dallo standard, non un accorgimento.
    """
    ripulito = nome_file.encode("ascii", "ignore").decode("ascii")
    ripulito = ripulito.replace('"', "").replace("\\", "").strip()
    if not ripulito:
        ripulito = "documento"

    return (
        f'attachment; filename="{ripulito}"; '
        f"filename*=UTF-8''{quote(nome_file, safe='')}"
    )
