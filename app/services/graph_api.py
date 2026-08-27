"""Il collegamento a Microsoft Graph: il gettone, le chiamate, gli errori.

Questo file e' l'unico punto di Aurora che parla davvero con Microsoft. Sopra
di lui sta `FonteGraph` (app/services/mail_source.py), che sa che cosa chiedere
- l'elenco dei messaggi, il file di un messaggio, lo spostamento in una
cartella - ma non sa niente di gettoni, di tentativi ripetuti e di codici HTTP.

    FonteGraph  -->  QUESTO FILE  -->  https://graph.microsoft.com
    che cosa         come, e che cosa fare quando va storto


PERCHE' GLI ERRORI SONO LA META' DEL FILE
-----------------------------------------

Un collegamento a un servizio esterno passa il tempo a non funzionare: la rete
aziendale cade, il segreto scade, l'ufficio informatico toglie un permesso,
Microsoft risponde "troppe richieste". Aurora gira su una macchina in cui non
c'e' nessuno seduto davanti, e l'unica cosa che resta di un guasto e' la frase
scritta nel registro.

Per questo **non esce mai di qui un errore tecnico grezzo**. Ogni guasto
diventa un `ErroreGraph` con due cose dentro:

  - `messaggio`, una frase in italiano che si capisce senza sapere che cosa sia
    un gettone di accesso, e che dice, quando si puo', **quale parametro** e'
    sbagliato;
  - `tecnico`, il dettaglio vero (codice HTTP, codice AADSTS, corpo della
    risposta), che finisce nel registro su file e da nessun'altra parte.

Chi cattura l'eccezione mostra `messaggio` e scrive `tecnico`: non deve
ricomporre nessuna frase e non deve indovinare niente.


LE QUATTRO COSE CHE VANNO STORTE, E COSA SI FA
----------------------------------------------

| Che cosa succede    | Come si vede      | Che cosa fa Aurora                |
|---------------------|-------------------|-----------------------------------|
| la rete non c'e'    | httpx non collega | si ferma e lo dice; poi riprova   |
| il gettone e' morto | HTTP 401          | ne prende uno nuovo e rifa' tutto |
| troppe richieste    | HTTP 429 o 503    | aspetta il Retry-After e riprova  |
| manca un permesso   | HTTP 403          | si ferma: serve una persona       |

Il rinnovo del gettone e' automatico anche **prima** che scada: il gettone si
tiene in memoria con la sua ora di scadenza e si rinnova quando mancano meno di
cinque minuti. Il 401 resta comunque gestito, perche' un gettone puo' essere
revocato prima della sua scadenza naturale.


PERCHE' msal SI IMPORTA DENTRO UNA FUNZIONE
-------------------------------------------

`import msal` sta dentro `_gettone_da_msal()` e non in cima al file. Non e' una
stranezza: la libreria serve **solo** a chi ha MAIL_PROVIDER=graph, e Aurora
deve poter partire - e i suoi test devono poter girare - su una macchina in cui
non e' installata. Con l'import in cima, l'assenza di msal romperebbe l'avvio
del programma intero invece della sola pagina della posta.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

logger = logging.getLogger("aurora.posta.graph")

# La radice delle chiamate. Sta qui e non nel .env: non e' configurazione
# dell'azienda, e' l'indirizzo di Microsoft.
BASE_GRAPH = "https://graph.microsoft.com/v1.0"

# Dove si chiede il gettone. Il posto del tenant lo prende MAIL_TENANT_ID.
AUTORITA = "https://login.microsoftonline.com/{tenant}"

# L'ambito delle credenziali applicative: "tutti i permessi che
# l'amministratore ha gia' concesso a questa applicazione". Non se ne chiedono
# altri, perche' con il flusso a credenziali applicative non c'e' nessuno a cui
# chiederli.
AMBITO = ["https://graph.microsoft.com/.default"]

# Quanto prima della scadenza si rinnova il gettone. Cinque minuti coprono con
# abbondanza un giro di acquisizione lungo: un gettone che scade a meta' di una
# richiesta e' un 401 che si poteva evitare.
MARGINE_RINNOVO_SECONDI = 300

# Quanti tentativi si fanno su una chiamata che chiede di riprovare (429, 503).
# Al quarto ci si ferma: se Microsoft sta ancora rallentando dopo tre attese, il
# giro va rimandato, non insistito.
TENTATIVI_MASSIMI = 4

# Quanto si accetta di aspettare, in secondi, per un singolo Retry-After. Oltre
# questo si rinuncia e lo si dice: il controllo della posta puo' avere dietro
# una persona che ha premuto un pulsante, e tenerla ferma dieci minuti davanti
# a una pagina bianca non e' aspettare, e' bloccarsi.
ATTESA_MASSIMA_SECONDI = 120

# Quanto si aspetta una risposta prima di considerarla persa. Il MIME di un
# messaggio con dentro un firmware puo' essere di parecchie decine di megabyte:
# il tempo di lettura e' largo apposta.
TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=15.0)


# ---------------------------------------------------------------------------
#  1. GLI ERRORI, GIA' SCRITTI IN ITALIANO
# ---------------------------------------------------------------------------


class ErroreGraph(Exception):
    """Qualcosa non ha funzionato nel colloquio con Microsoft 365.

    `messaggio` e' la frase da mostrare; `tecnico` il dettaglio da registrare.
    `parametro`, quando c'e', dice **quale parametro della configurazione** e'
    sbagliato: e' quello che permette alla pagina di configurazione di
    accendere di rosso il campo giusto invece di dire "non funziona".
    `codice_http`, quando c'e', serve a chi sta sopra per decidere se ha senso
    provare un'altra strada: una richiesta rifiutata per un permesso mancante
    va riferita a una persona, una richiesta che il servizio non sa eseguire si
    puo' rifare in un modo piu' semplice.
    """

    def __init__(
        self,
        messaggio: str,
        *,
        tecnico: str = "",
        parametro: str | None = None,
        codice_http: int | None = None,
    ) -> None:
        super().__init__(messaggio)
        self.messaggio = messaggio
        self.tecnico = tecnico or messaggio
        self.parametro = parametro
        self.codice_http = codice_http

    @property
    def da_riferire_a_una_persona(self) -> bool:
        """Vero quando riprovare in un altro modo non serve a niente.

        Credenziali rifiutate, permesso mancante, casella inesistente: sono i
        casi in cui il programma ha finito quello che poteva fare, e quello che
        manca lo deve fare qualcuno.
        """
        return self.codice_http in (401, 403, 404)


class LimiteDiFrequenza(ErroreGraph):
    """Microsoft ha chiesto di rallentare e l'attesa e' troppo lunga.

    `attendere` sono i secondi che ha chiesto: si scrivono nel messaggio,
    perche' "riprova fra un quarto d'ora" e' un'informazione, "non funziona"
    non lo e'.
    """

    def __init__(self, messaggio: str, *, attendere: float, tecnico: str = "") -> None:
        super().__init__(messaggio, tecnico=tecnico, codice_http=429)
        self.attendere = attendere


# I codici di errore di Azure AD che vale la pena di tradurre, con il parametro
# che li provoca. Sono quelli che si vedono davvero mentre si configura: un
# tenant scritto male, l'identificativo di un'applicazione che non esiste, un
# segreto copiato a meta' o scaduto.
#
# La chiave e' il codice che compare dentro "error_description". Chi non e' in
# elenco riceve comunque una frase italiana generica piu' il dettaglio nel
# registro: un codice sconosciuto non deve diventare un errore muto.
SPIEGAZIONI_AAD: dict[str, tuple[str | None, str]] = {
    "AADSTS90002": (
        "MAIL_TENANT_ID",
        "L'organizzazione indicata non esiste. Controlla l'identificativo "
        "dell'organizzazione: nel portale Microsoft e' la voce "
        "«ID directory (tenant)».",
    ),
    "AADSTS900023": (
        "MAIL_TENANT_ID",
        "L'identificativo dell'organizzazione non e' scritto in un modo "
        "riconoscibile. Deve essere l'identificativo lungo con i trattini "
        "oppure il nome di dominio dell'azienda.",
    ),
    "AADSTS700016": (
        "MAIL_CLIENT_ID",
        "L'applicazione indicata non risulta registrata in questa "
        "organizzazione. Controlla l'identificativo dell'applicazione: nel "
        "portale Microsoft e' la voce «ID applicazione (client)».",
    ),
    "AADSTS7000215": (
        "MAIL_CLIENT_SECRET",
        "Il segreto dell'applicazione non e' corretto. Il valore da copiare e' "
        "quello della colonna «Valore», non quello della colonna «ID segreto», "
        "e si puo' leggere solo nel momento in cui viene creato.",
    ),
    "AADSTS7000222": (
        "MAIL_CLIENT_SECRET",
        "Il segreto dell'applicazione e' scaduto. Va creato un segreto nuovo "
        "nel portale Microsoft e riscritto qui.",
    ),
    "AADSTS7000112": (
        "MAIL_CLIENT_ID",
        "L'applicazione indicata e' disattivata nell'organizzazione.",
    ),
    "AADSTS500011": (
        None,
        "L'organizzazione non ha concesso all'applicazione l'accesso a "
        "Microsoft Graph. Serve il consenso dell'amministratore.",
    ),
}


def spiega_errore_aad(descrizione: str) -> tuple[str | None, str]:
    """Da "error_description" di Azure AD alla frase italiana e al parametro.

    Si cerca il codice AADSTS dentro la descrizione invece di confrontarla per
    intero: Microsoft ci mette dentro l'ora, l'identificativo della richiesta e
    ogni tanto cambia la punteggiatura, ma il codice non cambia mai.
    """
    for codice, (parametro, frase) in SPIEGAZIONI_AAD.items():
        if codice in descrizione:
            return parametro, frase

    return None, (
        "Microsoft ha rifiutato le credenziali dell'applicazione. Il dettaglio "
        "e' nel registro su file; di solito e' uno dei tre parametri "
        "dell'applicazione a essere sbagliato."
    )


# ---------------------------------------------------------------------------
#  2. LE CREDENZIALI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Credenziali:
    """I quattro parametri con cui ci si collega alla casella.

    Stanno in un oggetto invece che in quattro argomenti perche' viaggiano
    sempre insieme e perche' cosi' la pagina di configurazione puo' costruirne
    uno con i valori appena scritti nel modulo - non ancora salvati - e
    provarli. E' quello che fa il pulsante VERIFICA.
    """

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    mailbox: str = ""

    def mancanti(self) -> list[str]:
        """I nomi dei parametri lasciati vuoti, in ordine di modulo."""
        coppie = (
            ("MAIL_TENANT_ID", self.tenant_id),
            ("MAIL_CLIENT_ID", self.client_id),
            ("MAIL_CLIENT_SECRET", self.client_secret),
            ("MAIL_MAILBOX_ADDRESS", self.mailbox),
        )
        return [nome for nome, valore in coppie if not (valore or "").strip()]


# ---------------------------------------------------------------------------
#  3. IL CLIENTE
# ---------------------------------------------------------------------------


class ClienteGraph:
    """Parla con Microsoft Graph per conto di una casella sola.

    **Il gettone si tiene in memoria e si rinnova da solo.** Non finisce su
    disco e non finisce nel database: e' valido un'ora, e un segreto scritto da
    qualche parte e' un segreto che qualcuno prima o poi legge. Al riavvio del
    server se ne chiede semplicemente un altro.

    **I tre argomenti in coda servono ai test, e a niente altro.**
    `trasporto` sostituisce il collegamento vero con uno finto che risponde
    quello che il test vuole; `fornitore_gettone` sostituisce il giro di msal;
    `dormi` evita che un test sulla limitazione di frequenza aspetti davvero.
    Cosi' le risposte di Graph - compreso il 429 con Retry-After e il 401 con
    il gettone scaduto - si provano tutte, sempre, senza casella aziendale e
    senza rete. E' la stessa idea per cui esiste `FonteLocale`.
    """

    def __init__(
        self,
        credenziali: Credenziali,
        *,
        trasporto: httpx.BaseTransport | None = None,
        fornitore_gettone: Callable[[], tuple[str, int]] | None = None,
        dormi: Callable[[float], None] | None = None,
    ) -> None:
        self.credenziali = credenziali
        self._trasporto = trasporto
        self._fornitore_gettone = fornitore_gettone or self._gettone_da_msal
        self._dormi = dormi or time.sleep

        # Il gettone di adesso e il momento in cui smette di valere.
        self._gettone: str | None = None
        self._gettone_scade_a: float = 0.0

        self._cliente_http: httpx.Client | None = None

    # --- Il collegamento ---------------------------------------------------

    @property
    def http(self) -> httpx.Client:
        """Il cliente HTTP, aperto la prima volta che serve.

        Uno solo per oggetto: httpx tiene aperta la connessione e la riusa, e
        un giro di acquisizione fa almeno due chiamate per messaggio. Riaprire
        il collegamento ogni volta vorrebbe dire rifare ogni volta la stretta
        di mano cifrata.
        """
        if self._cliente_http is None:
            self._cliente_http = httpx.Client(
                transport=self._trasporto,
                timeout=TIMEOUT,
                follow_redirects=True,
            )
        return self._cliente_http

    def chiudi(self) -> None:
        """Restituisce la connessione. Si puo' chiamare anche due volte."""
        if self._cliente_http is not None:
            self._cliente_http.close()
            self._cliente_http = None

    # --- Il gettone --------------------------------------------------------

    def gettone(self, *, rinnova: bool = False) -> str:
        """Il gettone da mettere in cima a ogni chiamata.

        Se quello in memoria vale ancora per piu' di cinque minuti si riusa;
        altrimenti se ne chiede uno nuovo. Con `rinnova=True` si butta via
        quello che c'e' e se ne chiede un altro: e' quello che si fa dopo un
        401, quando il gettone e' stato revocato prima della sua scadenza.
        """
        adesso = time.monotonic()
        if (
            not rinnova
            and self._gettone is not None
            and self._gettone_scade_a - MARGINE_RINNOVO_SECONDI > adesso
        ):
            return self._gettone

        mancanti = self.credenziali.mancanti()
        if mancanti:
            raise ErroreGraph(
                "Mancano i parametri della casella aziendale: "
                + ", ".join(mancanti)
                + ". Si scrivono nella pagina «Configurazione posta».",
                tecnico=f"parametri vuoti: {mancanti}",
                parametro=mancanti[0],
            )

        gettone, dura = self._fornitore_gettone()
        self._gettone = gettone
        self._gettone_scade_a = time.monotonic() + max(0, dura)
        logger.info(
            "Gettone di accesso ottenuto, vale per %s minuti", round(dura / 60)
        )
        return gettone

    def _gettone_da_msal(self) -> tuple[str, int]:
        """Chiede il gettone a Microsoft con le credenziali applicative.

        E' il flusso a credenziali applicative: non c'e' nessun utente che
        entra, c'e' un'applicazione che si presenta con il proprio segreto. E'
        quello che serve a un programma che gira su un server senza nessuno
        davanti, ed e' il motivo per cui il permesso da chiedere all'ufficio
        informatico e' `Mail.Read` **di tipo applicazione**
        (docs/RICHIESTA_IT.md).

        L'import di msal sta qui dentro apposta: vedi la spiegazione in cima al
        file.
        """
        try:
            import msal
        except ImportError as errore:
            raise ErroreGraph(
                "La libreria di collegamento a Microsoft 365 non e' installata "
                "su questo server. Chi lo amministra deve eseguire "
                "«pip install -r requirements.txt» dentro la cartella di "
                "Aurora e riavviare il programma.",
                tecnico=f"import msal fallito: {errore}",
            ) from errore

        try:
            # La costruzione sta **dentro** il try insieme alla richiesta, e non
            # e' un dettaglio: msal, quando costruisce l'applicazione, va a
            # chiedere a Microsoft se l'organizzazione indicata esiste. Quella
            # riga fallisce quando la rete non c'e' e quando il tenant e'
            # scritto storto, che sono due dei casi che questo file esiste per
            # raccontare bene.
            applicazione = msal.ConfidentialClientApplication(
                client_id=self.credenziali.client_id,
                authority=AUTORITA.format(tenant=self.credenziali.tenant_id),
                client_credential=self.credenziali.client_secret,
            )
            risposta = applicazione.acquire_token_for_client(scopes=AMBITO)
        except ValueError as errore:
            # msal usa ValueError per "questa autorita' non va bene": e' il
            # tenant scritto in un modo che non esiste.
            raise ErroreGraph(
                "L'organizzazione indicata non e' stata riconosciuta da "
                "Microsoft. Controlla l'identificativo dell'organizzazione: nel "
                "portale Microsoft e' la voce «ID directory (tenant)».",
                tecnico=f"{type(errore).__name__}: {errore}",
                parametro="MAIL_TENANT_ID",
            ) from errore
        except Exception as errore:
            # msal si porta dietro la propria libreria di rete e i propri
            # errori: qui si prende tutto quello che non e' una risposta e lo
            # si traduce, perche' di sopra nessuno sa che cosa siano.
            raise ErroreGraph(
                "Non si riesce a raggiungere il servizio di autenticazione di "
                "Microsoft. Controlla che questo server abbia accesso a "
                "internet e che il proxy aziendale lasci passare "
                "login.microsoftonline.com.",
                tecnico=f"{type(errore).__name__}: {errore}",
            ) from errore

        if not isinstance(risposta, dict) or "access_token" not in risposta:
            descrizione = ""
            if isinstance(risposta, dict):
                descrizione = str(
                    risposta.get("error_description") or risposta.get("error") or ""
                )
            parametro, frase = spiega_errore_aad(descrizione)
            raise ErroreGraph(
                frase,
                tecnico=f"msal non ha restituito un gettone: {descrizione}",
                parametro=parametro,
            )

        return str(risposta["access_token"]), int(risposta.get("expires_in", 3600))

    # --- Le chiamate -------------------------------------------------------

    def json(self, metodo: str, percorso: str, **extra: Any) -> dict[str, Any]:
        """Una chiamata che risponde con un oggetto JSON.

        `percorso` puo' essere relativo ("/users/...") oppure un indirizzo
        intero: le pagine successive di un elenco e il gettone delta arrivano
        da Graph gia' come indirizzi completi, e riscriverli sarebbe un modo di
        sbagliarli.
        """
        risposta = self._chiama(metodo, percorso, **extra)
        if not risposta.content:
            return {}
        try:
            risultato = risposta.json()
        except ValueError as errore:
            raise ErroreGraph(
                "Microsoft ha risposto in un modo che Aurora non ha capito. "
                "Il dettaglio e' nel registro su file.",
                tecnico=f"risposta non JSON ({risposta.status_code}): "
                f"{risposta.text[:400]}",
            ) from errore

        return risultato if isinstance(risultato, dict) else {}

    def byte(self, percorso: str, **extra: Any) -> bytes:
        """Una chiamata che risponde con un file: il MIME di un messaggio."""
        return self._chiama("GET", percorso, **extra).content

    def _chiama(self, metodo: str, percorso: str, **extra: Any) -> httpx.Response:
        """Fa la chiamata, e la rifa' quando ha senso rifarla.

        Due sono i casi in cui si riprova, e sono diversi fra loro:

          - **401**: il gettone non vale piu'. Se ne prende un altro e si rifa'
            la stessa chiamata, **una volta sola**: se anche il gettone nuovo
            viene rifiutato, il problema non e' il gettone;
          - **429 e 503**: Microsoft chiede di rallentare. Si aspettano i
            secondi che ha indicato lei nell'intestazione `Retry-After` e si
            riprova, fino a tre volte.

        Su tutto il resto non si riprova: un 403 riprovato resta un 403, e
        insistere e' il modo piu' rapido di farsi limitare davvero.
        """
        indirizzo = percorso if percorso.startswith("http") else BASE_GRAPH + percorso
        gia_rinnovato = False
        intestazioni_chiamante = dict(extra.pop("headers", {}) or {})

        for tentativo in range(1, TENTATIVI_MASSIMI + 1):
            intestazioni = dict(intestazioni_chiamante)
            intestazioni["Authorization"] = f"Bearer {self.gettone()}"

            try:
                risposta = self.http.request(
                    metodo, indirizzo, headers=intestazioni, **extra
                )
            except httpx.TimeoutException as errore:
                raise ErroreGraph(
                    "Microsoft 365 non ha risposto entro il tempo previsto. "
                    "Puo' essere la rete aziendale lenta o un blocco del "
                    "proxy: la lettura della posta riprendera' al controllo "
                    "successivo.",
                    tecnico=f"timeout su {metodo} {indirizzo}: {errore}",
                ) from errore
            except httpx.HTTPError as errore:
                raise ErroreGraph(
                    "Non si riesce a raggiungere Microsoft 365. Controlla che "
                    "questo server abbia accesso a internet e che il proxy "
                    "aziendale lasci passare graph.microsoft.com.",
                    tecnico=f"{type(errore).__name__} su {metodo} "
                    f"{indirizzo}: {errore}",
                ) from errore

            if risposta.status_code < 400:
                return risposta

            if risposta.status_code == 401 and not gia_rinnovato:
                # Il gettone e' stato revocato prima della scadenza. Se ne
                # prende uno nuovo e si rifa' la chiamata: e' il caso in cui
                # riprovare risolve davvero.
                logger.info(
                    "Gettone rifiutato da Microsoft: se ne chiede uno nuovo e "
                    "si riprova"
                )
                self.gettone(rinnova=True)
                gia_rinnovato = True
                continue

            if risposta.status_code in (429, 503) and tentativo < TENTATIVI_MASSIMI:
                attesa = secondi_da_aspettare(risposta, tentativo)
                if attesa > ATTESA_MASSIMA_SECONDI:
                    raise LimiteDiFrequenza(
                        "Microsoft 365 ha chiesto di rallentare e di riprovare "
                        f"fra {round(attesa / 60)} minuti. Aurora riprendera' "
                        "da sola al controllo successivo: non c'e' niente da "
                        "fare.",
                        attendere=attesa,
                        tecnico=f"HTTP {risposta.status_code} con Retry-After="
                        f"{risposta.headers.get('Retry-After')}",
                    )
                logger.warning(
                    "Microsoft chiede di rallentare (HTTP %s): si aspettano %s "
                    "secondi e si riprova (tentativo %s di %s)",
                    risposta.status_code,
                    attesa,
                    tentativo,
                    TENTATIVI_MASSIMI,
                )
                self._dormi(attesa)
                continue

            raise self._errore_dalla_risposta(risposta, metodo, indirizzo)

        # Si arriva qui solo con l'ultimo tentativo consumato da un 429.
        raise LimiteDiFrequenza(
            "Microsoft 365 continua a chiedere di rallentare. La lettura della "
            "posta riprendera' al controllo successivo.",
            attendere=ATTESA_MASSIMA_SECONDI,
            tecnico=f"{TENTATIVI_MASSIMI} tentativi esauriti su "
            f"{metodo} {indirizzo}",
        )

    def _errore_dalla_risposta(
        self, risposta: httpx.Response, metodo: str, indirizzo: str
    ) -> ErroreGraph:
        """Trasforma una risposta di errore nella frase da mostrare.

        Il corpo di Graph e' un JSON con dentro `error.code` e `error.message`.
        Sono in inglese e non si mostrano mai: servono a scegliere quale delle
        nostre frasi e' quella giusta, e finiscono nel registro su file.
        """
        codice_http = risposta.status_code
        codice = ""
        dettaglio = ""
        try:
            corpo = risposta.json()
            errore = (corpo or {}).get("error") or {}
            codice = str(errore.get("code") or "")
            dettaglio = str(errore.get("message") or "")
        except ValueError:
            dettaglio = risposta.text[:400]

        tecnico = f"HTTP {codice_http} su {metodo} {indirizzo} - {codice}: {dettaglio}"

        if codice_http == 401:
            return ErroreGraph(
                "Microsoft ha rifiutato le credenziali dell'applicazione. Di "
                "solito vuol dire che il segreto e' stato cambiato o e' "
                "scaduto: si controlla nella pagina «Configurazione posta».",
                tecnico=tecnico,
                parametro="MAIL_CLIENT_SECRET",
                codice_http=codice_http,
            )

        if codice_http == 403:
            # Due 403 diversi, e la differenza conta: uno si risolve dando un
            # permesso, l'altro correggendo la regola che restringe
            # l'applicazione a una casella sola.
            if "ApplicationAccessPolicy" in dettaglio or "Access to OData" in dettaglio:
                return ErroreGraph(
                    "L'applicazione non e' autorizzata a leggere questa "
                    "casella. La regola che limita Aurora a una sola casella "
                    "(Application Access Policy) non comprende l'indirizzo "
                    "indicato: va corretta da chi amministra Microsoft 365, "
                    "oppure va corretto l'indirizzo.",
                    tecnico=tecnico,
                    parametro="MAIL_MAILBOX_ADDRESS",
                    codice_http=codice_http,
                )
            return ErroreGraph(
                "All'applicazione manca il permesso di leggere la posta. "
                "L'ufficio informatico deve concedere il permesso «Mail.Read» "
                "di tipo applicazione e dare il consenso amministratore: la "
                "richiesta gia' pronta e' in docs/RICHIESTA_IT.md.",
                tecnico=tecnico,
                codice_http=codice_http,
            )

        if codice_http == 404:
            return ErroreGraph(
                "La casella indicata non esiste in questa organizzazione. "
                "Controlla l'indirizzo: deve essere quello di una casella vera "
                "di Microsoft 365, non un alias e non un gruppo.",
                tecnico=tecnico,
                parametro="MAIL_MAILBOX_ADDRESS",
                codice_http=codice_http,
            )

        if codice_http >= 500:
            return ErroreGraph(
                "Microsoft 365 ha risposto con un errore proprio. Non c'e' "
                "niente da correggere in Aurora: la lettura riprendera' al "
                "controllo successivo.",
                tecnico=tecnico,
                codice_http=codice_http,
            )

        return ErroreGraph(
            "Microsoft 365 ha rifiutato la richiesta. Il dettaglio e' nel "
            "registro su file.",
            tecnico=tecnico,
            codice_http=codice_http,
        )


def secondi_da_aspettare(risposta: httpx.Response, tentativo: int) -> float:
    """Quanto aspettare prima di riprovare, secondo Microsoft o secondo noi.

    Si rispetta `Retry-After` quando c'e', perche' e' il servizio a sapere
    quanto e' carico. Quando non c'e' - capita sui 503 - si raddoppia l'attesa
    a ogni tentativo (2, 4, 8 secondi): e' la regola normale per non peggiorare
    una coda gia' lunga presentandosi tutti insieme.
    """
    indicato = risposta.headers.get("Retry-After")
    if indicato:
        try:
            return max(0.0, float(indicato))
        except ValueError:
            # Retry-After puo' essere anche una data. Non si prova a leggerla:
            # e' un formato che Graph non usa, e sbagliare la conversione
            # vorrebbe dire aspettare fino a domani.
            logger.warning("Retry-After illeggibile: %s", indicato)

    return float(2**tentativo)
