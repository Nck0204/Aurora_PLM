"""Le pagine dei progetti.

    GET  /progetti                      elenco completo dei progetti visibili
    GET  /progetti/nuovo?versione={id}  modulo di apertura su una versione
    POST /progetti/nuovo                apre il progetto e compone la squadra
    GET  /progetti/{id}                 scheda del progetto

    GET  /progetti/{id}/fase            il modulo del passaggio di fase
    POST /progetti/{id}/fase/avanza     porta il progetto alla fase seguente
    POST /progetti/{id}/fase/richiedi   chiede il passaggio, senza farlo
    POST /progetti/{id}/fase/indietro   torna a una fase gia' attraversata
    POST /progetti/{id}/richieste/{rid} approva o respinge una richiesta
    POST /progetti/{id}/esiti/{rid}     segna letto l'esito di una richiesta

**Il percorso a fasi non e' scritto qui.** Come e' fatto, come lo si
attraversa e che cosa succede arrivando in fondo sta in
`app/services/phases.py`; queste rotte leggono un modulo, chiedono il
permesso e mostrano il risultato. In particolare **il divieto di tornare
indietro non e' un permesso**: e' una proprieta' della fase, e vale anche per
il creatore.

**Un progetto si apre su una versione di prodotto, mai da solo.** Per questo
il modulo di creazione vuole per forza il parametro "versione": non esiste una
pagina "nuovo progetto" da cui scegliere il prodotto dopo. Il legame e' uno a
uno e nasce insieme al progetto.

Chi non e' assegnato a un progetto non lo vede nell'elenco e non ne apre la
scheda: il controllo e' lo stesso nei due punti - `permissions.puo()` per la
scheda, `permissions.filtro_progetti()` per l'elenco, che sono la stessa
regola scritta due volte apposta perche' devono dire la stessa cosa - perche'
un elenco che nasconde una riga che poi si apre scrivendone l'indirizzo non e'
una protezione, e' una tenda.

**Un progetto che non si puo' vedere risponde 404**, con lo stesso messaggio
di uno che non esiste (D-051).
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore, richiedi_login
from app.models import Phase, PhaseTemplate, Project, User
from app.services import (
    documents,
    emails,
    lifecycle,
    permissions,
    phases,
    projects,
    users,
)
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.progetti")

router = APIRouter(prefix="/progetti", tags=["progetti"])

MESSAGGIO_PROGETTO_INESISTENTE = permissions.MESSAGGI_INESISTENTE[Project]

# Le quattro frasi che chiedono la motivazione. Sono quattro e non una perche'
# dicono quattro cose diverse: la motivazione di un avanzamento e' un
# resoconto, quella di un ritorno e' una giustificazione, e chiederle con le
# stesse parole vorrebbe dire non chiederle davvero.
MESSAGGIO_MOTIVAZIONE_AVANZAMENTO = (
    "Scrivi perche' il progetto puo' passare alla fase successiva: resta "
    "nello storico, ed e' quello che si legge quando si vuole sapere come si "
    "e' arrivati dove si e'."
)
MESSAGGIO_MOTIVAZIONE_RITORNO = (
    "Scrivi perche' il progetto deve tornare indietro. Un passo indietro "
    "senza una ragione scritta e' la cosa piu' difficile da spiegare fra un "
    "anno."
)
MESSAGGIO_MOTIVAZIONE_RICHIESTA = (
    "Scrivi perche' chiedi il passaggio: e' quello che leggera' il project "
    "manager per decidere."
)
MESSAGGIO_MOTIVAZIONE_DECISIONE = (
    "Scrivi la motivazione della tua decisione: chi ha chiesto il passaggio "
    "la ricevera' insieme all'esito."
)


def _progetto_visibile_o_errore(
    db: Session, project_id: uuid.UUID, utente: User
) -> Project:
    """Cerca il progetto e verifica che questa persona lo possa vedere.

    Le due risposte negative sono volutamente **indistinguibili**: 404 sia
    quando il progetto non esiste sia quando esiste e non e' di chi lo sta
    chiedendo. Fino alla sessione 6 la seconda era un 403, e dire "esiste ma
    non e' tuo" e' gia' dire qualcosa: che quel numero e' stato assegnato, che
    quel lavoro e' aperto. Chi prova gli indirizzi uno per uno si costruisce
    l'elenco dei progetti dell'azienda senza vederne nemmeno uno (D-051).
    """
    progetto = projects.trova_progetto(db, project_id)
    if progetto is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_PROGETTO_INESISTENTE)

    permissions.pretendi(db, utente, permissions.Azione.VEDERE, progetto)
    return progetto


# --- Elenco -----------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    q: str = "",
    stato: str = "",
    fase: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """L'elenco dei progetti visibili, con gli stessi filtri del cruscotto.

    E' la stessa interrogazione della pagina iniziale: la voce di menu
    "Progetti" porta qui, e chi ci arriva deve trovare quello che ha appena
    visto sul cruscotto, non un elenco costruito con altre regole.
    """
    return pagina(
        request,
        "progetti/elenco.html",
        progetti=projects.cruscotto(
            db, utente, testo=q or None, stato=stato or None, fase=fase or None
        ),
        filtri=projects.filtri_cruscotto(db, utente, stato, fase),
        q=q,
        stato_scelto=stato,
        fase_scelta=fase,
    )


# --- Apertura ---------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(
    request: Request,
    versione: str = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Mostra il modulo di apertura di un progetto su una versione.

    Lo apre il creatore. Non e' una scelta di comodo: aprire un progetto vuol
    dire assegnare delle persone, e chi assegna le persone e' chi gestisce
    l'anagrafica, non chi lavora dentro un progetto.
    """
    scelta = _versione_per_progetto(db, versione)

    return pagina(
        request,
        "progetti/nuovo.html",
        versione=scelta,
        prodotto=scelta.product,
        modelli=_opzioni_modelli(db),
        persone=_opzioni_persone(db),
    )


def _opzioni_persone(db: Session) -> list[tuple[str, str]]:
    """Le persone attive come coppie (identificatore, nome e cognome)."""
    return [
        (str(persona.id), persona.full_name)
        for persona in users.elenco_utenti(db, solo_attivi=True)
    ]


def _opzioni_modelli(db: Session) -> list[tuple[str, str]]:
    """I modelli di fasi attivi come coppie (identificatore, nome e versione).

    Il numero di versione compare nel testo perche' i modelli sono immutabili
    e ne convivono piu' versioni: "Standard v1" e "Standard v2" sono due
    percorsi diversi, e scegliere quello sbagliato si vedrebbe solo mesi dopo.
    """
    return [
        (str(modello.id), f"{modello.name} v{modello.version}")
        for modello in phases.modelli_di_fasi(db)
    ]


def _versione_per_progetto(db: Session, versione: str):
    """Cerca la versione su cui si vuole aprire il progetto e la controlla.

    Due rifiuti possibili, tutti e due con una frase italiana: la versione non
    esiste, oppure ci ha gia' un progetto sopra. Il secondo caso lo
    impedirebbe comunque il vincolo di unicita' del database, ma l'errore che
    ne verrebbe fuori sarebbe tecnico e in inglese.
    """
    try:
        trovata = lifecycle.trova_versione(db, uuid.UUID(versione))
    except (ValueError, AttributeError):
        trovata = None

    if trovata is None:
        raise HTTPException(
            status_code=404,
            detail="La versione di prodotto su cui aprire il progetto non esiste.",
        )

    if trovata.project is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Su questa versione c'e' gia' un progetto: una versione ne ha "
                "al massimo uno."
            ),
        )

    return trovata


@router.post("/nuovo")
def crea(
    request: Request,
    versione: Annotated[str, Form()] = "",
    project_manager: Annotated[str, Form()] = "",
    modello: Annotated[str, Form()] = "",
    norme: Annotated[str, Form()] = "",
    ingegneri: Annotated[list[str], Form()] = [],
    lettori: Annotated[list[str], Form()] = [],
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Apre il progetto, congela il modello di fasi e compone la squadra."""
    scelta = _versione_per_progetto(db, versione)

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "progetti/nuovo.html",
            stato=400,
            errore=messaggio,
            versione=scelta,
            prodotto=scelta.product,
            modelli=_opzioni_modelli(db),
            persone=_opzioni_persone(db),
            norme=norme,
        )

    responsabile = _utente_scelto(db, project_manager)
    if responsabile is None:
        return rimostra("Scegli il project manager del progetto.")

    modello_scelto = _modello_scelto(db, modello)
    if modello_scelto is None:
        return rimostra("Scegli il modello di fasi da seguire.")

    progetto = projects.apri_progetto(
        db,
        versione=scelta,
        project_manager=responsabile,
        modello=modello_scelto,
        norme=_norme_scritte(norme, modello_scelto),
        ingegneri=_utenti_scelti(db, ingegneri),
        lettori=_utenti_scelti(db, lettori),
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/progetti/{progetto.id}?aperto=1", status_code=303)


def _utente_scelto(db: Session, valore: str) -> User | None:
    """Cerca una persona dal suo identificatore, senza fidarsi del modulo."""
    try:
        return users.trova_utente(db, uuid.UUID(valore))
    except (ValueError, AttributeError):
        return None


def _utenti_scelti(db: Session, valori: list[str]) -> list[User]:
    """Le persone scelte in una casella a scelta multipla, quelle valide."""
    trovate: list[User] = []
    for valore in valori:
        persona = _utente_scelto(db, valore)
        if persona is not None and persona.is_active:
            trovate.append(persona)
    return trovate


def _modello_scelto(db: Session, valore: str) -> PhaseTemplate | None:
    """Cerca il modello di fasi scelto."""
    try:
        return db.scalars(
            select(PhaseTemplate).where(PhaseTemplate.id == uuid.UUID(valore))
        ).first()
    except (ValueError, AttributeError):
        return None


def _norme_scritte(testo: str, modello: PhaseTemplate) -> list[str]:
    """Le norme applicabili, una per riga, ripulite.

    Se la casella e' vuota si parte da quelle del modello: sono il punto di
    partenza ragionevole, e chi apre il progetto puo' toglierne o aggiungerne.
    Una volta scritte nel progetto non cambiano piu' da sole, nemmeno se il
    modello venisse sostituito (D-041).
    """
    righe = [riga.strip() for riga in testo.splitlines() if riga.strip()]
    if righe:
        return righe
    return list(modello.standards or [])


# --- Scheda -----------------------------------------------------------------


@router.get("/{project_id}")
def scheda(
    request: Request,
    project_id: uuid.UUID,
    aperto: int = 0,
    fase_cambiata: str = "",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """La scheda di un progetto: avanzamento, storico, squadra, documenti.

    In cima la barra delle fasi, che risponde in un secondo alla domanda che
    fanno tutti - "a che punto siamo?" - e sotto lo storico, che risponde alla
    seconda: "come ci siamo arrivati?".

    I due booleani dei permessi arrivano gia' decisi da permissions.puo(): la
    pagina li usa per sapere quali pulsanti disegnare, non per decidere se
    qualcuno ha diritto a qualcosa (D-051).
    """
    progetto = _progetto_visibile_o_errore(db, project_id, utente)

    return pagina(
        request,
        "progetti/scheda.html",
        progetto=progetto,
        versione=progetto.product_version,
        prodotto=progetto.product_version.product,
        squadra=projects.assegnazioni_attive(db, progetto.id),
        aperto=bool(aperto),
        fase_cambiata=fase_cambiata,
        **_contesto_fasi(db, progetto, utente),
        # Il riquadro dei documenti dice quanti se ne vedono e porta al loro
        # elenco. Il conteggio passa dallo stesso filtro dell'elenco, quindi
        # non puo' dire "tre documenti" a chi poi ne trova due.
        documenti_del_progetto=documents.conta_documenti(db, utente, progetto.id),
        messaggi_del_progetto=emails.conta_messaggi(
            db, utente, project_id=progetto.id
        ),
        puo_caricare=permissions.puo(
            db, utente, permissions.Azione.CARICARE, progetto
        ),
    )


def _contesto_fasi(db: Session, progetto: Project, utente: User) -> dict:
    """Tutto quello che riguarda le fasi, pronto per la pagina.

    Sta in una funzione perche' le pagine che ne hanno bisogno sono due - la
    scheda e il modulo del passaggio - e due copie dello stesso contesto
    divergono alla prima aggiunta.
    """
    avanza = permissions.puo(db, utente, permissions.Azione.MODIFICARE, progetto)
    chiede = permissions.puo(db, utente, permissions.Azione.RICHIEDERE, progetto)

    return {
        "avanzamento": phases.barra_avanzamento(db, progetto),
        "storico": phases.storico(db, progetto),
        "prossima_fase": phases.fase_successiva(db, progetto),
        "in_corso_da": phases.in_corso_da(db, progetto),
        "richiesta_in_attesa": phases.richiesta_in_attesa(db, progetto),
        "fasi_precedenti": phases.opzioni_fasi_precedenti(db, progetto),
        "puo_avanzare": avanza,
        # **Chi puo' avanzare non chiede: fa.** La regola di permissions.puo()
        # gia' lo dice per il project manager, ma il creatore puo' tutto e
        # quindi puo' anche chiedere: senza questa riga si troverebbe davanti
        # due moduli, e uno dei due gli proporrebbe di chiedere il permesso a
        # se' stesso.
        #
        # Non e' una decisione di permesso ed e' per questo che sta qui e non
        # in permissions.py: il permesso di chiedere il creatore ce l'ha, e se
        # costruisse la richiesta a mano verrebbe accolta. Questa riga decide
        # soltanto quale modulo disegnare.
        "puo_richiedere": chiede and not avanza,
    }


# --- Passaggi di fase -------------------------------------------------------
#
# Quattro rotte che scrivono e una che mostra il modulo. Le regole del
# percorso - che cosa viene dopo che cosa, da dove non si torna indietro, che
# cosa chiude il progetto - stanno tutte in app/services/phases.py: qui si
# legge un modulo, si chiede il permesso e si mostra il risultato.
#
# Il permesso e' sempre uno dei due: MODIFICARE per chi il progetto lo governa
# (avanza, torna indietro, decide le richieste altrui), RICHIEDERE per chi ci
# lavora e puo' soltanto domandare.


@router.get("/{project_id}/fase")
def mostra_fase(
    request: Request,
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Il modulo del passaggio di fase, con quello che questa persona puo' fare.

    Chi governa il progetto vede due moduli - avanza, torna indietro - chi ci
    lavora ne vede uno solo, quello della richiesta. Chi non puo' fare
    nessuna delle due cose non apre nemmeno la pagina: e' un 403, perche' il
    progetto lo vede gia' e quello che gli manca e' solo il permesso.
    """
    progetto = _progetto_visibile_o_errore(db, project_id, utente)

    contesto = _contesto_fasi(db, progetto, utente)
    if not contesto["puo_avanzare"] and not contesto["puo_richiedere"]:
        permissions.pretendi(db, utente, permissions.Azione.RICHIEDERE, progetto)

    return pagina(
        request,
        "progetti/fase.html",
        progetto=progetto,
        prodotto=progetto.product_version.product,
        versione=progetto.product_version,
        **contesto,
    )


def _pagina_fase_con_errore(
    request: Request,
    db: Session,
    progetto: Project,
    utente: User,
    errore: "phases.PassaggioNonAmmesso",
    motivazione: str = "",
) -> Response:
    """Rimostra il modulo del passaggio spiegando perche' e' stato rifiutato.

    L'eccezione porta con se' anche il **rimedio**, quando ne esiste uno: il
    caso vero e' il ritorno indietro da una fase che lo blocca, dove la
    risposta utile non e' "non si puo'" ma "si fa in quest'altro modo", con il
    collegamento gia' pronto.
    """
    logger.info(
        "Progetto %s: passaggio di fase rifiutato a '%s' (%s)",
        progetto.id,
        utente.username,
        errore.messaggio,
    )

    return pagina(
        request,
        "progetti/fase.html",
        stato=400,
        # "problema" e non "errore": base.html disegna da se' quello che si
        # chiama "errore", e qui l'avviso lo compone la pagina, perche' ci
        # deve mettere dentro il pulsante del rimedio. E' la strada che la
        # nota in cima a base.html indica per questo caso.
        problema=errore.messaggio,
        rimedio=errore.rimedio,
        etichetta_rimedio=phases.PassaggioNonAmmesso.ETICHETTA_RIMEDIO,
        progetto=progetto,
        prodotto=progetto.product_version.product,
        versione=progetto.product_version,
        motivazione=motivazione,
        **_contesto_fasi(db, progetto, utente),
    )


@router.post("/{project_id}/fase/avanza")
def avanza(
    request: Request,
    project_id: uuid.UUID,
    motivazione: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Porta il progetto nella fase successiva. Lo fa chi lo governa."""
    progetto = _progetto_visibile_o_errore(db, project_id, utente)
    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, progetto)

    if not motivazione.strip():
        return _pagina_fase_con_errore(
            request,
            db,
            progetto,
            utente,
            phases.PassaggioNonAmmesso(MESSAGGIO_MOTIVAZIONE_AVANZAMENTO),
        )

    try:
        phases.avanza(
            db,
            progetto=progetto,
            motivazione=motivazione,
            autore=utente,
            request=request,
        )
    except phases.PassaggioNonAmmesso as errore:
        return _pagina_fase_con_errore(
            request, db, progetto, utente, errore, motivazione
        )

    db.commit()
    return RedirectResponse(
        url=f"/progetti/{progetto.id}?fase_cambiata=avanzata", status_code=303
    )


@router.post("/{project_id}/fase/indietro")
def torna_indietro(
    request: Request,
    project_id: uuid.UUID,
    destinazione: Annotated[str, Form()] = "",
    motivazione: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Riporta il progetto a una fase gia' attraversata.

    Il permesso e' quello di chi governa il progetto, ma il permesso non
    basta: da una fase che blocca il ritorno non si torna indietro nemmeno
    avendolo. Quel divieto lo solleva il servizio, e la pagina che ne esce
    porta il collegamento alla creazione di una versione nuova di prodotto,
    che e' quello che si fa invece.
    """
    progetto = _progetto_visibile_o_errore(db, project_id, utente)
    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, progetto)

    if not motivazione.strip():
        return _pagina_fase_con_errore(
            request,
            db,
            progetto,
            utente,
            phases.PassaggioNonAmmesso(MESSAGGIO_MOTIVAZIONE_RITORNO),
        )

    fase = _fase_scelta(db, progetto, destinazione)
    if fase is None:
        return _pagina_fase_con_errore(
            request,
            db,
            progetto,
            utente,
            phases.PassaggioNonAmmesso("Scegli la fase a cui riportare il progetto."),
            motivazione,
        )

    try:
        phases.torna_a(
            db,
            progetto=progetto,
            destinazione=fase,
            motivazione=motivazione,
            autore=utente,
            request=request,
        )
    except phases.PassaggioNonAmmesso as errore:
        return _pagina_fase_con_errore(
            request, db, progetto, utente, errore, motivazione
        )

    db.commit()
    return RedirectResponse(
        url=f"/progetti/{progetto.id}?fase_cambiata=tornata", status_code=303
    )


@router.post("/{project_id}/fase/richiedi")
def richiedi(
    request: Request,
    project_id: uuid.UUID,
    motivazione: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Chiede il passaggio alla fase successiva. **Non cambia niente.**"""
    progetto = _progetto_visibile_o_errore(db, project_id, utente)
    permissions.pretendi(db, utente, permissions.Azione.RICHIEDERE, progetto)

    if not motivazione.strip():
        return _pagina_fase_con_errore(
            request,
            db,
            progetto,
            utente,
            phases.PassaggioNonAmmesso(MESSAGGIO_MOTIVAZIONE_RICHIESTA),
        )

    try:
        phases.richiedi(
            db,
            progetto=progetto,
            motivazione=motivazione,
            autore=utente,
            request=request,
        )
    except phases.PassaggioNonAmmesso as errore:
        return _pagina_fase_con_errore(
            request, db, progetto, utente, errore, motivazione
        )

    db.commit()
    return RedirectResponse(
        url=f"/progetti/{progetto.id}?fase_cambiata=richiesta", status_code=303
    )


@router.post("/{project_id}/richieste/{transition_id}")
def decidi(
    request: Request,
    project_id: uuid.UUID,
    transition_id: uuid.UUID,
    esito: Annotated[str, Form()] = "",
    motivazione: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Approva o respinge una richiesta di avanzamento.

    I due pulsanti mandano lo stesso modulo allo stesso indirizzo e cambiano
    un campo solo: la motivazione e' la stessa casella, e chiederla in due
    moduli diversi vorrebbe dire che chi respinge se la ritrova vuota dopo
    averla gia' scritta.

    **La motivazione e' obbligatoria in tutti e due i casi.** Approvare senza
    dire perche' sembra innocuo, ma il progetto e' appena avanzato di una fase
    e fra un anno "chi l'ha deciso e perche'" e' esattamente la domanda che si
    fara' qualcuno.
    """
    progetto = _progetto_visibile_o_errore(db, project_id, utente)
    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, progetto)

    passaggio = phases.trova_passaggio(db, transition_id)
    if passaggio is None or passaggio.project_id != progetto.id:
        raise HTTPException(
            status_code=404, detail="La richiesta di passaggio non esiste."
        )

    if not motivazione.strip():
        return _pagina_fase_con_errore(
            request,
            db,
            progetto,
            utente,
            phases.PassaggioNonAmmesso(MESSAGGIO_MOTIVAZIONE_DECISIONE),
        )

    try:
        phases.decidi(
            db,
            passaggio=passaggio,
            accolta=(esito == "approva"),
            motivazione=motivazione,
            autore=utente,
            request=request,
        )
    except phases.PassaggioNonAmmesso as errore:
        return _pagina_fase_con_errore(
            request, db, progetto, utente, errore, motivazione
        )

    db.commit()

    esito_leggibile = "approvata" if esito == "approva" else "respinta"
    return RedirectResponse(
        url=f"/progetti/{progetto.id}?fase_cambiata={esito_leggibile}",
        status_code=303,
    )


@router.post("/{project_id}/esiti/{transition_id}")
def esito_letto(
    project_id: uuid.UUID,
    transition_id: uuid.UUID,
    ritorno: Annotated[str, Form()] = "/",
    db: Session = Depends(get_db),
    utente: User = Depends(richiedi_login),
) -> Response:
    """Segna che chi aveva chiesto il passaggio ha letto com'e' andata.

    Il passaggio si cerca **dentro gli esiti di questa persona**, non con un
    identificatore preso dal modulo e poi confrontato: cosi' non c'e' nessun
    momento in cui il programma tiene in mano la notifica di qualcun altro.
    Un identificatore che non e' fra i suoi non esiste, e la risposta e' 404.
    """
    passaggio = phases.trova_esito_da_leggere(db, utente, transition_id)
    if passaggio is None or passaggio.project_id != project_id:
        raise HTTPException(
            status_code=404, detail="La richiesta di passaggio non esiste."
        )

    phases.segna_letto(db, passaggio)
    db.commit()

    # Si torna da dove si e' arrivati: la notifica compare sul cruscotto e
    # sulla scheda del progetto, e chiuderla non deve spostare chi la chiude.
    return RedirectResponse(url=_ritorno_sicuro(ritorno), status_code=303)


def _fase_scelta(db: Session, progetto: Project, valore: str) -> Phase | None:
    """La fase scelta nel modulo, se e' davvero una fase del suo percorso.

    Il controllo sul modello non e' pignoleria: senza, una richiesta scritta a
    mano potrebbe riportare un progetto in una fase di un modello diverso, e
    da li' in poi la sua barra di avanzamento non mostrerebbe piu' la fase in
    cui si trova.
    """
    try:
        fase = db.get(Phase, uuid.UUID(valore))
    except (ValueError, AttributeError):
        return None

    if fase is None or fase.phase_template_id != progetto.phase_template_id:
        return None
    return fase


def _ritorno_sicuro(percorso: str) -> str:
    """Un indirizzo interno a cui e' lecito rimandare dopo un POST.

    Si accettano solo i percorsi che cominciano con una barra sola: senza
    questo controllo, un modulo costruito a mano potrebbe far rimandare Aurora
    a un indirizzo esterno, e un rimando che parte dal programma dell'azienda
    e' esattamente quello che serve a rendere credibile una pagina finta.
    """
    if percorso.startswith("/") and not percorso.startswith("//"):
        return percorso
    return "/"
