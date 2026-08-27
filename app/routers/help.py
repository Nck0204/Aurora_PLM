"""La guida in linea.

    GET /aiuto           l'indice, con la casella di ricerca
    GET /aiuto/{nome}    una pagina della guida

**Basta essere entrati.** La guida non e' riservata a nessuno: spiega come si
usa il programma, e chi usa il programma deve poterla leggere. E' l'unica
sezione di servizio che compare a tutti nella barra laterale.

**La ricerca e' un modulo GET, come tutte le ricerche di Aurora.** Quello che
si e' cercato finisce nell'indirizzo, quindi il risultato di una ricerca si
mette nei preferiti e si manda a un collega. Con HTMX si aggiorna solo
l'elenco dei risultati; senza, si ricarica la pagina - che e' quello che ha
sempre fatto un modulo (D-036).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.models import User
from app.dependencies import richiedi_login
from app.services import guida
from app.templating import pagina, templates

logger = logging.getLogger("aurora.rotte.aiuto")

router = APIRouter(prefix="/aiuto", tags=["aiuto"])


@router.get("")
def indice(
    request: Request,
    q: str = "",
    utente: User = Depends(richiedi_login),
) -> Response:
    """L'indice della guida, oppure i risultati di una ricerca.

    Sono la stessa pagina e non due, perche' sono la stessa domanda vista due
    volte: "che cosa c'e' scritto qui dentro?". Separarle vorrebbe dire che chi
    cerca e non trova niente si ritrova su una pagina vuota, senza l'indice da
    cui ripartire.
    """
    domanda = (q or "").strip()
    risultati = guida.cerca(domanda) if domanda else []

    # La risposta a HTMX e' il solo pezzo dei risultati. E' l'unica altra
    # pagina di Aurora che lo fa oltre alla vetrina e alla configurazione
    # posta, e per la stessa ragione: la ricerca funziona anche senza.
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="aiuto/risultati.html",
            context={"risultati": risultati, "q": domanda},
        )

    return pagina(
        request,
        "aiuto/indice.html",
        pagine=guida.pagine(),
        risultati=risultati,
        q=domanda,
    )


@router.get("/{nome}")
def mostra(
    request: Request,
    nome: str,
    utente: User = Depends(richiedi_login),
) -> Response:
    """Una pagina della guida.

    Una pagina che non esiste risponde 404 come qualunque altro indirizzo
    sbagliato. Il messaggio pero' e' scritto apposta: chi ci arriva quasi
    sempre ci arriva da un'icona «?» il cui collegamento e' rimasto indietro,
    e la cosa utile da dirgli e' dove sta l'indice.
    """
    trovata = guida.pagina(nome)

    if trovata is None:
        logger.warning("Richiesta una pagina di guida che non esiste: «%s»", nome)
        raise HTTPException(
            status_code=404,
            detail=(
                "Questa pagina della guida non esiste. L'indice di tutto "
                "quello che c'e' e' all'indirizzo /aiuto."
            ),
        )

    return pagina(
        request,
        "aiuto/pagina.html",
        pagina_guida=trovata,
        # L'elenco delle altre pagine serve alla colonna di navigazione
        # laterale: da una pagina della guida si passa alla successiva senza
        # tornare all'indice.
        pagine=guida.pagine(),
    )
