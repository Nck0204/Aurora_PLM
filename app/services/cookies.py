"""I cookie di Aurora: come si chiamano e come si consegnano al browser.

Sono tre, e non ce ne saranno altri:

  aurora_sessione   il gettone della sessione in corso. Muore alla chiusura
                    del browser.
  aurora_ricordami  il gettone lungo emesso dalla casella "Ricordami". Dura
                    trenta giorni e sopravvive alla chiusura del browser.
  aurora_csrf       il gettone che protegge i moduli dalla falsificazione
                    delle richieste (vedi app/services/csrf.py).

Tutti e tre hanno gli stessi attributi di sicurezza:

  HttpOnly        il JavaScript della pagina non puo' leggerli. Se un giorno
                  finisse dentro una pagina uno script ostile, non potrebbe
                  portarsi via la sessione di chi la sta guardando.
  SameSite=Lax    il browser non li allega alle richieste che partono da un
                  altro sito. E' la prima difesa contro la falsificazione
                  delle richieste, e da sola blocca gia' i POST da fuori.
  Secure          li rimanda solo su connessione cifrata. E' un parametro di
                  configurazione, COOKIE_SECURE: falso in sviluppo (dove si
                  lavora su http e con true non si riuscirebbe a entrare),
                  vero in produzione.
  Path=/          valgono per tutto il programma.

Nella password non c'e' niente da dire: **nel cookie non ci finisce mai.**
Nemmeno il nome utente. Nel cookie c'e' solo un numero casuale, e il database
ne conserva l'impronta.


Perche' i cookie si "programmano" invece di impostarli e basta
-------------------------------------------------------------

Le funzioni qui sotto non scrivono il cookie nella risposta: lo mettono in
lista d'attesa dentro request.state. E' un piccolo giro in piu' che serve a
risolvere un problema vero.

Il rinnovo del gettone "ricordami" (vedi app/dependencies.py) avviene dentro
una dipendenza di FastAPI, cioe' **prima** che la rotta venga eseguita. Se la
rotta poi solleva un errore - un 403 perche' la pagina e' riservata al
creatore, per esempio - la risposta che arriva al browser e' quella prodotta
dal gestore degli errori, e i cookie impostati dalla dipendenza andrebbero
persi. Il gettone vecchio pero' e' gia' stato revocato: l'utente si
ritroverebbe buttato fuori per aver sbagliato pagina.

Mettendoli in lista d'attesa e applicandoli in fondo a tutto (lo fa il
middleware registrato in app/main.py), i cookie finiscono su **qualunque**
risposta esca, comprese le pagine di errore.
"""

from fastapi import Request, Response

from app.config import settings

# I nomi dei tre cookie. Il prefisso "aurora_" evita che si confondano con
# quelli di un altro programma servito dallo stesso indirizzo.
COOKIE_SESSIONE = "aurora_sessione"
COOKIE_RICORDAMI = "aurora_ricordami"
COOKIE_CSRF = "aurora_csrf"

# Nome della casella dentro request.state in cui i cookie aspettano.
_ATTESA = "cookie_in_attesa"


def _lista_di_attesa(request: Request) -> list[dict]:
    """Restituisce la lista dei cookie in attesa, creandola la prima volta."""
    if not hasattr(request.state, _ATTESA):
        setattr(request.state, _ATTESA, [])
    return getattr(request.state, _ATTESA)


def programma_cookie(
    request: Request,
    nome: str,
    valore: str,
    durata_secondi: int | None = None,
) -> None:
    """Mette un cookie in lista d'attesa perche' venga consegnato al browser.

    Con durata_secondi a None il cookie e' "di sessione": il browser lo tiene
    finche' resta aperto e lo butta alla chiusura. E' quello che vogliamo per
    la sessione normale. Con una durata, invece, il browser lo conserva su
    disco: e' il caso del "ricordami".
    """
    _lista_di_attesa(request).append(
        {
            "key": nome,
            "value": valore,
            "max_age": durata_secondi,
            "httponly": True,
            "samesite": "lax",
            "secure": settings.COOKIE_SECURE,
            "path": "/",
        }
    )


def programma_rimozione_cookie(request: Request, nome: str) -> None:
    """Mette in lista d'attesa la cancellazione di un cookie.

    Si ottiene consegnandone uno vuoto con durata zero: il browser lo sostituisce
    a quello che aveva e lo butta subito. Gli attributi devono essere gli stessi
    con cui era stato messo, altrimenti il browser lo considera un cookie diverso
    e quello vecchio resta al suo posto.
    """
    programma_cookie(request, nome, valore="", durata_secondi=0)


def applica_cookie(request: Request, response: Response) -> None:
    """Scrive nella risposta tutti i cookie rimasti in lista d'attesa.

    La chiama il middleware in app/main.py, una volta sola, quando la risposta
    e' ormai pronta e non puo' piu' cambiare tipo.
    """
    for cookie in _lista_di_attesa(request):
        response.set_cookie(**cookie)
