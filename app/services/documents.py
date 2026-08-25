"""I documenti di un progetto: caricamento, versioni, stato, ritiro, scarico.

E' il mestiere di Aurora. Tutto il resto - clienti, prodotti, progetti - serve
a dare un posto ai documenti; questi sono i documenti.

Tre idee tengono insieme il modulo, e conviene averle in mente prima di
leggere il codice.

**Il documento e' il contenitore, il file e' la versione.** "Schema elettrico
alimentatore" e' un documento e resta lo stesso per tutta la vita del
progetto: quello che cambia sono le sue versioni, una riga di
document_versions per ogni file caricato. Titolo, tipo, classificazione e
stato stanno sul documento perche' descrivono il documento; l'impronta, il
nome originale, la dimensione e la nota di modifica stanno sulla versione
perche' descrivono quel file li'.

**Le versioni non si modificano e non si cancellano.** Una versione caricata
e' un fatto avvenuto: se il file era sbagliato si carica la versione dopo, e
quella prima resta scaricabile identica a com'era. E' il motivo per cui
"sostituire un file" non e' un'operazione che esiste in Aurora.

**Il file non passa mai per il database.** Il contenuto lo deposita
app/services/storage.py, che restituisce un'impronta; qui si scrive soltanto
quell'impronta. Due documenti che contengono lo stesso file hanno la stessa
impronta e sul disco un file solo.

CHE COSA NON C'E', DI PROPOSITO. La presa in carico (checked_out_by_id sulla
tabella c'e' gia', ma nessuna rotta la valorizza) e la ricerca dentro il
contenuto dei file sono del rilascio R2.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    Classification,
    Document,
    DocumentState,
    DocumentVersion,
    ProductVersion,
    Project,
    User,
)
from app.services import audit, lifecycle, permissions, storage

logger = logging.getLogger("aurora.documenti")

# --- Le azioni registrate nel registro delle operazioni ---------------------

ACTION_DOCUMENT_CREATED = "document.created"
ACTION_VERSION_UPLOADED = "document.version_uploaded"
ACTION_STATE_CHANGED = "document.state_changed"
ACTION_DOCUMENT_DELETED = "document.deleted"
ACTION_DOCUMENT_RESTORED = "document.restored"
ACTION_DOCUMENT_DOWNLOADED = "document.download"

ENTITY_DOCUMENTS = "documents"

# Le colonne su cui si puo' ordinare l'elenco. La chiave e' quella che viaggia
# nell'indirizzo; il valore e' la colonna vera. Un ordinamento sconosciuto
# ricade su quello di partenza invece di far fallire la pagina: il parametro
# arriva da un indirizzo, e gli indirizzi si scrivono a mano.
ORDINAMENTI = {
    "titolo": Document.title,
    "tipo": Document.doc_type,
    "stato": Document.state,
    "aggiornato": Document.updated_at,
}
ORDINAMENTO_PREDEFINITO = "aggiornato"

# Il tipo che si scrive quando il browser non ne dichiara nessuno. E' quello
# che il protocollo prevede per "una sequenza di byte e non so altro".
MIME_SCONOSCIUTO = "application/octet-stream"

# Quanto puo' essere lungo un titolo e un nome di file, come nelle colonne.
LUNGHEZZA_TITOLO = 200
LUNGHEZZA_NOME_FILE = 255
LUNGHEZZA_TIPO = 80


class NotaObbligatoria(Exception):
    """Si e' provato a caricare una versione nuova senza dire che cosa cambia.

    Il messaggio e' gia' in italiano e va bene per essere mostrato.
    """


class DocumentoEliminato(Exception):
    """Si e' provato a operare su un documento che e' stato ritirato."""


@dataclass(frozen=True)
class Caricamento:
    """Un file che sta arrivando, prima che diventi una versione.

    sorgente      da dove leggere il contenuto. E' il file dell'upload, e si
                  legge una volta sola.
    nome_file     il nome che aveva sul computer di chi lo carica.
    mime_type     il tipo dichiarato dal browser.

    Esiste per non passare tre argomenti sciolti a quattro funzioni diverse:
    sono tre cose che viaggiano sempre insieme e che, separate, prima o poi si
    scambiano fra loro.
    """

    sorgente: BinaryIO
    nome_file: str
    mime_type: str


# ---------------------------------------------------------------------------
#  Lettura
# ---------------------------------------------------------------------------


def trova_documento(db: Session, document_id: uuid.UUID) -> Document | None:
    """Cerca un documento dal suo identificatore, ritirati compresi.

    I ritirati li restituisce apposta: la sezione da cui si ripristinano deve
    poterli aprire. Chi non li vuole guarda documento.is_deleted, che e' una
    domanda sola e si legge.
    """
    return db.get(Document, document_id)


def trova_versione(
    db: Session, version_id: uuid.UUID
) -> DocumentVersion | None:
    """Cerca una versione di documento dal suo identificatore."""
    return db.get(DocumentVersion, version_id)


def versioni_di(db: Session, document_id: uuid.UUID) -> list[DocumentVersion]:
    """Tutte le versioni di un documento, dalla piu' recente alla prima.

    L'ordine e' al contrario di quello della tabella perche' la domanda che si
    fa aprendo la scheda e' "com'e' adesso": la versione corrente sta in cima,
    la storia sotto.
    """
    return list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .options(selectinload(DocumentVersion.author))
            .order_by(DocumentVersion.version_number.desc())
        ).all()
    )


def versione_corrente(documento: Document) -> DocumentVersion | None:
    """L'ultima versione caricata, cioe' quella che vale adesso.

    None solo nell'istante fra la creazione del documento e il caricamento del
    suo primo file, che in Aurora non esiste: un documento nasce insieme alla
    sua versione 1. Il caso e' gestito lo stesso perche' una riga di database
    scritta a mano potrebbe produrlo, e una pagina non deve rompersi per
    questo.
    """
    if not documento.versions:
        return None
    return max(documento.versions, key=lambda versione: versione.version_number)


def prossimo_numero_versione(db: Session, document_id: uuid.UUID) -> int:
    """Il numero della prossima versione: uno piu' del massimo esistente.

    Si chiede al database invece di contare le righe gia' caricate in memoria:
    il vincolo di unicita' su (document_id, version_number) e' la rete di
    sicurezza, ma il numero giusto va calcolato sul dato vero.
    """
    massimo = db.scalar(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return (massimo or 0) + 1


def versione_di_prodotto_di(documento: Document) -> ProductVersion:
    """La versione di prodotto a cui appartiene il documento.

    Documento -> progetto -> versione di prodotto. Serve alla filigrana, che
    deve sapere se quella versione e' superata o obsoleta. E' una catena di
    due passaggi e sta in una funzione sua perche' la fanno in tre punti
    diversi: lo scarico, l'avviso prima dello scarico e la scheda.
    """
    return documento.project.product_version


def _visibili(utente: User) -> Select[tuple[Document]]:
    """L'interrogazione di partenza degli elenchi, gia' ristretta all'utente.

    Toglie i documenti ritirati e applica il filtro dei permessi
    (app/services/permissions.py). E' l'unico punto in cui i due filtri
    vengono messi: chi parte da qui non se li puo' dimenticare, che e' lo
    stesso principio di _progetti_visibili() nella sessione 5 (D-043).
    """
    interrogazione = (
        select(Document)
        .join(Project, Document.project_id == Project.id)
        .where(Document.deleted_at.is_(None))
    )

    filtro = permissions.filtro_visibilita(utente)
    if filtro is not None:
        interrogazione = interrogazione.where(filtro)

    return interrogazione


def _filtra(
    interrogazione: Select[Any],
    *,
    project_id: uuid.UUID | None,
    tipo: str | None,
    stato: str | None,
    testo: str | None,
) -> Select[Any]:
    """Aggiunge i filtri della barra di ricerca all'interrogazione.

    Sta in una funzione sua perche' serve due volte, una per contare le righe
    e una per prenderne una pagina: due elenchi di filtri scritti due volte
    prima o poi divergono, e l'impaginazione mostrerebbe un totale che non
    torna. E' la stessa precauzione di products._filtra().

    La ricerca e' **sul solo titolo**, come chiede la sessione. Cercare dentro
    il contenuto dei file e' del rilascio R2.
    """
    if project_id is not None:
        interrogazione = interrogazione.where(Document.project_id == project_id)

    if tipo:
        interrogazione = interrogazione.where(Document.doc_type == tipo)

    if stato:
        interrogazione = interrogazione.where(Document.state == stato)

    if testo:
        parola = f"%{testo.strip()}%"
        interrogazione = interrogazione.where(Document.title.ilike(parola))

    return interrogazione


def cerca_documenti(
    db: Session,
    utente: User,
    *,
    project_id: uuid.UUID | None = None,
    tipo: str | None = None,
    stato: str | None = None,
    testo: str | None = None,
    ordina: str = ORDINAMENTO_PREDEFINITO,
    verso: str = "desc",
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[Document], int]:
    """Una pagina di documenti visibili, piu' quanti ne ha trovati in tutto.

    Il totale serve all'impaginazione e alla riga di riepilogo: e' quanti ne
    ha trovati la ricerca, non quanti ne sono stati mostrati.

    Le versioni e i loro autori si caricano insieme ai documenti perche'
    l'elenco mostra la versione corrente, il suo autore e la sua data: senza,
    venticinque righe costerebbero settantacinque interrogazioni.
    """
    colonna = ORDINAMENTI.get(ordina, ORDINAMENTI[ORDINAMENTO_PREDEFINITO])
    verso_sql = colonna.desc() if verso == "desc" else colonna.asc()

    conteggio = _filtra(
        _visibili(utente).with_only_columns(func.count(Document.id)),
        project_id=project_id,
        tipo=tipo,
        stato=stato,
        testo=testo,
    )
    totale = db.scalar(conteggio) or 0

    righe = _filtra(
        _visibili(utente).options(
            selectinload(Document.classification),
            selectinload(Document.versions).selectinload(DocumentVersion.author),
            selectinload(Document.project)
            .selectinload(Project.product_version)
            .selectinload(ProductVersion.product),
        ),
        project_id=project_id,
        tipo=tipo,
        stato=stato,
        testo=testo,
    )

    pagina = max(1, pagina)
    righe = (
        righe.order_by(verso_sql, Document.title)
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
    )

    return list(db.scalars(righe).all()), totale


def documenti_ritirati(db: Session) -> list[Document]:
    """I documenti ritirati, dal piu' recente. Solo per il creatore.

    Non passa da _visibili() perche' quella funzione i ritirati li toglie
    apposta: questa e' la sezione dedicata di cui parla la regola 5 della
    sessione, ed e' l'unico posto in cui compaiono. La rotta che la usa
    dichiara Depends(richiedi_creatore), che e' il lucchetto vero.
    """
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_not(None))
            .options(
                selectinload(Document.classification),
                selectinload(Document.deleted_by),
                selectinload(Document.versions),
                selectinload(Document.project)
                .selectinload(Project.product_version)
                .selectinload(ProductVersion.product),
            )
            .order_by(Document.deleted_at.desc())
        ).all()
    )


def tipi_in_uso(db: Session, utente: User) -> list[str]:
    """I tipi di documento che compaiono davvero fra quelli visibili.

    Riempie la tendina del filtro: dentro ci sono solo tipi su cui qualcosa si
    trova, cosi' scegliendone uno non si finisce mai su un elenco vuoto. E' la
    stessa regola di projects.fasi_in_uso().
    """
    interrogazione = _visibili(utente).with_only_columns(Document.doc_type)
    return list(
        db.scalars(interrogazione.distinct().order_by(Document.doc_type)).all()
    )


def conta_documenti(db: Session, utente: User, project_id: uuid.UUID) -> int:
    """Quanti documenti visibili ha un progetto. Serve alla sua scheda."""
    interrogazione = _filtra(
        _visibili(utente).with_only_columns(func.count(Document.id)),
        project_id=project_id,
        tipo=None,
        stato=None,
        testo=None,
    )
    return db.scalar(interrogazione) or 0


def ultimo_rilascio(db: Session, document_id: uuid.UUID) -> AuditLog | None:
    """La riga di registro del rilascio piu' recente di questo documento.

    Serve alla scheda, che deve dire **chi** ha rilasciato il documento e
    **quando**: e' quello che chiede la regola 4 della sessione. Il dato non
    e' duplicato in una colonna di documents perche' e' gia' scritto nel
    registro delle operazioni, che e' il posto in cui i fatti vengono
    registrati (regola 6 di CLAUDE.md). Duplicarlo vorrebbe dire due verita'
    che possono divergere.
    """
    return db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == ENTITY_DOCUMENTS,
            AuditLog.entity_id == document_id,
            AuditLog.action == ACTION_STATE_CHANGED,
            AuditLog.new_value["state"].astext == DocumentState.RILASCIATO.value,
        )
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.occurred_at.desc())
    ).first()


def scarichi_di(
    db: Session, document_id: uuid.UUID, limite: int = 20
) -> list[AuditLog]:
    """Gli ultimi scarichi registrati per un documento, dal piu' recente.

    E' la meta' visibile della regola 6 della sessione: registrare gli scarichi
    serve a poter rispondere a "chi ha preso questo schema", e per rispondere
    bisogna che qualcuno possa guardare. La scheda del documento ne mostra gli
    ultimi venti.
    """
    return list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == ENTITY_DOCUMENTS,
                AuditLog.entity_id == document_id,
                AuditLog.action == ACTION_DOCUMENT_DOWNLOADED,
            )
            .options(selectinload(AuditLog.user))
            .order_by(AuditLog.occurred_at.desc())
            .limit(limite)
        ).all()
    )


# ---------------------------------------------------------------------------
#  Scrittura
# ---------------------------------------------------------------------------


def _titolo_dal_nome(nome_file: str) -> str:
    """Il titolo da usare quando chi carica non ne ha scritto uno.

    "Schema alimentatore rev C.pdf" diventa "Schema alimentatore rev C". Serve
    al caricamento di piu' file insieme, dove un titolo solo non puo' valere
    per tutti: ogni file diventa un documento e prende come titolo il proprio
    nome. Chi vuole titoli diversi li corregge dopo, ma intanto i file sono
    dentro, che e' quello che conta.
    """
    pulito = (nome_file or "").strip() or "Documento senza nome"
    if "." in pulito[1:]:
        pulito = pulito.rsplit(".", 1)[0]
    return pulito[:LUNGHEZZA_TITOLO]


def _nome_file_sicuro(nome_file: str) -> str:
    """Il nome originale, ridotto a quello che sta nella colonna.

    Non e' una ripulitura di sicurezza: sul disco questo nome non ci arriva
    mai (D-004), quindi non c'e' nessun percorso da difendere. Serve solo a
    non far fallire la scrittura per un nome piu' lungo di 255 caratteri, che
    capita con i file esportati dai programmi di disegno.
    """
    pulito = (nome_file or "").strip() or "documento"
    return pulito[:LUNGHEZZA_NOME_FILE]


def deposita_file(
    caricamento: Caricamento, limite_byte: int | None
) -> storage.Deposito:
    """Mette il contenuto nell'archivio e restituisce l'impronta.

    Sta prima di qualunque scrittura nel database, ed e' voluto: se il file e'
    troppo grande o il disco e' pieno, non e' stata creata nessuna riga da
    annullare. Il contrario - riga prima, file dopo - lascerebbe nel database
    documenti che puntano a un file che non c'e'.

    Il caso opposto (file depositato e transazione annullata) lascia
    nell'archivio un oggetto che nessuno riferisce: non e' un problema. Non
    occupa quasi niente, non si cancella per la regola 5 di CLAUDE.md, e al
    primo caricamento dello stesso contenuto viene riusato dalla
    deduplicazione.
    """
    return storage.deposita(caricamento.sorgente, limite_byte=limite_byte)


def crea_documento(
    db: Session,
    *,
    progetto: Project,
    titolo: str,
    tipo: str,
    classificazione: Classification,
    caricamento: Caricamento,
    deposito: storage.Deposito,
    autore: User,
    request: Request | None = None,
) -> tuple[Document, DocumentVersion]:
    """Crea un documento con la sua versione 1.

    Un documento nasce **sempre** insieme al suo primo file: un contenitore
    vuoto non serve a nessuno e sarebbe soltanto una riga che qualcuno un
    giorno si chiedera' che cosa ci fa li'. E' la stessa scelta di D-040, dove
    un prodotto nasce con la sua versione 1.

    **Un titolo vuoto diventa il nome del file**, senza estensione. Serve al
    caricamento di piu' file insieme, dove un titolo solo non puo' valere per
    tutti: ogni file diventa un documento e prende il proprio nome. La regola
    sta qui e non nella rotta perche' e' una regola, e le regole si provano
    con un test.

    Il contenuto e' gia' nell'archivio: qui arriva il deposito, cioe'
    l'impronta e la dimensione. Chi chiama ha gia' verificato i permessi.
    """
    scelto = titolo.strip() or _titolo_dal_nome(caricamento.nome_file)

    documento = Document(
        project_id=progetto.id,
        title=scelto[:LUNGHEZZA_TITOLO],
        doc_type=tipo.strip()[:LUNGHEZZA_TIPO],
        classification_id=classificazione.id,
        state=DocumentState.BOZZA,
    )
    db.add(documento)
    db.flush()

    audit.record(
        db,
        action=ACTION_DOCUMENT_CREATED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=autore.id,
        request=request,
        new_value={
            "project_id": str(progetto.id),
            "title": documento.title,
            "doc_type": documento.doc_type,
            "classification": classificazione.name,
        },
    )

    versione = _scrivi_versione(
        db,
        documento=documento,
        caricamento=caricamento,
        deposito=deposito,
        nota=None,
        autore=autore,
        request=request,
    )

    logger.info(
        "Documento '%s' creato nel progetto %s da '%s'",
        documento.title,
        progetto.id,
        autore.username,
    )

    return documento, versione


def aggiungi_versione(
    db: Session,
    *,
    documento: Document,
    caricamento: Caricamento,
    deposito: storage.Deposito,
    nota: str,
    autore: User,
    request: Request | None = None,
) -> DocumentVersion:
    """Aggiunge una versione a un documento esistente.

    **La nota e' obbligatoria.** Chi apre la scheda fra un anno deve poter
    leggere che cosa e' cambiato fra la versione 3 e la 4 senza aprire tutti e
    due i file: e' l'unica informazione che nessun programma potra' mai
    ricostruire da solo.

    **Un documento rilasciato torna in bozza.** Non e' una transizione del
    grafo (nessuno preme un pulsante "torna in bozza"): e' la conseguenza del
    caricamento, ed e' il modo in cui la regola "una versione rilasciata non
    si sostituisce" viene rispettata invece che aggirata. La versione
    rilasciata resta dov'e', identica e scaricabile; quella nuova e' una bozza
    che dovra' rifare tutto il giro (D-045).

    Il documento ritirato non accetta versioni: prima si ripristina.
    """
    if documento.is_deleted:
        raise DocumentoEliminato(
            "Questo documento e' stato ritirato: per caricare una versione "
            "nuova bisogna prima ripristinarlo."
        )

    if not nota or not nota.strip():
        raise NotaObbligatoria(
            "Scrivi che cosa cambia rispetto alla versione precedente: e' la "
            "sola informazione che nessuno potra' ricostruire dopo."
        )

    stato_precedente = documento.state

    versione = _scrivi_versione(
        db,
        documento=documento,
        caricamento=caricamento,
        deposito=deposito,
        nota=nota.strip(),
        autore=autore,
        request=request,
    )

    if stato_precedente is not lifecycle.STATO_DOCUMENTO_INIZIALE:
        documento.state = lifecycle.STATO_DOCUMENTO_INIZIALE
        audit.record(
            db,
            action=ACTION_STATE_CHANGED,
            entity_type=ENTITY_DOCUMENTS,
            entity_id=documento.id,
            user_id=autore.id,
            request=request,
            old_value={"state": stato_precedente.value},
            new_value={
                "state": documento.state.value,
                "motivo": "caricamento di una versione nuova",
            },
        )

    return versione


def _scrivi_versione(
    db: Session,
    *,
    documento: Document,
    caricamento: Caricamento,
    deposito: storage.Deposito,
    nota: str | None,
    autore: User,
    request: Request | None = None,
) -> DocumentVersion:
    """Scrive la riga di document_versions e la registra. Non decide niente.

    Sta in una funzione sua perche' la creazione di un documento e l'aggiunta
    di una versione fanno esattamente la stessa cosa: la differenza fra le due
    e' tutta prima (il documento c'e' gia' o va creato) e dopo (lo stato torna
    in bozza o no).
    """
    versione = DocumentVersion(
        document_id=documento.id,
        version_number=prossimo_numero_versione(db, documento.id),
        storage_hash=deposito.impronta,
        original_filename=_nome_file_sicuro(caricamento.nome_file),
        size_bytes=deposito.dimensione,
        mime_type=(caricamento.mime_type or MIME_SCONOSCIUTO)[:120],
        author_id=autore.id,
        note=nota,
    )
    db.add(versione)
    db.flush()

    audit.record(
        db,
        action=ACTION_VERSION_UPLOADED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=autore.id,
        request=request,
        new_value={
            "version_number": versione.version_number,
            "storage_hash": versione.storage_hash,
            "original_filename": versione.original_filename,
            "size_bytes": versione.size_bytes,
            # Serve a poter rispondere, dal solo registro, alla domanda "quanto
            # spazio ci ha fatto risparmiare la deduplicazione".
            "deduplicato": deposito.gia_presente,
        },
    )

    logger.info(
        "Documento %s: caricata la versione %s (%s byte, impronta %s, %s)",
        documento.id,
        versione.version_number,
        versione.size_bytes,
        versione.storage_hash,
        "gia' in archivio" if deposito.gia_presente else "nuova nell'archivio",
    )

    return versione


def cambia_stato(
    db: Session,
    *,
    documento: Document,
    nuovo_stato: DocumentState,
    autore: User,
    request: Request | None = None,
) -> Document:
    """Porta un documento in un altro stato, applicando il grafo.

    Solleva lifecycle.TransizioneNonAmmessa se il passaggio non e' previsto: il
    controllo viene prima di qualunque scrittura, quindi un tentativo rifiutato
    non lascia niente a meta'.

    Il commit non si fa qui: lo fa chi gestisce la richiesta, insieme alle
    righe di audit.
    """
    if documento.is_deleted:
        raise DocumentoEliminato(
            "Questo documento e' stato ritirato: per cambiarne lo stato "
            "bisogna prima ripristinarlo."
        )

    stato_precedente = documento.state
    lifecycle.verifica_transizione_documento(stato_precedente, nuovo_stato)

    documento.state = nuovo_stato

    audit.record(
        db,
        action=ACTION_STATE_CHANGED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=autore.id,
        request=request,
        old_value={"state": stato_precedente.value},
        new_value={"state": nuovo_stato.value},
    )

    logger.info(
        "Documento %s: da '%s' a '%s' per mano di '%s'",
        documento.id,
        stato_precedente.value,
        nuovo_stato.value,
        autore.username,
    )

    return documento


def elimina(
    db: Session,
    *,
    documento: Document,
    autore: User,
    request: Request | None = None,
) -> Document:
    """Ritira un documento dagli elenchi. Nessuna riga viene cancellata.

    Il documento sparisce dagli elenchi ordinari e resta visibile al creatore
    nella sezione dedicata, da cui si ripristina. Le sue versioni restano tutte
    dove sono e **i file nell'archivio non si toccano**: potrebbero essere
    riferiti da altri documenti che hanno lo stesso contenuto (D-004).
    """
    if documento.is_deleted:
        return documento

    documento.deleted_at = datetime.now(timezone.utc)
    documento.deleted_by_id = autore.id

    audit.record(
        db,
        action=ACTION_DOCUMENT_DELETED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=autore.id,
        request=request,
        old_value={"deleted_at": None},
        new_value={"deleted_at": documento.deleted_at.isoformat()},
    )

    logger.info("Documento %s ritirato da '%s'", documento.id, autore.username)
    return documento


def ripristina(
    db: Session,
    *,
    documento: Document,
    autore: User,
    request: Request | None = None,
) -> Document:
    """Rimette un documento ritirato negli elenchi ordinari.

    Torna esattamente com'era: stesso stato, stesse versioni, stessi file. Il
    ritiro non ha buttato via niente, quindi non c'e' niente da ricostruire.
    """
    if not documento.is_deleted:
        return documento

    quando = documento.deleted_at

    documento.deleted_at = None
    documento.deleted_by_id = None

    audit.record(
        db,
        action=ACTION_DOCUMENT_RESTORED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=autore.id,
        request=request,
        old_value={"deleted_at": quando.isoformat() if quando else None},
        new_value={"deleted_at": None},
    )

    logger.info(
        "Documento %s ripristinato da '%s'", documento.id, autore.username
    )
    return documento


def registra_scarico(
    db: Session,
    *,
    documento: Document,
    versione: DocumentVersion,
    utente: User,
    con_filigrana: bool,
    request: Request | None = None,
) -> None:
    """Scrive nel registro che qualcuno ha scaricato una versione.

    E' la regola 6 della sessione, ed e' anche la regola 6 di CLAUDE.md: chi,
    che cosa, quale versione, quando. La domanda a cui serve rispondere e'
    "chi ha in mano lo schema vecchio", e il giorno in cui la si fa e' il
    giorno in cui non si puo' piu' cominciare a registrare.

    Nella riga finisce anche se la copia consegnata portava la filigrana: due
    copie dello stesso file possono essere diverse, e dal registro si deve
    capire quale delle due e' uscita.

    Il commit lo fa la rotta, insieme alla consegna del file.
    """
    audit.record(
        db,
        action=ACTION_DOCUMENT_DOWNLOADED,
        entity_type=ENTITY_DOCUMENTS,
        entity_id=documento.id,
        user_id=utente.id,
        request=request,
        new_value={
            "version_number": versione.version_number,
            "version_id": str(versione.id),
            "original_filename": versione.original_filename,
            "storage_hash": versione.storage_hash,
            "filigrana": con_filigrana,
        },
    )

    logger.info(
        "Scarico: documento %s versione %s da '%s'%s",
        documento.id,
        versione.version_number,
        utente.username,
        " con filigrana" if con_filigrana else "",
    )


# ---------------------------------------------------------------------------
#  Le domande che si fanno le pagine
# ---------------------------------------------------------------------------


def filtri_elenco(
    db: Session, utente: User, tipo: str | None, stato: str | None
) -> list[dict]:
    """I due filtri della barra di ricerca, pronti per il componente.

    Li compone il servizio e non i template perche' le stesse due tendine
    compaiono nell'elenco generale e in quello di un progetto, e devono
    proporre le stesse voci con le stesse parole (docs/GUIDA_STILE.md,
    sezione 5).
    """
    return [
        {
            "nome": "tipo",
            "etichetta": "Tipo di documento",
            "opzioni": [(voce, voce) for voce in tipi_in_uso(db, utente)],
            "scelto": tipo or "",
            "vuoto": "Qualunque tipo",
        },
        {
            "nome": "stato",
            "etichetta": "Stato del documento",
            "opzioni": lifecycle.opzioni_stati_documento(),
            "scelto": stato or "",
            "vuoto": "Qualunque stato",
        },
    ]


def peso_leggibile(byte: int) -> str:
    """La dimensione di un file come la scriverebbe una persona.

    Sta qui e non in un filtro Jinja perche' e' una regola - dove sta la
    virgola, quando si passa ai megabyte - e le regole non si provano con un
    test se stanno dentro l'HTML.
    """
    if byte < 1024:
        return f"{byte} byte"
    if byte < 1024 * 1024:
        return f"{byte / 1024:.0f} kB"
    if byte < 1024 * 1024 * 1024:
        return f"{byte / (1024 * 1024):.1f} MB"
    return f"{byte / (1024 * 1024 * 1024):.2f} GB"
