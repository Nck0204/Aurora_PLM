"""Protezione dei moduli dalla falsificazione delle richieste (CSRF).

Il problema, in due righe. Chi e' entrato in Aurora ha un cookie di sessione,
e il browser lo allega **da solo** a ogni richiesta verso il nostro indirizzo.
Se la stessa persona apre in un'altra scheda una pagina ostile che contiene un
modulo puntato su Aurora e lo fa inviare, quella richiesta arriva con il
cookie di sessione buono e per il server e' indistinguibile da una richiesta
vera. Nessuno ha rubato niente: il browser ha fatto il suo mestiere.

La difesa, e perche' e' fatta cosi'
-----------------------------------

Si usa il metodo del **doppio invio**: lo stesso gettone casuale viaggia in
due posti diversi, in un cookie e in un campo nascosto del modulo, e il server
accetta la richiesta solo se i due coincidono. Chi scrive la pagina ostile puo'
far allegare il cookie dal browser, ma non puo' **leggerlo** per copiarne il
valore nel campo nascosto: glielo impediscono l'attributo HttpOnly e la regola
che un sito non legge i cookie di un altro. Senza il valore giusto nel campo,
la richiesta viene rifiutata.

Sopra a questa c'e' gia' una seconda difesa: i cookie di Aurora sono
SameSite=Lax, e il browser non li allega affatto a un POST che parte da un
altro sito. Le due difese si sovrappongono di proposito. SameSite dipende
interamente dal browser: basta un browser vecchio, o una configurazione
insolita, e non c'e' piu'. Il controllo del gettone, invece, lo facciamo noi.

Dove viene applicato
--------------------

Non rotta per rotta: la verifica e' una **dipendenza globale**, dichiarata una
volta sola nella creazione dell'applicazione in app/main.py. Vale quindi per
tutte le rotte che ci sono e per tutte quelle che verranno, e nessuno puo'
dimenticarsene aggiungendone una nuova. E' l'unico punto di questo programma
in cui si e' preferita una cosa automatica a una esplicita, perche' qui la
dimenticanza non si vede: la pagina funziona lo stesso, e manca solo la
difesa.
"""

import logging
import secrets

from fastapi import HTTPException, Request

from app.services.cookies import COOKIE_CSRF, programma_cookie

logger = logging.getLogger("aurora.csrf")

# Nome del campo nascosto che ogni modulo deve contenere. Nei template si
# scrive per esteso, una riga dentro ogni <form method="post">: la regola e'
# ricordata in cima ad app/templates/base.html.
CSRF_FIELD = "csrf"

# Lunghezza del gettone in byte, prima della codifica in testo.
CSRF_TOKEN_BYTES = 32

# I metodi che non cambiano niente sul server: non hanno bisogno di difesa.
# Tutti gli altri (POST, PUT, PATCH, DELETE) vengono verificati.
METODI_SICURI = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

MESSAGGIO_RIFIUTO = (
    "La pagina e' rimasta aperta troppo a lungo oppure la richiesta non "
    "proviene da Aurora. Torna indietro, ricarica la pagina e riprova."
)


def token_csrf(request: Request) -> str:
    """Restituisce il gettone da mettere nel campo nascosto del modulo.

    Lo prende dal cookie se c'e' gia'; se non c'e' ne genera uno nuovo e lo
    programma per essere consegnato al browser. In ogni caso, dentro la stessa
    richiesta restituisce sempre lo stesso valore: se una pagina contiene tre
    moduli, i tre campi nascosti hanno lo stesso gettone del cookie.

    Questa funzione e' registrata fra le funzioni globali di Jinja2, quindi i
    template la richiamano direttamente.
    """
    # Gia' calcolato in questa richiesta: si restituisce quello.
    gettone = getattr(request.state, "csrf_token", None)
    if gettone is not None:
        return gettone

    gettone = request.cookies.get(COOKIE_CSRF)
    if not gettone:
        gettone = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        # Nessuna durata: e' un cookie di sessione, muore con il browser. Un
        # gettone di protezione non ha nessuna ragione di sopravvivergli.
        programma_cookie(request, COOKIE_CSRF, gettone)

    request.state.csrf_token = gettone
    return gettone


async def verifica_csrf(request: Request) -> None:
    """Dipendenza globale: rifiuta i POST senza gettone valido.

    Sulle richieste che non cambiano niente non fa nessun controllo, ma
    prepara comunque il gettone: e' proprio la pagina con il modulo, che
    arriva con un GET, a doverlo avere.

    Il confronto usa secrets.compare_digest e non l'uguale normale. L'uguale
    smette di confrontare appena trova due caratteri diversi, quindi impiega
    piu' tempo quando i due valori hanno un inizio in comune; misurando i tempi
    di molte risposte si potrebbe indovinare il gettone un carattere per volta.
    compare_digest impiega lo stesso tempo in ogni caso.
    """
    gettone_atteso = token_csrf(request)

    if request.method in METODI_SICURI:
        return

    modulo = await request.form()
    gettone_ricevuto = modulo.get(CSRF_FIELD, "")

    if not isinstance(gettone_ricevuto, str) or not secrets.compare_digest(
        gettone_ricevuto, gettone_atteso
    ):
        logger.warning(
            "Gettone CSRF mancante o sbagliato su %s %s da %s",
            request.method,
            request.url.path,
            request.client.host if request.client else "origine ignota",
        )
        raise HTTPException(status_code=400, detail=MESSAGGIO_RIFIUTO)
