"""Le pagine che amministrano i modelli di fasi. Riservate al creatore.

    GET  /fasi                    l'elenco dei modelli, con quanti progetti
    GET  /fasi/nuovo              il modulo di creazione
    POST /fasi/nuovo              crea il modello, alla versione 1
    GET  /fasi/{id}               la scheda di un modello
    GET  /fasi/{id}/versione      il modulo della versione successiva
    POST /fasi/{id}/versione      scrive la versione successiva
    POST /fasi/{id}/proponibilita mette o toglie dai proponibili

**Non c'e' nessuna pagina che modifica un modello, e non e' una dimenticanza.**
I modelli di fasi sono immutabili (D-016): correggerne uno vuol dire scriverne
la versione successiva, che nasce accanto a quella vecchia e la sostituisce
solo per i progetti futuri. Un progetto aperto due anni fa e' passato per le
fasi di allora, e la sua storia deve continuare a raccontare quelle.

Per questo la pagina dell'elenco mostra, per ciascuna versione, **quanti
progetti la usano**: davanti a "Standard v1" e "Standard v2" la domanda che ci
si fa e' quale delle due si sta guardando, e il numero di lavori appesi e' la
risposta piu' breve.

Il lucchetto e' la dipendenza richiedi_creatore dichiarata sul router, che
chiede a permissions.puo() come ogni altra parte del programma (D-051).
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import PhaseTemplate, User
from app.services import phases
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.fasi")

# La dipendenza sta sul router e non sulle singole rotte: cosi' una rotta
# aggiunta domani da qualcun altro nasce gia' protetta.
router = APIRouter(
    prefix="/fasi",
    tags=["fasi"],
    dependencies=[Depends(richiedi_creatore)],
)

MESSAGGIO_MODELLO_INESISTENTE = "Il modello di fasi richiesto non esiste."

# Quante righe di fase mostra il modulo. Dieci perche' il percorso standard
# dell'azienda ne ha sei e le righe vuote non danno fastidio: un modulo con
# tre righe costringerebbe a ricaricare la pagina per aggiungerne una quarta,
# e aggiungere righe con JavaScript vorrebbe dire un modulo che senza
# JavaScript non si compila (regola D-036).
RIGHE_FASE = 10


def _modello_o_404(db: Session, phase_template_id: uuid.UUID) -> PhaseTemplate:
    """Cerca il modello e, se non c'e', si ferma con un 404."""
    modello = phases.trova_modello(db, phase_template_id)
    if modello is None:
        raise HTTPException(status_code=404, detail=MESSAGGIO_MODELLO_INESISTENTE)
    return modello


def _righe_dal_modulo(modulo) -> list[phases.FaseScritta]:
    """Legge le righe delle fasi da un modulo, saltando quelle vuote.

    Nomi e descrizioni arrivano come due elenchi paralleli - i campi di testo
    vengono inviati sempre, anche vuoti - mentre le due spunte hanno il numero
    della riga scritto nel nome. E' la solita faccenda delle caselle di
    spunta: il browser le invia **solo quando sono segnate**, quindi da un
    modulo di dieci righe con due spunte arriverebbero due campi e non venti,
    e senza il numero nel nome non ci sarebbe modo di sapere a quale riga
    appartengono (la stessa trappola risolta nella griglia dei permessi).

    Il numero nel nome e' quello della **riga del modulo**, non della fase: le
    righe vuote si saltano, quindi la terza fase puo' venire dalla settima
    riga. L'ordine finale lo stabilisce l'ordine di lettura, e il numero
    d'ordine lo mette il servizio.
    """
    nomi = modulo.getlist("fase_nome")
    descrizioni = modulo.getlist("fase_descrizione")

    scritte: list[phases.FaseScritta] = []
    for riga, nome in enumerate(nomi):
        if not str(nome).strip():
            continue
        scritte.append(
            phases.FaseScritta(
                nome=str(nome),
                descrizione=(
                    str(descrizioni[riga]) if riga < len(descrizioni) else ""
                ),
                blocca_ritorno=modulo.get(f"fase_blocca_{riga}") == "si",
                chiude_progetto=modulo.get(f"fase_chiude_{riga}") == "si",
            )
        )

    return scritte


def _norme_scritte(testo: str) -> list[str]:
    """Le norme applicabili, una per riga, ripulite."""
    return [riga.strip() for riga in testo.splitlines() if riga.strip()]


def _errore_nelle_fasi(scritte: list[phases.FaseScritta]) -> str | None:
    """Controlla l'elenco delle fasi e restituisce il primo problema trovato.

    Sono tre controlli e ciascuno evita un modello che poi non funzionerebbe:

      - **almeno una fase**, perche' un percorso vuoto non si attraversa;
      - **nomi diversi fra loro**, che e' anche un vincolo del database
        (unicita' su (phase_template_id, name)): senza questo controllo
        l'errore arriverebbe da PostgreSQL, tecnico e in inglese;
      - **una e una sola fase che chiude il progetto, ed e' l'ultima.** Senza,
        un progetto aperto su questo modello non si chiuderebbe mai e nessuno
        capirebbe perche'; con due, la prima chiuderebbe il progetto e la
        seconda non avrebbe piu' niente da chiudere; con una fase dopo di
        quella che chiude, quella fase non si raggiungerebbe mai - il progetto
        si e' gia' chiuso, e un progetto chiuso non avanza piu'.
    """
    if not scritte:
        return "Scrivi almeno una fase: un percorso vuoto non si attraversa."

    nomi = [fase.nome.strip().lower() for fase in scritte]
    if len(set(nomi)) != len(nomi):
        return (
            "Due fasi dello stesso modello non possono chiamarsi allo stesso "
            "modo: nello storico di un progetto non si distinguerebbero."
        )

    chiudono = [fase for fase in scritte if fase.chiude_progetto]
    if not chiudono:
        return (
            "Segna quale fase chiude il progetto. Senza, un progetto aperto "
            "su questo modello non si chiuderebbe mai."
        )
    if len(chiudono) > 1:
        return (
            "Una sola fase puo' chiudere il progetto: adesso ne sono segnate "
            f"{len(chiudono)}."
        )

    if chiudono[0] is not scritte[-1]:
        return (
            f"«{chiudono[0].nome}» chiude il progetto, ma non e' l'ultima "
            "fase del percorso: quelle che vengono dopo non si "
            "raggiungerebbero mai, perche' un progetto chiuso non avanza piu'."
        )

    return None


def _contesto_modulo(
    *,
    nome_modello: str,
    descrizione: str,
    norme: str,
    scritte: list[phases.FaseScritta],
) -> dict:
    """Quello che il modulo deve ricevere per rimostrarsi com'era.

    Le righe arrivano gia' lunghe RIGHE_FASE, riempite di righe vuote: il
    template le disegna in fila senza doverne contare nessuna.
    """
    righe = list(scritte)
    while len(righe) < RIGHE_FASE:
        righe.append(phases.FaseScritta(nome=""))

    return {
        "nome_modello": nome_modello,
        "descrizione": descrizione,
        "norme": norme,
        "righe": righe,
    }


# ---------------------------------------------------------------------------
#  L'elenco
# ---------------------------------------------------------------------------


@router.get("")
def elenco(
    request: Request,
    creata: str = "",
    db: Session = Depends(get_db),
) -> Response:
    """Tutti i modelli di fasi, con quante fasi e quanti progetti ciascuno.

    Ci sono anche quelli disattivati: sono le versioni superate, e sono
    proprio quelle che si viene a cercare qui quando si vuole sapere che
    percorso stia seguendo un progetto vecchio.
    """
    modelli = phases.modelli_di_fasi(db, comprese_disattivate=True)

    return pagina(
        request,
        "fasi/elenco.html",
        modelli=modelli,
        usi=phases.progetti_per_modello(db),
        creata=bool(creata),
    )


# ---------------------------------------------------------------------------
#  La creazione
# ---------------------------------------------------------------------------


@router.get("/nuovo")
def mostra_nuovo(request: Request) -> Response:
    """Il modulo di creazione di un modello, con le sue righe vuote."""
    return pagina(
        request,
        "fasi/nuovo.html",
        **_contesto_modulo(
            nome_modello="", descrizione="", norme="", scritte=[]
        ),
    )


@router.post("/nuovo")
async def crea(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Crea il modello alla versione 1, con le sue fasi in ordine."""
    modulo = await request.form()

    nome = str(modulo.get("nome_modello") or "")
    descrizione = str(modulo.get("descrizione") or "")
    norme = str(modulo.get("norme") or "")
    scritte = _righe_dal_modulo(modulo)

    def rimostra(messaggio: str) -> Response:
        return pagina(
            request,
            "fasi/nuovo.html",
            stato=400,
            errore=messaggio,
            **_contesto_modulo(
                nome_modello=nome,
                descrizione=descrizione,
                norme=norme,
                scritte=scritte,
            ),
        )

    if not nome.strip():
        return rimostra("Il nome del modello e' obbligatorio.")

    if phases.nome_gia_usato(db, nome):
        return rimostra(
            "Esiste gia' un modello con questo nome. Se vuoi cambiarlo, "
            "aprilo e creane la versione successiva: i modelli non si "
            "modificano."
        )

    problema = _errore_nelle_fasi(scritte)
    if problema is not None:
        return rimostra(problema)

    modello = phases.crea_modello(
        db,
        nome=nome,
        descrizione=descrizione,
        norme=_norme_scritte(norme),
        fasi=scritte,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/fasi/{modello.id}?creata=1", status_code=303)


# ---------------------------------------------------------------------------
#  La scheda e la versione successiva
# ---------------------------------------------------------------------------


@router.get("/{phase_template_id}")
def scheda(
    request: Request,
    phase_template_id: uuid.UUID,
    creata: int = 0,
    db: Session = Depends(get_db),
) -> Response:
    """La scheda di un modello: le sue fasi, le sue norme, i suoi progetti."""
    modello = _modello_o_404(db, phase_template_id)
    usi = phases.progetti_per_modello(db)
    fasi = phases.fasi_del_modello(db, modello.id)

    return pagina(
        request,
        "fasi/scheda.html",
        modello=modello,
        fasi=fasi,
        # La barra come la vedra' chi aprira' un progetto su questo modello.
        # Si compone qui e non nel template: un template che trasforma delle
        # righe in un elenco di dizionari contiene una regola
        # (docs/GUIDA_STILE.md, sezione 5).
        anteprima=phases.anteprima_percorso(fasi),
        progetti_che_lo_usano=usi.get(modello.id, 0),
        creata=bool(creata),
    )


@router.get("/{phase_template_id}/versione")
def mostra_versione(
    request: Request,
    phase_template_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Il modulo della versione successiva, precompilato con quella di adesso.

    Precompilato e non vuoto perche' quasi sempre si cambia una cosa sola: una
    fase in piu', un nome corretto, una norma aggiunta. Ricopiare a mano le
    altre cinque fasi sarebbe il modo piu' sicuro di introdurre una differenza
    che nessuno voleva.
    """
    modello = _modello_o_404(db, phase_template_id)
    fasi = phases.fasi_del_modello(db, modello.id)

    return pagina(
        request,
        "fasi/nuovo.html",
        partenza=modello,
        prossima_versione=modello.version + 1,
        **_contesto_modulo(
            nome_modello=modello.name,
            descrizione=modello.description or "",
            norme="\n".join(modello.standards or []),
            scritte=[
                phases.FaseScritta(
                    nome=fase.name,
                    descrizione=fase.description or "",
                    blocca_ritorno=fase.blocks_return,
                    chiude_progetto=fase.closes_project,
                )
                for fase in fasi
            ],
        ),
    )


@router.post("/{phase_template_id}/versione")
async def crea_versione(
    request: Request,
    phase_template_id: uuid.UUID,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Scrive la versione successiva e disattiva quella da cui e' partita.

    Il nome non si tocca: e' quello che tiene insieme le versioni di uno
    stesso percorso. Cambiarlo vorrebbe dire creare un modello diverso, e per
    quello c'e' l'altra pagina.
    """
    modello = _modello_o_404(db, phase_template_id)
    modulo = await request.form()

    descrizione = str(modulo.get("descrizione") or "")
    norme = str(modulo.get("norme") or "")
    scritte = _righe_dal_modulo(modulo)

    problema = _errore_nelle_fasi(scritte)
    if problema is not None:
        return pagina(
            request,
            "fasi/nuovo.html",
            stato=400,
            errore=problema,
            partenza=modello,
            prossima_versione=modello.version + 1,
            **_contesto_modulo(
                nome_modello=modello.name,
                descrizione=descrizione,
                norme=norme,
                scritte=scritte,
            ),
        )

    nuovo = phases.nuova_versione(
        db,
        partenza=modello,
        descrizione=descrizione,
        norme=_norme_scritte(norme),
        fasi=scritte,
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/fasi/{nuovo.id}?creata=1", status_code=303)


@router.post("/{phase_template_id}/proponibilita")
def proponibilita(
    request: Request,
    phase_template_id: uuid.UUID,
    proponibile: Annotated[str, Form()] = "",
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Mette o toglie un modello dall'elenco di quelli proponibili.

    Non tocca nessun progetto: chi lo sta gia' usando continua, esattamente
    come prima. E' l'unico verbo che si puo' usare su un modello gia' scritto.
    """
    modello = _modello_o_404(db, phase_template_id)

    phases.cambia_proponibilita(
        db,
        modello=modello,
        proponibile=(proponibile == "si"),
        autore=creatore,
        request=request,
    )
    db.commit()

    return RedirectResponse(url=f"/fasi/{modello.id}", status_code=303)
