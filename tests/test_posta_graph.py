"""La casella aziendale: Microsoft Graph, l'orologio, la configurazione.

E' il file della sessione 11 e sta accanto a `test_posta.py`, che prova il
motore. Qui non si prova il motore: si prova la **seconda fonte** e quello che
le gira intorno.

    1. le risposte di Graph, simulate
    2. i quattro modi di andare storto: rete, gettone, limitazione, permessi
    3. il segnalibro, cioe' la ripetibilita' su una casella
    4. il motore che digerisce i messaggi presi da Graph senza essere stato
       toccato
    5. la pianificazione e il blocco che impedisce due letture insieme
    6. la pagina di configurazione, compreso il caso "parametri sbagliati"
    7. la scadenza del segreto
    8. la scrittura del file .env

**Come si finge Microsoft.** Non con una libreria di simulazione e non con un
finto server: con `httpx.MockTransport`, che e' il trasporto che httpx usa al
posto della rete. `FintaCasella` risponde come risponderebbe Graph - le stesse
chiavi, gli stessi codici HTTP, le stesse intestazioni - e tiene il conto di
che cosa le e' stato chiesto. E' la stessa idea di `FonteLocale`: i casi
difficili si scrivono e si rileggono all'infinito, invece di doverseli far
capitare.

**Nessuno di questi test ha bisogno di msal**, ed e' voluto: il gettone si
inietta. La libreria vera serve solo al server aziendale, e i test devono
girare anche su una macchina che non l'ha installata.
"""

import json
import threading
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, EmailMessage, GlobalRole
from app.services import emails, env_file, mail_config, mail_scheduler
from app.services.graph_api import ClienteGraph, Credenziali, ErroreGraph
from app.services.mail_source import (
    FonteEmail,
    FonteGraph,
    FonteLocale,
    FonteNonDisponibile,
    MessaggioNonTrovato,
    SegnalibroGraph,
    fonte_configurata,
)
from tests.conftest import (
    PASSWORD_DI_PROVA,
    crea_utente,
    entra,
    gettone_csrf,
)
from tests.test_posta import eml, identificativo_di_prova, prodotto_con_versioni

CASELLA = "ordini@azienda.test"

# Credenziali finte, ma della forma giusta: la pagina di configurazione
# controlla che gli identificativi siano fatti come quelli di Azure AD, e con
# "prova" al posto dell'identificativo si proverebbe quel controllo invece di
# quello che si vuole provare.
CREDENZIALI = Credenziali(
    tenant_id="11111111-2222-3333-4444-555555555555",
    client_id="66666666-7777-8888-9999-000000000000",
    client_secret="un-segreto-finto",
    mailbox=CASELLA,
)


# ===========================================================================
#  Attrezzi: una casella di Microsoft 365 che non esiste
# ===========================================================================


class FintaCasella:
    """Risponde come risponderebbe Microsoft Graph, e tiene il conto.

    `copione` e' l'elenco delle risposte da dare **prima** di comportarsi
    normalmente: e' con quello che si provano il 429, il 401 e il 403, che
    sono risposte che una casella vera non da' quando uno le vuole.
    """

    def __init__(self, messaggi=None, cartelle=None):
        # id -> (non letto, istante di ricezione, byte del messaggio)
        self.messaggi: dict[str, dict] = dict(messaggi or {})
        # nome -> identificativo
        self.cartelle: dict[str, str] = dict(cartelle or {})
        self.spostati: list[tuple[str, str]] = []
        self.chiamate: list[tuple[str, str]] = []
        self.copione: list[httpx.Response] = []
        self.gettone_delta = "https://graph.microsoft.com/v1.0/delta-2"

    # --- Il trasporto ------------------------------------------------------

    def trasporto(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._rispondi)

    def cliente(self, **extra) -> ClienteGraph:
        """Un ClienteGraph che parla con questa casella invece che con la rete."""
        extra.setdefault("fornitore_gettone", lambda: ("gettone-finto", 3600))
        extra.setdefault("dormi", lambda secondi: None)
        return ClienteGraph(CREDENZIALI, trasporto=self.trasporto(), **extra)

    def fonte(self, segnalibro=None, **extra) -> FonteGraph:
        return FonteGraph(self.cliente(**extra), segnalibro=segnalibro)

    # --- Le risposte -------------------------------------------------------

    def _rispondi(self, richiesta: httpx.Request) -> httpx.Response:
        percorso = str(richiesta.url)
        self.chiamate.append((richiesta.method, percorso))

        if self.copione:
            return self.copione.pop(0)

        # La delta query, e il gettone che Microsoft consegna per la volta
        # dopo: e' un indirizzo intero e Aurora lo richiama tale e quale.
        if "/messages/delta" in percorso or percorso == self.gettone_delta:
            return self._delta(richiesta)
        if percorso.endswith("/$value"):
            return self._valore(percorso)
        if percorso.endswith("/move"):
            return self._sposta(richiesta, percorso)
        if "/mailFolders?" in percorso:
            return self._cerca_cartella(percorso)
        if richiesta.method == "POST" and percorso.endswith("/mailFolders"):
            return self._crea_cartella(richiesta)
        if "/mailFolders/inbox/messages" in percorso:
            return self._elenco_filtrato(percorso)
        if "/mailFolders/inbox?" in percorso:
            return httpx.Response(
                200,
                json={
                    "displayName": "Posta in arrivo",
                    "unreadItemCount": sum(
                        1 for m in self.messaggi.values() if m["non_letto"]
                    ),
                },
            )
        if f"/users/{CASELLA}?" in percorso:
            return httpx.Response(
                200, json={"displayName": "Ufficio ordini", "mail": CASELLA}
            )

        return httpx.Response(
            404, json={"error": {"code": "NotFound", "message": percorso}}
        )

    def _voci(self) -> list[dict]:
        return [
            {
                "id": identificativo,
                "isRead": not dati["non_letto"],
                "receivedDateTime": dati["ricevuto"],
            }
            for identificativo, dati in self.messaggi.items()
        ]

    def _delta(self, richiesta: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": self._voci(),
                "@odata.deltaLink": self.gettone_delta,
            },
        )

    def _elenco_filtrato(self, percorso: str) -> httpx.Response:
        return httpx.Response(200, json={"value": self._voci()})

    def _valore(self, percorso: str) -> httpx.Response:
        identificativo = percorso.split("/messages/")[1].split("/$value")[0]
        dati = self.messaggi.get(identificativo)
        if dati is None:
            return httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "no"}}
            )
        return httpx.Response(200, content=dati["mime"])

    def _sposta(self, richiesta: httpx.Request, percorso: str) -> httpx.Response:
        identificativo = percorso.split("/messages/")[1].split("/move")[0]
        destinazione = json.loads(richiesta.content)["destinationId"]
        self.spostati.append((identificativo, destinazione))
        self.messaggi.pop(identificativo, None)
        return httpx.Response(201, json={"id": identificativo})

    def _cerca_cartella(self, percorso: str) -> httpx.Response:
        trovate = [
            {"id": identificativo, "displayName": nome}
            for nome, identificativo in self.cartelle.items()
            if f"eq+%27{nome}%27" in percorso or f"eq '{nome}'" in percorso
        ]
        return httpx.Response(200, json={"value": trovate})

    def _crea_cartella(self, richiesta: httpx.Request) -> httpx.Response:
        nome = json.loads(richiesta.content)["displayName"]
        identificativo = f"cartella-{nome.lower()}"
        self.cartelle[nome] = identificativo
        return httpx.Response(201, json={"id": identificativo, "displayName": nome})

    # --- Aiuti per i test --------------------------------------------------

    def aggiungi(
        self,
        identificativo: str,
        *,
        mime: bytes = b"",
        non_letto: bool = True,
        ricevuto: str = "2026-08-27T09:00:00Z",
    ) -> str:
        self.messaggi[identificativo] = {
            "non_letto": non_letto,
            "ricevuto": ricevuto,
            "mime": mime or eml(identificativo=identificativo_di_prova()),
        }
        return identificativo

    def quante(self, pezzo: str) -> int:
        """Quante chiamate contengono quel pezzo di indirizzo."""
        return sum(1 for _, indirizzo in self.chiamate if pezzo in indirizzo)


def errore_json(codice: int, code: str = "ErrorAccessDenied", message: str = "no"):
    """Una risposta di errore come la scrive Graph."""
    return httpx.Response(codice, json={"error": {"code": code, "message": message}})


@pytest.fixture
def segnalibro(tmp_path) -> SegnalibroGraph:
    """Un segnalibro che scrive in una cartella temporanea, non in storage/."""
    return SegnalibroGraph(tmp_path / "posta_graph.json")


# ===========================================================================
#  1. LA FONTE: LEGGERE, SCARICARE, SPOSTARE
# ===========================================================================


def test_la_fonte_graph_rispetta_l_interfaccia():
    """La stessa verifica che nella sessione 10 si e' fatta su FonteLocale.

    E' il test piu' importante del file, perche' e' quello che dice che il
    motore non andava toccato: se questo passa, `emails.acquisisci()` sa gia'
    lavorare su una casella di Microsoft 365 (D-076).
    """
    assert isinstance(FintaCasella().fonte(), FonteEmail)


def test_si_leggono_solo_i_messaggi_non_letti(segnalibro):
    casella = FintaCasella()
    casella.aggiungi("uno")
    casella.aggiungi("due")
    casella.aggiungi("gia-letto", non_letto=False)

    trovati = casella.fonte(segnalibro).elenca_nuovi_messaggi()

    assert trovati == ["uno", "due"]


def test_il_messaggio_si_scarica_per_intero_dall_indirizzo_del_mime(segnalibro):
    """Il MIME integrale, non il messaggio ricomposto da Graph.

    E' quello che permette di conservare la corrispondenza come fatto avvenuto
    - intestazioni originali comprese - ed e' anche quello che il motore sa
    gia' leggere, perche' e' identico al contenuto di un file `.eml`.
    """
    casella = FintaCasella()
    dati = eml(oggetto="Con le lettere accentate: perche' pero'")
    casella.aggiungi("uno", mime=dati)

    fonte = casella.fonte(segnalibro)

    assert fonte.scarica_messaggio_grezzo("uno") == dati
    assert casella.quante("/messages/uno/$value") == 1


def test_un_messaggio_sparito_dalla_casella_si_salta_senza_fermare_il_giro(
    segnalibro,
):
    """Qualcuno lo ha spostato a mano mentre Aurora stava leggendo.

    Non e' un guasto: e' `MessaggioNonTrovato`, che il motore gia' cattura per
    saltare quel messaggio e proseguire con gli altri.
    """
    fonte = FintaCasella().fonte(segnalibro)

    with pytest.raises(MessaggioNonTrovato):
        fonte.scarica_messaggio_grezzo("uno-che-non-c-e")


def test_le_due_cartelle_si_creano_se_non_ci_sono(segnalibro):
    casella = FintaCasella()
    casella.aggiungi("uno")
    casella.aggiungi("due")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    fonte.marca_elaborato("uno")
    fonte.sposta_in_quarantena("due")

    assert casella.cartelle == {
        "Elaborate": "cartella-elaborate",
        "Quarantena": "cartella-quarantena",
    }
    assert casella.spostati == [
        ("uno", "cartella-elaborate"),
        ("due", "cartella-quarantena"),
    ]


def test_una_cartella_che_c_e_gia_non_si_ricrea(segnalibro):
    """Si cerca, si trova, e non si chiede piu' niente.

    L'identificativo si tiene da parte: un giro con cinquecento messaggi
    farebbe altrimenti cinquecento ricerche della stessa cartella.
    """
    casella = FintaCasella(cartelle={"Elaborate": "cartella-esistente"})
    casella.aggiungi("uno")
    casella.aggiungi("due")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    fonte.marca_elaborato("uno")
    fonte.marca_elaborato("due")

    assert casella.quante("/mailFolders?") == 1
    assert casella.quante("POST") == 0
    assert [destinazione for _, destinazione in casella.spostati] == [
        "cartella-esistente",
        "cartella-esistente",
    ]


def test_dalla_casella_non_si_cancella_mai_niente(segnalibro):
    """Regola 5 di CLAUDE.md, verificata invece che raccomandata."""
    casella = FintaCasella()
    casella.aggiungi("uno")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()
    fonte.scarica_messaggio_grezzo("uno")
    fonte.marca_elaborato("uno")

    assert not any(metodo == "DELETE" for metodo, _ in casella.chiamate)


# ===========================================================================
#  2. IL SEGNALIBRO: DOVE ERAVAMO ARRIVATI
# ===========================================================================


def test_il_segno_si_salva_solo_quando_tutti_i_messaggi_sono_a_posto(segnalibro):
    """La riga che rende ripetibile un giro su una casella.

    Finche' un messaggio elencato non e' stato spostato, il gettone delta non
    avanza: al controllo successivo Microsoft riproporra' la stessa finestra,
    i messaggi gia' archiviati verranno riconosciuti dal loro Message-ID e
    quello rimasto indietro verra' riprovato.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    casella.aggiungi("due")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    fonte.marca_elaborato("uno")
    assert segnalibro.leggi() == {}, "un messaggio e' ancora da sistemare"

    fonte.marca_elaborato("due")
    assert segnalibro.leggi()["delta_link"] == casella.gettone_delta


def test_una_casella_senza_niente_da_leggere_salva_comunque_il_segno(segnalibro):
    """Un giro senza niente da fare e' un giro finito.

    Senza questa regola una casella tranquilla non registrerebbe mai il proprio
    segno - lo salva lo spostamento dell'ultimo messaggio, e di messaggi non ce
    n'e' stato nessuno - e ogni controllo ripartirebbe dall'inizio della
    cartella.
    """
    casella = FintaCasella()

    assert casella.fonte(segnalibro).elenca_nuovi_messaggi() == []
    assert segnalibro.leggi()["delta_link"] == casella.gettone_delta


def test_uno_spostamento_fallito_non_fa_avanzare_il_segno(segnalibro):
    """Se il messaggio resta nella posta in arrivo, il segno resta indietro.

    Altrimenti quel messaggio non comparirebbe mai piu' fra le differenze, e
    resterebbe li' non letto per sempre.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    casella.copione = [errore_json(500, "ServiceUnavailable")]
    fonte.marca_elaborato("uno")

    assert segnalibro.leggi() == {}


def test_lo_spostamento_che_fallisce_non_solleva(segnalibro):
    """Come FonteLocale: a quel punto il messaggio e' gia' nel database.

    Un'eccezione qui fermerebbe l'archiviazione di tutti i messaggi che
    vengono dopo, ed e' esattamente il giorno in cui l'acquisizione serve di
    piu'.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    casella.copione = [errore_json(403, "ErrorAccessDenied")]
    fonte.marca_elaborato("uno")  # non deve sollevare


def test_senza_il_permesso_di_spostare_il_segno_avanza_lo_stesso(segnalibro):
    """Con `Mail.Read` e basta, lo spostamento riceve 403 e lo ricevera' sempre.

    Tenere il segno indietro vorrebbe dire riscaricare tutta la posta in arrivo
    a ogni controllo per riprovare una cosa che non riuscira' mai. Il messaggio
    e' gia' archiviato: il segno avanza, e nel registro resta scritto quale
    permesso manca.
    """
    casella = FintaCasella(cartelle={"Elaborate": "cartella-elaborate"})
    casella.aggiungi("uno")
    fonte = casella.fonte(segnalibro)
    fonte.elenca_nuovi_messaggi()

    casella.copione = [errore_json(403, "ErrorAccessDenied", "no")]
    fonte.marca_elaborato("uno")

    assert segnalibro.leggi()["delta_link"] == casella.gettone_delta


def test_il_segno_scaduto_fa_rileggere_la_cartella_da_capo(segnalibro):
    """Il 410 di Microsoft vuol dire "quel gettone non vale piu'"."""
    casella = FintaCasella()
    casella.aggiungi("uno")
    segnalibro.scrivi(delta_link="https://graph.microsoft.com/v1.0/delta-vecchio")

    casella.copione = [errore_json(410, "resyncRequired", "token expired")]
    trovati = casella.fonte(segnalibro).elenca_nuovi_messaggi()

    assert trovati == ["uno"]


def test_se_la_delta_non_funziona_si_passa_al_filtro_sulla_data(segnalibro):
    """La strada di riserva chiesta dal punto 3 della sessione.

    Si riconosce dall'indirizzo: niente "delta", e dentro il filtro c'e' la
    data dell'ultimo istante elaborato.
    """
    casella = FintaCasella()
    casella.aggiungi("uno", ricevuto="2026-08-27T09:30:00Z")
    segnalibro.scrivi(ultimo_istante="2026-08-01T00:00:00Z")

    casella.copione = [errore_json(400, "BadRequest", "delta non supportata")]
    fonte = casella.fonte(segnalibro)
    trovati = fonte.elenca_nuovi_messaggi()

    assert trovati == ["uno"]
    filtrate = [
        indirizzo
        for _, indirizzo in casella.chiamate
        if "%24filter" in indirizzo or "$filter" in indirizzo
    ]
    assert filtrate, "non e' stata usata la strada del filtro sulla data"
    assert "isRead+eq+false" in filtrate[0]
    assert "2026-08-01T00%3A00%3A00Z" in filtrate[0]

    fonte.marca_elaborato("uno")
    assert segnalibro.leggi()["ultimo_istante"] == "2026-08-27T09:30:00Z"


def test_un_segnalibro_illeggibile_non_ferma_niente(tmp_path):
    """Un file rotto vale come nessun file: si riparte dall'inizio.

    E' la stessa regola dei file di config/ (D-039): il programma continua a
    funzionare anche quando un file di contorno e' scritto male.
    """
    percorso = tmp_path / "posta_graph.json"
    percorso.write_text("{ questo non e' JSON", encoding="utf-8")
    segno = SegnalibroGraph(percorso)

    assert segno.leggi() == {}

    casella = FintaCasella()
    casella.aggiungi("uno")
    assert casella.fonte(segno).elenca_nuovi_messaggi() == ["uno"]


# ===========================================================================
#  3. I QUATTRO MODI DI ANDARE STORTO
# ===========================================================================


def test_la_limitazione_di_frequenza_rispetta_l_intestazione(segnalibro):
    """Il 429 con Retry-After: si aspetta quello che ha detto Microsoft.

    Non un secondo scelto da noi: e' il servizio a sapere quanto e' carico.
    Il tempo non si aspetta davvero - `dormi` e' sostituito - ma si verifica
    che sia stato chiesto di aspettare proprio quei secondi.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    attese: list[float] = []

    casella.copione = [httpx.Response(429, headers={"Retry-After": "7"})]
    fonte = casella.fonte(segnalibro, dormi=attese.append)

    assert fonte.elenca_nuovi_messaggi() == ["uno"]
    assert attese == [7.0]


def test_senza_retry_after_l_attesa_raddoppia(segnalibro):
    """Sul 503 Microsoft spesso non dice quanto: si raddoppia a ogni tentativo.

    E' la regola normale per non peggiorare una coda gia' lunga presentandosi
    tutti insieme.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    attese: list[float] = []

    casella.copione = [httpx.Response(503), httpx.Response(503)]
    fonte = casella.fonte(segnalibro, dormi=attese.append)
    fonte.elenca_nuovi_messaggi()

    assert attese == [2.0, 4.0]


def test_un_attesa_troppo_lunga_non_blocca_chi_ha_premuto_il_pulsante(segnalibro):
    """Un quarto d'ora davanti a una pagina bianca non e' aspettare.

    Sopra i due minuti si rinuncia e si dice fra quanto riprovare: il controllo
    successivo ci riprovera' da solo.
    """
    casella = FintaCasella()
    casella.copione = [httpx.Response(429, headers={"Retry-After": "900"})]

    with pytest.raises(FonteNonDisponibile) as problema:
        casella.fonte(segnalibro).elenca_nuovi_messaggi()

    assert "15 minuti" in str(problema.value)


def test_il_gettone_scaduto_si_rinnova_e_la_chiamata_si_rifa(segnalibro):
    """Il 401: se ne chiede uno nuovo e si rifa' la stessa richiesta.

    E' l'unico caso in cui riprovare risolve davvero, ed e' anche quello che
    capita per davvero: un gettone dura un'ora e i controlli durano dei mesi.
    """
    casella = FintaCasella()
    casella.aggiungi("uno")
    gettoni: list[str] = []

    def fornitore() -> tuple[str, int]:
        gettoni.append(f"gettone-{len(gettoni) + 1}")
        return gettoni[-1], 3600

    casella.copione = [errore_json(401, "InvalidAuthenticationToken", "expired")]
    fonte = casella.fonte(segnalibro, fornitore_gettone=fornitore)

    assert fonte.elenca_nuovi_messaggi() == ["uno"]
    assert gettoni == ["gettone-1", "gettone-2"], (
        "il gettone doveva essere richiesto una seconda volta"
    )


def test_il_gettone_si_rinnova_da_solo_prima_di_scadere():
    """Con un gettone che sta per scadere se ne chiede un altro senza aspettare
    il 401: cinque minuti di margine coprono un giro di acquisizione lungo."""
    quanti = []

    def fornitore() -> tuple[str, int]:
        quanti.append(1)
        # Vale un minuto: meno del margine di rinnovo.
        return "gettone", 60

    cliente = ClienteGraph(CREDENZIALI, fornitore_gettone=fornitore)
    cliente.gettone()
    cliente.gettone()

    assert len(quanti) == 2

    lungo = ClienteGraph(CREDENZIALI, fornitore_gettone=lambda: ("g", 3600))
    assert lungo.gettone() == lungo.gettone() == "g"


def test_la_rete_assente_diventa_una_frase_in_italiano(segnalibro):
    """Nessun errore tecnico grezzo arriva a chi guarda la pagina."""

    def cade(richiesta: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    cliente = ClienteGraph(
        CREDENZIALI,
        trasporto=httpx.MockTransport(cade),
        fornitore_gettone=lambda: ("g", 3600),
    )

    with pytest.raises(FonteNonDisponibile) as problema:
        FonteGraph(cliente, segnalibro=segnalibro).elenca_nuovi_messaggi()

    frase = str(problema.value)
    assert "Non si riesce a raggiungere Microsoft 365" in frase
    assert "getaddrinfo" not in frase, "un errore tecnico e' arrivato all'utente"


def test_il_permesso_mancante_dice_che_cosa_chiedere(segnalibro):
    casella = FintaCasella()
    casella.copione = [
        errore_json(403, "ErrorAccessDenied", "Access is denied. Check credentials.")
    ]

    with pytest.raises(FonteNonDisponibile) as problema:
        casella.fonte(segnalibro).elenca_nuovi_messaggi()

    assert "Mail.Read" in str(problema.value)


def test_la_regola_che_limita_la_casella_si_riconosce_dal_permesso_mancante(
    segnalibro,
):
    """Due 403 diversi: uno si risolve dando un permesso, l'altro correggendo
    la Application Access Policy. Dirli allo stesso modo manderebbe l'ufficio
    informatico a guardare la cosa sbagliata."""
    casella = FintaCasella()
    casella.copione = [
        errore_json(
            403,
            "ErrorAccessDenied",
            "Access to OData is disabled. ApplicationAccessPolicy",
        )
    ]

    with pytest.raises(FonteNonDisponibile) as problema:
        casella.fonte(segnalibro).elenca_nuovi_messaggi()

    assert "Application Access Policy" in str(problema.value)


# ===========================================================================
#  4. IL MOTORE, CHE NON E' STATO TOCCATO
# ===========================================================================


def test_il_motore_archivia_i_messaggi_presi_dalla_casella(db_session, segnalibro):
    """Il giro completo con la fonte Graph al posto di quella locale.

    E' la prova che l'astrazione della sessione 10 era quella giusta:
    `emails.acquisisci()` e' la stessa funzione di prima, riga per riga.
    """
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    casella = FintaCasella()
    casella.aggiungi(
        "attribuito",
        mime=eml(
            identificativo=identificativo_di_prova("graph-uno"),
            oggetto=f"[{prodotto.code}][V1][SPECS] dalla casella",
        ),
    )
    casella.aggiungi(
        "in-quarantena",
        mime=eml(
            identificativo=identificativo_di_prova("graph-due"),
            oggetto="Nessun codice qui dentro",
        ),
    )

    riepilogo = emails.acquisisci(db_session, casella.fonte(segnalibro))

    assert riepilogo.letti == 2
    assert riepilogo.archiviati == 1
    assert riepilogo.in_quarantena == 1
    assert casella.spostati == [
        ("attribuito", "cartella-elaborate"),
        ("in-quarantena", "cartella-quarantena"),
    ]


def test_rileggere_la_stessa_casella_non_duplica_niente(db_session, segnalibro):
    """La ripetibilita' vale anche su Graph, e per lo stesso motivo di sempre:
    il Message-ID e' unico (D-074). Qui il messaggio resta nella posta in
    arrivo - come se lo spostamento non fosse riuscito - e si rilegge."""
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    identificativo = identificativo_di_prova("graph-ripetuto")
    dati = eml(
        identificativo=identificativo,
        oggetto=f"[{prodotto.code}][V1][SPECS] due volte",
    )

    for _ in range(2):
        casella = FintaCasella()
        casella.aggiungi("uno", mime=dati)
        riepilogo = emails.acquisisci(db_session, casella.fonte(segnalibro))

    assert riepilogo.letti == 1
    assert riepilogo.archiviati == 0
    assert riepilogo.gia_presenti == 1

    quanti = db_session.scalars(
        select(EmailMessage).where(
            EmailMessage.internet_message_id == identificativo.strip("<>")
        )
    ).all()
    assert len(quanti) == 1, "il secondo giro ha creato un doppione"


def test_il_messaggio_gia_archiviato_finisce_comunque_nella_cartella_giusta(
    db_session, segnalibro
):
    """Se il primo giro non era riuscito a spostarlo, lo sposta il secondo.

    E' la stessa proprieta' della fonte locale: la posta in arrivo si svuota
    comunque, anche se il programma si e' spento a meta' del giro precedente.
    """
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    dati = eml(
        identificativo=identificativo_di_prova("graph-recupero"),
        oggetto=f"[{prodotto.code}][V1][SPECS] recuperato",
    )

    primo = FintaCasella()
    primo.aggiungi("uno", mime=dati)
    primo.copione = [errore_json(500, "ServiceUnavailable")]
    emails.acquisisci(db_session, primo.fonte(segnalibro))

    secondo = FintaCasella()
    secondo.aggiungi("uno", mime=dati)
    riepilogo = emails.acquisisci(db_session, secondo.fonte(segnalibro))

    assert riepilogo.gia_presenti == 1
    assert secondo.spostati == [("uno", "cartella-elaborate")]


# ===========================================================================
#  5. LA PIANIFICAZIONE
# ===========================================================================


def test_due_controlli_non_si_sovrappongono(db_session):
    """Il blocco chiesto dal punto 7 della sessione.

    Il primo controllo viene simulato tenendo il blocco da un altro filo di
    esecuzione: il secondo non si mette in coda, risponde che ce n'e' gia' uno
    in corso e se ne va.
    """
    preso = threading.Event()
    lascia = threading.Event()

    def occupa():
        with mail_scheduler._blocco:
            preso.set()
            lascia.wait(timeout=5)

    filo = threading.Thread(target=occupa)
    filo.start()
    try:
        assert preso.wait(timeout=5)
        esito = mail_scheduler.controlla(db_session)
    finally:
        lascia.set()
        filo.join(timeout=5)

    assert esito.sovrapposto is True
    assert esito.riuscito is False
    assert "gia' in corso" in esito.messaggio


def test_il_controllo_finito_lascia_il_blocco_libero(db_session):
    """Un controllo andato storto non deve lasciare il blocco chiuso.

    Se lo lasciasse, la posta smetterebbe di essere letta fino al riavvio del
    server: e' il modo peggiore di rompersi, perche' non si vede.
    """
    mail_scheduler.controlla(db_session)

    assert mail_scheduler.in_corso() is False


def test_il_controllo_non_solleva_mai_e_racconta_com_e_andato(
    db_session, monkeypatch
):
    """Qualunque cosa vada storta esce come un esito con una frase in italiano.

    E' quello che permette al lavoro pianificato di riprovare al turno dopo
    invece di morire e non ripartire piu'.
    """

    def fonte_rotta():
        raise FonteNonDisponibile("La casella non risponde: prova di un test.")

    monkeypatch.setattr(
        mail_scheduler.mail_source, "fonte_configurata", fonte_rotta
    )

    esito = mail_scheduler.controlla(db_session)

    assert esito.riuscito is False
    assert esito.variante == "errore"
    assert esito.messaggio == "La casella non risponde: prova di un test."


def test_l_orologio_non_parte_con_la_cartella_di_file():
    """Con MAIL_PROVIDER=locale i file li mette una persona.

    Che puo' premere "Controlla adesso" subito dopo, invece di aspettare
    cinque minuti che scatti un orologio.
    """
    assert settings.MAIL_PROVIDER == "locale"
    assert mail_scheduler.avvia() is False
    assert mail_scheduler.acceso() is False


# ===========================================================================
#  6. LA PAGINA DI CONFIGURAZIONE
# ===========================================================================


@pytest.fixture
def configurazione_ripristinata():
    """Rimette i parametri della posta com'erano, qualunque cosa faccia il test.

    Sono l'unico stato di Aurora che vive fuori dalla transazione del database:
    senza questo, un test che salva la configurazione la lascerebbe cambiata
    per tutti quelli che vengono dopo.
    """
    prima = {
        nome: getattr(settings, nome)
        for nome in (
            "MAIL_PROVIDER",
            "MAIL_TENANT_ID",
            "MAIL_CLIENT_ID",
            "MAIL_CLIENT_SECRET",
            "MAIL_MAILBOX_ADDRESS",
            "MAIL_SECRET_EXPIRES_ON",
            "MAIL_POLL_MINUTES",
            "MAIL_SCHEDULER_ENABLED",
        )
    }
    yield
    for nome, valore in prima.items():
        setattr(settings, nome, valore)


@pytest.fixture
def env_finto(tmp_path, monkeypatch):
    """Fa scrivere la configurazione in un file temporaneo, non nel .env vero."""
    percorso = tmp_path / ".env"
    percorso.write_text(
        "# Configurazione di prova\nAPP_NAME=Aurora\nMAIL_PROVIDER=locale\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(env_file, "ENV_FILE", percorso)
    return percorso


def valori_di_prova(**cambiati) -> dict[str, str]:
    """I valori del modulo, tutti compilati, con quello che il test cambia."""
    valori = {
        "MAIL_PROVIDER": "graph",
        "MAIL_TENANT_ID": CREDENZIALI.tenant_id,
        "MAIL_CLIENT_ID": CREDENZIALI.client_id,
        "MAIL_CLIENT_SECRET": CREDENZIALI.client_secret,
        "MAIL_MAILBOX_ADDRESS": CASELLA,
        "MAIL_SECRET_EXPIRES_ON": "",
        "MAIL_POLL_MINUTES": "5",
        "MAIL_SCHEDULER_ENABLED": "si",
    }
    valori.update(cambiati)
    return valori


def cliente_che_risponde(risposte, monkeypatch, *, gettone=None):
    """Sostituisce il collegamento vero con uno che risponde quello che si vuole."""
    casella = FintaCasella()
    casella.copione = list(risposte)

    def costruttore(credenziali):
        return casella.cliente(
            fornitore_gettone=gettone or (lambda: ("gettone-finto", 3600))
        )

    monkeypatch.setattr(mail_config, "nuovo_cliente", costruttore)
    return casella


@pytest.mark.parametrize(
    "nome, valore, pezzo_atteso",
    [
        ("MAIL_TENANT_ID", "non-un-identificativo", "identificativo lungo"),
        ("MAIL_CLIENT_ID", "12345", "identificativo lungo"),
        ("MAIL_MAILBOX_ADDRESS", "ufficio ordini", "indirizzo di posta completo"),
        ("MAIL_SECRET_EXPIRES_ON", "15/03/2027", "anno davanti"),
        ("MAIL_POLL_MINUTES", "0", "piu' frequente di un minuto"),
        ("MAIL_POLL_MINUTES", "tre", "numero di minuti"),
    ],
)
def test_un_valore_scritto_storto_lo_dice_subito(nome, valore, pezzo_atteso):
    """I controlli che non hanno bisogno di Microsoft.

    Servono a due cose: non far partire una chiamata che fallira' di sicuro, e
    dare una risposta immediata a chi ha copiato il campo sbagliato.
    """
    problema = mail_config.verifica_forma(nome, valore)

    assert problema is not None
    assert pezzo_atteso in problema


def test_il_tenant_si_puo_scrivere_anche_come_dominio():
    assert mail_config.verifica_forma("MAIL_TENANT_ID", "azienda.it") is None


@pytest.mark.parametrize(
    "descrizione_aad, parametro_atteso, pezzo_atteso",
    [
        ("AADSTS90002: Tenant not found", "MAIL_TENANT_ID", "organizzazione"),
        (
            "AADSTS700016: Application not found in the directory",
            "MAIL_CLIENT_ID",
            "applicazione",
        ),
        (
            "AADSTS7000215: Invalid client secret provided",
            "MAIL_CLIENT_SECRET",
            "segreto",
        ),
        (
            "AADSTS7000222: The provided client secret keys are expired",
            "MAIL_CLIENT_SECRET",
            "scaduto",
        ),
    ],
)
def test_la_pagina_dice_quale_parametro_e_sbagliato(
    descrizione_aad, parametro_atteso, pezzo_atteso, monkeypatch
):
    """Il criterio di accettazione numero 2 della sessione.

    Microsoft, per fortuna, ci mette del suo: i codici AADSTS dicono
    esattamente quale delle tre credenziali ha rifiutato. Quello che fa Aurora
    e' tradurli in una frase e accendere il campo giusto.
    """

    def gettone_rifiutato():
        from app.services.graph_api import spiega_errore_aad

        parametro, frase = spiega_errore_aad(descrizione_aad)
        raise ErroreGraph(frase, tecnico=descrizione_aad, parametro=parametro)

    cliente_che_risponde([], monkeypatch, gettone=gettone_rifiutato)

    esito = mail_config.prova_parametro("MAIL_TENANT_ID", valori_di_prova())

    assert esito.riuscita is False
    assert esito.parametro == parametro_atteso
    assert pezzo_atteso in esito.messaggio.lower()
    assert "AADSTS" not in esito.messaggio


def test_una_casella_inesistente_lo_dice_sul_campo_della_casella(monkeypatch):
    cliente_che_risponde(
        [errore_json(404, "ErrorInvalidUser", "user not found")], monkeypatch
    )

    esito = mail_config.prova_parametro("MAIL_MAILBOX_ADDRESS", valori_di_prova())

    assert esito.riuscita is False
    assert esito.parametro == "MAIL_MAILBOX_ADDRESS"
    assert "casella indicata non esiste" in esito.messaggio


def test_la_verifica_riuscita_dice_quanti_messaggi_ci_sono(monkeypatch):
    casella = cliente_che_risponde([], monkeypatch)
    casella.aggiungi("uno")
    casella.aggiungi("due")

    esito = mail_config.prova_completa(valori_di_prova())

    assert esito.riuscita is True
    assert "Ufficio ordini" in esito.messaggio
    assert "2 messaggi" in esito.messaggio


def test_la_verifica_dice_che_cosa_manca_ancora():
    """Meta' foglio dall'ufficio informatico: si salva quello che c'e'.

    E chi preme VERIFICA legge che cosa manca, invece di leggere che non
    funziona.
    """
    esito = mail_config.prova_parametro(
        "MAIL_MAILBOX_ADDRESS", valori_di_prova(MAIL_CLIENT_SECRET="")
    )

    assert esito.riuscita is False
    assert "segreto dell'applicazione" in esito.messaggio


def test_il_segreto_lasciato_vuoto_conferma_quello_che_c_e(
    configurazione_ripristinata,
):
    """Un campo vuoto vuol dire "lascia quello di prima", non "cancellalo"."""
    settings.MAIL_CLIENT_SECRET = "quello-di-prima"

    credenziali = mail_config.credenziali_da(valori_di_prova(MAIL_CLIENT_SECRET=""))

    assert credenziali.client_secret == "quello-di-prima"


# --- Le pagine --------------------------------------------------------------


def test_la_pagina_di_configurazione_e_riservata_al_creatore(client, db_session):
    crea_utente(db_session, username="prova.posta.normale")
    entra(client, "prova.posta.normale", PASSWORD_DI_PROVA)

    assert client.get("/posta/configurazione").status_code == 403


def test_la_pagina_mostra_i_campi_e_la_diagnostica(client, db_session):
    crea_utente(
        db_session, username="prova.posta.capo", ruolo=GlobalRole.CREATORE
    )
    entra(client, "prova.posta.capo", PASSWORD_DI_PROVA)

    pagina = client.get("/posta/configurazione")

    assert pagina.status_code == 200
    for parametro in mail_config.PARAMETRI:
        assert f'name="{parametro.nome}"' in pagina.text
    assert "Come sta il collegamento" in pagina.text
    assert settings.MAIL_CLIENT_SECRET not in pagina.text or not settings.MAIL_CLIENT_SECRET


def test_il_salvataggio_scrive_il_file_e_lascia_una_riga_nel_registro(
    client, db_session, env_finto, configurazione_ripristinata
):
    """Il punto 9: la configurazione si completa senza toccare file di testo.

    E il fatto resta scritto nel registro come qualunque altra modifica: chi,
    quando, quali parametri. Il valore del segreto no.
    """
    crea_utente(
        db_session, username="prova.posta.salva", ruolo=GlobalRole.CREATORE
    )
    entra(client, "prova.posta.salva", PASSWORD_DI_PROVA)

    dati = valori_di_prova(MAIL_MAILBOX_ADDRESS=f"prova-{uuid.uuid4().hex[:6]}@a.test")
    dati["csrf"] = gettone_csrf(client, "/posta/configurazione")

    risposta = client.post(
        "/posta/configurazione", data=dati, follow_redirects=False
    )

    assert risposta.status_code == 303

    scritto = env_finto.read_text(encoding="utf-8")
    assert "# Configurazione di prova" in scritto, "i commenti sono stati persi"
    assert f"MAIL_MAILBOX_ADDRESS={dati['MAIL_MAILBOX_ADDRESS']}" in scritto
    assert settings.MAIL_MAILBOX_ADDRESS == dati["MAIL_MAILBOX_ADDRESS"]

    voce = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.action == mail_config.ACTION_MAIL_CONFIG_UPDATED)
        .order_by(AuditLog.seq.desc())
    ).first()
    assert voce is not None
    assert CREDENZIALI.client_secret not in str(voce.new_value)
    assert voce.new_value["MAIL_CLIENT_SECRET"] == mail_config.SEGRETO_NASCOSTO


def test_un_valore_storto_non_viene_salvato_e_la_pagina_lo_dice(
    client, db_session, env_finto, configurazione_ripristinata
):
    crea_utente(
        db_session, username="prova.posta.storto", ruolo=GlobalRole.CREATORE
    )
    entra(client, "prova.posta.storto", PASSWORD_DI_PROVA)

    dati = valori_di_prova(MAIL_TENANT_ID="questo-non-va-bene")
    dati["csrf"] = gettone_csrf(client, "/posta/configurazione")

    risposta = client.post("/posta/configurazione", data=dati)

    assert risposta.status_code == 400
    assert "identificativo lungo" in risposta.text
    assert "MAIL_TENANT_ID=questo-non-va-bene" not in env_finto.read_text(
        encoding="utf-8"
    )


def test_la_verifica_risponde_anche_senza_javascript(
    client, db_session, monkeypatch
):
    """Senza HTMX la stessa rotta risponde con la pagina intera.

    E' D-036: quello che deve funzionare per forza non dipende da uno script,
    e una pagina di configurazione che si puo' usare solo con JavaScript e'
    inutilizzabile proprio il giorno in cui il collegamento non va.
    """
    crea_utente(db_session, username="prova.posta.js", ruolo=GlobalRole.CREATORE)
    entra(client, "prova.posta.js", PASSWORD_DI_PROVA)

    cliente_che_risponde(
        [errore_json(404, "ErrorInvalidUser", "no")], monkeypatch
    )

    dati = valori_di_prova()
    dati["parametro"] = "MAIL_MAILBOX_ADDRESS"
    dati["csrf"] = gettone_csrf(client, "/posta/configurazione")

    intera = client.post("/posta/configurazione/verifica", data=dati)
    assert "<html" in intera.text
    assert "casella indicata non esiste" in intera.text

    dati["csrf"] = gettone_csrf(client, "/posta/configurazione")
    cliente_che_risponde([errore_json(404, "ErrorInvalidUser", "no")], monkeypatch)
    frammento = client.post(
        "/posta/configurazione/verifica",
        data=dati,
        headers={"HX-Request": "true"},
    )
    assert "<html" not in frammento.text
    assert 'id="esito-verifica"' in frammento.text


# ===========================================================================
#  7. LA SCADENZA DEL SEGRETO
# ===========================================================================


@pytest.mark.parametrize(
    "fra_quanti_giorni, variante_attesa, da_mostrare",
    [
        (90, "nessuna", False),
        (31, "nessuna", False),
        (30, "informazione", True),
        (20, "informazione", True),
        (14, "attenzione", True),
        (8, "attenzione", True),
        (7, "errore", True),
        (1, "errore", True),
        (0, "errore", True),
        (-3, "errore", True),
    ],
)
def test_la_scadenza_del_segreto_si_segnala_con_evidenza_crescente(
    fra_quanti_giorni, variante_attesa, da_mostrare, configurazione_ripristinata
):
    """Il punto 8: da trenta giorni prima, e sempre piu' forte.

    La soglia non e' un dettaglio grafico: quando il segreto scade la posta
    smette di arrivare e non c'e' nessun messaggio che lo dica. Trenta giorni
    sono il tempo che serve all'ufficio informatico per prepararne un altro.
    """
    oggi = date(2026, 8, 27)
    settings.MAIL_SECRET_EXPIRES_ON = (
        oggi + timedelta(days=fra_quanti_giorni)
    ).isoformat()

    scadenza = mail_config.scadenza_segreto(oggi=oggi)

    assert scadenza is not None
    assert scadenza.variante == variante_attesa
    assert scadenza.da_mostrare is da_mostrare


def test_un_segreto_scaduto_lo_dice_a_chiare_lettere(configurazione_ripristinata):
    settings.MAIL_SECRET_EXPIRES_ON = "2026-08-01"

    scadenza = mail_config.scadenza_segreto(oggi=date(2026, 8, 27))

    assert scadenza is not None
    assert scadenza.scaduto is True
    assert "e' scaduto il 01/08/2026" in scadenza.messaggio


def test_la_diagnostica_segnala_la_scadenza_vicina(configurazione_ripristinata):
    settings.MAIL_PROVIDER = "graph"
    settings.MAIL_TENANT_ID = CREDENZIALI.tenant_id
    settings.MAIL_CLIENT_ID = CREDENZIALI.client_id
    settings.MAIL_CLIENT_SECRET = CREDENZIALI.client_secret
    settings.MAIL_MAILBOX_ADDRESS = CASELLA
    settings.MAIL_SECRET_EXPIRES_ON = (
        date(2026, 8, 27) + timedelta(days=5)
    ).isoformat()

    voci = {v.etichetta: v for v in mail_config.diagnostica(oggi=date(2026, 8, 27))}

    assert voci["Parametri"].variante == "successo"
    assert voci["Scadenza del segreto"].variante == "errore"
    assert "smette di arrivare" in voci["Scadenza del segreto"].nota


def test_la_diagnostica_dice_quali_parametri_mancano(configurazione_ripristinata):
    settings.MAIL_PROVIDER = "graph"
    settings.MAIL_TENANT_ID = ""
    settings.MAIL_CLIENT_ID = ""
    settings.MAIL_CLIENT_SECRET = ""
    settings.MAIL_MAILBOX_ADDRESS = ""

    voci = {v.etichetta: v for v in mail_config.diagnostica()}

    assert voci["Parametri"].variante == "errore"
    assert "identificativo dell'organizzazione" in voci["Parametri"].valore


# ===========================================================================
#  8. IL FILE .env
# ===========================================================================


def test_scrivere_un_parametro_non_tocca_il_resto_del_file(tmp_path):
    """I commenti del .env sono la sola documentazione che chi amministra il
    server abbia sottomano: riscrivere il file da zero li perderebbe."""
    percorso = tmp_path / ".env"
    percorso.write_text(
        "# Il nome del programma\n"
        "APP_NAME=Aurora\n"
        "\n"
        "# Ogni quanto si controlla\n"
        "MAIL_POLL_MINUTES=5\n",
        encoding="utf-8",
    )

    env_file.scrivi_parametri(
        {"MAIL_POLL_MINUTES": "10", "MAIL_TENANT_ID": "azienda.it"},
        percorso=percorso,
    )

    scritto = percorso.read_text(encoding="utf-8")
    assert "# Il nome del programma" in scritto
    assert "APP_NAME=Aurora" in scritto
    assert "MAIL_POLL_MINUTES=10" in scritto
    assert "MAIL_POLL_MINUTES=5" not in scritto
    assert "MAIL_TENANT_ID=azienda.it" in scritto
    assert (tmp_path / ".env.precedente").read_text(encoding="utf-8").count(
        "MAIL_POLL_MINUTES=5"
    ) == 1


def test_un_valore_con_spazi_esce_fra_virgolette(tmp_path):
    percorso = tmp_path / ".env"
    env_file.scrivi_parametri({"APP_NAME": "Aurora di prova"}, percorso=percorso)

    assert 'APP_NAME="Aurora di prova"' in percorso.read_text(encoding="utf-8")


def test_una_riga_commentata_non_viene_scambiata_per_il_parametro(tmp_path):
    """`# MAIL_POLL_MINUTES=5` e' un commento, non un'assegnazione."""
    percorso = tmp_path / ".env"
    percorso.write_text("# MAIL_POLL_MINUTES=5\n", encoding="utf-8")

    env_file.scrivi_parametri({"MAIL_POLL_MINUTES": "9"}, percorso=percorso)

    scritto = percorso.read_text(encoding="utf-8")
    assert "# MAIL_POLL_MINUTES=5" in scritto
    assert "MAIL_POLL_MINUTES=9" in scritto


# ===========================================================================
#  9. NESSUNA REGRESSIONE SULLA FONTE LOCALE
# ===========================================================================


def test_con_il_provider_locale_la_fonte_e_ancora_quella_di_prima():
    """Il primo criterio di accettazione della sessione.

    Con MAIL_PROVIDER=locale non deve essere cambiato niente: gli altri
    ottantuno test della posta girano su questa fonte e devono continuare a
    passare senza modifiche.
    """
    assert settings.MAIL_PROVIDER == "locale"
    assert isinstance(fonte_configurata(), FonteLocale)


def test_con_il_provider_graph_senza_parametri_ci_si_ferma_dicendo_quali(
    configurazione_ripristinata,
):
    """Una fonte che restituisse un elenco vuoto lascerebbe credere che la
    casella sia vuota, che e' il modo peggiore di non funzionare."""
    settings.MAIL_PROVIDER = "graph"
    settings.MAIL_TENANT_ID = ""
    settings.MAIL_CLIENT_ID = ""
    settings.MAIL_CLIENT_SECRET = ""
    settings.MAIL_MAILBOX_ADDRESS = ""

    with pytest.raises(FonteNonDisponibile) as problema:
        fonte_configurata()

    assert "MAIL_TENANT_ID" in str(problema.value)


def test_con_il_provider_graph_configurato_si_ottiene_la_fonte_graph(
    configurazione_ripristinata,
):
    settings.MAIL_PROVIDER = "graph"
    settings.MAIL_TENANT_ID = CREDENZIALI.tenant_id
    settings.MAIL_CLIENT_ID = CREDENZIALI.client_id
    settings.MAIL_CLIENT_SECRET = CREDENZIALI.client_secret
    settings.MAIL_MAILBOX_ADDRESS = CASELLA

    assert isinstance(fonte_configurata(), FonteGraph)
