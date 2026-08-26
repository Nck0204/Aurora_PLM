"""I progetti: apertura su una versione, squadra, e chi vede che cosa.

Un progetto si apre **su una versione di prodotto**, non su un prodotto, ed e'
uno solo per versione: il vincolo di unicita' su projects.product_version_id
e' quello che rende il legame uno a uno. La versione 2 di un prodotto e' un
lavoro nuovo, con la sua squadra e le sue fasi.

Due regole di questo modulo meritano di essere lette prima del codice.

**Le fasi non stanno qui.** Il percorso di un progetto - com'e' fatto, come
lo si attraversa, chi lo puo' muovere - sta tutto in
`app/services/phases.py`. Qui restano l'apertura, la squadra e il cruscotto.
Quando un progetto nasce, e' quel servizio a farlo entrare nella prima fase e
a scriverne il primo passaggio.

**Il modello di fasi si congela.** Alla nascita il progetto si tiene
l'identificatore del modello scelto e si **copia dentro** le norme
applicabili. I modelli sono immutabili per costruzione (una correzione
diventa una versione nuova del modello), quindi il legame gia' basterebbe; la
copia delle norme serve perche' quelle, sul singolo progetto, si possono
allargare o restringere. Un progetto aperto due anni fa deve raccontare le
fasi e le norme di allora, non quelle di adesso (D-041).

**Chi non e' assegnato non vede.** L'elenco dei progetti di una persona e'
costruito sulle sue assegnazioni non revocate. Non e' un filtro grafico: la
riga che non gli spetta non esce nemmeno dal database. Il creatore fa
eccezione e li vede tutti, perche' e' lui che li apre e che assegna le
persone.

**La regola non e' scritta qui.** Chi vede un progetto lo decide
`permissions.puo()`, come per qualunque altro permesso di Aurora, e la
condizione SQL degli elenchi e' `permissions.filtro_progetti()`, che e' la
stessa regola riscritta (D-051). Qui si mette il filtro
nell'interrogazione, non si stabilisce che cosa filtri.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Assignment,
    Customer,
    Phase,
    PhaseTemplate,
    Product,
    ProductVersion,
    Project,
    ProjectRole,
    User,
)
from app.services import audit, lifecycle, permissions, phases

logger = logging.getLogger("aurora.progetti")

ACTION_PROJECT_CREATED = "project.created"
ACTION_ASSIGNMENT_CREATED = "assignment.created"
ACTION_ASSIGNMENT_REVOKED = "assignment.revoked"

ENTITY_PROJECTS = "projects"
ENTITY_ASSIGNMENTS = "assignments"


# --- Lettura ----------------------------------------------------------------


def trova_progetto(db: Session, project_id: uuid.UUID) -> Project | None:
    """Cerca un progetto dal suo identificatore."""
    return db.get(Project, project_id)


def assegnazioni_attive(db: Session, project_id: uuid.UUID) -> list[Assignment]:
    """La squadra di adesso: le assegnazioni non revocate, con la persona."""
    return list(
        db.scalars(
            select(Assignment)
            .where(
                Assignment.project_id == project_id,
                Assignment.revoked_at.is_(None),
            )
            .options(selectinload(Assignment.user))
            .order_by(Assignment.project_role, Assignment.created_at)
        ).all()
    )


def utente_assegnato(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Dice se quella persona ha un'assegnazione **non revocata** sul progetto."""
    return (
        db.scalars(
            select(Assignment.id).where(
                Assignment.project_id == project_id,
                Assignment.user_id == user_id,
                Assignment.revoked_at.is_(None),
            )
        ).first()
        is not None
    )


def _progetti_visibili(utente: User) -> Select[tuple[Project]]:
    """L'interrogazione di partenza del cruscotto, gia' ristretta all'utente.

    Il filtro e' `permissions.filtro_progetti()`, cioe' la stessa regola che
    risponde quando si apre la scheda di un progetto solo. Qui non si decide
    niente: si mette la condizione, e la si mette in un punto solo, cosi' chi
    parte da questa funzione non se la puo' dimenticare.

    Restituisce None per il creatore, che vede tutto: in quel caso
    all'interrogazione non si aggiunge nessuna condizione.
    """
    interrogazione = (
        select(Project)
        .join(ProductVersion, Project.product_version_id == ProductVersion.id)
        .join(Product, ProductVersion.product_id == Product.id)
    )

    filtro = permissions.filtro_progetti(utente)
    if filtro is not None:
        interrogazione = interrogazione.where(filtro)

    return interrogazione


def cruscotto(
    db: Session,
    utente: User,
    *,
    testo: str | None = None,
    stato: str | None = None,
    fase: str | None = None,
    aperti: bool = True,
) -> list[Project]:
    """I progetti che questa persona vede, per la pagina iniziale.

    I filtri chiesti dall'azienda sono due - lo stato del ciclo di vita della
    versione e il nome della fase corrente - e insieme a loro c'e' la casella
    di ricerca che la barra dei filtri porta comunque con se': cerca nel
    codice del prodotto e nel nome del cliente, che sono le due cose con cui
    in azienda un progetto viene chiamato a voce.

    Il filtro sulla fase e' **sul nome** e non sull'identificatore. Due modelli
    di fasi diversi hanno due righe distinte per la fase "Concept" (e' la
    conseguenza dell'immutabilita' dei modelli, docs/MODELLO_DATI.md 4.7): chi
    guarda il cruscotto e sceglie "Concept" vuole vedere tutti i progetti che
    sono a quel punto, non quelli di un modello soltanto.

    L'ordine mette in cima i lavori piu' recenti: il cruscotto si guarda la
    mattina per sapere a che punto e' quello che si sta facendo adesso.
    """
    # Le tre righe di selectinload evitano che disegnare venti righe di
    # cruscotto costi ottanta interrogazioni: senza, ogni riga andrebbe a
    # chiedere per conto suo la versione, il prodotto, il cliente, la fase e
    # il responsabile.
    interrogazione = _progetti_visibili(utente).options(
        selectinload(Project.product_version)
        .selectinload(ProductVersion.product)
        .selectinload(Product.customer),
        selectinload(Project.current_phase),
        selectinload(Project.project_manager),
    )

    if aperti:
        interrogazione = interrogazione.where(Project.closed_at.is_(None))

    if testo:
        parola = f"%{testo.strip()}%"
        interrogazione = interrogazione.join(
            Customer, Product.customer_id == Customer.id
        ).where(or_(Product.code.ilike(parola), Customer.name.ilike(parola)))

    if stato:
        interrogazione = interrogazione.where(
            ProductVersion.lifecycle_state == stato
        )

    if fase:
        interrogazione = interrogazione.join(
            Phase, Project.current_phase_id == Phase.id
        ).where(Phase.name == fase)

    interrogazione = interrogazione.order_by(Project.opened_at.desc())

    return list(db.scalars(interrogazione).all())


def fasi_in_uso(db: Session, utente: User) -> list[str]:
    """I nomi delle fasi in cui si trovano i progetti visibili a questa persona.

    Serve a riempire la tendina del filtro: dentro ci sono solo fasi in cui
    qualcosa si trova davvero, cosi' scegliendone una non si finisce mai su un
    elenco vuoto.
    """
    interrogazione = (
        _progetti_visibili(utente)
        .join(Phase, Project.current_phase_id == Phase.id)
        .where(Project.closed_at.is_(None))
    )

    # Si prende il solo nome della fase: l'interrogazione di partenza seleziona
    # i progetti, qui interessa un'altra colonna.
    nomi = db.scalars(
        interrogazione.with_only_columns(Phase.name).distinct().order_by(Phase.name)
    ).all()

    return list(nomi)


def filtri_cruscotto(
    db: Session, utente: User, stato: str | None, fase: str | None
) -> list[dict]:
    """I due filtri della barra di ricerca, pronti per il componente.

    Li compone il servizio e non i template perche' le stesse due tendine
    compaiono in due pagine - il cruscotto e l'elenco dei progetti - e devono
    proporre le stesse voci con le stesse parole. Scritte due volte, alla
    prima modifica ne resterebbe indietro una.

    Le voci della tendina delle fasi sono solo quelle in cui si trova
    qualcosa: una scelta che porta a un elenco vuoto e' una scelta che non
    andava proposta.
    """
    return [
        {
            "nome": "stato",
            "etichetta": "Stato del ciclo di vita",
            "opzioni": lifecycle.opzioni_stati(),
            "scelto": stato or "",
            "vuoto": "Qualunque stato",
        },
        {
            "nome": "fase",
            "etichetta": "Fase corrente",
            "opzioni": [(nome, nome) for nome in fasi_in_uso(db, utente)],
            "scelto": fase or "",
            "vuoto": "Qualunque fase",
        },
    ]


def conta_progetti_visibili(db: Session, utente: User) -> int:
    """Quanti progetti aperti vede questa persona, filtri esclusi."""
    interrogazione = _progetti_visibili(utente).where(Project.closed_at.is_(None))
    return (
        db.scalar(
            interrogazione.with_only_columns(func.count(Project.id)).order_by(None)
        )
        or 0
    )


# --- Scrittura --------------------------------------------------------------


def apri_progetto(
    db: Session,
    *,
    versione: ProductVersion,
    project_manager: User,
    modello: PhaseTemplate,
    norme: list[str],
    ingegneri: list[User],
    lettori: list[User],
    autore: User,
    request: Request | None = None,
) -> Project:
    """Apre il progetto su una versione di prodotto e ne compone la squadra.

    Fa quattro cose, in quest'ordine:

      1. crea il progetto, congelando il modello di fasi scelto e copiandoci
         dentro le norme applicabili;
      2. lo fa entrare nella **prima fase** del modello, passando dal servizio
         delle fasi: l'ingresso e' un passaggio come tutti gli altri e lascia
         la sua riga nello storico;
      3. assegna il project manager e poi ingegneri e lettori;
      4. registra tutto nel registro delle operazioni.

    Chi chiama ha gia' verificato che sulla versione non ci sia gia' un
    progetto: il vincolo di unicita' del database e' la rete di sicurezza, non
    il controllo.
    """
    progetto = Project(
        product_version_id=versione.id,
        project_manager_id=project_manager.id,
        phase_template_id=modello.id,
        standards=list(norme),
        opened_at=datetime.now(timezone.utc),
    )
    db.add(progetto)
    db.flush()

    audit.record(
        db,
        action=ACTION_PROJECT_CREATED,
        entity_type=ENTITY_PROJECTS,
        entity_id=progetto.id,
        user_id=autore.id,
        request=request,
        new_value={
            "product_version_id": str(versione.id),
            "project_manager": project_manager.username,
            "phase_template": f"{modello.name} v{modello.version}",
            "standards": list(norme),
        },
    )

    # L'ingresso nella prima fase e' un fatto che succede adesso e va scritto
    # adesso: se non lo si scrive, la storia delle fasi comincia dal secondo
    # passaggio e nessuno sa piu' quando il progetto e' entrato nel primo -
    # ne' da quanto tempo ci sta dentro. Lo scrive il servizio delle fasi,
    # che e' l'unico che muove un progetto lungo il suo percorso.
    phases.entra_nella_prima_fase(
        db, progetto=progetto, autore=autore, request=request
    )

    # Il project manager e' anche un assegnato: il suo permesso non deve
    # dipendere da quale delle due colonne si guarda. Cosi' "chi vede questo
    # progetto" ha una risposta sola - chi ha un'assegnazione non revocata - e
    # il responsabile non e' un caso a parte da ricordarsi ogni volta.
    assegna(
        db,
        progetto=progetto,
        utente=project_manager,
        ruolo=ProjectRole.PROJECT_MANAGER,
        autore=autore,
        request=request,
    )

    for ingegnere in ingegneri:
        if ingegnere.id != project_manager.id:
            assegna(
                db,
                progetto=progetto,
                utente=ingegnere,
                ruolo=ProjectRole.INGEGNERE,
                autore=autore,
                request=request,
            )

    for lettore in lettori:
        # Chi e' gia' nella squadra con un ruolo piu' alto non viene
        # retrocesso a lettore: l'indice unico parziale ammette una sola
        # assegnazione attiva per persona, e la prima che si e' scritta e'
        # quella che vale.
        if lettore.id != project_manager.id and not any(
            lettore.id == ingegnere.id for ingegnere in ingegneri
        ):
            assegna(
                db,
                progetto=progetto,
                utente=lettore,
                ruolo=ProjectRole.LETTORE,
                autore=autore,
                request=request,
            )

    logger.info(
        "Progetto aperto sulla versione %s da '%s', responsabile '%s'",
        versione.id,
        autore.username,
        project_manager.username,
    )

    return progetto


def assegna(
    db: Session,
    *,
    progetto: Project,
    utente: User,
    ruolo: ProjectRole,
    autore: User,
    request: Request | None = None,
) -> Assignment:
    """Mette una persona nella squadra di un progetto, con un ruolo.

    Se la persona ha gia' un'assegnazione attiva su questo progetto, quella
    viene **revocata** prima di scriverne una nuova: l'indice unico parziale
    su (project_id, user_id) limitato alle righe non revocate ammette un solo
    ruolo attivo per persona, e due ruoli insieme renderebbero ambiguo il
    calcolo dei permessi. La riga vecchia resta in tabella con la sua data:
    "chi aveva accesso a questo progetto in marzo" e' una domanda a cui si
    deve poter rispondere.
    """
    esistente = db.scalars(
        select(Assignment).where(
            Assignment.project_id == progetto.id,
            Assignment.user_id == utente.id,
            Assignment.revoked_at.is_(None),
        )
    ).first()

    if esistente is not None:
        if esistente.project_role is ruolo:
            return esistente
        revoca(db, assegnazione=esistente, autore=autore, request=request)

    assegnazione = Assignment(
        project_id=progetto.id,
        user_id=utente.id,
        project_role=ruolo,
        assigned_by_id=autore.id,
    )
    db.add(assegnazione)
    db.flush()

    audit.record(
        db,
        action=ACTION_ASSIGNMENT_CREATED,
        entity_type=ENTITY_ASSIGNMENTS,
        entity_id=assegnazione.id,
        user_id=autore.id,
        request=request,
        new_value={
            "project_id": str(progetto.id),
            "user": utente.username,
            "project_role": ruolo.value,
        },
    )

    return assegnazione


def revoca(
    db: Session,
    *,
    assegnazione: Assignment,
    autore: User,
    request: Request | None = None,
) -> Assignment:
    """Toglie una persona dalla squadra. La riga resta, con data e autore."""
    assegnazione.revoked_at = datetime.now(timezone.utc)
    assegnazione.revoked_by_id = autore.id

    audit.record(
        db,
        action=ACTION_ASSIGNMENT_REVOKED,
        entity_type=ENTITY_ASSIGNMENTS,
        entity_id=assegnazione.id,
        user_id=autore.id,
        request=request,
        old_value={"project_role": assegnazione.project_role.value},
        new_value={"revoked": True},
    )

    return assegnazione
