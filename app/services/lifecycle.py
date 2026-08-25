"""Il ciclo di vita di una versione di prodotto: chi puo' cambiarlo e come.

Questo modulo contiene tre cose, e sono le tre regole che l'azienda ha
chiesto per prime:

  1. **Il grafo delle transizioni**, cioe' da quale stato si puo' passare a
     quale altro. Sta qui sotto, in una tabella sola, ed e' l'unico posto in
     cui e' scritto: cambiare le regole vuol dire cambiare quelle righe e
     nient'altro. Una transizione non prevista viene rifiutata con una frase
     in italiano che dice quali sono quelle possibili, non con un errore
     tecnico.

  2. **Il superamento automatico.** Quando una versione passa a "rilasciato",
     la versione precedente dello stesso prodotto passa da sola a "superato".
     E' l'unica regola di Aurora che cambia una riga senza che nessuno gliel'
     abbia chiesto direttamente, e per questo l'operazione viene registrata
     nel registro di audit **come azione di sistema**, cioe' senza autore
     (audit_logs.user_id resta nullo: vedi docs/MODELLO_DATI.md, 4.9).

  3. **Chi puo' cambiare stato**: il creatore e il project manager del
     progetto aperto su quella versione. Nessun altro.

La conferma che l'utente vede prima di rilasciare - "attenzione, la versione
1 passera' a superato" - la costruisce la rotta usando le stesse due funzioni
che poi eseguono l'operazione (versione_precedente e transizione_ammessa).
Non e' un dettaglio: se la conferma si calcolasse per conto suo, prima o poi
direbbe una cosa e il programma ne farebbe un'altra.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LifecycleState, ProductVersion, User
from app.services import audit

logger = logging.getLogger("aurora.ciclo_vita")


# ---------------------------------------------------------------------------
#  1. IL GRAFO DELLE TRANSIZIONI
# ---------------------------------------------------------------------------
#
#      in sviluppo ──> rilasciato ──> in produzione
#                          │                │
#                          └──> superato <──┘
#                                   │
#            (da ogni stato) ──> obsoleto
#
# Si legge cosi': la chiave e' lo stato di partenza, l'elenco a destra sono
# gli stati in cui si puo' andare. Un elenco vuoto vuol dire che da li' non
# si va piu' da nessuna parte.
#
# Le scelte che non sono ovvie e che vale la pena di ricordare:
#
#   - **non si torna indietro.** Da "rilasciato" non si rientra in sviluppo:
#     una versione rilasciata e' un fatto avvenuto, e se serve rimetterci le
#     mani si deriva una versione nuova. E' lo stesso principio per cui un
#     documento caricato non si modifica ma si ricarica (docs/MODELLO_DATI.md);
#   - **a "superato" si arriva anche a mano**, non solo per il superamento
#     automatico: una linea di prodotto che l'azienda smette di seguire va
#     dichiarata superata anche senza che esista una versione che la sostituisce;
#   - **"obsoleto" e' l'unico stato terminale** e si raggiunge da tutti gli
#     altri: e' la fine del ciclo, e da li' non si esce.
#
# Per cambiare le regole si cambia questa tabella. Non c'e' nessun altro
# posto in cui gli stati vengano confrontati fra loro.

TRANSIZIONI_AMMESSE: dict[LifecycleState, tuple[LifecycleState, ...]] = {
    LifecycleState.IN_SVILUPPO: (
        LifecycleState.RILASCIATO,
        LifecycleState.OBSOLETO,
    ),
    LifecycleState.RILASCIATO: (
        LifecycleState.IN_PRODUZIONE,
        LifecycleState.SUPERATO,
        LifecycleState.OBSOLETO,
    ),
    LifecycleState.IN_PRODUZIONE: (
        LifecycleState.SUPERATO,
        LifecycleState.OBSOLETO,
    ),
    LifecycleState.SUPERATO: (LifecycleState.OBSOLETO,),
    LifecycleState.OBSOLETO: (),
}

# Lo stato che richiede una motivazione scritta a mano. Non e' una regola del
# grafo ma una regola dell'azienda: dichiarare obsoleto un prodotto e' una
# decisione, e fra due anni deve essere possibile sapere perche' e' stata
# presa.
STATO_CON_MOTIVAZIONE = LifecycleState.OBSOLETO


def nome_stato(stato: LifecycleState) -> str:
    """Lo stato come si legge in italiano: "in sviluppo", non "in_sviluppo".

    Il valore nel database ha il trattino basso perche' e' un identificatore
    di un tipo enumerato di PostgreSQL; quello che si legge non ce l'ha.
    """
    return stato.value.replace("_", " ")


def elenco_stati(stati: tuple[LifecycleState, ...]) -> str:
    """Gli stati in fila, come si scriverebbero in una frase italiana."""
    nomi = [nome_stato(stato) for stato in stati]
    if not nomi:
        return ""
    if len(nomi) == 1:
        return nomi[0]
    return ", ".join(nomi[:-1]) + " e " + nomi[-1]


class TransizioneNonAmmessa(Exception):
    """Il passaggio di stato richiesto non e' previsto dal grafo.

    Il messaggio e' gia' scritto in italiano e va bene per essere mostrato a
    chi sta usando il programma: dice che cosa non si puo' fare e che cosa si
    puo' fare invece. Chi la cattura non deve ricomporre nessuna frase.
    """


def transizione_ammessa(da: LifecycleState, a: LifecycleState) -> bool:
    """Dice se si puo' passare da uno stato all'altro. Non solleva niente."""
    return a in TRANSIZIONI_AMMESSE.get(da, ())


def verifica_transizione(da: LifecycleState, a: LifecycleState) -> None:
    """Controlla la transizione e, se non e' ammessa, la spiega e si ferma.

    E' il punto unico in cui il grafo viene consultato prima di scrivere:
    tutte le strade che cambiano lo stato di una versione passano di qui.
    """
    if transizione_ammessa(da, a):
        return

    possibili = TRANSIZIONI_AMMESSE.get(da, ())

    if da == a:
        messaggio = (
            f"La versione e' gia' nello stato «{nome_stato(a)}»: "
            "non c'e' niente da cambiare."
        )
    elif not possibili:
        messaggio = (
            f"Una versione «{nome_stato(da)}» non cambia piu' stato: "
            "e' l'ultimo passo del ciclo di vita."
        )
    else:
        messaggio = (
            f"Una versione «{nome_stato(da)}» non puo' passare a "
            f"«{nome_stato(a)}». Da qui si puo' andare soltanto a: "
            f"{elenco_stati(possibili)}."
        )

    raise TransizioneNonAmmessa(messaggio)


def opzioni_stati() -> list[tuple[str, str]]:
    """Tutti gli stati come coppie (valore, testo), per le tendine dei filtri.

    Il valore e' quello scritto nel database ("in_sviluppo"), il testo quello
    che si legge ("in sviluppo"). Le coppie si compongono qui e non nei
    template: un template che sa trasformare un valore in un'etichetta e' un
    template che contiene una regola, e le regole stanno nel codice.
    """
    return [(stato.value, nome_stato(stato)) for stato in LifecycleState]


def stati_raggiungibili(da: LifecycleState) -> tuple[LifecycleState, ...]:
    """Gli stati proponibili a partire da quello attuale.

    Le pagine ci costruiscono i pulsanti: cosi' non si propone mai
    un'operazione che verrebbe poi rifiutata, e il giorno in cui il grafo
    cambia cambiano anche i pulsanti, senza toccare nessun template.
    """
    return TRANSIZIONI_AMMESSE.get(da, ())


# ---------------------------------------------------------------------------
#  2. CHI PUO' CAMBIARE STATO
# ---------------------------------------------------------------------------


def puo_cambiare_stato(versione: ProductVersion, utente: User) -> bool:
    """Vero per il creatore e per il project manager del progetto.

    Il progetto e' quello aperto su **questa** versione: il legame e' uno a
    uno (projects.product_version_id e' unico). Una versione su cui non e'
    ancora stato aperto nessun progetto la muove solo il creatore, perche'
    non c'e' ancora nessun responsabile a cui la decisione appartenga.
    """
    if utente.is_creatore:
        return True

    progetto = versione.project
    return progetto is not None and progetto.project_manager_id == utente.id


MESSAGGIO_NON_AUTORIZZATO = (
    "Il ciclo di vita di una versione lo cambiano il project manager del suo "
    "progetto e chi ha il ruolo di creatore."
)


# ---------------------------------------------------------------------------
#  3. IL CAMBIO DI STATO E IL SUPERAMENTO AUTOMATICO
# ---------------------------------------------------------------------------

ACTION_STATE_CHANGED = "product_version.state_changed"
ACTION_SUPERSEDED = "product_version.superseded"
ENTITY = "product_versions"


def versione_precedente(
    db: Session, versione: ProductVersion
) -> ProductVersion | None:
    """La versione dello stesso prodotto immediatamente precedente a questa.

    "Precedente" vuol dire con il numero di versione piu' alto fra quelli piu'
    bassi di questo: se esistono la 1, la 2 e la 4, la precedente della 4 e'
    la 2. Non si guarda la catena delle derivazioni: una versione puo' essere
    derivata dalla 1 pur venendo dopo la 3, e quella che il rilascio manda in
    pensione e' comunque quella che era in campo fino a un momento fa.
    """
    return db.scalars(
        select(ProductVersion)
        .where(
            ProductVersion.product_id == versione.product_id,
            ProductVersion.version_number < versione.version_number,
        )
        .order_by(ProductVersion.version_number.desc())
        .limit(1)
    ).first()


def versione_da_superare(
    db: Session, versione: ProductVersion
) -> ProductVersion | None:
    """La versione che il rilascio di questa manderebbe a "superato".

    None quando non c'e' una versione precedente, oppure quando c'e' ma il
    suo stato attuale non ammette il passaggio a "superato" - una versione
    gia' obsoleta, per esempio, resta obsoleta. Il grafo vale anche per le
    operazioni che fa il programma da solo: e' l'unico modo perche' resti
    vero che gli stati si muovono solo lungo le frecce.

    Questa e' la funzione che la pagina di conferma usa per dire all'utente
    che cosa sta per succedere, ed e' la stessa che il rilascio usa per farlo
    succedere davvero.
    """
    precedente = versione_precedente(db, versione)
    if precedente is None:
        return None
    if not transizione_ammessa(precedente.lifecycle_state, LifecycleState.SUPERATO):
        return None
    return precedente


def cambia_stato(
    db: Session,
    versione: ProductVersion,
    nuovo_stato: LifecycleState,
    autore: User,
    request: Request | None = None,
    motivazione: str | None = None,
) -> ProductVersion | None:
    """Porta una versione in un altro stato, applicando tutte le regole.

    Solleva TransizioneNonAmmessa se il passaggio non e' nel grafo: il
    controllo viene prima di qualunque scrittura, quindi un tentativo
    rifiutato non lascia niente a meta'.

    Restituisce la versione **superata automaticamente**, se il passaggio a
    "rilasciato" ne ha superata una; None in tutti gli altri casi. La rotta la
    usa per dire all'utente che cosa e' successo oltre a quello che aveva
    chiesto: un'operazione che ne provoca un'altra deve dirlo, altrimenti
    qualcuno si trova una versione cambiata di stato e non sa perche'.

    Il commit non si fa qui. Lo fa chi gestisce la richiesta, insieme alle
    righe di audit: o si scrive tutto o non si scrive niente.
    """
    stato_precedente = versione.lifecycle_state
    verifica_transizione(stato_precedente, nuovo_stato)

    versione.lifecycle_state = nuovo_stato

    # La data di rilascio si scrive una volta sola, la prima. Se un giorno il
    # grafo permettesse di rientrare in "rilasciato", la data da conservare
    # resterebbe quella del primo rilascio: e' quella che compare sui
    # documenti gia' consegnati al cliente.
    if nuovo_stato is LifecycleState.RILASCIATO and versione.released_at is None:
        versione.released_at = datetime.now(timezone.utc)

    nuovo_valore: dict[str, str] = {"lifecycle_state": nuovo_stato.value}
    if motivazione:
        nuovo_valore["motivazione"] = motivazione

    audit.record(
        db,
        action=ACTION_STATE_CHANGED,
        entity_type=ENTITY,
        entity_id=versione.id,
        user_id=autore.id,
        request=request,
        old_value={"lifecycle_state": stato_precedente.value},
        new_value=nuovo_valore,
    )

    logger.info(
        "Versione %s: da '%s' a '%s' per mano di '%s'",
        versione.id,
        stato_precedente.value,
        nuovo_stato.value,
        autore.username,
    )

    if nuovo_stato is LifecycleState.RILASCIATO:
        return _supera_la_precedente(db, versione, request)

    return None


def _supera_la_precedente(
    db: Session, rilasciata: ProductVersion, request: Request | None
) -> ProductVersion | None:
    """Manda a "superato" la versione precedente. E' la regola automatica.

    La riga di registro che ne esce ha user_id nullo di proposito: non l'ha
    chiesta nessuno, l'ha decisa il programma applicando una regola. Scriverci
    dentro chi ha premuto il pulsante direbbe una cosa falsa - quella persona
    ha rilasciato la versione nuova, non ha superato la vecchia - e fra un
    anno, leggendo il registro, non si distinguerebbe piu' una decisione presa
    da una persona da una conseguenza calcolata dal programma.

    In new_value resta scritto **da quale versione** e' stata superata: e' la
    sola informazione che rende quella riga comprensibile senza dover andare a
    guardare l'ora esatta delle righe vicine.
    """
    precedente = versione_da_superare(db, rilasciata)
    if precedente is None:
        return None

    stato_precedente = precedente.lifecycle_state
    precedente.lifecycle_state = LifecycleState.SUPERATO

    audit.record(
        db,
        action=ACTION_SUPERSEDED,
        entity_type=ENTITY,
        entity_id=precedente.id,
        user_id=None,  # azione di sistema: vedi la spiegazione qui sopra
        request=request,
        old_value={"lifecycle_state": stato_precedente.value},
        new_value={
            "lifecycle_state": LifecycleState.SUPERATO.value,
            "superata_da_versione": rilasciata.version_number,
            "superata_da_id": str(rilasciata.id),
        },
    )

    logger.info(
        "Superamento automatico: versione %s (numero %s) superata dalla %s",
        precedente.id,
        precedente.version_number,
        rilasciata.version_number,
    )

    return precedente


def trova_versione(db: Session, version_id: uuid.UUID) -> ProductVersion | None:
    """Cerca una versione dal suo identificatore."""
    return db.get(ProductVersion, version_id)
