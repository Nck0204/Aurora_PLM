"""Le fasi di un progetto: i modelli di percorso e il flusso di avanzamento.

**LE FASI SONO DATI, NON CODICE.** E' il principio che regge tutto questo
file, e va letto prima di modificarlo. Aggiungere una fase, rinominarla,
riordinarla o costruire un percorso completamente diverso non deve costare
nessuna riga di programma: si crea un modello di fasi dall'interfaccia e si
apre un progetto su quello. In questo file non c'e' nessun confronto fra il
nome di una fase e una stringa scritta a mano, e non ce ne deve entrare: se
capita di doverne scrivere uno, quello che manca e' una **proprieta' della
fase**, non un `if` (D-055).

Le proprieta' oggi sono due, e stanno nella tabella `phases`:

    blocks_return    da questa fase non si torna indietro
    closes_project   entrando in questa fase, il progetto si chiude

Tutto il resto lo dice l'ordine (`sort_order`): la fase successiva e' quella
con l'ordine immediatamente piu' alto, le precedenti sono quelle con l'ordine
piu' basso.


NON E' UN TERZO GRAFO DI TRANSIZIONI
------------------------------------

CLAUDE.md dice che i grafi delle transizioni stanno tutti in
`app/services/lifecycle.py` e in nessun altro posto: sono due, quello di una
versione di prodotto e quello di un documento (D-042, D-044). Le fasi non
sono il terzo e questo file non lo viola, perche' qui **non c'e' nessun
grafo**: gli stati di un ciclo di vita sono un elenco chiuso scritto in
`enums.py`, con delle frecce decise dal programma; le fasi sono righe di una
tabella, in un ordine che stabilisce chi crea il modello. Un grafo di fasi
scritto in Python sarebbe esattamente l'errore che questa sessione deve
evitare.


LE QUATTRO STRADE CHE UN PROGETTO PUO' PRENDERE
-----------------------------------------------

    avanza()      chi governa il progetto lo porta nella fase successiva;
    richiedi()    chi ci lavora **chiede** di avanzare, e la richiesta resta
                  in attesa finche' qualcuno non la guarda;
    decidi()      la richiesta viene accolta (e la fase cambia) o respinta;
    torna_a()     si rientra in una fase gia' attraversata.

Tutte e quattro lasciano una riga in `phase_transitions` e una nel registro
delle operazioni. Nessuna cancella niente: una richiesta respinta resta,
perche' "perche' a marzo il progetto e' rimasto fermo" e' una domanda a cui si
deve poter rispondere.

**Qui non si decide nessun permesso.** Chi puo' fare che cosa lo dice
`permissions.puo()`, come per ogni altra cosa di Aurora (D-051): le rotte
chiedono a lui prima di chiamare queste funzioni. Quello che sta qui sono le
regole del percorso, che sono un'altra cosa - il divieto di tornare indietro
da una fase che blocca vale anche per il creatore.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Phase,
    PhaseTemplate,
    PhaseTransition,
    PhaseTransitionState,
    ProductVersion,
    Project,
    User,
)
from app.services import audit

logger = logging.getLogger("aurora.fasi")

# --- Le azioni scritte nel registro delle operazioni ------------------------

ACTION_PHASE_ENTERED = "project.phase_entered"
ACTION_PHASE_REQUESTED = "project.phase_requested"
ACTION_PHASE_APPROVED = "project.phase_approved"
ACTION_PHASE_REJECTED = "project.phase_rejected"
ACTION_PHASE_RETURNED = "project.phase_returned"
ACTION_PROJECT_CLOSED = "project.closed"

ACTION_TEMPLATE_CREATED = "phase_template.created"
ACTION_TEMPLATE_VERSIONED = "phase_template.versioned"
ACTION_TEMPLATE_DEACTIVATED = "phase_template.deactivated"
ACTION_TEMPLATE_REACTIVATED = "phase_template.reactivated"

ENTITY_PROJECTS = "projects"
ENTITY_PHASE_TEMPLATES = "phase_templates"
ENTITY_PHASE_TRANSITIONS = "phase_transitions"


class PassaggioNonAmmesso(Exception):
    """Il passaggio di fase richiesto non si puo' fare.

    Il messaggio e' gia' scritto in italiano e va bene per essere mostrato a
    chi sta usando il programma: dice che cosa non si puo' fare e, quando
    esiste, che cosa si puo' fare invece. Chi la cattura lo mostra e basta.

    E' la stessa idea di lifecycle.TransizioneNonAmmessa, e per la stessa
    ragione: un messaggio ricomposto da chi cattura l'eccezione e' un
    messaggio che prima o poi differisce da quello scritto qui.
    """

    def __init__(self, messaggio: str, rimedio: str | None = None) -> None:
        super().__init__(messaggio)
        self.messaggio = messaggio
        # L'indirizzo di quello che si puo' fare al posto di quello che e'
        # stato rifiutato. La pagina ci disegna un pulsante: un divieto che
        # non dice come si fa invece e' un divieto che fa telefonare qualcuno.
        self.rimedio = rimedio

    # Testo del pulsante che porta al rimedio. E' uno solo perche' oggi il
    # rimedio e' uno solo; il giorno in cui ce ne fosse un altro, diventa un
    # parametro come "rimedio".
    ETICHETTA_RIMEDIO = "Crea una versione nuova del prodotto"


# ---------------------------------------------------------------------------
#  1. LEGGERE UN PERCORSO
# ---------------------------------------------------------------------------


def modelli_di_fasi(
    db: Session, comprese_disattivate: bool = False
) -> list[PhaseTemplate]:
    """I modelli di fasi, in ordine di nome e di versione.

    Senza argomenti restituisce solo quelli **proponibili** per un progetto
    nuovo. Un modello disattivato resta valido per i progetti che lo stanno
    gia' usando - i modelli non si toccano mai, D-016 - ma non si propone piu'
    per i lavori nuovi.

    Con comprese_disattivate=True escono tutti: serve alla pagina che li
    amministra, che deve mostrare anche le versioni vecchie e dire quanti
    progetti le usano.
    """
    interrogazione = select(PhaseTemplate)
    if not comprese_disattivate:
        interrogazione = interrogazione.where(PhaseTemplate.is_active.is_(True))

    return list(
        db.scalars(
            interrogazione.options(selectinload(PhaseTemplate.phases)).order_by(
                PhaseTemplate.name, PhaseTemplate.version
            )
        ).all()
    )


def trova_modello(db: Session, phase_template_id: uuid.UUID) -> PhaseTemplate | None:
    """Cerca un modello di fasi dal suo identificatore."""
    return db.get(PhaseTemplate, phase_template_id)


def fasi_del_modello(db: Session, phase_template_id: uuid.UUID) -> list[Phase]:
    """Le fasi di un modello, in ordine di attraversamento."""
    return list(
        db.scalars(
            select(Phase)
            .where(Phase.phase_template_id == phase_template_id)
            .order_by(Phase.sort_order)
        ).all()
    )


def fasi_del_progetto(db: Session, progetto: Project) -> list[Phase]:
    """Le fasi che questo progetto attraversa: quelle del modello congelato.

    Sono quelle del modello scelto quando il progetto e' stato aperto, non
    quelle del modello di adesso: se nel frattempo e' nata una versione nuova
    del modello, questo progetto continua a seguire quella con cui e' nato
    (D-041).
    """
    return fasi_del_modello(db, progetto.phase_template_id)


def progetti_per_modello(db: Session) -> dict[uuid.UUID, int]:
    """Quanti progetti usano ciascun modello di fasi.

    E' il numero che rende leggibile la pagina dei modelli: davanti a
    "Standard v1" e "Standard v2" la domanda che ci si fa e' "quale sto
    guardando, quello vecchio o quello nuovo?", e la risposta e' quanti lavori
    ci sono appesi.

    Una interrogazione sola con un raggruppamento, non una per riga: i modelli
    sono pochi ma i progetti no, e un conteggio per riga in una pagina e' il
    modo piu' comune di rendere lenta una pagina che non ha motivo di esserlo.
    """
    righe = db.execute(
        select(Project.phase_template_id, func.count(Project.id)).group_by(
            Project.phase_template_id
        )
    ).all()
    return {template_id: quanti for template_id, quanti in righe}


def fase_successiva(db: Session, progetto: Project) -> Phase | None:
    """La fase in cui il progetto andrebbe avanzando di un passo.

    None quando il progetto e' gia' nell'ultima fase del suo percorso, oppure
    quando non e' ancora entrato in nessuna: nel secondo caso la "successiva"
    sarebbe la prima, ma quel passaggio lo fa l'apertura del progetto e non
    l'avanzamento.
    """
    if progetto.current_phase_id is None:
        return None

    corrente = db.get(Phase, progetto.current_phase_id)
    if corrente is None:
        return None

    return db.scalars(
        select(Phase)
        .where(
            Phase.phase_template_id == progetto.phase_template_id,
            Phase.sort_order > corrente.sort_order,
        )
        .order_by(Phase.sort_order)
        .limit(1)
    ).first()


def fasi_precedenti(db: Session, progetto: Project) -> list[Phase]:
    """Le fasi che stanno prima di quella corrente, in ordine.

    Sono le sole in cui un ritorno ha senso: tornare "avanti" e' un
    avanzamento, e ha una sua strada con le sue regole.
    """
    if progetto.current_phase_id is None:
        return []

    corrente = db.get(Phase, progetto.current_phase_id)
    if corrente is None:
        return []

    return list(
        db.scalars(
            select(Phase)
            .where(
                Phase.phase_template_id == progetto.phase_template_id,
                Phase.sort_order < corrente.sort_order,
            )
            .order_by(Phase.sort_order)
        ).all()
    )


def opzioni_fasi_precedenti(db: Session, progetto: Project) -> list[tuple[str, str]]:
    """Le fasi a cui si puo' tornare, come coppie (identificatore, nome).

    Si compongono qui e non nel template per la regola della sezione 5 di
    docs/GUIDA_STILE.md: un template che mette in fila identificatori e nomi
    contiene una regola, e le regole non si provano con un test se stanno
    dentro l'HTML.
    """
    return [(str(fase.id), fase.name) for fase in fasi_precedenti(db, progetto)]


# ---------------------------------------------------------------------------
#  2. LA BARRA DELL'AVANZAMENTO E LO STORICO
# ---------------------------------------------------------------------------


def barra_avanzamento(db: Session, progetto: Project) -> list[dict]:
    """Le fasi come le vuole il componente `avanzamento`, gia' pronte.

    Conclusa quella gia' attraversata, corrente quella di adesso, niente per
    le prossime: l'ordine di attraversamento e' `sort_order`, quindi "gia'
    attraversata" vuol dire "prima di quella corrente".

    La data che compare sotto le fasi concluse e' quella in cui il progetto
    ne e' **uscito**, presa dal passaggio che l'ha chiusa. Non e' un ornamento:
    e' quello che trasforma la barra da "a che punto siamo" a "quanto ci
    abbiamo messo", che e' la seconda domanda che fanno tutti.
    """
    fasi = fasi_del_progetto(db, progetto)
    uscite = _date_di_uscita(db, progetto)

    posizione_corrente = _posizione(fasi, progetto.current_phase_id)

    barra: list[dict] = []
    for indice, fase in enumerate(fasi):
        if posizione_corrente is not None and indice < posizione_corrente:
            stato = "conclusa"
        elif indice == posizione_corrente:
            stato = "corrente"
        else:
            stato = ""

        uscita = uscite.get(fase.id)
        barra.append(
            {
                "nome": fase.name,
                "stato": stato,
                "data": uscita.strftime("%d/%m/%y") if uscita else None,
            }
        )

    return barra


def anteprima_percorso(fasi: list[Phase]) -> list[dict]:
    """Le fasi di un modello per il componente dell'avanzamento, senza stato.

    Serve alla scheda di un modello, che mostra il percorso come lo vedra' chi
    aprira' un progetto su di lui. Nessuna fase e' "corrente": non c'e' nessun
    progetto: sono tutte da fare, ed e' esattamente quello che si vuole vedere
    mentre si decide se l'ordine e' giusto.
    """
    return [{"nome": fase.name, "stato": ""} for fase in fasi]


def _posizione(fasi: list[Phase], phase_id: uuid.UUID | None) -> int | None:
    """A che punto dell'elenco sta una fase. None se non c'e'."""
    if phase_id is None:
        return None
    for indice, fase in enumerate(fasi):
        if fase.id == phase_id:
            return indice
    return None


def _date_di_uscita(db: Session, progetto: Project) -> dict[uuid.UUID, datetime]:
    """Per ogni fase, quando il progetto ne e' uscito l'ultima volta.

    Si legge dai passaggi **approvati**: quello che porta da A a B e' anche
    quello che chiude A. Una richiesta in attesa non ha chiuso niente, e una
    respinta nemmeno.
    """
    date: dict[uuid.UUID, datetime] = {}
    for passaggio in _passaggi_avvenuti(db, progetto):
        if passaggio.from_phase_id is not None:
            date[passaggio.from_phase_id] = _quando(passaggio)
    return date


def _passaggi_avvenuti(db: Session, progetto: Project) -> list[PhaseTransition]:
    """I passaggi che hanno davvero cambiato la fase, dal piu' vecchio."""
    return [
        passaggio
        for passaggio in tutti_i_passaggi(db, progetto)
        if passaggio.state is PhaseTransitionState.APPROVATA
    ]


def tutti_i_passaggi(db: Session, progetto: Project) -> list[PhaseTransition]:
    """Tutte le righe di passaggio di un progetto, dalla piu' vecchia.

    Comprese le richieste in attesa e quelle respinte: sono la storia del
    progetto quanto i passaggi avvenuti.
    """
    return list(
        db.scalars(
            select(PhaseTransition)
            .where(PhaseTransition.project_id == progetto.id)
            .options(
                selectinload(PhaseTransition.from_phase),
                selectinload(PhaseTransition.to_phase),
                selectinload(PhaseTransition.requested_by),
                selectinload(PhaseTransition.decided_by),
            )
            .order_by(PhaseTransition.created_at)
        ).all()
    )


def _quando(passaggio: PhaseTransition) -> datetime:
    """Il momento che conta per un passaggio.

    Per uno avvenuto e' `decided_at`, cioe' quando la fase e' cambiata
    davvero: una richiesta scritta lunedi' e approvata giovedi' ha cambiato la
    fase giovedi', e misurare la durata delle fasi su lunedi' direbbe che il
    progetto e' stato in due fasi contemporaneamente per tre giorni.

    Per una richiesta ancora in attesa e' `created_at`, che e' quando e' stata
    scritta: non c'e' ancora nessuna decisione da datare.
    """
    return passaggio.decided_at or passaggio.created_at


@dataclass(frozen=True)
class VoceStorico:
    """Una riga dello storico delle fasi, gia' pronta da mostrare.

    Tutto quello che c'e' dentro e' testo composto in Python: la pagina lo
    disegna e basta. E' la regola della sezione 5 di docs/GUIDA_STILE.md, e
    qui vale doppio - "approvata da Luigi Bianchi, su richiesta di Mario
    Rossi" e' una frase che si compone guardando tre colonne, e una frase
    costruita dentro un `{% if %}` non si prova con un test.
    """

    quando: datetime
    da: str | None
    a: str
    chi: str
    esito: str
    variante: str
    motivazione: str | None
    motivazione_decisione: str | None
    durata: str | None
    in_attesa: bool


def storico(db: Session, progetto: Project) -> list[VoceStorico]:
    """La storia delle fasi del progetto, dalla piu' recente alla piu' vecchia.

    Ogni riga dice chi, quando, da dove a dove, con quale motivazione e
    **quanto e' durata la fase che si e' lasciata**. La durata sta sulla riga
    che chiude la fase e non su quella che la apre: e' li' che il numero e'
    noto, ed e' li' che chi legge se lo chiede.

    L'ordine e' al contrario di quello del database perche' una storia si
    guarda dalla fine: la domanda e' quasi sempre "che cosa e' successo per
    ultimo".
    """
    passaggi = tutti_i_passaggi(db, progetto)

    # Quando il progetto e' entrato in ciascuna fase: serve a calcolare la
    # durata di quella che il passaggio successivo chiudera'. Si costruisce
    # scorrendo i passaggi avvenuti in avanti, perche' la durata di una fase
    # e' la differenza fra due passaggi consecutivi.
    ingresso: dict[uuid.UUID, datetime] = {}
    durate: dict[uuid.UUID, timedelta] = {}

    for passaggio in passaggi:
        if passaggio.state is not PhaseTransitionState.APPROVATA:
            continue
        momento = _quando(passaggio)
        if passaggio.from_phase_id is not None:
            entrata = ingresso.get(passaggio.from_phase_id)
            if entrata is not None:
                durate[passaggio.id] = momento - entrata
        ingresso[passaggio.to_phase_id] = momento

    voci = [
        _voce_storico(passaggio, durate.get(passaggio.id))
        for passaggio in passaggi
    ]
    voci.reverse()
    return voci


def _voce_storico(passaggio: PhaseTransition, durata: timedelta | None) -> VoceStorico:
    """Compone la riga di storico di un passaggio."""
    richiedente = passaggio.requested_by.full_name
    decisore = passaggio.decided_by.full_name if passaggio.decided_by else None

    if passaggio.state is PhaseTransitionState.RICHIESTA:
        chi = richiedente
        esito = "in attesa"
        variante = "attenzione"
    elif passaggio.state is PhaseTransitionState.RESPINTA:
        chi = f"{decisore}, su richiesta di {richiedente}"
        esito = "respinta"
        variante = "errore"
    elif passaggio.from_phase_id is None:
        chi = richiedente
        esito = "apertura"
        variante = "neutra"
    elif decisore is not None and decisore != richiedente:
        chi = f"{decisore}, su richiesta di {richiedente}"
        esito = "approvata"
        variante = "successo"
    else:
        chi = richiedente
        esito = _verso(passaggio)
        variante = "accento" if esito == "avanzamento" else "attenzione"

    return VoceStorico(
        quando=_quando(passaggio),
        da=passaggio.from_phase.name if passaggio.from_phase else None,
        a=passaggio.to_phase.name,
        chi=chi,
        esito=esito,
        variante=variante,
        motivazione=passaggio.reason,
        motivazione_decisione=passaggio.decision_reason,
        durata=durata_leggibile(durata),
        in_attesa=passaggio.state is PhaseTransitionState.RICHIESTA,
    )


def _verso(passaggio: PhaseTransition) -> str:
    """"avanzamento" o "ritorno", guardando l'ordine delle due fasi."""
    if passaggio.from_phase is None:
        return "avanzamento"
    if passaggio.to_phase.sort_order < passaggio.from_phase.sort_order:
        return "ritorno"
    return "avanzamento"


def durata_leggibile(durata: timedelta | None) -> str | None:
    """Una durata come la direbbe una persona: "3 giorni", "5 ore".

    None resta None: una fase che non si e' ancora chiusa non ha una durata, e
    scrivere "0 giorni" sarebbe dire una cosa falsa.

    Sotto l'ora non si scende: un progetto industriale non si misura in
    minuti, e "meno di un'ora" e' piu' onesto di "43 minuti" - che sembra un
    dato preciso e invece dipende da quando qualcuno si e' ricordato di
    premere il pulsante.
    """
    if durata is None:
        return None

    giorni = durata.days
    if giorni >= 1:
        return f"{giorni} giorn{'o' if giorni == 1 else 'i'}"

    ore = int(durata.total_seconds() // 3600)
    if ore >= 1:
        return f"{ore} or{'a' if ore == 1 else 'e'}"

    return "meno di un'ora"


def in_corso_da(db: Session, progetto: Project) -> str | None:
    """Da quanto tempo il progetto e' nella fase in cui si trova adesso."""
    if progetto.current_phase_id is None:
        return None

    ingresso: datetime | None = None
    for passaggio in _passaggi_avvenuti(db, progetto):
        if passaggio.to_phase_id == progetto.current_phase_id:
            ingresso = _quando(passaggio)

    if ingresso is None:
        return None

    return durata_leggibile(datetime.now(timezone.utc) - ingresso)


# ---------------------------------------------------------------------------
#  3. MUOVERE UN PROGETTO
# ---------------------------------------------------------------------------


def avanza(
    db: Session,
    *,
    progetto: Project,
    motivazione: str,
    autore: User,
    request: Request | None = None,
) -> PhaseTransition:
    """Porta il progetto nella fase successiva. Lo fa chi lo governa.

    Se la fase in cui si entra e' quella che chiude il percorso
    (`closes_project`), il progetto si chiude nello stesso momento: la
    chiusura non e' un'operazione a parte da ricordarsi, e' la conseguenza di
    essere arrivati in fondo.

    Il commit non si fa qui: lo fa chi gestisce la richiesta, insieme alle
    righe di registro. O si scrive tutto o non si scrive niente.
    """
    prossima = fase_successiva(db, progetto)
    if prossima is None:
        raise PassaggioNonAmmesso(
            "Il progetto e' gia' nell'ultima fase del suo percorso: "
            "da qui non si avanza."
        )

    return _esegui(
        db,
        progetto=progetto,
        destinazione=prossima,
        motivazione=motivazione,
        richiedente=autore,
        decisore=autore,
        azione=ACTION_PHASE_ENTERED,
        request=request,
    )


def torna_a(
    db: Session,
    *,
    progetto: Project,
    destinazione: Phase,
    motivazione: str,
    autore: User,
    request: Request | None = None,
) -> PhaseTransition:
    """Riporta il progetto in una fase gia' attraversata.

    **Il divieto e' qui, ed e' una proprieta' della fase corrente.** Da una
    fase con `blocks_return` non si torna indietro, e non e' una questione di
    permessi: non ci torna nemmeno il creatore. Quando il progetto e' arrivato
    li' dentro, il prodotto e' in mano ai progettisti; riavvolgerlo vorrebbe
    dire far finta che quel lavoro non sia stato fatto. Quello che si fa
    invece e' aprire una **versione nuova del prodotto**, che e' un lavoro
    nuovo con la sua storia - e l'eccezione porta con se' l'indirizzo per
    farlo, perche' un divieto che non dice come si fa invece e' un divieto che
    fa telefonare qualcuno.
    """
    corrente = (
        db.get(Phase, progetto.current_phase_id)
        if progetto.current_phase_id
        else None
    )

    if corrente is None:
        raise PassaggioNonAmmesso(
            "Il progetto non e' ancora entrato in nessuna fase: "
            "non c'e' niente da cui tornare indietro."
        )

    if corrente.blocks_return:
        raise PassaggioNonAmmesso(
            f"Da «{corrente.name}» non si torna a una fase precedente. "
            "Quando un progetto e' arrivato qui il lavoro di progettazione e' "
            "cominciato, e riportarlo indietro racconterebbe una storia che "
            "non e' avvenuta. Se serve rimetterci le mani si crea una "
            "versione nuova del prodotto, che nasce con il suo progetto e le "
            "sue fasi.",
            rimedio=f"/versioni/{progetto.product_version_id}/deriva",
        )

    if destinazione.sort_order >= corrente.sort_order:
        raise PassaggioNonAmmesso(
            f"«{destinazione.name}» non e' una fase precedente a "
            f"«{corrente.name}»: per andare avanti si usa l'avanzamento."
        )

    return _esegui(
        db,
        progetto=progetto,
        destinazione=destinazione,
        motivazione=motivazione,
        richiedente=autore,
        decisore=autore,
        azione=ACTION_PHASE_RETURNED,
        request=request,
    )


def richiedi(
    db: Session,
    *,
    progetto: Project,
    motivazione: str,
    autore: User,
    request: Request | None = None,
) -> PhaseTransition:
    """Chiede di avanzare di una fase. **Non cambia niente.**

    La riga nasce in stato "richiesta" e resta li' finche' il project manager
    non la guarda: compare nel suo cruscotto, e chi ha chiesto ne vede l'esito
    nel proprio.

    Una richiesta per volta. La seconda non e' un errore di chi la scrive - e'
    un progetto in cui due persone hanno visto la stessa cosa - ma due
    richieste identiche in attesa costringono chi decide a rispondere due
    volte alla stessa domanda, e la seconda risposta non vuol dire niente.
    """
    prossima = fase_successiva(db, progetto)
    if prossima is None:
        raise PassaggioNonAmmesso(
            "Il progetto e' gia' nell'ultima fase del suo percorso: "
            "non c'e' niente da chiedere."
        )

    if richiesta_in_attesa(db, progetto) is not None:
        raise PassaggioNonAmmesso(
            "C'e' gia' una richiesta di avanzamento in attesa su questo "
            "progetto: aspetta che venga decisa."
        )

    passaggio = PhaseTransition(
        project_id=progetto.id,
        from_phase_id=progetto.current_phase_id,
        to_phase_id=prossima.id,
        state=PhaseTransitionState.RICHIESTA,
        requested_by_id=autore.id,
        reason=motivazione or None,
    )
    db.add(passaggio)
    db.flush()

    audit.record(
        db,
        action=ACTION_PHASE_REQUESTED,
        entity_type=ENTITY_PROJECTS,
        entity_id=progetto.id,
        user_id=autore.id,
        request=request,
        new_value={
            "to_phase": prossima.name,
            "transition_id": str(passaggio.id),
            "motivazione": motivazione or None,
        },
    )

    logger.info(
        "Progetto %s: '%s' chiede il passaggio a '%s'",
        progetto.id,
        autore.username,
        prossima.name,
    )

    return passaggio


def decidi(
    db: Session,
    *,
    passaggio: PhaseTransition,
    accolta: bool,
    motivazione: str,
    autore: User,
    request: Request | None = None,
) -> PhaseTransition:
    """Accoglie o respinge una richiesta di avanzamento.

    Accolta, la fase cambia adesso: `decided_at` e' il momento in cui e'
    cambiata, e la durata delle fasi si misura su quello e non su quando la
    richiesta era stata scritta.

    Respinta, non cambia niente e la riga resta con la sua motivazione. E' la
    parte che sembra inutile e non lo e': un progetto fermo per due settimane
    ha una ragione, e questa e' l'unica riga che la conserva.

    Una richiesta gia' decisa non si decide una seconda volta. Puo' succedere
    davvero - due schermi aperti sulla stessa pagina del cruscotto, due clic -
    e la seconda decisione sovrascriverebbe la prima senza lasciare traccia.
    """
    if passaggio.state is not PhaseTransitionState.RICHIESTA:
        raise PassaggioNonAmmesso(
            "Questa richiesta e' gia' stata decisa: non c'e' piu' niente da "
            "approvare o respingere."
        )

    progetto = passaggio.project
    adesso = datetime.now(timezone.utc)

    passaggio.decided_by_id = autore.id
    passaggio.decided_at = adesso
    passaggio.decision_reason = motivazione or None

    if not accolta:
        passaggio.state = PhaseTransitionState.RESPINTA

        audit.record(
            db,
            action=ACTION_PHASE_REJECTED,
            entity_type=ENTITY_PHASE_TRANSITIONS,
            entity_id=passaggio.id,
            user_id=autore.id,
            request=request,
            old_value={"state": PhaseTransitionState.RICHIESTA.value},
            new_value={
                "state": PhaseTransitionState.RESPINTA.value,
                "project_id": str(progetto.id),
                "to_phase": passaggio.to_phase.name,
                "motivazione": motivazione or None,
            },
        )

        logger.info(
            "Progetto %s: '%s' respinge il passaggio a '%s'",
            progetto.id,
            autore.username,
            passaggio.to_phase.name,
        )
        return passaggio

    passaggio.state = PhaseTransitionState.APPROVATA

    audit.record(
        db,
        action=ACTION_PHASE_APPROVED,
        entity_type=ENTITY_PHASE_TRANSITIONS,
        entity_id=passaggio.id,
        user_id=autore.id,
        request=request,
        old_value={"state": PhaseTransitionState.RICHIESTA.value},
        new_value={
            "state": PhaseTransitionState.APPROVATA.value,
            "project_id": str(progetto.id),
            "to_phase": passaggio.to_phase.name,
            "richiesta_da": passaggio.requested_by.username,
            "motivazione": motivazione or None,
        },
    )

    _entra_nella_fase(
        db,
        progetto=progetto,
        destinazione=passaggio.to_phase,
        autore=autore,
        request=request,
        quando=adesso,
    )

    logger.info(
        "Progetto %s: '%s' approva il passaggio a '%s' chiesto da '%s'",
        progetto.id,
        autore.username,
        passaggio.to_phase.name,
        passaggio.requested_by.username,
    )

    return passaggio


def _esegui(
    db: Session,
    *,
    progetto: Project,
    destinazione: Phase,
    motivazione: str,
    richiedente: User,
    decisore: User,
    azione: str,
    request: Request | None,
) -> PhaseTransition:
    """Scrive un passaggio gia' deciso e sposta il progetto.

    E' la strada di chi governa il progetto: chiede e decide nello stesso
    momento, quindi la riga nasce gia' approvata con le due colonne uguali.
    Che siano due colonne e non una e' voluto: fra due anni si deve poter
    distinguere un avanzamento deciso da una persona sola da uno chiesto da
    qualcuno e approvato da qualcun altro.
    """
    adesso = datetime.now(timezone.utc)

    passaggio = PhaseTransition(
        project_id=progetto.id,
        from_phase_id=progetto.current_phase_id,
        to_phase_id=destinazione.id,
        state=PhaseTransitionState.APPROVATA,
        requested_by_id=richiedente.id,
        decided_by_id=decisore.id,
        decided_at=adesso,
        reason=motivazione or None,
    )
    db.add(passaggio)
    db.flush()

    partenza = passaggio.from_phase.name if passaggio.from_phase else None

    audit.record(
        db,
        action=azione,
        entity_type=ENTITY_PROJECTS,
        entity_id=progetto.id,
        user_id=decisore.id,
        request=request,
        old_value={"phase": partenza} if partenza else None,
        new_value={
            "phase": destinazione.name,
            "transition_id": str(passaggio.id),
            "motivazione": motivazione or None,
        },
    )

    _entra_nella_fase(
        db,
        progetto=progetto,
        destinazione=destinazione,
        autore=decisore,
        request=request,
        quando=adesso,
    )

    logger.info(
        "Progetto %s: da '%s' a '%s' per mano di '%s'",
        progetto.id,
        partenza,
        destinazione.name,
        decisore.username,
    )

    return passaggio


def _entra_nella_fase(
    db: Session,
    *,
    progetto: Project,
    destinazione: Phase,
    autore: User,
    request: Request | None,
    quando: datetime,
) -> None:
    """Sposta il progetto e, se la fase lo prevede, lo chiude.

    La chiusura sta qui e in nessun altro posto: e' la conseguenza di essere
    entrati nell'ultima casella del percorso, non un'operazione che qualcuno
    deve ricordarsi di fare dopo. Un progetto arrivato in fondo e lasciato
    aperto e' un progetto che continua a comparire fra quelli in corso, e a
    quel punto il cruscotto smette di voler dire qualcosa.

    Il ritorno a una fase precedente **riapre** un progetto chiuso. E' il caso
    raro ma reale della chiusura sbagliata: se il ritorno e' consentito - e da
    una fase che blocca non lo e' - allora il progetto sta ricominciando a
    muoversi, e lasciarlo segnato come chiuso sarebbe una contraddizione
    scritta in due colonne.
    """
    # Si assegnano tutte e due: la chiave esterna e il collegamento. Scrivere
    # solo la prima lascerebbe progetto.current_phase con la fase di prima
    # finche' qualcuno non ricarica la riga, e chi legge subito dopo - la
    # pagina che si disegna, il test che verifica - vedrebbe il progetto
    # ancora dov'era.
    progetto.current_phase_id = destinazione.id
    progetto.current_phase = destinazione

    if destinazione.closes_project:
        if progetto.closed_at is None:
            progetto.closed_at = quando
            audit.record(
                db,
                action=ACTION_PROJECT_CLOSED,
                entity_type=ENTITY_PROJECTS,
                entity_id=progetto.id,
                user_id=autore.id,
                request=request,
                new_value={"closed_at": quando.isoformat(), "phase": destinazione.name},
            )
            logger.info(
                "Progetto %s chiuso entrando nella fase '%s'",
                progetto.id,
                destinazione.name,
            )
        return

    if progetto.closed_at is not None:
        progetto.closed_at = None
        audit.record(
            db,
            action=ACTION_PROJECT_CLOSED,
            entity_type=ENTITY_PROJECTS,
            entity_id=progetto.id,
            user_id=autore.id,
            request=request,
            old_value={"closed_at": "valorizzato"},
            new_value={"closed_at": None, "phase": destinazione.name},
        )
        logger.info(
            "Progetto %s riaperto: e' tornato nella fase '%s'",
            progetto.id,
            destinazione.name,
        )


def entra_nella_prima_fase(
    db: Session,
    *,
    progetto: Project,
    autore: User,
    request: Request | None = None,
) -> PhaseTransition | None:
    """Fa entrare un progetto appena aperto nella prima fase del suo modello.

    None quando il modello non ha nessuna fase: un modello vuoto e' possibile
    (nessuno vieta di crearne uno e riempirlo dopo) e non deve far fallire
    l'apertura di un progetto.

    La riga di passaggio con `from_phase_id` nullo e' il primo capitolo della
    storia del progetto. Fino alla sessione 7 quell'ingresso lasciava soltanto
    una riga nel registro delle operazioni: adesso che lo storico delle fasi
    si mostra in una pagina, senza questa riga la storia comincerebbe dal
    secondo passaggio e non si saprebbe piu' da quando dura la prima fase.
    """
    fasi = fasi_del_modello(db, progetto.phase_template_id)
    if not fasi:
        return None

    return _esegui(
        db,
        progetto=progetto,
        destinazione=fasi[0],
        motivazione="Apertura del progetto.",
        richiedente=autore,
        decisore=autore,
        azione=ACTION_PHASE_ENTERED,
        request=request,
    )


# ---------------------------------------------------------------------------
#  4. LE RICHIESTE: CHI LE DEVE GUARDARE, CHI NE ASPETTA L'ESITO
# ---------------------------------------------------------------------------


def richiesta_in_attesa(db: Session, progetto: Project) -> PhaseTransition | None:
    """La richiesta di avanzamento aperta su questo progetto, se c'e'."""
    return db.scalars(
        select(PhaseTransition)
        .where(
            PhaseTransition.project_id == progetto.id,
            PhaseTransition.state == PhaseTransitionState.RICHIESTA,
        )
        .options(
            selectinload(PhaseTransition.to_phase),
            selectinload(PhaseTransition.requested_by),
        )
        .order_by(PhaseTransition.created_at)
        .limit(1)
    ).first()


def trova_passaggio(
    db: Session, transition_id: uuid.UUID
) -> PhaseTransition | None:
    """Cerca un passaggio dal suo identificatore."""
    return db.get(PhaseTransition, transition_id)


def richieste_da_decidere(db: Session, utente: User) -> list[PhaseTransition]:
    """Le richieste che questa persona deve guardare, dalla piu' vecchia.

    Sono quelle aperte sui progetti di cui e' responsabile. Il filtro e'
    nell'interrogazione e non nella pagina: una richiesta di un progetto che
    non e' suo non deve nemmeno uscire dal database.

    Il creatore non compare qui apposta. Puo' decidere qualunque richiesta -
    puo' tutto, dappertutto - ma il cruscotto e' la lista delle cose che
    aspettano **te**, e riempirla con le richieste di tutta l'azienda la
    renderebbe la lista di quelle che aspettano qualcun altro.

    Le piu' vecchie in cima: una richiesta di tre giorni fa e' piu' urgente di
    una di stamattina, e un elenco che mette in cima l'ultima arrivata e' un
    elenco in cui la prima si perde.
    """
    return list(
        db.scalars(
            select(PhaseTransition)
            .join(Project, PhaseTransition.project_id == Project.id)
            .where(
                PhaseTransition.state == PhaseTransitionState.RICHIESTA,
                Project.project_manager_id == utente.id,
            )
            .options(
                selectinload(PhaseTransition.to_phase),
                selectinload(PhaseTransition.from_phase),
                selectinload(PhaseTransition.requested_by),
                selectinload(PhaseTransition.project)
                .selectinload(Project.product_version)
                .selectinload(ProductVersion.product),
            )
            .order_by(PhaseTransition.created_at)
        ).all()
    )


@dataclass(frozen=True)
class Esito:
    """Un esito da leggere, con le sue parole gia' scelte.

    Le parole sono tre e cambiano tutte insieme: il titolo dell'avviso, la
    frase che dice chi ha deciso che cosa, e la tinta. Sceglierle nel template
    vorrebbe dire scrivere dentro l'HTML che "approvata" al femminile diventa
    "approvato" al maschile quando il verbo cambia - che e' una regola, e le
    regole non stanno nei template (docs/GUIDA_STILE.md, sezione 5).
    """

    passaggio: PhaseTransition
    titolo: str
    frase: str
    variante: str


# Le parole dei due esiti. Sono una tabella e non due rami di un `if` perche'
# cosi' si leggono insieme: il giorno in cui se ne aggiungesse un terzo, si
# vedrebbe subito che cosa manca.
PAROLE_ESITO: dict[PhaseTransitionState, tuple[str, str, str]] = {
    PhaseTransitionState.APPROVATA: ("approvata", "approvato", "successo"),
    PhaseTransitionState.RESPINTA: ("respinta", "respinto", "errore"),
}


def esiti_da_leggere(db: Session, utente: User) -> list[Esito]:
    """Gli esiti delle richieste di questa persona che non ha ancora letto.

    E' la notifica dentro l'applicazione chiesta dalla sessione: chi ha
    chiesto un passaggio deve sapere com'e' andata anche se in quel momento
    stava guardando un'altra pagina.

    Le richieste che la persona ha deciso da se' non ci finiscono: un project
    manager che avanza il proprio progetto ha appena visto succedere quello
    che ha chiesto, e dirglielo di nuovo sarebbe rumore.
    """
    return [_esito(passaggio) for passaggio in _passaggi_da_leggere(db, utente)]


def _esito(passaggio: PhaseTransition) -> Esito:
    """Compone le parole di un esito."""
    participio, verbo, variante = PAROLE_ESITO[passaggio.state]
    decisore = passaggio.decided_by.full_name if passaggio.decided_by else "Aurora"

    return Esito(
        passaggio=passaggio,
        titolo=f"La tua richiesta di passaggio e' stata {participio}",
        frase=(
            f"{decisore} ha {verbo} il passaggio a "
            f"«{passaggio.to_phase.name}»."
        ),
        variante=variante,
    )


def _passaggi_da_leggere(db: Session, utente: User) -> list[PhaseTransition]:
    """Le righe grezze degli esiti non ancora letti di questa persona."""
    return list(
        db.scalars(
            select(PhaseTransition)
            .where(
                PhaseTransition.requested_by_id == utente.id,
                PhaseTransition.decided_by_id.is_not(None),
                PhaseTransition.decided_by_id != utente.id,
                PhaseTransition.seen_at.is_(None),
                PhaseTransition.state != PhaseTransitionState.RICHIESTA,
            )
            .options(
                selectinload(PhaseTransition.to_phase),
                selectinload(PhaseTransition.decided_by),
                selectinload(PhaseTransition.project)
                .selectinload(Project.product_version)
                .selectinload(ProductVersion.product),
            )
            .order_by(PhaseTransition.decided_at)
        ).all()
    )


def trova_esito_da_leggere(
    db: Session, utente: User, transition_id: uuid.UUID
) -> PhaseTransition | None:
    """L'esito non ancora letto **di questa persona**, se esiste.

    Si cerca dentro l'elenco di quelli suoi e non con un db.get() seguito da
    un confronto: cosi' non c'e' nessun momento in cui il programma ha in mano
    la riga di qualcun altro. E' la stessa idea del filtro negli elenchi -
    quello che non ti spetta non esce nemmeno dal database - applicata a una
    riga sola.
    """
    for passaggio in _passaggi_da_leggere(db, utente):
        if passaggio.id == transition_id:
            return passaggio
    return None


def segna_letto(db: Session, passaggio: PhaseTransition) -> PhaseTransition:
    """Segna che chi aveva chiesto il passaggio ha letto l'esito.

    Non si registra nell'audit trail: aver letto una notifica non e'
    un'operazione sui dati dell'azienda, e una riga di registro per ogni
    notifica chiusa renderebbe illeggibile il registro delle cose che contano
    (regola 6 di CLAUDE.md, letta per quello che vuol dire).
    """
    if passaggio.seen_at is None:
        passaggio.seen_at = datetime.now(timezone.utc)
    return passaggio


# ---------------------------------------------------------------------------
#  5. AMMINISTRARE I MODELLI
# ---------------------------------------------------------------------------
#
# I modelli di fasi sono **immutabili** (D-016). Non c'e' nessuna funzione che
# modifica un modello: c'e' nuova_versione(), che ne scrive uno nuovo con lo
# stesso nome e il numero di versione aumentato di uno, e disattiva quello da
# cui e' partita.
#
# Il perche' e' scritto in D-016 e vale la pena di ripeterlo qui, perche' e'
# questo il file in cui verrebbe voglia di aggiungere una modifica: un
# progetto aperto due anni fa e' passato per le fasi di allora. Se il modello
# si potesse correggere a posteriori, la sua storia racconterebbe fasi che al
# tempo non esistevano, e le approvazioni registrate risulterebbero riferite a
# passaggi mai avvenuti.


@dataclass(frozen=True)
class FaseScritta:
    """Una fase come arriva dal modulo di creazione di un modello.

    Non e' la riga del database: e' quello che una persona ha scritto, ancora
    da verificare. Tenerle separate evita di costruire righe a meta' e poi
    doverle buttare.
    """

    nome: str
    descrizione: str = ""
    blocca_ritorno: bool = False
    chiude_progetto: bool = False


def crea_modello(
    db: Session,
    *,
    nome: str,
    descrizione: str,
    norme: list[str],
    fasi: list[FaseScritta],
    autore: User,
    request: Request | None = None,
) -> PhaseTemplate:
    """Crea un modello di fasi nuovo, alla versione 1.

    Il nome deve essere libero: due modelli con lo stesso nome sarebbero due
    versioni dello stesso, e quella e' un'altra strada (nuova_versione).
    Chi chiama ha gia' verificato con nome_gia_usato(); il vincolo di unicita'
    su (name, version) e' la rete, non il controllo.
    """
    modello = PhaseTemplate(
        name=nome.strip(),
        description=descrizione.strip() or None,
        standards=list(norme),
        is_active=True,
        version=1,
    )
    db.add(modello)
    db.flush()

    _scrivi_fasi(db, modello, fasi)

    audit.record(
        db,
        action=ACTION_TEMPLATE_CREATED,
        entity_type=ENTITY_PHASE_TEMPLATES,
        entity_id=modello.id,
        user_id=autore.id,
        request=request,
        new_value={
            "name": modello.name,
            "version": modello.version,
            "standards": list(norme),
            "phases": [fase.nome for fase in fasi],
        },
    )

    logger.info(
        "Modello di fasi '%s' v%s creato da '%s' con %s fasi",
        modello.name,
        modello.version,
        autore.username,
        len(fasi),
    )

    return modello


def nuova_versione(
    db: Session,
    *,
    partenza: PhaseTemplate,
    descrizione: str,
    norme: list[str],
    fasi: list[FaseScritta],
    autore: User,
    request: Request | None = None,
) -> PhaseTemplate:
    """Scrive la versione successiva di un modello. **Non modifica quella vecchia.**

    E' l'unico modo di correggere un modello, e non e' un giro largo per
    arrivare a una modifica: e' proprio un'altra cosa. Il modello vecchio
    resta esattamente com'era, con le sue fasi e i progetti che ci sono
    appesi; quello nuovo parte da adesso.

    Il modello di partenza viene **disattivato**: da questo momento non si
    propone piu' per i progetti nuovi. Non viene toccato in nessun altro modo,
    e i progetti che lo usano non se ne accorgono (D-041).
    """
    successiva = (
        db.scalar(
            select(func.max(PhaseTemplate.version)).where(
                PhaseTemplate.name == partenza.name
            )
        )
        or partenza.version
    ) + 1

    modello = PhaseTemplate(
        name=partenza.name,
        description=descrizione.strip() or None,
        standards=list(norme),
        is_active=True,
        version=successiva,
    )
    db.add(modello)
    db.flush()

    _scrivi_fasi(db, modello, fasi)

    partenza.is_active = False

    audit.record(
        db,
        action=ACTION_TEMPLATE_VERSIONED,
        entity_type=ENTITY_PHASE_TEMPLATES,
        entity_id=modello.id,
        user_id=autore.id,
        request=request,
        old_value={
            "name": partenza.name,
            "version": partenza.version,
            "is_active": False,
        },
        new_value={
            "name": modello.name,
            "version": modello.version,
            "standards": list(norme),
            "phases": [fase.nome for fase in fasi],
        },
    )

    logger.info(
        "Modello di fasi '%s': dalla v%s nasce la v%s, per mano di '%s'",
        modello.name,
        partenza.version,
        modello.version,
        autore.username,
    )

    return modello


def _scrivi_fasi(db: Session, modello: PhaseTemplate, fasi: list[FaseScritta]) -> None:
    """Scrive le fasi di un modello appena creato, numerandole in ordine.

    L'ordine e' quello in cui sono arrivate: chi compila il modulo scrive le
    fasi nell'ordine in cui si attraversano, che e' l'unico ordine che abbia
    senso, e il numero glielo mette il programma. Un campo "numero d'ordine"
    da compilare a mano sarebbe un campo da correggere tutte le volte che si
    inserisce una fase in mezzo.
    """
    for posizione, fase in enumerate(fasi, start=1):
        db.add(
            Phase(
                phase_template_id=modello.id,
                name=fase.nome.strip(),
                sort_order=posizione,
                description=fase.descrizione.strip() or None,
                blocks_return=fase.blocca_ritorno,
                closes_project=fase.chiude_progetto,
            )
        )
    db.flush()


def nome_gia_usato(db: Session, nome: str) -> bool:
    """Dice se esiste gia' un modello con questo nome, a qualunque versione."""
    return (
        db.scalars(
            select(PhaseTemplate.id).where(
                func.lower(PhaseTemplate.name) == nome.strip().lower()
            )
        ).first()
        is not None
    )


def cambia_proponibilita(
    db: Session,
    *,
    modello: PhaseTemplate,
    proponibile: bool,
    autore: User,
    request: Request | None = None,
) -> PhaseTemplate:
    """Mette o toglie un modello dall'elenco di quelli proponibili.

    Non e' una cancellazione e non tocca nessun progetto: un modello
    disattivato continua a governare i progetti che lo usano, esattamente come
    prima. Sparisce soltanto dalla tendina di chi apre un progetto nuovo.
    """
    modello.is_active = proponibile

    audit.record(
        db,
        action=(
            ACTION_TEMPLATE_REACTIVATED if proponibile else ACTION_TEMPLATE_DEACTIVATED
        ),
        entity_type=ENTITY_PHASE_TEMPLATES,
        entity_id=modello.id,
        user_id=autore.id,
        request=request,
        old_value={"is_active": not proponibile},
        new_value={"is_active": proponibile},
    )

    return modello
