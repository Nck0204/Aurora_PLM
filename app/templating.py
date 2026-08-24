"""Il motore dei template, in un posto solo.

Sta qui e non in app/main.py per una ragione pratica: i router lo usano, e
main.py importa i router. Se l'oggetto "templates" stesse in main.py, ogni
router dovrebbe importare main e main importerebbe i router: due moduli che si
importano a vicenda, che in Python funziona solo per caso e smette di
funzionare appena si sposta una riga.

Qui dentro ci sono anche le funzioni che i template possono richiamare
direttamente e la funzione pagina(), che compone una risposta HTML mettendoci
dentro le poche cose che servono a tutte le pagine.
"""

from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, settings
from app.services.csrf import token_csrf

templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")

# Funzioni richiamabili da dentro un template. Ce n'e' una sola: quella che
# restituisce il gettone da mettere nel campo nascosto di ogni modulo. Si
# richiama cosi', dentro ogni <form method="post">:
#
#     <input type="hidden" name="csrf" value="{{ token_csrf(request) }}">
templates.env.globals["token_csrf"] = token_csrf


def pagina(
    request: Request,
    nome: str,
    stato: int = 200,
    **contesto: Any,
) -> Response:
    """Compone una pagina HTML aggiungendo il contesto comune a tutte.

    Il contesto comune e' di due voci sole:

      app_name   il nome del programma, che compare nel titolo della finestra;
      utente     chi sta guardando la pagina, oppure None se non e' entrato.
                 Serve alla barra in cima, che mostra il nome e il collegamento
                 per uscire.

    L'utente viene preso da request.state, dove lo ha lasciato la dipendenza
    utente_corrente (vedi app/dependencies.py). Cosi' i template non devono
    riceverlo esplicitamente da ogni rotta, e non capita la pagina in cui la
    barra in cima dice "non sei entrato" perche' qualcuno ha dimenticato di
    passarlo.
    """
    contesto.setdefault("app_name", settings.APP_NAME)
    contesto.setdefault("utente", getattr(request.state, "utente", None))

    return templates.TemplateResponse(
        request=request,
        name=nome,
        context=contesto,
        status_code=stato,
    )
