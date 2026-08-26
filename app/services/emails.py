"""Il motore che archivia la posta e la attacca alla versione giusta.

Prende i messaggi da una `FonteEmail` (app/services/mail_source.py), li fa
leggere a `email_parsing.py` e ne fa righe di `email_messages` e
`email_attachments`. Non sa da dove arrivino i messaggi e non sa come sono
fatti dentro: sa che cosa farne.

    fonte  -->  email_parsing  -->  QUESTO FILE  -->  database + archivio
    dove       che cosa c'e'       a chi appartiene


LE QUATTRO STRADE DELL'ATTRIBUZIONE, IN ORDINE
----------------------------------------------

Un messaggio appartiene a una **versione di prodotto**, non a un progetto: la
corrispondenza con il cliente continua anche dopo che il progetto e' chiuso e
il prodotto e' in produzione. Per capire a quale, si prova nell'ordine:

  a. **l'oggetto formattato** `[RMS1100-24-110SW][V2][SPECS]`, riconosciuto
     anche dietro a "R:", "Re:", "Fwd:", "I:" e a qualunque combinazione di
     maiuscole e spazi;
  b. **il codice prodotto scritto in mezzo alla frase**, senza parentesi;
  c. **il filo di conversazione**: se un messaggio dello stesso scambio e'
     gia' archiviato e attribuito, si eredita la sua attribuzione;
  d. **la quarantena**, che non e' un errore ma una domanda a una persona.

L'ordine non e' casuale: e' dal piu' esplicito al piu' congetturale. Chi ha
scritto `[RMS1100-24-110SW][V2]` nell'oggetto ha detto esattamente dove
voleva finire, e nessuna deduzione successiva deve poterlo smentire.


TRE REGOLE CHE VALGONO SEMPRE
-----------------------------

**Ripetibile all'infinito.** L'identificativo del messaggio (`Message-ID`) e'
unico: un messaggio gia' archiviato viene riconosciuto e saltato, senza errori
e senza doppioni. I messaggi che il `Message-ID` non ce l'hanno - i file rotti
- ne ricevono uno ricavato dall'impronta del file, che e' altrettanto stabile.

**Un messaggio per volta, una transazione per volta.** L'elaborazione di un
messaggio finisce con un `commit()` suo, ed e' l'unico punto di Aurora in cui
un servizio decide quando scrivere invece di lasciarlo alla rotta. La ragione
sta nel punto 7 della sessione: un errore su un messaggio non deve interrompere
gli altri, e con una transazione unica per tutto il giro il primo messaggio
storto porterebbe con se' i cinquecento gia' fatti. Vedi D-070.

**Mai scartare.** Anche il file rotto viene archiviato: il `.eml` va
nell'archivio per impronta come tutti gli altri file (D-004), la riga viene
scritta, e il messaggio finisce in quarantena con scritto perche'. Un
messaggio che Aurora non capisce e' comunque un messaggio che l'azienda ha
ricevuto.
"""

import io
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    EmailAssignmentState,
    EmailAttachment,
    EmailMessage,
    LifecycleState,
    Product,
    ProductVersion,
    Project,
    User,
)
from app.services import audit, email_reasons, etichette, permissions, storage
from app.services.email_parsing import (
    MessaggioLetto,
    elementi_candidati,
    identificativi_in,
    leggi_messaggio,
)
from app.services.mail_source import FonteEmail, MessaggioNonTrovato

logger = logging.getLogger("aurora.posta")


# --- Le azioni registrate nel registro delle operazioni ---------------------
#
# Le prime due erano gia' in audit.CATALOGO dalla sessione 9, scritte in
# anticipo apposta: "il giorno in cui quella pagina nascera', registrare
# l'operazione sara' una riga sola invece di una discussione su come
# chiamarla". Il giorno e' oggi.

ACTION_EMAIL_ARCHIVED = "email.archived"
ACTION_EMAIL_QUARANTINED = "email.quarantined"
ACTION_EMAIL_ASSIGNED_MANUAL = "email.assigned_manual"
ACTION_EMAIL_DOWNLOAD = "email.download"

ENTITY_EMAILS = "email_messages"


# --- Come un messaggio e' stato attribuito ---------------------------------
#
# Sono i nomi delle quattro strade, quelli che finiscono dentro
# subject_parsed["via"] e che la pagina del messaggio traduce in italiano.
# Sono identificatori e stanno in inglese come tutto il resto del codice; le
# frasi italiane sono qui sotto, in NOMI_VIA.

VIA_OGGETTO = "subject_format"
VIA_OGGETTO_LIBERO = "subject_text"
VIA_CONVERSAZIONE = "thread"
VIA_MANUALE = "manual"

NOMI_VIA: dict[str, str] = {
    VIA_OGGETTO: "dal codice nell'oggetto, scritto fra parentesi",
    VIA_OGGETTO_LIBERO: "dal codice trovato nell'oggetto",
    VIA_CONVERSAZIONE: "ereditata da un altro messaggio della conversazione",
    VIA_MANUALE: "assegnata a mano",
}


# --- Gli stati del ciclo di vita che chiudono una versione ------------------
#
# "La versione piu' recente non chiusa" e' la versione con il numero piu' alto
# fra quelle che non sono ne' superate ne' obsolete. Le due costanti stanno
# qui e non in lifecycle.py perche' non sono una transizione: sono il modo in
# cui la posta legge lo stato, e lifecycle.py e' il file dei **passaggi** fra
# stati (CLAUDE.md, sezione 8).
STATI_CHIUSI: tuple[LifecycleState, ...] = (
    LifecycleState.SUPERATO,
    LifecycleState.OBSOLETO,
)


# --- Gli esiti dell'elaborazione di un messaggio ----------------------------

STATO_ARCHIVIATO = "archiviato"
STATO_QUARANTENA = "quarantena"
STATO_GIA_PRESENTE = "gia_presente"
STATO_ERRORE = "errore"

# Le frasi della quarantena. Sono qui e non sparse nel codice perche' le legge
# una persona che deve decidere che cosa fare, e due frasi diverse per la
# stessa situazione la manderebbero a cercare una differenza che non c'e'.
MOTIVO_NESSUN_CODICE = (
    "Nell'oggetto non c'e' nessun codice prodotto che Aurora riconosca, e "
    "nessun altro messaggio della conversazione e' gia' archiviato."
)
MOTIVO_VERSIONE_INESISTENTE = (
    "L'oggetto chiede la versione {versione} del prodotto {codice}, che non "
    "esiste. Aurora non ne sceglie un'altra al posto tuo."
)
MOTIVO_PRODOTTO_SENZA_VERSIONI = (
    "Il prodotto {codice} e' stato riconosciuto ma non ha nessuna versione a "
    "cui attaccare il messaggio."
)

# Quanti giri al massimo fa la ricostruzione di un filo di conversazione.
# Tre bastano: l'intestazione References contiene gia' tutta la catena, e il
# giro serve solo per i programmi di posta che la scrivono a meta'.
GIRI_DEL_FILO = 3

# Quanti messaggi si guardano al massimo cercando chi cita il nostro
# identificativo. Un filo di conversazione vero non arriva a tanto, e il
# limite impedisce che un identificativo cortissimo, finito per caso dentro
# mille References, faccia leggere mezza tabella.
MASSIMI_CANDIDATI_DEL_FILO = 200


@dataclass(frozen=True)
class Attribuzione:
    """A quale versione appartiene un messaggio, e come lo si e' capito.

    versione            la versione di prodotto, o None per la quarantena;
    via                 quale delle quattro strade ha risposto;
    motivo_quarantena   la frase in italiano che spiega perche' non e' stato
                        attribuito. Valorizzata **solo** quando versione e'
                        None: e' quella che si legge nella pagina della
                        quarantena, ed e' quella che dice a chi guarda se ha
                        davanti un errore di battitura del mittente o un
                        prodotto che in Aurora non c'e' ancora.
    """

    versione: ProductVersion | None
    via: str | None = None
    motivo_quarantena: str | None = None

    @property
    def attribuito(self) -> bool:
        """Vero quando il messaggio ha trovato la sua versione."""
        return self.versione is not None


@dataclass(frozen=True)
class Esito:
    """Come e' andata con un messaggio.

    identificativo   quello con cui la fonte chiama il messaggio (per
                     FonteLocale e' il nome del file);
    stato            archiviato, quarantena, gia_presente, errore;
    messaggio        la riga scritta o quella che c'era gia', quando c'e';
    dettaglio        una frase in italiano, da mostrare a chi ha avviato
                     l'elaborazione.
    """

    identificativo: str
    stato: str
    messaggio: EmailMessage | None = None
    dettaglio: str = ""


@dataclass(frozen=True)
class Riepilogo:
    """Com'e' andato un giro di acquisizione, messaggio per messaggio."""

    esiti: tuple[Esito, ...]

    def _quanti(self, stato: str) -> int:
        return sum(1 for esito in self.esiti if esito.stato == stato)

    @property
    def letti(self) -> int:
        """Quanti messaggi sono stati presi in mano."""
        return len(self.esiti)

    @property
    def archiviati(self) -> int:
        """Quanti sono stati archiviati e attribuiti a una versione."""
        return self._quanti(STATO_ARCHIVIATO)

    @property
    def in_quarantena(self) -> int:
        """Quanti sono stati archiviati ma non attribuiti."""
        return self._quanti(STATO_QUARANTENA)

    @property
    def gia_presenti(self) -> int:
        """Quanti c'erano gia' e sono stati saltati senza fare niente."""
        return self._quanti(STATO_GIA_PRESENTE)

    @property
    def errori(self) -> int:
        """Su quanti qualcosa e' andato storto. Restano nella cartella."""
        return self._quanti(STATO_ERRORE)

    @property
    def messaggi_di_errore(self) -> list[str]:
        """Le frasi degli esiti andati storti, per mostrarle in pagina."""
        return [
            f"{esito.identificativo}: {esito.dettaglio}"
            for esito in self.esiti
            if esito.stato == STATO_ERRORE
        ]


# ---------------------------------------------------------------------------
#  1. L'ATTRIBUZIONE
# ---------------------------------------------------------------------------


def _prodotto_per_codice(db: Session, codice: str) -> Product | None:
    """Il prodotto con quel codice, senza distinzione di maiuscole.

    Il confronto ignora le maiuscole perche' il codice lo scrive una persona
    dentro l'oggetto di un messaggio, e nessuno controlla il tasto delle
    maiuscole mentre scrive a un cliente.

    **Anche i prodotti disattivati contano.** Un prodotto messo da parte
    continua a ricevere posta - una richiesta di ricambi, una contestazione -
    e mandare quella posta in quarantena vorrebbe dire chiedere a una persona
    di rispondere a una domanda a cui il programma sa gia' rispondere.
    """
    pulito = (codice or "").strip()
    if not pulito:
        return None

    return db.scalars(
        select(Product).where(func.upper(Product.code) == pulito.upper())
    ).first()


def _prodotto_fra_gli_elementi(db: Session, oggetto: str | None) -> Product | None:
    """Il prodotto il cui codice compare da qualche parte nell'oggetto.

    E' la seconda strada dell'attribuzione: il codice scritto in mezzo alla
    frase, senza parentesi. Si estraggono le parole che potrebbero essere un
    codice e si chiede al database quali lo sono davvero, con una
    interrogazione sola invece di una per parola.

    A parita' di corrispondenza vince **l'elemento piu' lungo**: se esistono
    "RMS1100" e "RMS1100-24" e l'oggetto contiene il secondo, il messaggio va
    al secondo. La corrispondenza piu' specifica e' quella che chi ha scritto
    l'oggetto aveva in mente.
    """
    candidati = elementi_candidati(oggetto)
    if not candidati:
        return None

    trovati = db.scalars(
        select(Product).where(
            func.upper(Product.code).in_([voce.upper() for voce in candidati])
        )
    ).all()
    if not trovati:
        return None

    per_codice = {prodotto.code.upper(): prodotto for prodotto in trovati}

    # I candidati sono gia' ordinati dal piu' lungo al piu' corto.
    for candidato in candidati:
        prodotto = per_codice.get(candidato.upper())
        if prodotto is not None:
            return prodotto

    return None


def versione_da_usare(db: Session, prodotto: Product) -> ProductVersion | None:
    """La versione a cui attaccare un messaggio che non ne indica una.

    **La piu' recente non chiusa**, come chiede la sessione: il numero piu'
    alto fra le versioni che non sono superate ne' obsolete. E' quella su cui
    si sta lavorando, ed e' quella di cui si parla scrivendo senza precisare.

    Quando sono chiuse **tutte** si prende comunque la piu' recente. Non e'
    una deroga alla regola: e' il caso in cui la regola non ha candidati, e
    l'alternativa sarebbe mandare in quarantena un messaggio di cui si conosce
    il prodotto con certezza. Un prodotto fuori produzione riceve posta - una
    contestazione, una richiesta di ricambi - e quella posta appartiene alla
    sua ultima versione (D-072).
    """
    versioni = db.scalars(
        select(ProductVersion)
        .where(ProductVersion.product_id == prodotto.id)
        .order_by(ProductVersion.version_number.desc())
    ).all()

    if not versioni:
        return None

    for versione in versioni:
        if versione.lifecycle_state not in STATI_CHIUSI:
            return versione

    return versioni[0]


def _versione_numero(
    db: Session, prodotto: Product, numero: int
) -> ProductVersion | None:
    """La versione con quel numero, di quel prodotto."""
    return db.scalars(
        select(ProductVersion).where(
            ProductVersion.product_id == prodotto.id,
            ProductVersion.version_number == numero,
        )
    ).first()


def _identificativi_del_filo(letto: MessaggioLetto) -> list[str]:
    """Gli identificativi degli altri messaggi dello scambio, dal piu' vicino.

    Prima quello di In-Reply-To, che e' il messaggio a cui si sta rispondendo
    e quindi il parente piu' stretto; poi quelli di References al contrario,
    perche' i programmi di posta li scrivono dal piu' vecchio al piu' recente
    e qui si vuole l'ordine opposto.

    L'ordine conta: se due messaggi dello stesso filo sono attribuiti a due
    versioni diverse - capita quando una conversazione lunga scavalca il
    rilascio di una versione nuova - si eredita da quello piu' vicino.
    """
    vicini = identificativi_in(letto.in_risposta_a)
    lontani = list(reversed(identificativi_in(letto.riferimenti)))

    ordinati: list[str] = []
    for identificativo in vicini + lontani:
        if identificativo not in ordinati:
            ordinati.append(identificativo)
    return ordinati


def _versione_dal_filo(db: Session, letto: MessaggioLetto) -> ProductVersion | None:
    """La versione ereditata da un altro messaggio della stessa conversazione.

    Si guarda in **tutte e due le direzioni**, e non e' un lusso: i file di una
    cartella si leggono in ordine di nome, quindi puo' benissimo capitare di
    archiviare prima la risposta e poi il messaggio originale.

      - i messaggi che **noi citiamo** (In-Reply-To, References);
      - i messaggi che **citano noi**, cioe' quelli il cui In-Reply-To o le cui
        References contengono il nostro identificativo.

    Contano solo i messaggi gia' attribuiti: da uno in quarantena non c'e'
    niente da ereditare.
    """
    identificativi = _identificativi_del_filo(letto)

    if identificativi:
        parenti = db.scalars(
            select(EmailMessage).where(
                EmailMessage.internet_message_id.in_(identificativi),
                EmailMessage.product_version_id.is_not(None),
            )
        ).all()

        # L'ordine dell'IN non e' quello dell'elenco: si riordina qui, dal
        # parente piu' stretto.
        per_identificativo = {
            parente.internet_message_id: parente for parente in parenti
        }
        for identificativo in identificativi:
            parente = per_identificativo.get(identificativo)
            if parente is not None:
                return parente.product_version

    # L'altra direzione: chi cita noi. Il confronto e' un "contiene" perche'
    # References e' un'intestazione di testo con dentro piu' identificativi;
    # autoescape=True impedisce che un identificativo con dentro "%" o "_" si
    # trasformi in un carattere jolly.
    nostro = letto.identificativo
    figli = db.scalars(
        select(EmailMessage)
        .where(
            EmailMessage.product_version_id.is_not(None),
            or_(
                EmailMessage.in_reply_to.contains(nostro, autoescape=True),
                EmailMessage.thread_references.contains(nostro, autoescape=True),
            ),
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(MASSIMI_CANDIDATI_DEL_FILO)
    ).all()

    for figlio in figli:
        return figlio.product_version

    return None


def attribuisci(db: Session, letto: MessaggioLetto) -> Attribuzione:
    """A quale versione di prodotto appartiene questo messaggio.

    Prova le quattro strade nell'ordine scritto in cima al file. Non scrive
    niente: e' una domanda, e la risposta la usa `elabora_messaggio()`.

    **Un caso merita di essere letto due volte.** Quando l'oggetto dichiara una
    versione che non esiste - `[RMS1100-24-110SW][V7]` su un prodotto che di
    versioni ne ha due - il messaggio va in quarantena e **non** si prosegue
    con le strade b e c. Il prodotto lo conosciamo, quindi la strada b
    troverebbe lo stesso codice e attaccherebbe il messaggio alla versione
    piu' recente, cioe' a una versione diversa da quella che il mittente ha
    scritto. Fra attaccare la posta alla versione sbagliata e chiedere a una
    persona, si chiede: le mail sono il posto dove stanno meta' delle
    decisioni, e una decisione archiviata sotto la versione sbagliata e' una
    decisione persa (D-073).
    """
    scomposizione = letto.scomposizione

    # (a) l'oggetto formattato, dietro a qualunque prefisso di risposta.
    if scomposizione.codice:
        prodotto = _prodotto_per_codice(db, scomposizione.codice)
        if prodotto is not None:
            if scomposizione.versione is not None:
                versione = _versione_numero(db, prodotto, scomposizione.versione)
                if versione is None:
                    return Attribuzione(
                        versione=None,
                        motivo_quarantena=MOTIVO_VERSIONE_INESISTENTE.format(
                            versione=scomposizione.versione, codice=prodotto.code
                        ),
                    )
                return Attribuzione(versione=versione, via=VIA_OGGETTO)

            versione = versione_da_usare(db, prodotto)
            if versione is None:
                return Attribuzione(
                    versione=None,
                    motivo_quarantena=MOTIVO_PRODOTTO_SENZA_VERSIONI.format(
                        codice=prodotto.code
                    ),
                )
            return Attribuzione(versione=versione, via=VIA_OGGETTO)

    # (b) il codice scritto in mezzo alla frase, senza parentesi.
    prodotto = _prodotto_fra_gli_elementi(db, letto.oggetto)
    if prodotto is not None:
        versione = versione_da_usare(db, prodotto)
        if versione is not None:
            return Attribuzione(versione=versione, via=VIA_OGGETTO_LIBERO)

    # (c) il filo di conversazione.
    ereditata = _versione_dal_filo(db, letto)
    if ereditata is not None:
        return Attribuzione(versione=ereditata, via=VIA_CONVERSAZIONE)

    # (d) la quarantena.
    return Attribuzione(versione=None, motivo_quarantena=MOTIVO_NESSUN_CODICE)


def _scomposizione_da_scrivere(
    db: Session, letto: MessaggioLetto, attribuzione: Attribuzione
) -> dict[str, Any]:
    """Che cosa finisce in `email_messages.subject_parsed`.

    E' un dato **ricavato**, come `products.code_parts`: serve a spiegare in
    pagina perche' un messaggio e' finito dov'e', e a ritrovare i messaggi con
    un motivo sconosciuto. Non e' la fonte della verita' di niente, e
    ricalcolarlo domani con regole diverse non farebbe danni.

    "motivo_riconosciuto" e' falso quando la terza parentesi contiene una
    sigla che non e' fra i motivi ammessi. Non impedisce l'attribuzione - il
    codice prodotto e' quello che conta - ma resta scritto, cosi' chi
    amministra puo' accorgersi che ne serve uno nuovo.
    """
    scomposizione = letto.scomposizione

    scritto: dict[str, Any] = {
        "oggetto_pulito": scomposizione.pulito,
        "prefissi": list(scomposizione.prefissi),
        "formattato": scomposizione.formattato,
        "via": attribuzione.via,
    }

    if scomposizione.codice:
        scritto["codice"] = scomposizione.codice
    if scomposizione.versione is not None:
        scritto["versione"] = scomposizione.versione
    if scomposizione.motivo:
        motivo = email_reasons.normalizza(scomposizione.motivo)
        scritto["motivo"] = motivo
        scritto["motivo_riconosciuto"] = motivo in email_reasons.codici_ammessi(db)
    if letto.difetti:
        scritto["difetti"] = list(letto.difetti)
    if letto.identificativo_costruito:
        scritto["identificativo_costruito"] = True

    return scritto


# ---------------------------------------------------------------------------
#  2. L'ELABORAZIONE DI UN MESSAGGIO
# ---------------------------------------------------------------------------


def trova_per_identificativo(db: Session, identificativo: str) -> EmailMessage | None:
    """Il messaggio gia' archiviato con quel Message-ID, se c'e'.

    E' la funzione che rende ripetibile tutta l'acquisizione: prima di
    scrivere qualunque cosa si chiede se quel messaggio c'e' gia'.
    """
    if not identificativo:
        return None

    return db.scalars(
        select(EmailMessage).where(
            EmailMessage.internet_message_id == identificativo
        )
    ).first()


def _scrivi_messaggio(
    db: Session,
    *,
    letto: MessaggioLetto,
    deposito: storage.Deposito,
    depositi_allegati: list[tuple[Any, storage.Deposito]],
    attribuzione: Attribuzione,
    identificativo_fonte: str,
) -> EmailMessage:
    """Costruisce le righe del messaggio e dei suoi allegati.

    Non fa commit e non registra niente nell'audit trail: fa una cosa sola, e
    chi la chiama la mette dentro la transazione insieme al resto.
    """
    messaggio = EmailMessage(
        product_version_id=(
            attribuzione.versione.id if attribuzione.versione is not None else None
        ),
        internet_message_id=letto.identificativo,
        in_reply_to=letto.in_risposta_a,
        thread_references=letto.riferimenti,
        sender=letto.mittente,
        recipients=letto.destinatari,
        subject=letto.oggetto,
        subject_parsed=_scomposizione_da_scrivere(db, letto, attribuzione),
        sent_at=letto.inviato_il,
        received_at=datetime.now(timezone.utc),
        storage_hash=deposito.impronta,
        body_text=letto.corpo,
        assignment_state=(
            EmailAssignmentState.AUTOMATICA
            if attribuzione.attribuito
            else EmailAssignmentState.QUARANTENA
        ),
        quarantine_reason=attribuzione.motivo_quarantena,
        source_reference=identificativo_fonte[:400] or None,
    )
    db.add(messaggio)
    db.flush()

    for allegato, deposito_allegato in depositi_allegati:
        db.add(
            EmailAttachment(
                email_message_id=messaggio.id,
                filename=allegato.nome_file,
                storage_hash=deposito_allegato.impronta,
                size_bytes=deposito_allegato.dimensione,
                mime_type=allegato.mime_type,
            )
        )
    db.flush()

    return messaggio


def elabora_messaggio(
    db: Session,
    dati: bytes,
    *,
    identificativo_fonte: str,
    autore: User | None = None,
    request: Request | None = None,
) -> Esito:
    """Archivia un messaggio. **Non solleva mai** e chiude la transazione.

    Il giro, e l'ordine conta:

      1. si legge il messaggio - questa parte non tocca il database;
      2. si guarda se quel `Message-ID` c'e' gia': se c'e' si esce subito
         senza scrivere niente. E' la ripetibilita';
      3. il `.eml` per intero e ogni allegato vanno nell'archivio per
         impronta, **prima** di qualunque riga. Se il disco e' pieno non e'
         stata creata nessuna riga da annullare (e' lo stesso ordine di
         `documents.deposita_file()`);
      4. si attribuisce, si scrivono le righe, si registra l'operazione;
      5. `commit()`.

    Qualunque cosa vada storta fra il 3 e il 5 produce un `rollback()` e un
    esito di errore: nel database non resta niente di parziale e il messaggio
    resta nella cartella, quindi si riprovera' al giro successivo (punto 6
    della sessione). Nell'archivio puo' restare un file che non riferisce
    nessuno: non e' un problema, non si cancella (regola 5 di CLAUDE.md) e la
    deduplicazione lo riusera' al tentativo successivo.
    """
    if len(dati) > settings.max_upload_bytes:
        return Esito(
            identificativo=identificativo_fonte,
            stato=STATO_ERRORE,
            dettaglio=(
                "il messaggio supera la dimensione massima consentita per un "
                "file caricato"
            ),
        )

    letto = leggi_messaggio(dati)

    esistente = trova_per_identificativo(db, letto.identificativo)
    if esistente is not None:
        return Esito(
            identificativo=identificativo_fonte,
            stato=STATO_GIA_PRESENTE,
            messaggio=esistente,
            dettaglio="era gia' archiviato",
        )

    try:
        deposito = storage.deposita(
            io.BytesIO(dati), limite_byte=settings.max_upload_bytes
        )

        depositi_allegati = [
            (allegato, storage.deposita(io.BytesIO(allegato.contenuto)))
            for allegato in letto.allegati
        ]

        attribuzione = attribuisci(db, letto)

        messaggio = _scrivi_messaggio(
            db,
            letto=letto,
            deposito=deposito,
            depositi_allegati=depositi_allegati,
            attribuzione=attribuzione,
            identificativo_fonte=identificativo_fonte,
        )

        _registra_archiviazione(
            db,
            messaggio=messaggio,
            attribuzione=attribuzione,
            letto=letto,
            autore=autore,
            request=request,
        )

        db.commit()

    except IntegrityError:
        # Due giri di acquisizione contemporanei, o lo stesso file presente
        # due volte nella cartella con due nomi: il vincolo di unicita' su
        # internet_message_id ha fatto il suo mestiere. Non e' un errore, e'
        # la ripetibilita' che funziona anche sotto concorrenza.
        db.rollback()
        esistente = trova_per_identificativo(db, letto.identificativo)
        logger.info(
            "Il messaggio %s risultava gia' archiviato al momento della "
            "scrittura: non e' stato duplicato",
            letto.identificativo,
        )
        return Esito(
            identificativo=identificativo_fonte,
            stato=STATO_GIA_PRESENTE,
            messaggio=esistente,
            dettaglio="era gia' archiviato",
        )

    except (SQLAlchemyError, OSError, storage.FileTroppoGrande) as errore:
        db.rollback()
        logger.error(
            "Il messaggio '%s' non e' stato archiviato: %s",
            identificativo_fonte,
            errore,
        )
        return Esito(
            identificativo=identificativo_fonte,
            stato=STATO_ERRORE,
            dettaglio="non e' stato possibile archiviarlo; resta da elaborare",
        )

    if attribuzione.attribuito:
        return Esito(
            identificativo=identificativo_fonte,
            stato=STATO_ARCHIVIATO,
            messaggio=messaggio,
            dettaglio=f"attribuito a {etichette.nome_versione(attribuzione.versione)}",
        )

    return Esito(
        identificativo=identificativo_fonte,
        stato=STATO_QUARANTENA,
        messaggio=messaggio,
        dettaglio=attribuzione.motivo_quarantena or "",
    )


def _registra_archiviazione(
    db: Session,
    *,
    messaggio: EmailMessage,
    attribuzione: Attribuzione,
    letto: MessaggioLetto,
    autore: User | None,
    request: Request | None,
) -> None:
    """Scrive nel registro delle operazioni che il messaggio e' entrato.

    Una riga per messaggio, e una sola: `email.archived` quando l'attribuzione
    e' riuscita, `email.quarantined` quando no. Scriverne due per lo stesso
    fatto - archiviato **e** in quarantena - renderebbe illeggibile il conteggio
    delle voci del registro, e la differenza fra i due casi e' proprio quello
    che una riga sola deve dire.

    "user_id" puo' essere nullo: l'acquisizione la puo' avviare una persona
    dalla pagina della posta oppure, dalla sessione 11, un lavoro pianificato.
    Nel secondo caso non c'e' nessuna persona a cui attribuire il fatto, e
    scriverci dentro un utente qualunque sarebbe una bugia.
    """
    if attribuzione.attribuito:
        audit.record(
            db,
            action=ACTION_EMAIL_ARCHIVED,
            entity_type=ENTITY_EMAILS,
            entity_id=messaggio.id,
            user_id=autore.id if autore is not None else None,
            request=request,
            etichetta=etichette.nome_messaggio(messaggio),
            new_value={
                "versione": etichette.nome_versione(attribuzione.versione),
                "attribuzione": NOMI_VIA.get(attribuzione.via or "", ""),
                "allegati": len(letto.allegati),
            },
        )
        return

    audit.record(
        db,
        action=ACTION_EMAIL_QUARANTINED,
        entity_type=ENTITY_EMAILS,
        entity_id=messaggio.id,
        user_id=autore.id if autore is not None else None,
        request=request,
        etichetta=etichette.nome_messaggio(messaggio),
        new_value={
            "motivo": attribuzione.motivo_quarantena or "",
            "allegati": len(letto.allegati),
        },
    )


# ---------------------------------------------------------------------------
#  3. IL GIRO COMPLETO
# ---------------------------------------------------------------------------


def acquisisci(
    db: Session,
    fonte: FonteEmail,
    *,
    autore: User | None = None,
    request: Request | None = None,
) -> Riepilogo:
    """Prende tutti i messaggi che la fonte ha da dare e li archivia.

    **Un messaggio storto non ferma gli altri** (punto 7 della sessione): ogni
    messaggio ha la sua transazione e il suo esito, e il giro prosegue.

    Lo spostamento nella fonte avviene **dopo** il commit, ed e' voluto. Se il
    programma si spegne in mezzo, il file resta dov'e' e al giro successivo
    viene riletto, riconosciuto come gia' archiviato e spostato allora: la
    cartella si svuota comunque e nel database non compare niente due volte.
    L'ordine inverso perderebbe il messaggio per sempre.

    I messaggi che erano gia' archiviati vengono spostati nella cartella che
    corrisponde a **dove sono adesso**: un messaggio archiviato ieri e ancora
    in quarantena va in `quarantena/`, uno gia' attribuito va in `elaborate/`.
    Cosi' guardando le due cartelle si vede lo stesso quadro che si vede in
    Aurora.
    """
    identificativi = fonte.elenca_nuovi_messaggi()
    logger.info("Acquisizione della posta: %s messaggi da leggere", len(identificativi))

    esiti: list[Esito] = []

    for identificativo in identificativi:
        try:
            dati = fonte.scarica_messaggio_grezzo(identificativo)
        except MessaggioNonTrovato as errore:
            logger.warning("Messaggio saltato: %s", errore)
            esiti.append(
                Esito(
                    identificativo=identificativo,
                    stato=STATO_ERRORE,
                    dettaglio="non e' piu' disponibile nella cartella",
                )
            )
            continue

        esito = elabora_messaggio(
            db,
            dati,
            identificativo_fonte=identificativo,
            autore=autore,
            request=request,
        )
        esiti.append(esito)

        _sposta_nella_fonte(fonte, identificativo, esito)

    riepilogo = Riepilogo(esiti=tuple(esiti))
    logger.info(
        "Acquisizione finita: %s archiviati, %s in quarantena, %s gia' "
        "presenti, %s errori",
        riepilogo.archiviati,
        riepilogo.in_quarantena,
        riepilogo.gia_presenti,
        riepilogo.errori,
    )
    return riepilogo


def _sposta_nella_fonte(fonte: FonteEmail, identificativo: str, esito: Esito) -> None:
    """Dice alla fonte dove mettere il messaggio appena trattato.

    Un errore lascia il file dov'e': e' l'unico modo perche' il giro
    successivo lo riprovi.
    """
    if esito.stato == STATO_ERRORE:
        return

    if esito.stato == STATO_QUARANTENA:
        fonte.sposta_in_quarantena(identificativo)
        return

    if esito.stato == STATO_GIA_PRESENTE and esito.messaggio is not None:
        in_quarantena = (
            esito.messaggio.assignment_state == EmailAssignmentState.QUARANTENA
        )
        if in_quarantena:
            fonte.sposta_in_quarantena(identificativo)
            return

    fonte.marca_elaborato(identificativo)


# ---------------------------------------------------------------------------
#  4. IL FILO DI CONVERSAZIONE
# ---------------------------------------------------------------------------


def messaggi_del_filo(
    db: Session, messaggio: EmailMessage, includi_se_stesso: bool = False
) -> list[EmailMessage]:
    """Gli altri messaggi della stessa conversazione, gia' archiviati.

    Serve alla pagina della quarantena: assegnando a mano un messaggio si
    propone di assegnare anche gli altri dello stesso scambio, perche' una
    conversazione appartiene tutta allo stesso prodotto e assegnarne dodici uno
    per volta e' il modo piu' sicuro di smettere di usare la quarantena.

    L'insieme si costruisce a giri: si parte dagli identificativi che questo
    messaggio conosce, si cercano i messaggi che li portano o che li citano, e
    si ricomincia con gli identificativi appena trovati. Bastano pochi giri -
    l'intestazione References contiene gia' tutta la catena - e il limite di
    GIRI_DEL_FILO impedisce che una conversazione lunghissima faccia leggere
    mezza tabella.

    L'ordine e' cronologico, come tutti gli elenchi di posta di Aurora.
    """
    conosciuti: set[str] = {messaggio.internet_message_id}
    conosciuti.update(_identificativi_scritti(messaggio))

    trovati: dict[uuid.UUID, EmailMessage] = {messaggio.id: messaggio}

    for _ in range(GIRI_DEL_FILO):
        nuovi = _messaggi_che_toccano(db, conosciuti, trovati.keys())
        if not nuovi:
            break

        for trovato in nuovi:
            trovati[trovato.id] = trovato
            conosciuti.add(trovato.internet_message_id)
            conosciuti.update(_identificativi_scritti(trovato))

    elenco = sorted(
        trovati.values(),
        key=lambda riga: riga.sent_at or riga.received_at,
    )

    if includi_se_stesso:
        return elenco
    return [riga for riga in elenco if riga.id != messaggio.id]


def _identificativi_scritti(messaggio: EmailMessage) -> list[str]:
    """Gli identificativi che un messaggio archiviato cita nelle intestazioni."""
    return identificativi_in(messaggio.in_reply_to) + identificativi_in(
        messaggio.thread_references
    )


def _messaggi_che_toccano(
    db: Session, identificativi: set[str], gia_visti
) -> list[EmailMessage]:
    """I messaggi archiviati che portano o che citano uno di quegli id.

    Le due condizioni sono le due direzioni del filo: il messaggio **e'** uno
    di quelli citati, oppure **cita** uno di quelli conosciuti. Senza la
    seconda, un messaggio a cui nessuno ha ancora risposto non porterebbe con
    se' le proprie risposte.
    """
    if not identificativi:
        return []

    citazioni = [
        or_(
            EmailMessage.in_reply_to.contains(identificativo, autoescape=True),
            EmailMessage.thread_references.contains(identificativo, autoescape=True),
        )
        for identificativo in identificativi
    ]

    interrogazione = (
        select(EmailMessage)
        .where(
            or_(
                EmailMessage.internet_message_id.in_(identificativi),
                *citazioni,
            )
        )
        .limit(MASSIMI_CANDIDATI_DEL_FILO)
    )

    esclusi = set(gia_visti)
    return [
        trovato
        for trovato in db.scalars(interrogazione).all()
        if trovato.id not in esclusi
    ]


# ---------------------------------------------------------------------------
#  5. L'ASSEGNAZIONE A MANO
# ---------------------------------------------------------------------------


def assegna(
    db: Session,
    messaggio: EmailMessage,
    *,
    versione: ProductVersion,
    autore: User,
    request: Request | None = None,
) -> None:
    """Attacca un messaggio a una versione di prodotto, per decisione di una persona.

    Vale sia per un messaggio in quarantena - il caso normale - sia per uno
    gia' attribuito che era finito sulla versione sbagliata: sono la stessa
    operazione, e distinguerle vorrebbe dire due funzioni che fanno la stessa
    cosa e due righe di registro diverse per lo stesso fatto.

    **Il motivo della quarantena non si cancella.** Resta scritto anche dopo
    l'assegnazione: e' la storia di come questo messaggio e' arrivato dov'e',
    e la prima domanda che ci si fa guardando un messaggio assegnato a mano e'
    proprio perche' Aurora non ci fosse arrivata da sola.

    Chi chiama ha gia' verificato i permessi.
    """
    prima = {
        "versione": (
            etichette.nome_versione(messaggio.product_version)
            if messaggio.product_version is not None
            else None
        ),
        "stato": messaggio.assignment_state.value,
    }

    messaggio.product_version_id = versione.id
    messaggio.assignment_state = EmailAssignmentState.MANUALE
    messaggio.assigned_by_id = autore.id

    scomposizione = dict(messaggio.subject_parsed or {})
    scomposizione["via"] = VIA_MANUALE
    messaggio.subject_parsed = scomposizione

    db.flush()

    audit.record(
        db,
        action=ACTION_EMAIL_ASSIGNED_MANUAL,
        entity_type=ENTITY_EMAILS,
        entity_id=messaggio.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_messaggio(messaggio),
        old_value=prima,
        new_value={
            "versione": etichette.nome_versione(versione),
            "stato": EmailAssignmentState.MANUALE.value,
        },
    )

    logger.info(
        "'%s' ha assegnato il messaggio %s a %s",
        autore.username,
        messaggio.id,
        etichette.nome_versione(versione),
    )


def assegna_il_filo(
    db: Session,
    messaggio: EmailMessage,
    *,
    versione: ProductVersion,
    autore: User,
    request: Request | None = None,
) -> list[EmailMessage]:
    """Assegna anche gli altri messaggi in quarantena della conversazione.

    Restituisce quelli che ha assegnato, per poterlo dire in pagina.

    **Si toccano solo quelli in quarantena.** Un messaggio dello stesso filo
    gia' attribuito - a mano o dal programma - resta dov'e': l'attribuzione di
    una conversazione lunga puo' cambiare per strada, e sovrascrivere una
    decisione gia' presa non e' quello che chiede chi preme "assegna anche gli
    altri".
    """
    assegnati: list[EmailMessage] = []

    for altro in messaggi_del_filo(db, messaggio):
        if altro.assignment_state != EmailAssignmentState.QUARANTENA:
            continue
        assegna(db, altro, versione=versione, autore=autore, request=request)
        assegnati.append(altro)

    return assegnati


def registra_scarico(
    db: Session,
    messaggio: EmailMessage,
    *,
    che_cosa: str,
    utente: User,
    request: Request | None = None,
) -> None:
    """Scrive nel registro che qualcuno ha scaricato il messaggio o un allegato.

    La corrispondenza con i clienti e' materiale riservato quanto i documenti,
    e sui documenti lo scarico si registra dalla sessione 6: qui vale lo
    stesso ragionamento. "che_cosa" e' il nome dell'allegato oppure il file
    `.eml`, e finisce nella descrizione della voce.
    """
    audit.record(
        db,
        action=ACTION_EMAIL_DOWNLOAD,
        entity_type=ENTITY_EMAILS,
        entity_id=messaggio.id,
        user_id=utente.id,
        request=request,
        etichetta=etichette.nome_messaggio(messaggio),
        new_value={"scaricato": che_cosa},
    )


# ---------------------------------------------------------------------------
#  6. LEGGERE GLI ELENCHI
# ---------------------------------------------------------------------------


def trova_messaggio(db: Session, message_id: uuid.UUID) -> EmailMessage | None:
    """Un messaggio dal suo identificatore, con quello che serve alla scheda."""
    return db.scalars(
        select(EmailMessage)
        .where(EmailMessage.id == message_id)
        .options(
            selectinload(EmailMessage.attachments),
            selectinload(EmailMessage.assigned_by),
            selectinload(EmailMessage.product_version).selectinload(
                ProductVersion.product
            ),
        )
    ).first()


def allegato_di(
    db: Session, messaggio: EmailMessage, attachment_id: uuid.UUID
) -> EmailAttachment | None:
    """Un allegato, **verificando che sia di quel messaggio**.

    Il controllo non e' pignoleria: l'indirizzo di scarico porta dentro tutti
    e due gli identificatori, e senza questa verifica si potrebbe chiedere
    l'allegato di un messaggio che non si ha il permesso di vedere passando
    per uno che si vede.
    """
    return db.scalars(
        select(EmailAttachment).where(
            EmailAttachment.id == attachment_id,
            EmailAttachment.email_message_id == messaggio.id,
        )
    ).first()


def _visibili(db: Session, utente: User) -> Select[tuple[EmailMessage]]:
    """L'interrogazione di partenza degli elenchi, gia' ristretta all'utente.

    Il filtro e' quello di `permissions.filtro_email()`, cioe' la stessa regola
    di `permissions.puo()` scritta come SQL. E' l'unico punto in cui si mette:
    chi parte da qui non se lo puo' dimenticare, che e' lo stesso principio di
    `documents._visibili()`.
    """
    interrogazione = select(EmailMessage)

    filtro = permissions.filtro_email(db, utente)
    if filtro is not None:
        interrogazione = interrogazione.where(filtro)

    return interrogazione


def _quando():
    """La data su cui si ordina e si filtra un elenco di messaggi.

    La data di invio quando c'e', quella di ricezione quando manca. Sono due
    cose diverse e un messaggio rotto puo' non avere la prima: ordinare su una
    colonna che a volte e' nulla metterebbe quei messaggi tutti in fondo, cioe'
    proprio quelli che si vuole guardare per primi.
    """
    return func.coalesce(EmailMessage.sent_at, EmailMessage.received_at)


def _filtra(
    interrogazione: Select[Any],
    *,
    product_version_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    stato: str | None,
    testo: str | None,
    dal: date | None,
    al: date | None,
) -> Select[Any]:
    """Aggiunge i filtri della barra di ricerca all'interrogazione.

    Sta in una funzione sua perche' serve due volte, una per contare e una per
    prendere una pagina: due elenchi di filtri scritti due volte prima o poi
    divergono, e l'impaginazione mostrerebbe un totale che non torna.

    **La ricerca guarda mittente, oggetto e corpo**, come chiede il punto 4
    della sessione. Il corpo e' la colonna `body_text`, cioe' il messaggio
    ridotto a testo semplice al momento dell'archiviazione: cercare dentro il
    `.eml` originale vorrebbe dire aprire un file per riga.
    """
    if product_version_id is not None:
        interrogazione = interrogazione.where(
            EmailMessage.product_version_id == product_version_id
        )

    if project_id is not None:
        # Il progetto non e' una colonna dei messaggi: ci si arriva dalla
        # versione di prodotto, che e' quello a cui un messaggio e' attaccato.
        interrogazione = interrogazione.where(
            EmailMessage.product_version_id.in_(
                select(Project.product_version_id).where(Project.id == project_id)
            )
        )

    if stato:
        interrogazione = interrogazione.where(
            EmailMessage.assignment_state == stato
        )

    if testo:
        parola = f"%{testo.strip()}%"
        interrogazione = interrogazione.where(
            or_(
                EmailMessage.sender.ilike(parola),
                EmailMessage.subject.ilike(parola),
                EmailMessage.body_text.ilike(parola),
            )
        )

    if dal is not None:
        interrogazione = interrogazione.where(
            _quando() >= datetime.combine(dal, datetime.min.time(), timezone.utc)
        )

    if al is not None:
        # L'intervallo comprende il giorno scritto: si confronta con la
        # mezzanotte del giorno **dopo**. Scrivendo "al 26 agosto" nessuno
        # intende "fino alle 00:00 del 26".
        interrogazione = interrogazione.where(
            _quando()
            < datetime.combine(al, datetime.max.time(), timezone.utc)
        )

    return interrogazione


def cerca_messaggi(
    db: Session,
    utente: User,
    *,
    product_version_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    stato: str | None = None,
    testo: str | None = None,
    dal: date | None = None,
    al: date | None = None,
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[EmailMessage], int]:
    """Una pagina di messaggi visibili, piu' quanti ne ha trovati in tutto.

    L'ordine e' **cronologico dal piu' recente**, come chiede il punto 1 della
    sessione: la posta si guarda cominciando da quella di oggi.
    """
    conteggio = _filtra(
        _visibili(db, utente).with_only_columns(func.count(EmailMessage.id)),
        product_version_id=product_version_id,
        project_id=project_id,
        stato=stato,
        testo=testo,
        dal=dal,
        al=al,
    )
    totale = db.scalar(conteggio) or 0

    righe = _filtra(
        _visibili(db, utente).options(
            selectinload(EmailMessage.attachments),
            selectinload(EmailMessage.product_version).selectinload(
                ProductVersion.product
            ),
        ),
        product_version_id=product_version_id,
        project_id=project_id,
        stato=stato,
        testo=testo,
        dal=dal,
        al=al,
    )

    pagina = max(1, pagina)
    righe = (
        righe.order_by(_quando().desc(), EmailMessage.id)
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
    )

    return list(db.scalars(righe).all()), totale


def conta_messaggi(db: Session, utente: User, *, project_id: uuid.UUID) -> int:
    """Quanti messaggi di quel progetto questa persona puo' vedere.

    Serve al riquadro della posta nella scheda del progetto. Passa dallo stesso
    filtro dell'elenco perche' un numero che non torna con le righe mostrate
    dice esattamente quello che si stava cercando di non dire (D-051).
    """
    interrogazione = _filtra(
        _visibili(db, utente).with_only_columns(func.count(EmailMessage.id)),
        product_version_id=None,
        project_id=project_id,
        stato=None,
        testo=None,
        dal=None,
        al=None,
    )
    return db.scalar(interrogazione) or 0


def in_quarantena(db: Session, pagina: int = 1, per_pagina: int = 25):
    """I messaggi che aspettano di essere assegnati a mano, dal piu' recente.

    Non passa dal filtro dei permessi e non e' una svista: la pagina che la usa
    e' riservata al creatore (D-069). Un messaggio in quarantena non e'
    attaccato a nessuna versione, quindi non c'e' nessun progetto su cui la
    matrice possa dire qualcosa, e l'unica regola scrivibile e' "lo vede chi
    amministra Aurora".
    """
    conteggio = select(func.count(EmailMessage.id)).where(
        EmailMessage.assignment_state == EmailAssignmentState.QUARANTENA
    )
    totale = db.scalar(conteggio) or 0

    pagina = max(1, pagina)
    righe = (
        select(EmailMessage)
        .where(EmailMessage.assignment_state == EmailAssignmentState.QUARANTENA)
        .options(selectinload(EmailMessage.attachments))
        .order_by(_quando().desc(), EmailMessage.id)
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
    )

    return list(db.scalars(righe).all()), totale


def conta_in_quarantena(db: Session) -> int:
    """Quanti messaggi aspettano una persona. Serve al pallino sulla pagina."""
    return db.scalar(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.assignment_state == EmailAssignmentState.QUARANTENA
        )
    ) or 0


# ---------------------------------------------------------------------------
#  7. QUELLO CHE SERVE ALLE PAGINE
# ---------------------------------------------------------------------------


def opzioni_stati() -> list[tuple[str, str]]:
    """Gli stati di attribuzione come coppie (valore, etichetta italiana).

    Si compongono qui e non nel template (docs/GUIDA_STILE.md, sezione 5).
    """
    return [
        (EmailAssignmentState.AUTOMATICA.value, "attribuiti dal programma"),
        (EmailAssignmentState.MANUALE.value, "assegnati a mano"),
        (EmailAssignmentState.QUARANTENA.value, "in quarantena"),
    ]


def nome_stato(stato: EmailAssignmentState | str) -> str:
    """Come si scrive uno stato di attribuzione in una pagina."""
    valore = stato.value if isinstance(stato, EmailAssignmentState) else str(stato)
    for codice, etichetta in opzioni_stati():
        if codice == valore:
            return etichetta
    return valore


def come_attribuito(messaggio: EmailMessage) -> str:
    """La frase che spiega come questo messaggio e' finito dov'e'.

    La via sta dentro `subject_parsed`, che e' un dato ricavato: se manca -
    per i messaggi archiviati prima della sessione 10 - si risponde con lo
    stato, che c'e' sempre.
    """
    via = (messaggio.subject_parsed or {}).get("via")
    if via and via in NOMI_VIA:
        return NOMI_VIA[via]
    return nome_stato(messaggio.assignment_state)


def destinatari_di(messaggio: EmailMessage, tipo: str) -> list[str]:
    """Gli indirizzi di un tipo ("a", "cc", "ccn"), come si scrivono in pagina.

    Si compone qui e non nel template perche' e' una trasformazione, e le
    trasformazioni si provano con un test solo se stanno in Python.
    """
    scritti: list[str] = []
    for destinatario in messaggio.recipients or []:
        if not isinstance(destinatario, dict) or destinatario.get("tipo") != tipo:
            continue
        indirizzo = str(destinatario.get("indirizzo") or "").strip()
        nome = str(destinatario.get("nome") or "").strip()
        if not indirizzo:
            continue
        scritti.append(f"{nome} <{indirizzo}>" if nome else indirizzo)
    return scritti


def motivo_riconosciuto(messaggio: EmailMessage) -> tuple[str | None, bool]:
    """Il motivo scritto nell'oggetto e se e' fra quelli ammessi.

    Restituisce (None, True) quando l'oggetto non ne conteneva nessuno: non
    averlo scritto non e' un errore, e la pagina non deve segnalare niente.
    """
    scomposizione = messaggio.subject_parsed or {}
    motivo = scomposizione.get("motivo")
    if not motivo:
        return None, True
    return str(motivo), bool(scomposizione.get("motivo_riconosciuto", False))


def filtri_elenco(stato: str) -> list[dict[str, Any]]:
    """I filtri della barra di ricerca dell'elenco della posta."""
    return [
        {
            "nome": "stato",
            "etichetta": "Attribuzione",
            "opzioni": opzioni_stati(),
            "scelto": stato,
            "vuoto": "Qualunque attribuzione",
        }
    ]


def data_scritta(valore: str) -> date | None:
    """Una data letta da un parametro dell'indirizzo, senza fidarsene.

    Un indirizzo puo' essere scritto a mano o restare in un preferito dopo che
    la pagina e' cambiata: `?dal=ieri` non deve produrre un errore tecnico ma
    comportarsi come se il parametro non ci fosse.
    """
    testo = (valore or "").strip()
    if not testo:
        return None
    try:
        return date.fromisoformat(testo)
    except ValueError:
        return None


def _versioni_cercabili(db: Session, testo: str, quante: int) -> list[ProductVersion]:
    """Le versioni di prodotto il cui codice somiglia a quello cercato.

    Serve alla ricerca del modulo di assegnazione: chi smista la quarantena
    conosce il codice del prodotto, non l'identificatore della sua versione.
    """
    parola = f"%{testo.strip()}%"
    return list(
        db.scalars(
            select(ProductVersion)
            .join(Product, Product.id == ProductVersion.product_id)
            .where(
                or_(
                    Product.code.ilike(parola),
                    Product.description.ilike(parola),
                )
            )
            .options(selectinload(ProductVersion.product))
            .order_by(Product.code, ProductVersion.version_number.desc())
            .limit(quante)
        ).all()
    )


def cerca_versioni(
    db: Session, testo: str, quante: int = 20
) -> list[tuple[str, str]]:
    """Le versioni proponibili nel modulo di assegnazione, come coppie.

    La coppia e' (identificatore, "RMS1100-24-110SW v2 - in sviluppo"): lo
    stato serve a chi sceglie, perche' fra la versione 2 in sviluppo e la 1
    superata la posta di oggi appartiene quasi sempre alla prima.

    Senza testo si propongono le versioni piu' recenti, cosi' il modulo non
    parte vuoto.
    """
    if testo.strip():
        versioni = _versioni_cercabili(db, testo, quante)
    else:
        versioni = list(
            db.scalars(
                select(ProductVersion)
                .options(selectinload(ProductVersion.product))
                .order_by(ProductVersion.created_at.desc())
                .limit(quante)
            ).all()
        )

    return [
        (
            str(versione.id),
            f"{etichette.nome_versione(versione)} - "
            f"{versione.lifecycle_state.value.replace('_', ' ')}",
        )
        for versione in versioni
    ]


def trova_versione(db: Session, valore: str) -> ProductVersion | None:
    """La versione scelta nel modulo, senza fidarsi del modulo."""
    try:
        return db.get(ProductVersion, uuid.UUID(valore))
    except (ValueError, AttributeError, SQLAlchemyError):
        return None
