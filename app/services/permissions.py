"""Chi puo' fare che cosa. **Questo e' l'unico posto che lo decide.**

Tutto il programma fa una domanda sola, e la fa qui:

    permissions.puo(db, utente, Azione.VEDERE, documento)

Non ci sono altre domande. Non c'e' una funzione che risponde per i documenti
e un'altra per i progetti, non c'e' un `if utente.is_creatore` dentro una
rotta, non c'e' un `{% if %}` dentro un template che decide se una persona ha
diritto a vedere un pulsante. C'e' `puo()`, e chi vuole sapere qualcosa la
chiama. Un test lo verifica leggendo i sorgenti (test_permessi.py).

Il perche' e' scritto in docs/DECISIONI.md, D-051, e in due righe e' questo:
le regole di accesso sbagliate non si vedono. Un elenco che mostra una riga di
troppo sembra un elenco normale, e chi lo guarda non ha modo di accorgersene.
L'unica difesa e' che la regola stia in un punto solo, dove si legge tutta
insieme e dove un test la puo' esercitare in tutte le sue combinazioni.


IL MODELLO
----------

Una persona accede a un documento se e solo se:

  1. **e' il creatore** - il ruolo globale, chi amministra Aurora: puo' tutto,
     dappertutto; oppure
  2. **e' il project manager del progetto** a cui il documento appartiene -
     quello scritto in projects.project_manager_id: sui documenti dei propri
     progetti puo' tutto, qualunque cosa dica la matrice; oppure
  3. **e' assegnato al progetto**, e la casella della matrice all'incrocio fra
     il suo ruolo in **quel** progetto e la classificazione del documento
     consente quell'operazione.

Fuori da questi tre casi non c'e' accesso: chi non e' assegnato a un progetto
non ha nessun ruolo su quel progetto, quindi non ha nessun permesso sui suoi
documenti.

Il punto 2 e' un'eccezione voluta e non una scorciatoia. Il responsabile di un
progetto risponde di tutto quello che c'e' dentro, comprese le offerte e i
contratti: una matrice che gli nascondesse un documento del suo progetto
sarebbe una matrice sbagliata, e il modo di scoprirlo sarebbe una telefonata.
Attenzione alla distinzione: l'eccezione vale per **il** project manager del
progetto, non per chiunque abbia il ruolo di progetto `project_manager`. Per
quest'ultimo decide la matrice, come per tutti gli altri.


LE DUE STRADE, E PERCHE' DEVONO DIRE LA STESSA COSA
---------------------------------------------------

La stessa regola serve in due forme:

  - **puo()** risponde su un oggetto solo, e serve a ogni pagina che lo apre;
  - **filtro_documenti() / filtro_progetti()** sono la stessa regola scritta
    come condizione SQL, e servono agli elenchi.

Devono dare la stessa risposta. Un elenco che nasconde una riga che poi si
apre scrivendone l'indirizzo non e' una protezione, e' una tenda; e un elenco
che nasconde la riga ma la conta lo e' anche meno, perche' dice il numero
esatto delle cose che non si dovrebbero sapere. Per esserne certi le due
scritture partono dalla stessa tabella, stanno nello stesso file a poche righe
di distanza, e c'e' un test che le confronta su tutte le combinazioni.


COME SI RISPONDE DI NO
----------------------

Con `pretendi()`, che non restituisce niente e interrompe:

  - **404** quando la persona non puo' nemmeno vedere l'oggetto. Non "403,
    esiste ma non e' tuo": 404, come se non ci fosse. Dire "esiste ma non lo
    puoi vedere" e' gia' dire qualcosa - che quel numero di documento e'
    stato assegnato, che quel progetto e' aperto - e chi prova mille indirizzi
    di fila si costruisce l'elenco di quello che non deve sapere;
  - **403** quando la persona l'oggetto lo vede gia' e le manca solo il
    permesso per quell'operazione. Li' non c'e' piu' niente da nascondere, e
    un 404 manderebbe qualcuno a cercare un guasto che non c'e' invece che a
    chiedere il permesso.

Questa e' la parte che corregge D-043, che aveva scelto il 403 anche per il
primo caso.


UNA CASELLA CHE MANCA VALE NO
------------------------------

Se in permission_rules non c'e' la riga per una coppia (ruolo,
classificazione) il permesso e' negato e il fatto finisce nel registro. E'
l'unico modo prudente di sbagliare: il contrario vorrebbe dire che
aggiungendo una classificazione si aprono per sbaglio dei documenti a chi non
doveva vederli. La pagina che crea una classificazione scrive comunque tutte
le sue caselle (crea_classificazione), quindi in condizioni normali non manca
mai niente.


UN PROGETTO CHIUSO E' IN SOLA LETTURA
-------------------------------------

Quando un progetto entra nella fase che lo chiude, tutto quello che c'e'
dentro smette di cambiare: niente documenti nuovi, niente cambi di stato,
niente passaggi di fase. Resta visibile a chi lo vedeva - un progetto chiuso
e' un archivio, e un archivio si consulta - e resta modificabile dal solo
creatore, che e' l'unico che possa riaprirlo riportandolo indietro (D-058).

La regola sta scritta qui in due punti, uno per ciascuna delle due strade:
dentro `_permessi_su_classificazione` per i documenti e dentro
`_puo_sul_progetto` per il progetto, piu' la sua copia SQL in
`filtro_documenti`. Non e' in una rotta apposta: le strade che portano a
caricare un documento sono tre, e una regola messa su due di quelle tre e'
una regola che non c'e'.


LA MATRICE SI MODIFICA, E L'EFFETTO E' IMMEDIATO
-------------------------------------------------

La seconda meta' di questo file e' la scrittura: la matrice e le
classificazioni si correggono dalla pagina /permessi, riservata al creatore.
Non c'e' nessuna copia in memoria di niente: ogni richiesta rilegge la
matrice dal database, quindi una correzione vale dalla pagina successiva per
tutti quelli che sono collegati in quel momento, senza che nessuno debba
uscire e rientrare. E' la stessa ragione per cui app/dependencies.py rilegge
l'utente a ogni richiesta invece di fidarsi del cookie.
"""

import enum
import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    Classification,
    Document,
    EmailMessage,
    PermissionRule,
    Product,
    ProductVersion,
    Project,
    ProjectRole,
    User,
)
from app.services import audit, etichette

logger = logging.getLogger("aurora.permessi")


# ---------------------------------------------------------------------------
#  1. IL VOCABOLARIO: le azioni e gli oggetti su cui si chiede
# ---------------------------------------------------------------------------


class Azione(str, enum.Enum):
    """Le cinque cose che si possono chiedere di fare.

    vedere        sapere che l'oggetto esiste, aprirlo, scaricarlo;
    caricare      mettere dentro qualcosa di nuovo (un documento, una
                  versione);
    modificare    cambiare l'oggetto: lo stato, il ritiro, il ciclo di vita,
                  la fase di un progetto;
    richiedere    **chiedere** un cambiamento che non si ha il permesso di
                  fare: oggi e' l'avanzamento di fase, che un ingegnere puo'
                  domandare e il project manager decide (sessione 8);
    amministrare  le sezioni riservate al creatore: utenti, clienti, matrice
                  dei permessi, modelli di fasi, documenti ritirati, vetrina
                  dello stile.

    **TRE DI QUESTE SONO COLONNE DELLA MATRICE, DUE NO.** Vedere, caricare e
    modificare sono le tre caselle di `permission_rules`: aggiungerne una
    vorrebbe dire aggiungere una colonna alla tabella e una migrazione, e non
    e' una cosa che capita per sbaglio. Amministrare e richiedere non sono
    caselle - la matrice governa i documenti, e nessuna di queste due parla di
    documenti: sono decise da una regola scritta qui sotto, ed e' per questo
    che `Permessi.consente()` risponde "no" a tutte e due.
    """

    VEDERE = "vedere"
    CARICARE = "caricare"
    MODIFICARE = "modificare"
    RICHIEDERE = "richiedere"
    AMMINISTRARE = "amministrare"


@dataclass(frozen=True)
class BersaglioCaricamento:
    """Dove si sta per caricare un documento che ancora non esiste.

    Serve perche' `puo(..., CARICARE, documento)` non si puo' chiedere su un
    documento che non c'e' ancora: al momento del caricamento esistono solo il
    progetto e la classificazione scelta nel modulo, ed e' su quella coppia
    che la matrice ha qualcosa da dire.
    """

    progetto: Project
    classification_id: uuid.UUID


class _Amministrazione:
    """L'oggetto su cui si chiede il permesso di amministrare.

    Non e' una riga del database: e' "Aurora nel suo insieme". Esiste come
    oggetto perche' `puo()` prende sempre un oggetto, e una funzione che a
    volte lo prende e a volte no e' una funzione che si sbaglia a chiamare.
    Se ne crea una sola istanza, qui sotto.
    """

    def __repr__(self) -> str:  # pragma: no cover - solo per il debug
        return "<amministrazione di Aurora>"


AMMINISTRAZIONE = _Amministrazione()


@dataclass(frozen=True)
class Permessi:
    """Le tre caselle della matrice, per una persona su una classificazione.

    Serve dove le tre risposte servono tutte insieme - la scheda di un
    documento le usa tutte e tre - per non chiedere tre volte la stessa cosa
    con tre interrogazioni. Chi ne vuole una sola chiama `puo()`.
    """

    vedere: bool
    caricare: bool
    modificare: bool

    def consente(self, azione: Azione) -> bool:
        """Traduce un'azione nella casella corrispondente."""
        if azione is Azione.VEDERE:
            return self.vedere
        if azione is Azione.CARICARE:
            return self.caricare
        if azione is Azione.MODIFICARE:
            return self.modificare
        # AMMINISTRARE e RICHIEDERE non sono caselle della matrice. La prima
        # e' del creatore, e chi e' creatore non arriva mai fin qui; la
        # seconda riguarda le fasi di un progetto, non i suoi documenti.
        return False


NESSUNO = Permessi(vedere=False, caricare=False, modificare=False)
TUTTI = Permessi(vedere=True, caricare=True, modificare=True)


# ---------------------------------------------------------------------------
#  2. LA DOMANDA: puo()
# ---------------------------------------------------------------------------


def puo(db: Session, utente: User, azione: Azione, oggetto: object) -> bool:
    """**L'unica funzione che decide un permesso in tutta Aurora.**

    Prende chi sta chiedendo, che cosa vuole fare e su che cosa, e risponde
    si' o no. Gli oggetti che sa trattare sono cinque:

      Document              un documento gia' esistente;
      BersaglioCaricamento  un documento che si sta per creare, cioe' la
                            coppia (progetto, classificazione);
      EmailMessage          un messaggio di posta archiviato;
      Project               un progetto;
      ProductVersion        una versione di prodotto;
      Product               un prodotto;
      AMMINISTRAZIONE       le sezioni riservate al creatore.

    Il prodotto e' arrivato con la sessione 9, insieme alla scheda "Storico"
    che ogni oggetto adesso ha: la storia di un oggetto la vede chi vede
    l'oggetto, e per rispondere a quella domanda questa funzione doveva saper
    trattare anche i prodotti.

    **Le persone non sono in questo elenco.** Le pagine che parlano di una
    persona - la sua scheda, i suoi accessi, il suo storico - sono tutte nella
    sezione riservata al creatore, e il permesso lo chiede la dipendenza
    richiedi_creatore, che a sua volta lo chiede qui con AMMINISTRAZIONE. E'
    la stessa domanda fatta nel modo previsto per le pagine di
    amministrazione, e la risposta negativa e' un 403 invece di un 404.

    Su un oggetto che non sa trattare risponde **no** e lo scrive nel
    registro. E' l'unico modo prudente di sbagliare: chi aggiungesse un
    oggetto nuovo dimenticandosi di insegnarlo a questa funzione se ne
    accorge perche' la pagina non si apre, non perche' si apre a tutti.
    """
    # Il creatore passa di qui e non dai casi sotto. E' una riga sola apposta:
    # ripetere "if utente.is_creatore" dentro ogni regola vorrebbe dire che
    # il giorno in cui se ne aggiunge una la si puo' dimenticare, e quella
    # dimenticanza chiuderebbe fuori proprio chi amministra il programma.
    if utente.is_creatore:
        return True

    if isinstance(oggetto, Document):
        return _permessi_su_documento(db, utente, oggetto).consente(azione)

    if isinstance(oggetto, BersaglioCaricamento):
        # Su una classificazione messa da parte non si carica piu' niente,
        # nemmeno costruendo la richiesta a mano. Il menu a tendina non la
        # propone gia', ma il menu e' un suggerimento: il divieto sta qui.
        # E' anche l'invariante che tiene: una classe si disattiva solo
        # quando non e' addosso a nessun documento, e da quel momento non ce
        # ne finiscono altri, quindi disattivata vuol dire per sempre vuota.
        if azione is Azione.CARICARE and not _classificazione_attiva(
            db, oggetto.classification_id
        ):
            return False

        return _permessi_su_classificazione(
            db, utente, oggetto.progetto, oggetto.classification_id
        ).consente(azione)

    if isinstance(oggetto, EmailMessage):
        return _permessi_sul_messaggio(db, utente, oggetto).consente(azione)

    if isinstance(oggetto, Project):
        return _puo_sul_progetto(db, utente, azione, oggetto)

    if isinstance(oggetto, ProductVersion):
        return _puo_sulla_versione(db, utente, azione, oggetto)

    if isinstance(oggetto, Product):
        return _puo_sul_prodotto(azione)

    if isinstance(oggetto, _Amministrazione):
        # Il creatore ha gia' avuto la sua risposta in cima: qui arriva solo
        # chi creatore non e', e per lui la risposta e' no.
        return False

    logger.error(
        "puo() chiamata su un oggetto che non sa trattare (%s): "
        "il permesso viene negato",
        type(oggetto).__name__,
    )
    return False


def pretendi(
    db: Session, utente: User, azione: Azione, oggetto: object
) -> None:
    """Come puo(), ma invece di rispondere "no" interrompe la richiesta.

    E' quello che chiamano le rotte, perche' una rotta che ha appena scoperto
    di non poter proseguire non ha niente da restituire.

    **404 quando la persona non vede nemmeno l'oggetto**, con lo stesso
    identico messaggio che si riceve quando l'oggetto davvero non esiste:
    altrimenti la differenza fra le due risposte direbbe che esiste.
    **403 quando lo vede gia'** e le manca solo il permesso per quella
    operazione: li' non c'e' piu' niente da nascondere.
    """
    if puo(db, utente, azione, oggetto):
        return

    # Un bersaglio di caricamento non e' una riga del database: e' il progetto
    # piu' la classificazione scelta nel modulo, e nessuno dei due e' un
    # segreto - la persona il progetto lo vede, e le classificazioni compaiono
    # nei filtri degli elenchi. Non c'e' nessuna esistenza da nascondere, e la
    # risposta giusta e' 403 con la spiegazione di quale permesso manca.
    if isinstance(oggetto, BersaglioCaricamento):
        raise HTTPException(status_code=403, detail=_messaggio_negato(azione, oggetto))

    vede = azione is not Azione.VEDERE and puo(db, utente, Azione.VEDERE, oggetto)

    if vede:
        logger.info(
            "'%s' non puo' %s su %s",
            utente.username,
            azione.value,
            type(oggetto).__name__,
        )
        raise HTTPException(status_code=403, detail=_messaggio_negato(azione, oggetto))

    logger.info(
        "'%s' ha chiesto un %s che non puo' vedere: risponde 404",
        utente.username,
        type(oggetto).__name__,
    )
    raise HTTPException(status_code=404, detail=_messaggio_inesistente(oggetto))


# --- Le regole vere, una per tipo di oggetto -------------------------------


def _permessi_su_documento(db: Session, utente: User, documento: Document) -> Permessi:
    """Le tre caselle per questa persona su questo documento.

    Un documento **ritirato** lo vede solo il creatore, nella sua sezione: per
    tutti gli altri e' come se non ci fosse, ed e' il 404 di pretendi() a
    dirlo. Il ritiro e' logico, il documento resta in tabella (regola 5 di
    CLAUDE.md), ma resta come un fatto storico, non come una cosa da aprire.
    """
    if documento.is_deleted:
        return NESSUNO

    return _permessi_su_classificazione(
        db, utente, documento.project, documento.classification_id
    )


def _permessi_su_classificazione(
    db: Session,
    utente: User,
    progetto: Project,
    classification_id: uuid.UUID,
) -> Permessi:
    """Le tre caselle per questa persona su questa classe, in questo progetto.

    E' il cuore del modello. Il creatore non arriva mai fin qui: gli ha gia'
    risposto puo().

    **Un progetto chiuso e' in sola lettura**, per tutti quelli che non sono
    il creatore, project manager compreso (D-058). I documenti restano
    visibili - un progetto chiuso e' un archivio, e un archivio si consulta -
    ma non se ne carica piu' e non se ne cambia lo stato. Il filtro sta qui e
    non in una rotta perche' le strade che portano a caricare un documento
    sono tre, e una regola messa su due di quelle tre e' una regola che non
    c'e'.
    """
    permessi = _permessi_di_ruolo(db, utente, progetto, classification_id)

    if progetto.closed_at is not None:
        return Permessi(vedere=permessi.vedere, caricare=False, modificare=False)

    return permessi


def _permessi_di_ruolo(
    db: Session,
    utente: User,
    progetto: Project,
    classification_id: uuid.UUID,
) -> Permessi:
    """Le tre caselle che il ruolo di questa persona le da', progetto aperto."""
    # Il responsabile del progetto puo' tutto sui documenti del suo progetto,
    # qualunque cosa dica la matrice. Vedi la spiegazione in cima al file.
    if progetto.project_manager_id == utente.id:
        return TUTTI

    ruolo = ruolo_nel_progetto(db, progetto.id, utente.id)
    if ruolo is None:
        return NESSUNO

    regola = db.scalars(
        select(PermissionRule).where(
            PermissionRule.project_role == ruolo,
            PermissionRule.classification_id == classification_id,
        )
    ).first()

    if regola is None:
        logger.warning(
            "Manca la casella della matrice per (%s, classificazione %s): "
            "il permesso viene negato",
            ruolo.value,
            classification_id,
        )
        return NESSUNO

    return Permessi(
        vedere=regola.can_view,
        caricare=regola.can_upload,
        modificare=regola.can_edit,
    )


# --- La posta: una classificazione come le altre ---------------------------
#
# I messaggi di posta non hanno una colonna "classificazione": ne hanno una
# sola, sempre la stessa, ed e' quella che si chiama CLASSE_CORRISPONDENZA. La
# sessione 10 lo stabilisce cosi' apposta - "sono trattate come classificazione
# Corrispondenza, mappata sulla matrice esistente" - e la conseguenza e' che
# qui non nasce nessuna regola nuova: un messaggio e' un documento di
# classificazione Corrispondenza, nel progetto della versione a cui e'
# attaccato (D-069).

CLASSE_CORRISPONDENZA = "Corrispondenza"


def classificazione_corrispondenza(db: Session) -> Classification | None:
    """La classificazione con cui si decidono i permessi sulla posta.

    E' una riga di `classifications` come le altre - la crea la migrazione
    `d4b8607e15a2` e la si amministra dalla pagina delle classificazioni -
    e viene cercata **per nome**, perche' e' l'unico modo di riferirsi a una
    riga che una persona puo' rinominare senza avvisare nessuno.

    Se manca, la risposta di tutte le domande sulla posta diventa "no" per
    tutti tranne il creatore. E' l'unico modo prudente di sbagliare: senza la
    classificazione non esiste nessuna casella della matrice da guardare, e
    nessuna casella vuol dire nessun permesso deciso. Il guasto finisce nel
    registro su file, perche' non e' una situazione normale.
    """
    trovata = db.scalars(
        select(Classification).where(
            func.lower(Classification.name) == CLASSE_CORRISPONDENZA.lower()
        )
    ).first()

    if trovata is None:
        logger.error(
            "Manca la classificazione '%s': i permessi sui messaggi di posta "
            "vengono negati a tutti tranne al creatore. Va ricreata dalla "
            "pagina delle classificazioni.",
            CLASSE_CORRISPONDENZA,
        )

    return trovata


def _permessi_sul_messaggio(
    db: Session, utente: User, messaggio: EmailMessage
) -> Permessi:
    """Le tre caselle per questa persona su questo messaggio di posta.

    Il messaggio e' attaccato a una **versione di prodotto**; il progetto
    aperto su quella versione e' quello su cui la matrice ha qualcosa da dire.
    Da li' in poi la domanda e' identica a quella di un documento, e infatti
    la risposta la da' la stessa funzione.

    **Due casi valgono zero, e sono voluti.**

    Un messaggio **in quarantena** non e' attaccato a niente: non esiste
    nessun progetto, quindi nessun ruolo, quindi nessuna casella. Lo vede solo
    il creatore, a cui `puo()` ha gia' risposto prima di arrivare qui, ed e' il
    motivo per cui la pagina della quarantena e' riservata (D-069).

    Un messaggio attaccato a una versione **su cui non e' stato aperto nessun
    progetto** e' nella stessa situazione: la matrice parla di ruoli dentro un
    progetto, e senza progetto non ci sono ruoli. Capita per la posta che
    arriva prima che il lavoro cominci, e la risposta giusta e' che la veda chi
    amministra finche' il progetto non c'e'.
    """
    versione = messaggio.product_version
    if versione is None:
        return NESSUNO

    progetto = versione.project
    if progetto is None:
        return NESSUNO

    classe = classificazione_corrispondenza(db)
    if classe is None:
        return NESSUNO

    return _permessi_su_classificazione(db, utente, progetto, classe.id)


def _puo_sul_progetto(
    db: Session, utente: User, azione: Azione, progetto: Project
) -> bool:
    """Che cosa questa persona puo' fare su un progetto.

    vedere        chi e' assegnato, il responsabile, il creatore (D-043);
    caricare      chi ha almeno una classificazione con cui caricare qui:
                  serve al pulsante "Carica un documento", che altrimenti
                  porterebbe a un modulo con il menu a tendina vuoto;
    modificare    il responsabile e il creatore: e' chi decide del lavoro.
                  E' anche il permesso con cui si avanza di fase, si torna a
                  una fase precedente e si decide una richiesta altrui;
    richiedere    chi e' nella squadra ma non la governa: puo' **chiedere**
                  l'avanzamento di fase, che poi decidera' il responsabile
                  (D-056);
    amministrare  il creatore, a cui pero' ha gia' risposto puo().

    **Un progetto chiuso e' in sola lettura** per tutti tranne il creatore
    (D-058): non si avanza, non si torna indietro, non si chiede e non si
    carica. Resta visibile a chi lo vedeva, perche' un progetto chiuso e'
    un archivio e un archivio si consulta.
    """
    if azione is Azione.AMMINISTRARE:
        return False

    # Il creatore non arriva mai qui: gli ha gia' risposto puo(). Quindi
    # questa riga chiude fuori tutti gli altri, responsabile compreso.
    if progetto.closed_at is not None and azione is not Azione.VEDERE:
        return False

    if azione is Azione.MODIFICARE:
        return progetto.project_manager_id == utente.id

    if azione is Azione.RICHIEDERE:
        # Chi governa il progetto non chiede: fa. Se questa riga non ci
        # fosse, il responsabile si troverebbe davanti due pulsanti che fanno
        # la stessa cosa in due modi diversi, e uno dei due gli chiederebbe
        # il permesso a se' stesso.
        if progetto.project_manager_id == utente.id:
            return False
        return ruolo_nel_progetto(db, progetto.id, utente.id) is not None

    if azione is Azione.CARICARE:
        return bool(classificazioni_caricabili(db, progetto, utente))

    # VEDERE
    if progetto.project_manager_id == utente.id:
        return True
    return ruolo_nel_progetto(db, progetto.id, utente.id) is not None


def _puo_sulla_versione(
    db: Session, utente: User, azione: Azione, versione: ProductVersion
) -> bool:
    """Che cosa questa persona puo' fare su una versione di prodotto.

    **Vedere: tutti quelli che sono entrati.** Il catalogo dei prodotti e
    delle loro versioni e' il vocabolario comune dell'azienda: nasconderne un
    pezzo vorrebbe dire che due persone che parlano dello stesso prodotto non
    sanno di parlarne. I documenti, che sono la parte riservata, hanno le loro
    regole.

    **Modificare: il project manager del progetto aperto su questa versione, e
    il creatore.** E' la regola che stava in lifecycle.puo_cambiare_stato()
    fino alla sessione 7, e vale sia per il cambio di stato sia per la
    derivazione di una versione nuova: sono la stessa decisione presa in due
    momenti. Una versione su cui non e' ancora stato aperto nessun progetto la
    muove solo il creatore, perche' non c'e' ancora nessun responsabile a cui
    la decisione appartenga.
    """
    if azione is Azione.VEDERE:
        return True

    if azione in (Azione.AMMINISTRARE, Azione.RICHIEDERE):
        return False

    progetto = versione.project
    return progetto is not None and progetto.project_manager_id == utente.id


def _puo_sul_prodotto(azione: Azione) -> bool:
    """Che cosa questa persona puo' fare su un prodotto.

    **Vedere: tutti quelli che sono entrati**, per la stessa ragione delle
    versioni - il catalogo dei prodotti e' il vocabolario comune dell'azienda.
    E' anche la regola che le rotte di app/routers/products.py applicavano
    gia' dichiarando Depends(richiedi_login) sulla lettura.

    **Tutto il resto: il creatore**, che a questa funzione non arriva mai
    perche' gli ha gia' risposto puo(). Creare e modificare un prodotto sono
    rotte con Depends(richiedi_creatore).

    Non riceve ne' la sessione ne' il prodotto perche' non le servono: la
    regola non guarda nessun dato. Prenderli per simmetria con le altre
    funzioni vorrebbe dire scrivere due argomenti che nessuno usa, e chi legge
    si chiederebbe dove finiscono.
    """
    return azione is Azione.VEDERE


def _classificazione_attiva(db: Session, classification_id: uuid.UUID) -> bool:
    """Dice se quella classificazione e' ancora fra quelle in uso."""
    classe = db.get(Classification, classification_id)
    return classe is not None and classe.is_active


def ruolo_nel_progetto(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectRole | None:
    """Il ruolo attivo di una persona su un progetto, None se non e' assegnata.

    "Attivo" vuol dire con revoked_at nullo. Una persona ha al massimo un ruolo
    attivo per progetto: e' il vincolo dell'indice unico parziale su
    assignments, ed e' quello che rende questa funzione una domanda con una
    risposta sola.
    """
    return db.scalars(
        select(Assignment.project_role).where(
            Assignment.project_id == project_id,
            Assignment.user_id == user_id,
            Assignment.revoked_at.is_(None),
        )
    ).first()


# --- I messaggi del diniego ------------------------------------------------
#
# Stanno qui e non nelle rotte per una ragione precisa: il messaggio del 404
# deve essere **identico** a quello che si riceve quando l'oggetto davvero non
# esiste. Se ogni rotta se lo scrivesse per conto suo, prima o poi due
# risposte differirebbero di una virgola, e quella virgola direbbe a chi la
# nota che l'oggetto c'e'.

MESSAGGI_INESISTENTE: dict[type, str] = {
    Document: "Il documento richiesto non esiste.",
    Project: "Il progetto richiesto non esiste.",
    ProductVersion: "La versione richiesta non esiste.",
    Product: "Il prodotto richiesto non esiste.",
    EmailMessage: "Il messaggio richiesto non esiste.",
}

MESSAGGIO_INESISTENTE_GENERICO = "L'oggetto richiesto non esiste."

MESSAGGI_NEGATO: dict[Azione, str] = {
    Azione.CARICARE: (
        "Il tuo ruolo in questo progetto non permette di caricare documenti "
        "con questa classificazione."
    ),
    Azione.MODIFICARE: (
        "Il tuo ruolo in questo progetto non permette di modificare questo "
        "oggetto."
    ),
    Azione.RICHIEDERE: (
        "Il tuo ruolo in questo progetto non permette di chiedere il "
        "passaggio alla fase successiva."
    ),
    Azione.AMMINISTRARE: (
        "Questa sezione e' riservata a chi ha il ruolo di creatore."
    ),
    Azione.VEDERE: "Non hai il permesso di vedere questo oggetto.",
}

# Il messaggio del progetto chiuso e' a parte perche' non dipende dal ruolo di
# chi chiede: e' vero per tutti allo stesso modo, responsabile compreso, e
# dirgli "il tuo ruolo non permette" gli farebbe cercare un permesso che non
# esiste.
MESSAGGIO_PROGETTO_CHIUSO = (
    "Questo progetto e' chiuso: si puo' leggere ma non si puo' piu' "
    "cambiare. Chi ha il ruolo di creatore puo' riaprirlo riportandolo a "
    "una fase precedente."
)


def _messaggio_inesistente(oggetto: object) -> str:
    """La frase del 404, uguale per l'oggetto che manca e per quello negato."""
    return MESSAGGI_INESISTENTE.get(type(oggetto), MESSAGGIO_INESISTENTE_GENERICO)


def _messaggio_negato(azione: Azione, oggetto: object) -> str:
    """La frase del 403, che dice quale permesso manca."""
    if isinstance(oggetto, Project) and oggetto.closed_at is not None:
        return MESSAGGIO_PROGETTO_CHIUSO
    if isinstance(oggetto, BersaglioCaricamento) and (
        oggetto.progetto.closed_at is not None
    ):
        return MESSAGGIO_PROGETTO_CHIUSO
    if isinstance(oggetto, Document) and oggetto.project.closed_at is not None:
        return MESSAGGIO_PROGETTO_CHIUSO
    if isinstance(oggetto, ProductVersion) and azione is Azione.MODIFICARE:
        return (
            "Il ciclo di vita di una versione lo cambiano il project manager "
            "del suo progetto e chi ha il ruolo di creatore."
        )
    if isinstance(oggetto, Project) and azione is Azione.MODIFICARE:
        return (
            "Un progetto lo modificano il suo project manager e chi ha il "
            "ruolo di creatore."
        )
    return MESSAGGI_NEGATO[azione]


# ---------------------------------------------------------------------------
#  3. LA STESSA REGOLA PER GLI ELENCHI
# ---------------------------------------------------------------------------
#
# Quello che segue e' `puo()` riscritta come condizione SQL. Non e' una
# seconda regola: e' la stessa, e c'e' un test che glielo fa dimostrare su
# tutte le combinazioni di ruolo, classificazione e azione.
#
# **Vale anche per i conteggi.** Un documento invisibile non deve comparire
# nemmeno nel numero: "tre documenti" scritto sopra un elenco che ne mostra
# due dice esattamente quello che si stava cercando di non dire.


def filtro_documenti(
    utente: User, azione: Azione = Azione.VEDERE
) -> ColumnElement[bool] | None:
    """La condizione che, in un where(), lascia solo i documenti consentiti.

    Restituisce None per il creatore, che vede tutto e per cui non serve
    nessun filtro: chi la usa non aggiunge niente all'interrogazione.

    Per tutti gli altri e' un OR di due possibilita', che sono i punti 2 e 3
    del modello scritto in cima al file:

      - il documento appartiene a un progetto di cui questa persona e' il
        responsabile;
      - esiste un'assegnazione non revocata di questa persona sul progetto del
        documento, il cui ruolo ha il permesso richiesto sulla classificazione
        del documento.

    Sono due EXISTS correlati su Document, quindi la condizione si porta
    dentro tutto quello che le serve: chi la usa non deve aggiungere nessuna
    join, e non puo' sbagliarla.

    **Il progetto chiuso e' in sola lettura anche qui.** Per "vedere" non
    cambia niente - un archivio si consulta - ma per caricare e modificare la
    condizione si chiude, esattamente come fa puo() (D-058). Le due strade
    devono dire la stessa cosa: e' il patto di questo file.
    """
    if utente.is_creatore:
        return None

    colonna = {
        Azione.VEDERE: PermissionRule.can_view,
        Azione.CARICARE: PermissionRule.can_upload,
        Azione.MODIFICARE: PermissionRule.can_edit,
    }[azione]

    # correlate(Document) e' obbligatorio e non decorativo: senza,
    # SQLAlchemy vede "projects" anche nell'interrogazione esterna - gli
    # elenchi dei documenti la uniscono per mostrare il prodotto - e la
    # correla via da tutte e due, lasciando la sottointerrogazione senza
    # nessuna tabella da cui leggere. Cosi' si dice quale tabella viene da
    # fuori: il documento, e solo lui.
    responsabile = (
        exists(
            select(Project.id).where(
                Project.id == Document.project_id,
                Project.project_manager_id == utente.id,
            )
        )
        .correlate(Document)
    )

    dalla_matrice = exists(
        select(PermissionRule.id)
        .join(
            Assignment,
            and_(
                Assignment.project_role == PermissionRule.project_role,
                Assignment.project_id == Document.project_id,
                Assignment.user_id == utente.id,
                Assignment.revoked_at.is_(None),
            ),
        )
        .where(
            PermissionRule.classification_id == Document.classification_id,
            colonna.is_(True),
        )
        .correlate(Document)
    )

    consentito = or_(responsabile, dalla_matrice)

    if azione is Azione.VEDERE:
        return consentito

    progetto_aperto = exists(
        select(Project.id).where(
            Project.id == Document.project_id,
            Project.closed_at.is_(None),
        )
    ).correlate(Document)

    return and_(progetto_aperto, consentito)


def filtro_progetti(utente: User) -> ColumnElement[bool] | None:
    """La condizione che lascia solo i progetti che questa persona vede.

    E' `puo(..., VEDERE, progetto)` scritta come SQL: il responsabile piu' gli
    assegnati. Il creatore non ha filtro.

    E' un EXISTS e non una join per la stessa ragione di filtro_documenti():
    una join in piu' cambia il numero di righe, e un conteggio fatto su
    un'interrogazione con una join di troppo conta due volte le stesse cose.
    """
    if utente.is_creatore:
        return None

    return or_(
        Project.project_manager_id == utente.id,
        exists(
            select(Assignment.id)
            .where(
                Assignment.project_id == Project.id,
                Assignment.user_id == utente.id,
                Assignment.revoked_at.is_(None),
            )
            .correlate(Project)
        ),
    )


def filtro_email(
    db: Session, utente: User, azione: Azione = Azione.VEDERE
) -> ColumnElement[bool] | None:
    """La condizione che lascia solo i messaggi di posta consentiti.

    E' `puo(..., messaggio)` scritta come SQL, ed e' la stessa regola: il
    messaggio arriva alla sua versione di prodotto, la versione al progetto
    aperto su di lei, e li' si guarda la casella della matrice all'incrocio fra
    il ruolo di questa persona in quel progetto e la classificazione
    "Corrispondenza".

    Restituisce None per il creatore, che vede tutto.

    **Un messaggio in quarantena non compare in nessun elenco**, per nessuno:
    non ha versione, quindi tutti e due gli EXISTS sono falsi. La quarantena ha
    la sua pagina, riservata (D-069).

    Prende la sessione - a differenza di `filtro_documenti()` - perche' deve
    cercare la classificazione per nome. Senza quella riga non c'e' nessuna
    casella da guardare, e la condizione diventa "falso": nessuno vede niente,
    che e' l'unico modo prudente di sbagliare.
    """
    if utente.is_creatore:
        return None

    classe = classificazione_corrispondenza(db)
    if classe is None:
        return false()

    colonna = {
        Azione.VEDERE: PermissionRule.can_view,
        Azione.CARICARE: PermissionRule.can_upload,
        Azione.MODIFICARE: PermissionRule.can_edit,
    }[azione]

    # correlate(EmailMessage) per la stessa ragione di filtro_documenti():
    # senza, SQLAlchemy correlerebbe via anche le tabelle dell'interrogazione
    # esterna e la sottointerrogazione resterebbe senza niente da cui leggere.
    responsabile = exists(
        select(Project.id).where(
            Project.product_version_id == EmailMessage.product_version_id,
            Project.project_manager_id == utente.id,
        )
    ).correlate(EmailMessage)

    dalla_matrice = exists(
        select(Assignment.id)
        .join(Project, Project.id == Assignment.project_id)
        .join(
            PermissionRule,
            and_(
                PermissionRule.project_role == Assignment.project_role,
                PermissionRule.classification_id == classe.id,
                colonna.is_(True),
            ),
        )
        .where(
            Project.product_version_id == EmailMessage.product_version_id,
            Assignment.user_id == utente.id,
            Assignment.revoked_at.is_(None),
        )
        .correlate(EmailMessage)
    )

    return or_(responsabile, dalla_matrice)


# ---------------------------------------------------------------------------
#  4. LE CLASSIFICAZIONI, LETTE
# ---------------------------------------------------------------------------


def classificazioni_caricabili(
    db: Session, progetto: Project, utente: User
) -> list[Classification]:
    """Le classificazioni con cui questa persona puo' caricare in un progetto.

    Serve al menu a tendina della pagina di caricamento: proporre una
    classificazione con cui il caricamento verrebbe poi rifiutato e' un modo
    di far perdere tempo a chi ha appena aspettato il caricamento di un file
    da 300 MB.

    Le classificazioni attive sono una manciata di righe: si leggono tutte e
    si filtrano in Python chiamando `puo()`, che e' il punto - anche questo
    elenco esce dalla stessa regola di tutto il resto.
    """
    return [
        classificazione
        for classificazione in elenco_classificazioni(db)
        if puo(
            db,
            utente,
            Azione.CARICARE,
            BersaglioCaricamento(
                progetto=progetto, classification_id=classificazione.id
            ),
        )
    ]


def elenco_classificazioni(
    db: Session, comprese_disattivate: bool = False
) -> list[Classification]:
    """Le classificazioni attive, nell'ordine in cui vanno mostrate.

    Serve ai filtri degli elenchi, dove non c'e' un progetto solo su cui
    calcolare i permessi: si propongono tutte, e i documenti che la persona
    non puo' vedere non compaiono comunque perche' li toglie
    filtro_documenti().

    Con comprese_disattivate=True escono anche quelle messe da parte: serve
    alla pagina che le amministra, che deve poterle riattivare, e alla
    matrice, che le mostra tutte perche' una classificazione disattivata puo'
    ancora essere addosso a dei documenti vecchi.
    """
    interrogazione = select(Classification)
    if not comprese_disattivate:
        interrogazione = interrogazione.where(Classification.is_active.is_(True))

    return list(
        db.scalars(
            interrogazione.order_by(Classification.sort_order, Classification.name)
        ).all()
    )


def trova_classificazione(
    db: Session, classification_id: uuid.UUID
) -> Classification | None:
    """Una classificazione per identificativo, disattivata o no."""
    return db.get(Classification, classification_id)


def documenti_con_classificazione(db: Session, classification_id: uuid.UUID) -> int:
    """Quanti documenti hanno questa classificazione, ritirati compresi.

    I ritirati si contano apposta: un documento ritirato non e' sparito, e'
    solo fuori dagli elenchi. Se lo si ripristinasse e la sua classificazione
    non ci fosse piu', non ci sarebbe modo di dire chi lo puo' vedere.
    """
    return (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.classification_id == classification_id
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
#  5. LA MATRICE, LETTA E SCRITTA
# ---------------------------------------------------------------------------

ACTION_MATRIX_CHANGED = "permission_rule.changed"
ACTION_CLASSIFICATION_CREATED = "classification.created"
ACTION_CLASSIFICATION_RENAMED = "classification.renamed"
ACTION_CLASSIFICATION_MOVED = "classification.moved"
ACTION_CLASSIFICATION_DEACTIVATED = "classification.deactivated"
ACTION_CLASSIFICATION_REACTIVATED = "classification.reactivated"

ENTITY_PERMISSION_RULES = "permission_rules"
ENTITY_CLASSIFICATIONS = "classifications"

# I tre permessi, con l'etichetta con cui compaiono nella griglia e il nome
# della colonna. Sono elencati qui una volta sola: la pagina, il salvataggio,
# il registro e la verifica degli accessi leggono tutti da qui, cosi' il
# giorno in cui se ne aggiungesse un quarto ci sarebbe una riga da cambiare e
# non cinque da trovare.
PERMESSI_DELLA_MATRICE: tuple[tuple[str, str], ...] = (
    ("can_view", "visualizza"),
    ("can_upload", "carica"),
    ("can_edit", "modifica"),
)


@dataclass
class CasellaMatrice:
    """Una casella della griglia: un ruolo, una classificazione, tre spunte."""

    project_role: ProjectRole
    classificazione: Classification
    can_view: bool
    can_upload: bool
    can_edit: bool

    @property
    def nome_campo(self) -> str:
        """Il prefisso dei tre campi del modulo, per questa casella.

        Il nome contiene il ruolo e l'identificativo della classificazione,
        perche' il modulo torna indietro come un elenco piatto di campi e da
        li' si deve poter risalire a quale casella apparteneva ciascuno.
        """
        return f"{self.project_role.value}:{self.classificazione.id}"


def matrice(db: Session) -> list[CasellaMatrice]:
    """Tutte le caselle, ordinate per ruolo e poi per classificazione.

    Le caselle che in tabella non ci fossero escono comunque, con i tre
    permessi a falso: la griglia deve avere tutti i suoi quadretti, e una
    casella mancante e' esattamente quello che la pagina serve a correggere.

    Le classificazioni **disattivate non compaiono**, e non e' una scelta
    estetica: una classe si disattiva solo quando non e' addosso a nessun
    documento, e da quel momento non ne accetta di nuovi, quindi le sue
    caselle non governano piu' niente. Le righe restano in tabella e tornano
    a governare il giorno in cui la classe viene riattivata.
    """
    classificazioni = elenco_classificazioni(db)

    righe = {
        (regola.project_role, regola.classification_id): regola
        for regola in db.scalars(select(PermissionRule)).all()
    }

    caselle: list[CasellaMatrice] = []
    for ruolo in ProjectRole:
        for classificazione in classificazioni:
            regola = righe.get((ruolo, classificazione.id))
            caselle.append(
                CasellaMatrice(
                    project_role=ruolo,
                    classificazione=classificazione,
                    can_view=bool(regola and regola.can_view),
                    can_upload=bool(regola and regola.can_upload),
                    can_edit=bool(regola and regola.can_edit),
                )
            )

    return caselle


@dataclass(frozen=True)
class Cambiamento:
    """Una casella che cambia: com'era e come diventa.

    Serve due volte: per la pagina di conferma, che deve mostrare che cosa si
    sta per fare, e per il registro, che deve conservare il valore precedente
    e quello successivo.
    """

    project_role: ProjectRole
    classificazione: Classification
    prima: dict[str, bool]
    dopo: dict[str, bool]

    @property
    def permessi_cambiati(self) -> list[str]:
        """I nomi in italiano dei permessi che cambiano davvero."""
        return [
            etichetta
            for colonna, etichetta in PERMESSI_DELLA_MATRICE
            if self.prima[colonna] != self.dopo[colonna]
        ]


def confronta_matrice(
    db: Session, scelte: dict[str, bool]
) -> list[Cambiamento]:
    """Che cosa cambierebbe applicando queste scelte. Non scrive niente.

    "scelte" e' quello che arriva dal modulo, gia' ridotto a un dizionario
    che va da "ruolo:classificazione:colonna" a vero/falso. Le caselle non
    nominate restano come sono: un modulo puo' arrivare incompleto, e un
    permesso concesso per omissione sarebbe il peggiore dei modi di
    concederlo.
    """
    cambiamenti: list[Cambiamento] = []

    for casella in matrice(db):
        prima = {
            colonna: getattr(casella, colonna)
            for colonna, _ in PERMESSI_DELLA_MATRICE
        }
        dopo = {
            colonna: scelte.get(f"{casella.nome_campo}:{colonna}", prima[colonna])
            for colonna, _ in PERMESSI_DELLA_MATRICE
        }

        if prima != dopo:
            cambiamenti.append(
                Cambiamento(
                    project_role=casella.project_role,
                    classificazione=casella.classificazione,
                    prima=prima,
                    dopo=dopo,
                )
            )

    return cambiamenti


def salva_matrice(
    db: Session,
    cambiamenti: list[Cambiamento],
    autore: User,
    request: Request | None = None,
) -> int:
    """Scrive i cambiamenti e ne registra ciascuno. Restituisce quanti.

    Una riga di registro per casella, non una per salvataggio: "che cosa
    poteva vedere un ingegnere il 3 marzo" e' una domanda a cui si deve poter
    rispondere, e per rispondere serve sapere quale casella e' cambiata, non
    che qualcuno ha premuto Salva.

    Il commit non si fa qui: lo fa la rotta, insieme a tutto il resto.
    """
    for cambiamento in cambiamenti:
        regola = db.scalars(
            select(PermissionRule).where(
                PermissionRule.project_role == cambiamento.project_role,
                PermissionRule.classification_id == cambiamento.classificazione.id,
            )
        ).first()

        if regola is None:
            # La casella mancava: si crea adesso. E' il caso di una
            # classificazione aggiunta senza completare la matrice, che
            # permissions.py trattava come "no" scrivendolo nel registro.
            regola = PermissionRule(
                project_role=cambiamento.project_role,
                classification_id=cambiamento.classificazione.id,
            )
            db.add(regola)

        for colonna, _ in PERMESSI_DELLA_MATRICE:
            setattr(regola, colonna, cambiamento.dopo[colonna])

        db.flush()

        audit.record(
            db,
            action=ACTION_MATRIX_CHANGED,
            entity_type=ENTITY_PERMISSION_RULES,
            entity_id=regola.id,
            user_id=autore.id,
            request=request,
            etichetta=(
                f"{cambiamento.project_role.value} su "
                f"{cambiamento.classificazione.name}"
            ),
            old_value={
                "ruolo": cambiamento.project_role.value,
                "classificazione": cambiamento.classificazione.name,
                **cambiamento.prima,
            },
            new_value={
                "ruolo": cambiamento.project_role.value,
                "classificazione": cambiamento.classificazione.name,
                **cambiamento.dopo,
            },
        )

    if cambiamenti:
        logger.info(
            "'%s' ha corretto %s caselle della matrice dei permessi",
            autore.username,
            len(cambiamenti),
        )

    return len(cambiamenti)


# ---------------------------------------------------------------------------
#  6. LE CLASSIFICAZIONI, SCRITTE
# ---------------------------------------------------------------------------


def nome_gia_usato(
    db: Session, nome: str, escludi: uuid.UUID | None = None
) -> bool:
    """Dice se esiste gia' una classificazione con questo nome.

    Il confronto e' senza distinzione di maiuscole: "Tecnico" e "tecnico"
    sarebbero due voci indistinguibili in un menu a tendina, e la prima volta
    che qualcuno ne sceglie una sbagliata il documento finisce dietro i
    permessi di un'altra classe.
    """
    interrogazione = select(Classification.id).where(
        func.lower(Classification.name) == nome.strip().lower()
    )
    if escludi is not None:
        interrogazione = interrogazione.where(Classification.id != escludi)

    return db.scalars(interrogazione).first() is not None


def crea_classificazione(
    db: Session,
    *,
    nome: str,
    descrizione: str,
    autore: User,
    request: Request | None = None,
) -> Classification:
    """Crea una classificazione **e tutte le sue caselle della matrice**.

    Le caselle nascono con i tre permessi a falso, cioe' nessuno vede niente
    finche' qualcuno non decide il contrario. E' l'unico ordine prudente:
    creare la classe e poi i permessi vorrebbe dire che fra i due momenti - e
    sono due richieste diverse, con un essere umano in mezzo che potrebbe
    andare a pranzo - la classe esiste senza regole, e una casella che manca
    e' un permesso che nessuno ha deciso.

    L'ordinamento parte in fondo: chi la crea la sposta dove vuole.
    """
    ultimo = db.scalar(select(func.max(Classification.sort_order))) or 0

    classificazione = Classification(
        name=nome.strip(),
        description=descrizione.strip() or None,
        sort_order=ultimo + 1,
        is_active=True,
    )
    db.add(classificazione)
    db.flush()

    for ruolo in ProjectRole:
        db.add(
            PermissionRule(
                project_role=ruolo,
                classification_id=classificazione.id,
                can_view=False,
                can_upload=False,
                can_edit=False,
            )
        )
    db.flush()

    audit.record(
        db,
        action=ACTION_CLASSIFICATION_CREATED,
        entity_type=ENTITY_CLASSIFICATIONS,
        entity_id=classificazione.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_classificazione(classificazione),
        new_value={
            "nome": classificazione.name,
            "ordine": classificazione.sort_order,
            "caselle": len(ProjectRole),
        },
    )

    logger.info(
        "'%s' ha creato la classificazione '%s' con %s caselle a permessi "
        "chiusi",
        autore.username,
        classificazione.name,
        len(ProjectRole),
    )
    return classificazione


def rinomina_classificazione(
    db: Session,
    classificazione: Classification,
    *,
    nome: str,
    descrizione: str,
    autore: User,
    request: Request | None = None,
) -> None:
    """Cambia nome e descrizione. I permessi e i documenti non si toccano.

    Rinominare e' sicuro proprio perche' i documenti puntano
    all'identificativo e non al nome: "Commerciale" che diventa "Vendite"
    resta la stessa classe, con le stesse caselle e gli stessi documenti
    dietro.
    """
    prima = {"nome": classificazione.name, "descrizione": classificazione.description}

    classificazione.name = nome.strip()
    classificazione.description = descrizione.strip() or None
    db.flush()

    audit.record(
        db,
        action=ACTION_CLASSIFICATION_RENAMED,
        entity_type=ENTITY_CLASSIFICATIONS,
        entity_id=classificazione.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_classificazione(classificazione),
        old_value=prima,
        new_value={
            "nome": classificazione.name,
            "descrizione": classificazione.description,
        },
    )


def sposta_classificazione(
    db: Session,
    classificazione: Classification,
    *,
    verso: str,
    autore: User,
    request: Request | None = None,
) -> bool:
    """Sposta una classificazione di un posto in su o in giu'.

    Restituisce falso se era gia' in cima (o in fondo) e non c'e' stato
    niente da fare.

    Lo scambio e' fra questa e la sua vicina, non una rinumerazione di tutte:
    scambiare due valori e' un'operazione che si legge, mentre rinumerare
    l'intera colonna e' un'operazione che, la volta che va storta, lascia
    tutte le classificazioni con lo stesso numero.
    """
    tutte = elenco_classificazioni(db, comprese_disattivate=True)
    posizioni = {c.id: indice for indice, c in enumerate(tutte)}

    indice = posizioni.get(classificazione.id)
    if indice is None:
        return False

    vicina_indice = indice - 1 if verso == "su" else indice + 1
    if vicina_indice < 0 or vicina_indice >= len(tutte):
        return False

    vicina = tutte[vicina_indice]

    # Gli ordinamenti potrebbero essere uguali (due righe con lo stesso
    # sort_order, ordinate poi per nome): in quel caso scambiarli non
    # cambierebbe niente, quindi si riparte dalla posizione nell'elenco.
    classificazione.sort_order, vicina.sort_order = vicina_indice + 1, indice + 1
    db.flush()

    audit.record(
        db,
        action=ACTION_CLASSIFICATION_MOVED,
        entity_type=ENTITY_CLASSIFICATIONS,
        entity_id=classificazione.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_classificazione(classificazione),
        old_value={"ordine": indice + 1},
        new_value={"ordine": vicina_indice + 1},
    )
    return True


def disattiva_classificazione(
    db: Session,
    classificazione: Classification,
    *,
    autore: User,
    request: Request | None = None,
) -> None:
    """Toglie una classificazione dai menu. **Non cancella niente.**

    Chi chiama deve avere gia' verificato con documenti_con_classificazione()
    che non sia in uso: una classe addosso a dei documenti non si tocca,
    perche' toglierla vorrebbe dire lasciare quei documenti senza la riga che
    dice chi li puo' vedere.

    La riga resta in tabella con le sue caselle (regola 5 di CLAUDE.md):
    sparisce dai menu a tendina e dai filtri, e si puo' riattivare.
    """
    classificazione.is_active = False
    db.flush()

    audit.record(
        db,
        action=ACTION_CLASSIFICATION_DEACTIVATED,
        entity_type=ENTITY_CLASSIFICATIONS,
        entity_id=classificazione.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_classificazione(classificazione),
        old_value={"attiva": True},
        new_value={"attiva": False},
    )


def riattiva_classificazione(
    db: Session,
    classificazione: Classification,
    *,
    autore: User,
    request: Request | None = None,
) -> None:
    """Rimette una classificazione nei menu, com'era, con le sue caselle."""
    classificazione.is_active = True
    db.flush()

    audit.record(
        db,
        action=ACTION_CLASSIFICATION_REACTIVATED,
        entity_type=ENTITY_CLASSIFICATIONS,
        entity_id=classificazione.id,
        user_id=autore.id,
        request=request,
        etichetta=etichette.nome_classificazione(classificazione),
        old_value={"attiva": False},
        new_value={"attiva": True},
    )


# ---------------------------------------------------------------------------
#  7. LA VERIFICA DEGLI ACCESSI DI UNA PERSONA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RigaAccesso:
    """Una riga della verifica: una classificazione dentro un progetto."""

    classificazione: Classification
    vedere: bool
    caricare: bool
    modificare: bool

    @property
    def nessuno(self) -> bool:
        """Vero quando su questa classificazione non puo' proprio niente."""
        return not (self.vedere or self.caricare or self.modificare)


@dataclass(frozen=True)
class AccessoAlProgetto:
    """Che cosa una persona puo' fare dentro un progetto, classe per classe."""

    progetto: Project
    ruolo: ProjectRole | None
    e_responsabile: bool
    righe: list[RigaAccesso]

    @property
    def documenti_visibili(self) -> int:
        """Su quante classificazioni vede qualcosa."""
        return sum(1 for riga in self.righe if riga.vedere)


def verifica_accessi(db: Session, utente: User) -> list[AccessoAlProgetto]:
    """A quali progetti e classificazioni questa persona ha accesso.

    Serve alla pagina che il creatore apre per controllare la configurazione
    senza dover entrare con le credenziali di qualcun altro - cosa che, oltre
    a essere impossibile visto che le password non si rileggono, renderebbe
    illeggibile il registro delle operazioni.

    **Le risposte le da' `puo()`**, una per casella, esattamente come le
    darebbe a una pagina vera. Se questa funzione ricalcolasse i permessi per
    conto suo sarebbe una seconda regola, e una pagina che serve a controllare
    che le regole siano giuste non puo' essere l'unica a usarne una diversa.

    Per il creatore l'elenco esce comunque - i progetti che ha in mano come
    responsabile - ma la pagina scrive a chiare lettere che vede tutto: sono
    le sue credenziali a stabilirlo, non le assegnazioni.
    """
    progetti = list(
        db.scalars(
            select(Project)
            .join(ProductVersion, Project.product_version_id == ProductVersion.id)
            .join(Product, ProductVersion.product_id == Product.id)
            .where(
                or_(
                    Project.project_manager_id == utente.id,
                    exists(
                        select(Assignment.id)
                        .where(
                            Assignment.project_id == Project.id,
                            Assignment.user_id == utente.id,
                            Assignment.revoked_at.is_(None),
                        )
                        .correlate(Project)
                    ),
                )
            )
            .order_by(Product.code, ProductVersion.version_number)
        ).all()
    )

    classificazioni = elenco_classificazioni(db)

    accessi: list[AccessoAlProgetto] = []
    for progetto in progetti:
        righe = []
        for classificazione in classificazioni:
            bersaglio = _bersaglio(progetto, classificazione)
            righe.append(
                RigaAccesso(
                    classificazione=classificazione,
                    vedere=puo(db, utente, Azione.VEDERE, bersaglio),
                    caricare=puo(db, utente, Azione.CARICARE, bersaglio),
                    modificare=puo(db, utente, Azione.MODIFICARE, bersaglio),
                )
            )

        accessi.append(
            AccessoAlProgetto(
                progetto=progetto,
                ruolo=ruolo_nel_progetto(db, progetto.id, utente.id),
                e_responsabile=progetto.project_manager_id == utente.id,
                righe=righe,
            )
        )

    return accessi


def _bersaglio(
    progetto: Project, classificazione: Classification
) -> BersaglioCaricamento:
    """Scorciatoia per non ripetere tre volte la stessa costruzione."""
    return BersaglioCaricamento(
        progetto=progetto, classification_id=classificazione.id
    )
