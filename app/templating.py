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
from app.navigation import (
    MENU_PRINCIPALE,
    MENU_SERVIZIO,
    sezione_corrente,
    voci_visibili,
)
from app.services.csrf import token_csrf
from app.services.users import ruolo_mostrato

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

    Il contesto comune e' di sette voci:

      app_name          il nome del programma, che compare nel titolo della
                        finestra e nella barra laterale;
      utente            chi sta guardando la pagina, oppure None se non e'
                        entrato. Serve alla barra in cima, che mostra il nome
                        e il collegamento per uscire;
      voci_menu, voci_menu_servizio
                        le voci della barra laterale gia' filtrate per ruolo
                        (vedi app/navigation.py). Il template le disegna e
                        basta: non decide chi puo' vedere che cosa;
      sezione           il percorso della voce di menu da segnare come
                        corrente;
      puo_amministrare  se chi guarda puo' aprire le sezioni riservate. E'
                        gia' la risposta di permissions.puo(), calcolata da
                        app/dependencies.py: i template la usano per sapere
                        se disegnare un pulsante, **non** per decidere se
                        qualcuno ha diritto a qualcosa. Quella decisione e'
                        gia' stata presa (D-051);
      ruolo_utente      il nome del ruolo globale di chi guarda, per la barra
                        in cima. E' testo da mostrare, non un permesso.

    **Due nomi sono occupati e non si possono usare nel contesto.** Questa
    funzione ha due parametri suoi, "nome" (il file del template) e "stato"
    (il codice HTTP della risposta): passandoli come variabili di contesto -
    per esempio per far tornare al modulo il nome scritto da chi lo stava
    compilando - Python li assegnerebbe ai parametri e l'errore che ne esce
    ("pagina() got multiple values for argument 'nome'") non dice niente a chi
    lo legge. Si passa "nome_cliente", "nome_prodotto", "stato_scelto". E' la
    stessa trappola dei nomi dei macro di Jinja spiegata in
    docs/GUIDA_STILE.md, sezione 4.

    L'utente viene preso da request.state, dove lo ha lasciato la dipendenza
    utente_corrente (vedi app/dependencies.py). Cosi' i template non devono
    riceverlo esplicitamente da ogni rotta, e non capita la pagina in cui la
    barra in cima dice "non sei entrato" perche' qualcuno ha dimenticato di
    passarlo.
    """
    utente = getattr(request.state, "utente", None)
    puo_amministrare = bool(getattr(request.state, "puo_amministrare", False))

    contesto.setdefault("app_name", settings.APP_NAME)
    contesto.setdefault("utente", utente)
    contesto.setdefault("puo_amministrare", puo_amministrare)
    contesto.setdefault(
        "ruolo_utente",
        ruolo_mostrato(utente).testo if utente is not None else None,
    )
    contesto.setdefault(
        "voci_menu",
        voci_visibili(MENU_PRINCIPALE, utente, puo_amministrare),
    )
    contesto.setdefault(
        "voci_menu_servizio",
        voci_visibili(MENU_SERVIZIO, utente, puo_amministrare),
    )
    contesto.setdefault("sezione", sezione_corrente(request.url.path))

    return templates.TemplateResponse(
        request=request,
        name=nome,
        context=contesto,
        status_code=stato,
    )
