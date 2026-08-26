"""Le pagine del registro delle operazioni. Riservate al ruolo creatore.

    GET /registro           l'elenco filtrato, con impaginazione
    GET /registro/esporta   gli stessi risultati come file CSV

**Perche' riservato al creatore.** Il registro dice chi ha fatto che cosa, e
messo insieme dice anche a che ora entra ed esce ciascuno. E' uno strumento di
verifica, non un tabellone: chi amministra Aurora risponde di come lo usa. Chi
ha bisogno della storia di un oggetto preciso - un documento, un progetto -
non deve passare di qui: ha la scheda "Storico" dentro la pagina di
quell'oggetto, che gli mostra le voci che lo riguardano se e solo se
l'oggetto lo puo' vedere.

**L'esportazione lascia traccia.** Il file CSV che esce da qui e' una copia
del registro che se ne va da Aurora, e chi l'ha fatta e quando e' esattamente
il genere di domanda a cui un audit trail deve saper rispondere. La voce viene
scritta e confermata **prima** che il file cominci a partire: se venisse
scritta dopo, un collegamento interrotto a meta' scarico lascerebbe uscire
mezzo registro senza che ne resti traccia.
"""

import csv
import io
import logging
import math
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import richiedi_creatore
from app.models import User
from app.services import audit, registro
from app.templating import pagina

logger = logging.getLogger("aurora.rotte.registro")

# La dipendenza sta sul router e non sulle singole rotte: cosi' una rotta
# aggiunta domani da qualcun altro nasce gia' protetta.
router = APIRouter(
    prefix="/registro",
    tags=["registro"],
    dependencies=[Depends(richiedi_creatore)],
)

# Quante voci al massimo entrano in un'esportazione. Il file si prepara in
# memoria prima di partire, quindi il tetto non e' un capriccio: senza,
# un'esportazione senza filtri su un registro di cinque anni metterebbe in
# ginocchio il server aziendale. Chi ha bisogno di tutto usa
# scripts/archivia_audit.py, che scrive su disco a blocchi.
MASSIMO_ESPORTAZIONE = 20_000

# Il separatore del file CSV. Il punto e virgola e non la virgola perche' il
# file lo apre Excel in italiano, che con la virgola mette tutta la riga in
# una cella sola. Vedi D-066.
SEPARATORE_CSV = ";"


def _data(valore: str | None) -> date | None:
    """Legge una data scritta nell'indirizzo, senza fidarsene.

    Il formato e' quello che manda <input type="date">, cioe' aaaa-mm-gg. Un
    indirizzo si puo' scrivere a mano o restare in un preferito dopo che la
    pagina e' cambiata: "?dal=ieri" non deve produrre un errore tecnico ma
    comportarsi come se il parametro non ci fosse.
    """
    if not valore:
        return None
    try:
        return datetime.strptime(valore.strip(), "%Y-%m-%d").date()
    except ValueError:
        logger.info("data non valida nei filtri del registro: %r", valore)
        return None


def _intero(valore: str | None, predefinito: int) -> int:
    """Legge un numero da un parametro dell'indirizzo, senza fidarsene."""
    try:
        return int(valore) if valore is not None else predefinito
    except ValueError:
        return predefinito


def _filtro_dalla_richiesta(request: Request) -> registro.Filtro:
    """Compone il filtro leggendo i parametri dell'indirizzo.

    I parametri si leggono qui e non nella firma della rotta perche' sono
    sette e servono a tutte e due le rotte di questo file, quella che disegna
    l'elenco e quella che lo esporta: le due devono guardare esattamente gli
    stessi, altrimenti si esporterebbe qualcosa di diverso da quello che si
    sta guardando.
    """
    parametri = request.query_params
    return registro.Filtro(
        dal_giorno=_data(parametri.get("dal")),
        al_giorno=_data(parametri.get("al")),
        utente=(parametri.get("utente") or "").strip(),
        azione=(parametri.get("azione") or "").strip(),
        gruppo=(parametri.get("gruppo") or "").strip(),
        entita=(parametri.get("entita") or "").strip(),
        testo=(parametri.get("q") or "").strip(),
    )


def _tendine(db: Session, filtro: registro.Filtro) -> list[dict]:
    """I quattro menu a tendina della barra di ricerca, gia' composti.

    Si compongono qui e non nel template: comporre un elenco di scelte e'
    lavoro del codice (docs/GUIDA_STILE.md, sezione 5).
    """
    return [
        {
            "nome": "utente",
            "etichetta": "Utente",
            "opzioni": registro.opzioni_utenti(db),
            "scelto": filtro.utente,
            "vuoto": "Chiunque",
        },
        {
            "nome": "gruppo",
            "etichetta": "Gruppo di azioni",
            "opzioni": audit.opzioni_gruppi(),
            "scelto": filtro.gruppo,
            "vuoto": "Qualunque gruppo",
        },
        {
            "nome": "azione",
            "etichetta": "Tipo di azione",
            "opzioni": audit.opzioni_azioni(),
            "scelto": filtro.azione,
            "vuoto": "Qualunque azione",
        },
        {
            "nome": "entita",
            "etichetta": "Tipo di oggetto",
            "opzioni": registro.opzioni_entita(),
            "scelto": filtro.entita,
            "vuoto": "Qualunque oggetto",
        },
    ]


@router.get("")
def elenco(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """L'elenco del registro, filtrato e impaginato.

    Il numero di pagina si legge dai parametri della richiesta e non dalla
    firma: nell'indirizzo si chiama "pagina", che in questo file e' gia' il
    nome della funzione che compone le risposte HTML.
    """
    filtro = _filtro_dalla_richiesta(request)
    numero = max(1, _intero(request.query_params.get("pagina"), 1))

    voci, totale = registro.cerca(
        db, filtro, pagina=numero, per_pagina=settings.PAGE_SIZE
    )

    return pagina(
        request,
        "registro/elenco.html",
        voci=[_voce_per_la_pagina(voce) for voce in voci],
        totale=totale,
        pagina_corrente=numero,
        totale_pagine=math.ceil(totale / settings.PAGE_SIZE) if totale else 0,
        parametri=filtro.parametri(),
        filtro=filtro,
        q=filtro.testo,
        tendine=_tendine(db, filtro),
        date_scelte=[
            {
                "nome": "dal",
                "etichetta": "Dal giorno",
                "valore": filtro.dal_giorno.isoformat() if filtro.dal_giorno else "",
            },
            {
                "nome": "al",
                "etichetta": "Al giorno",
                "valore": filtro.al_giorno.isoformat() if filtro.al_giorno else "",
            },
        ],
        massimo_esportazione=MASSIMO_ESPORTAZIONE,
    )


def _voce_per_la_pagina(voce) -> dict:
    """Una riga del registro con tutto quello che serve a disegnarla.

    Il template riceve i valori gia' tradotti - l'etichetta italiana
    dell'azione, il nome del tipo di oggetto, l'indirizzo della sua scheda -
    perche' un template che trasforma un valore in un'etichetta contiene una
    regola, e le regole non si provano con un test se stanno dentro l'HTML
    (docs/GUIDA_STILE.md, sezione 5).
    """
    return {
        "seq": voce.seq,
        "quando": voce.occurred_at.astimezone(),
        "autore": registro.nome_autore(voce),
        "azione": audit.etichetta_azione(voce.action),
        "codice_azione": voce.action,
        "entita": registro.etichetta_entita(voce.entity_type),
        "entity_id": voce.entity_id,
        "indirizzo": registro.indirizzo_entita(voce.entity_type, voce.entity_id),
        "descrizione": voce.description,
        "prima": voce.old_value or {},
        "dopo": voce.new_value or {},
        "ip": voce.ip,
        "impronta": voce.entry_hash,
    }


@router.get("/esporta")
def esporta(
    request: Request,
    creatore: User = Depends(richiedi_creatore),
    db: Session = Depends(get_db),
) -> Response:
    """Le voci filtrate come file CSV, e l'esportazione stessa nel registro.

    **Il file si prepara tutto prima di cominciare a mandarlo.** Il tetto di
    MASSIMO_ESPORTAZIONE righe lo rende possibile, e in cambio si ottiene una
    cosa che vale: se qualcosa va storto - un filtro che non torna, il
    database che non risponde - l'errore arriva come una pagina di errore
    normale, e non come un file mezzo scritto che l'utente si ritrova nella
    cartella degli scarichi senza sapere che e' incompleto.
    """
    filtro = _filtro_dalla_richiesta(request)
    voci = registro.tutte(db, filtro, massimo=MASSIMO_ESPORTAZIONE)

    # Il BOM in cima. Senza, Excel in italiano legge un file UTF-8 come se
    # fosse a codifica di sistema e le lettere accentate diventano geroglifici.
    # Si scrive a mano perche' newline="" e la codifica utf-8-sig insieme
    # farebbero due strade diverse per la stessa cosa (D-066).
    testo = io.StringIO(newline="")
    testo.write("﻿")
    scrittore = csv.writer(testo, delimiter=SEPARATORE_CSV, lineterminator="\r\n")
    for riga in registro.righe_csv(voci):
        scrittore.writerow(riga)

    contenuto = testo.getvalue().encode("utf-8")
    nome_file = f"registro-aurora-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"

    # La traccia dell'esportazione, scritta e confermata **prima** di mandare
    # il file: un collegamento interrotto a meta' scarico non deve poter far
    # uscire mezzo registro senza lasciare traccia.
    audit.record(
        db,
        action=audit.ACTION_AUDIT_EXPORTED,
        entity_type=audit.ENTITY_SISTEMA,
        user_id=creatore.id,
        request=request,
        new_value={
            "righe": len(voci),
            "filtri": filtro.parametri() or "nessuno",
            "file": nome_file,
            "troncato": len(voci) >= MASSIMO_ESPORTAZIONE,
        },
        description=(
            f"Registro esportato in CSV: {len(voci)} "
            f"voc{'e' if len(voci) == 1 else 'i'}, filtri "
            f"{filtro.parametri() or 'nessuno'}"
        ),
    )
    db.commit()

    logger.info(
        "'%s' ha esportato %s voci del registro nel file %s",
        creatore.username,
        len(voci),
        nome_file,
    )

    return StreamingResponse(
        io.BytesIO(contenuto),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome_file}"'},
    )
