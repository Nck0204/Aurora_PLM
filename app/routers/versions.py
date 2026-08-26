"""Le pagine delle versioni di prodotto.

    GET  /versioni/{id}                 scheda della versione
    POST /versioni/{id}                 corregge il motivo della derivazione
    GET  /versioni/{id}/deriva          modulo per derivarne una nuova
    POST /versioni/{id}/deriva          crea la versione derivata
    GET  /versioni/{id}/stato           **conferma** del cambio di stato
    POST /versioni/{id}/stato           esegue il cambio di stato

LA CONFERMA E' UNA PAGINA, NON UNA FINESTRA. Rilasciare una versione fa
passare da sola la precedente a "superato": e' un'operazione che ne provoca
un'altra, e chi la esegue deve poter leggere che cosa succedera' **prima** di
premere. Una finestra modale ha bisogno di JavaScript per aprirsi, e se non si
aprisse l'operazione partirebbe senza che nessuno abbia letto niente. La
regola sta in docs/GUIDA_STILE.md: se la finestra non si aprisse, l'utente
resterebbe bloccato? Allora non e' una finestra, e' una pagina.

Il testo della conferma lo costruisce lifecycle.versione_da_superare(), che e'
la stessa funzione che poi il rilascio usa davvero: la conferma non puo'
raccontare una cosa diversa da quella che succedera'.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_login
from app.models import LifecycleState, ProductVersion, User
from app.services import lifecycle, permissions, product_codes, products, projects
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.versioni")

router = APIRouter(prefix="/versioni", tags=["versioni"])

MESSAGGIO_VERSIONE_INESISTENTE = "La versione richiesta non esiste."

# Chi puo' creare una versione derivata e' chi puo' muoverne il ciclo di vita:
# il project manager del progetto e il creatore. E' la stessa regola, e passa
# per la stessa domanda - permissions.puo(..., MODIFICARE, versione) - perche'
# le due operazioni sono la stessa decisione presa in due momenti ("questo
# lavoro va avanti cosi'") e due regole separate finirebbero per allontanarsi.
#
# Il messaggio del diniego sta in permissions.py insieme alla regola: qui non
# c'e' niente da decidere.


def _versione_o_404(db: Session, version_id: uuid.UUID) -> ProductVersion:
    """Cerca la versione e, se non c'e', si ferma con un 404 in italiano."""
    versione = lifecycle.trova_versione(db, version_id)
    if versione is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_VERSIONE_INESISTENTE)
    return versione


def _stato_o_400(valore: str) -> LifecycleState:
    """Converte il testo arrivato dal modulo in uno stato del ciclo di vita.

    Uno stato inventato puo' arrivare solo da una richiesta costruita a mano:
    le pagine propongono un elenco chiuso, costruito sul grafo. Si risponde
    comunque in italiano e senza dettagli tecnici.
    """
    try:
        return LifecycleState(valore)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Lo stato richiesto non esiste fra quelli del ciclo di vita.",
        ) from None


def _versioni_scelta(db: Session, product_id) -> list[tuple[str, str]]:
    """Le versioni del prodotto come coppie (identificatore, testo).

    Il testo dice numero e stato ("versione 2 - rilasciato"): scegliendo da
    dove derivare, sapere in che stato si trova ciascuna e' meta' della
    decisione.
    """
    return [
        (
            str(v.id),
            f"versione {v.version_number} - {lifecycle.nome_stato(v.lifecycle_state)}",
        )
        for v in products.versioni_di(db, product_id)
    ]


def _contesto_scheda(db: Session, versione: ProductVersion, utente: User) -> dict:
    """Le cose che servono a disegnare la scheda di una versione.

    Sta in una funzione perche' la scheda si mostra da tre punti diversi -
    dopo un'apertura normale, dopo un modulo rifiutato e dopo un cambio di
    stato riuscito - e un contesto ricomposto a mano in tre punti prima o poi
    si dimentica un pezzo in due di essi.
    """
    prodotto = versione.product
    piu_recente = products.versione_piu_recente(db, prodotto.id)

    return {
        "versione": versione,
        "prodotto": prodotto,
        "coppie": product_codes.scomposizione_leggibile(prodotto.code_parts),
        "progetto": versione.project,
        "squadra": (
            projects.assegnazioni_attive(db, versione.project.id)
            if versione.project is not None
            else []
        ),
        # L'avviso in cima: c'e' solo quando questa **non** e' la piu' recente.
        "versione_corrente": (
            piu_recente
            if piu_recente is not None and piu_recente.id != versione.id
            else None
        ),
        "stati_possibili": lifecycle.stati_raggiungibili(versione.lifecycle_state),
        # Il template disegna i pulsanti del ciclo di vita solo se la
        # risposta e' si': la decisione arriva gia' presa (D-051).
        "puo_cambiare_stato": permissions.puo(
            db, utente, permissions.Azione.MODIFICARE, versione
        ),
        # Correggere il motivo della derivazione e' la stessa decisione del
        # cambio di stato, quindi la stessa risposta: si chiede una volta
        # sola e la si passa due volte, perche' le due cose potrebbero
        # separarsi domani e il template non deve saperlo.
        "puo_correggere": permissions.puo(
            db, utente, permissions.Azione.MODIFICARE, versione
        ),
        "nome_stato": lifecycle.nome_stato,
    }


# --- Scheda -----------------------------------------------------------------


@router.get("/{version_id}")
def scheda(
    request: Request,
    version_id: uuid.UUID,
    cambiato: str = "",
    superata: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di una versione.

    I due parametri dell'indirizzo servono a mostrare le notifiche dopo un
    cambio di stato: "cambiato" e' il nuovo stato, "superata" il numero della
    versione che il rilascio ha mandato in pensione. Sono testo mostrato, non
    dati riservati: nell'indirizzo ci possono stare.
    """
    versione = _versione_o_404(db, version_id)

    # Il parametro arriva come valore del database ("in_produzione"); nella
    # notifica si legge la forma con gli spazi. Un valore inventato da chi ha
    # scritto l'indirizzo a mano semplicemente non mostra nessuna notifica.
    try:
        cambiato_leggibile = lifecycle.nome_stato(LifecycleState(cambiato))
    except ValueError:
        cambiato_leggibile = ""

    return pagina(
        request,
        "versioni/scheda.html",
        **_contesto_scheda(db, versione, utente),
        cambiato=cambiato_leggibile,
        superata=superata,
    )


@router.post("/{version_id}")
def salva(
    request: Request,
    version_id: uuid.UUID,
    motivo: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Corregge il motivo della derivazione di una versione.

    **E' l'unico campo modificabile, e non e' una dimenticanza.** Numero,
    prodotto e versione di provenienza sono fatti avvenuti; lo stato del ciclo
    di vita ha la sua strada, che passa dal grafo delle transizioni e da una
    pagina di conferma. Il motivo della derivazione e' invece una nota scritta
    da una persona di fretta, e va corretta il giorno in cui ci si accorge che
    non si capisce. La spiegazione per esteso e' in products.modifica_versione().

    Chi puo' correggerla e' chi puo' muovere il ciclo di vita della versione:
    il project manager del suo progetto e il creatore. E' la stessa domanda,
    fatta alla stessa funzione.
    """
    versione = _versione_o_404(db, version_id)
    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, versione)

    cambiati = products.modifica_versione(
        db, versione, motivo=motivo, autore=utente, request=request
    )
    db.commit()

    # Si risponde con un rimando e non con la pagina: cosi' un aggiornamento
    # del browser non rispedisce il modulo.
    coda = "?salvato=si" if cambiati else "?invariato=si"
    return RedirectResponse(f"/versioni/{versione.id}{coda}", status_code=303)


# --- Derivazione ------------------------------------------------------------


@router.get("/{version_id}/deriva")
def mostra_deriva(
    request: Request,
    version_id: uuid.UUID,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Mostra il modulo per creare una versione derivata da questa.

    La versione di origine si sceglie fra tutte quelle del prodotto: si arriva
    qui da una in particolare, ma capita di accorgersi che si voleva partire
    da un'altra, e tornare indietro per rifare la stessa strada e' il genere
    di attrito che fa scrivere le cose su un foglio invece che nel programma.
    """
    versione = _versione_o_404(db, version_id)

    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, versione)

    return pagina(
        request,
        "versioni/deriva.html",
        origine=versione,
        prodotto=versione.product,
        versioni_scelta=_versioni_scelta(db, versione.product_id),
        prossimo_numero=products.prossimo_numero_versione(db, versione.product_id),
    )


@router.post("/{version_id}/deriva")
def deriva(
    request: Request,
    version_id: uuid.UUID,
    origine: Annotated[str, Form()] = "",
    motivazione: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Crea la versione derivata e porta sulla sua scheda."""
    versione = _versione_o_404(db, version_id)

    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, versione)

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "versioni/deriva.html",
            stato=400,
            errore=messaggio,
            origine=versione,
            prodotto=versione.product,
            versioni_scelta=_versioni_scelta(db, versione.product_id),
            prossimo_numero=products.prossimo_numero_versione(
                db, versione.product_id
            ),
            motivazione=motivazione,
        )

    if not motivazione.strip():
        return rimostra(
            "Scrivi perche' serve una versione nuova: fra due anni sara' "
            "l'unica risposta a questa domanda."
        )

    try:
        scelta = lifecycle.trova_versione(db, uuid.UUID(origine))
    except (ValueError, AttributeError):
        scelta = None

    if scelta is None:
        return rimostra("La versione di origine scelta non esiste.")

    if scelta.product_id != versione.product_id:
        # Puo' arrivare solo da una richiesta costruita a mano: il modulo
        # propone le sole versioni di questo prodotto.
        return rimostra("La versione di origine deve essere dello stesso prodotto.")

    nuova = products.deriva_versione(
        db,
        origine=scelta,
        motivazione=motivazione,
        autore=utente,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/versioni/{nuova.id}", status_code=303)


# --- Cambio di stato --------------------------------------------------------


@router.get("/{version_id}/stato")
def conferma_stato(
    request: Request,
    version_id: uuid.UUID,
    nuovo: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La pagina di conferma del cambio di stato.

    Dice tre cose, e la seconda e' quella che l'azienda ha chiesto per prima:

      1. da quale stato a quale stato si sta passando;
      2. **quale versione verra' superata**, se si sta rilasciando;
      3. che serve una motivazione, se si sta dichiarando obsoleto.

    Se la transizione non e' ammessa, la pagina non compare nemmeno: si torna
    alla scheda con il messaggio del grafo. Meglio dirlo prima che far
    premere un pulsante per poi rifiutarlo.
    """
    versione = _versione_o_404(db, version_id)

    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, versione)

    nuovo_stato = _stato_o_400(nuovo)

    try:
        lifecycle.verifica_transizione(versione.lifecycle_state, nuovo_stato)
    except lifecycle.TransizioneNonAmmessa as rifiuto:
        return pagina(
            request,
            "versioni/scheda.html",
            stato=400,
            errore=str(rifiuto),
            **_contesto_scheda(db, versione, utente),
        )

    da_superare = (
        lifecycle.versione_da_superare(db, versione)
        if nuovo_stato is LifecycleState.RILASCIATO
        else None
    )
    precedente = (
        lifecycle.versione_precedente(db, versione)
        if nuovo_stato is LifecycleState.RILASCIATO
        else None
    )

    return pagina(
        request,
        "versioni/conferma_stato.html",
        versione=versione,
        prodotto=versione.product,
        nuovo_stato=nuovo_stato,
        da_superare=da_superare,
        # La versione precedente che **non** verra' toccata, perche' il suo
        # stato non lo consente. Va detto: il silenzio verrebbe letto come
        # "non c'era nessuna versione prima".
        precedente_intoccata=(
            precedente if precedente is not None and da_superare is None else None
        ),
        serve_motivazione=(nuovo_stato is lifecycle.STATO_CON_MOTIVAZIONE),
        nome_stato=lifecycle.nome_stato,
    )


@router.post("/{version_id}/stato")
def cambia_stato(
    request: Request,
    version_id: uuid.UUID,
    nuovo: Annotated[str, Form()] = "",
    motivazione: Annotated[str, Form()] = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Esegue il cambio di stato, dopo la conferma.

    Il grafo viene consultato di nuovo qui dentro, dal servizio: la verifica
    fatta per disegnare la pagina di conferma non conta, perche' fra quella e
    questa richiesta puo' essere passato del tempo e qualcun altro puo' aver
    mosso la stessa versione. E' la ragione per cui il controllo sta nel
    servizio e non nella rotta.
    """
    versione = _versione_o_404(db, version_id)

    permissions.pretendi(db, utente, permissions.Azione.MODIFICARE, versione)

    nuovo_stato = _stato_o_400(nuovo)

    if nuovo_stato is lifecycle.STATO_CON_MOTIVAZIONE and not motivazione.strip():
        return pagina(
            request,
            "versioni/conferma_stato.html",
            stato=400,
            errore=(
                "Per dichiarare obsoleta una versione bisogna scrivere "
                "perche': resta nel registro delle operazioni."
            ),
            versione=versione,
            prodotto=versione.product,
            nuovo_stato=nuovo_stato,
            da_superare=None,
            precedente_intoccata=None,
            serve_motivazione=True,
            nome_stato=lifecycle.nome_stato,
        )

    try:
        superata = lifecycle.cambia_stato(
            db,
            versione,
            nuovo_stato,
            autore=utente,
            request=request,
            motivazione=motivazione,
        )
    except lifecycle.TransizioneNonAmmessa as rifiuto:
        # Niente e' stato scritto: il servizio verifica prima di toccare la
        # riga. Si torna alla scheda con la spiegazione del grafo, che e' gia'
        # una frase italiana comprensibile.
        db.rollback()
        return pagina(
            request,
            "versioni/scheda.html",
            stato=400,
            errore=str(rifiuto),
            **_contesto_scheda(db, versione, utente),
        )

    db.commit()

    indirizzo = f"/versioni/{versione.id}?cambiato={nuovo_stato.value}"
    if superata is not None:
        indirizzo += f"&superata={superata.version_number}"

    return RedirectResponse(url=indirizzo, status_code=303)
