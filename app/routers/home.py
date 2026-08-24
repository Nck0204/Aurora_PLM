"""La pagina iniziale.

Una rotta sola. In questa sessione mostra il minimo indispensabile: chi e'
entrato, il suo ruolo, e i collegamenti alle poche cose che esistono. Serve
soprattutto ad avere un posto dove arrivare dopo l'accesso e da cui provare
l'uscita.

La struttura di navigazione vera e' della sessione 9.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_login
from app.models import User
from app.services import auth
from app.templating import pagina

router = APIRouter(tags=["pagine"])


@router.get("/")
def home(
    request: Request,
    password_cambiata: int = 0,
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """La pagina iniziale, riservata a chi e' entrato.

    Il parametro password_cambiata vale 1 quando si arriva qui subito dopo aver
    cambiato la password, e serve solo a mostrare la conferma. E' un numero,
    non un dato: nell'indirizzo non finisce mai niente di riservato.
    """
    return pagina(
        request,
        "home.html",
        password_cambiata=bool(password_cambiata),
        sessioni_attive=auth.conta_sessioni_attive(db, utente.id),
    )
