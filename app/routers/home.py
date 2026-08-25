"""La pagina iniziale, che dalla sessione 5 e' il cruscotto.

Una rotta sola. Mostra i progetti che la persona che sta guardando puo'
vedere, con codice prodotto, versione, cliente, fase corrente, stato del ciclo
di vita e responsabile, piu' i due filtri per stato e per fase.

E' la pagina che tutti aprono la mattina, e questo detta due scelte:

  - **si legge a colpo d'occhio**: una tabella sola in cima, senza riquadri
    intorno, con le colonne che rispondono alla domanda "a che punto siamo";
  - **non mostra quello che non spetta**: chi non e' assegnato a un progetto
    non lo vede. Il filtro non e' grafico, e' nell'interrogazione (vedi
    app/services/projects.py).

Il profilo e le sessioni aperte restano piu' in basso: sono cose che si
guardano una volta ogni tanto, ma toglierle vorrebbe dire togliere anche
"Esci da tutti i dispositivi", che e' l'unico modo che una persona ha di
chiudere una sessione dimenticata su un altro calcolatore.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import richiedi_login
from app.models import User
from app.services import auth, projects
from app.templating import pagina

router = APIRouter(tags=["pagine"])


@router.get("/")
def home(
    request: Request,
    password_cambiata: int = 0,
    q: str = "",
    stato: str = "",
    fase: str = "",
    utente: User = Depends(richiedi_login),
    db: Session = Depends(get_db),
) -> Response:
    """Il cruscotto: i progetti visibili a chi sta guardando.

    Il parametro password_cambiata vale 1 quando si arriva qui subito dopo
    aver cambiato la password, e serve solo a mostrare la conferma. E' un
    numero, non un dato: nell'indirizzo non finisce mai niente di riservato.

    I due filtri viaggiano nell'indirizzo con un modulo GET, come tutte le
    ricerche di Aurora: cosi' "i miei progetti in verifica" e' un indirizzo
    che si mette nei preferiti.
    """
    visibili = projects.cruscotto(
        db, utente, testo=q or None, stato=stato or None, fase=fase or None
    )

    return pagina(
        request,
        "home.html",
        password_cambiata=bool(password_cambiata),
        sessioni_attive=auth.conta_sessioni_attive(db, utente.id),
        progetti=visibili,
        totale_progetti=projects.conta_progetti_visibili(db, utente),
        filtri=projects.filtri_cruscotto(db, utente, stato, fase),
        q=q,
        stato_scelto=stato,
        fase_scelta=fase,
    )
