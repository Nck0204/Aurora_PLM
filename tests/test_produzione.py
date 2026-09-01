"""Le verifiche della messa in esercizio (sessione 13).

Sono le cose che la sessione 13 chiedeva di **verificare**, non di costruire:
esistevano gia' quasi tutte, e quello che mancava e' scritto qui accanto con
la sua correzione.

Un test che verifica una precauzione ha un mestiere diverso da un test che
verifica una funzione: la funzione, se si rompe, qualcuno se ne accorge il
giorno stesso; la precauzione, se sparisce, non se ne accorge nessuno finche'
non serve. Per questo stanno tutte insieme in un file solo, con scritto
accanto che cosa proteggono.

Quello che c'e' dentro, in ordine:

  1. le intestazioni di sicurezza su ogni risposta;
  2. la protezione dei moduli, su tutti i moduli;
  3. il limite di dimensione dei caricamenti;
  4. la limitazione di frequenza sull'accesso;
  5. che nessun dato riservato finisca nei registri o negli indirizzi;
  6. che i messaggi di errore non raccontino niente di tecnico;
  7. che i cookie siano come devono essere in produzione.
"""

import io
import logging
import re
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.main import (
    HSTS,
    INTESTAZIONI_DI_SICUREZZA,
    NascondiSegretiNegliIndirizzi,
)
from app.models import AuditLog, GlobalRole, LoginAttempt, User, UserSession
from app.services import storage
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_utente,
    entra,
    gettone_csrf,
)


def _come_un_browser_vero(client, percorso: str):
    """Apre una pagina ricevendo la risposta anche quando la rotta esplode.

    Il finto browser di Starlette, di partenza, **rilancia** le eccezioni non
    gestite invece di consegnare la risposta: e' quello che serve a quasi tutti
    i test, perche' un errore in un test deve mostrare la riga che l'ha
    causato. Qui pero' si sta verificando proprio la pagina che riceverebbe una
    persona davanti a un guasto, quindi serve l'altro comportamento.

    Non si puo' cambiare l'impostazione dopo aver costruito il finto browser -
    la legge una volta sola, quando si costruisce - quindi se ne apre uno
    nuovo. I cookie si portano dietro da quello di partenza, cosi' la sessione
    aperta con `entra()` continua a valere.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as altro:
        altro.cookies = client.cookies
        return altro.get(percorso, headers={"accept": "text/html"})


# ---------------------------------------------------------------------------
#  1. Le intestazioni di sicurezza
# ---------------------------------------------------------------------------

# Le pagine su cui si controlla: una senza accesso, una dopo l'accesso, una di
# errore, e la rotta di servizio. Le intestazioni devono esserci su tutte e
# quattro, perche' il middleware non guarda che pagina sia.
PAGINE_DA_CONTROLLARE = ("/entra", "/", "/salute", "/una-pagina-che-non-esiste")


@pytest.mark.parametrize("percorso", PAGINE_DA_CONTROLLARE)
def test_ogni_risposta_porta_le_intestazioni_di_sicurezza(client, percorso):
    """Le intestazioni ci sono su qualunque risposta esca, errori compresi.

    Sono un middleware e non una cosa scritta rotta per rotta, per la stessa
    ragione per cui la protezione CSRF e' una dipendenza globale (D-028): una
    rotta a cui mancassero funzionerebbe benissimo, e la mancanza si
    scoprirebbe il giorno in cui qualcuno ne approfitta.
    """
    risposta = client.get(percorso, headers={"accept": "text/html"})

    for nome, valore in INTESTAZIONI_DI_SICUREZZA.items():
        assert risposta.headers.get(nome) == valore, (
            f"{percorso} e' uscita senza l'intestazione {nome}"
        )


def test_la_politica_dei_contenuti_vieta_gli_script_scritti_nelle_pagine(client):
    """script-src resta 'self': nessuno script dentro l'HTML viene eseguito.

    E' la meta' che conta della politica dei contenuti, ed e' scrivibile cosi'
    stretta soltanto perche' la regola 1 di CLAUDE.md dice che Aurora non
    carica niente da fuori. Se un giorno qualcuno aggiungesse `'unsafe-inline'`
    qui, la politica smetterebbe di difendere da quello da cui esiste per
    difendere - e questo test diventerebbe rosso.
    """
    politica = client.get("/entra").headers["Content-Security-Policy"]

    assert "script-src 'self'" in politica
    assert "unsafe-inline" not in politica.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in politica
    assert "form-action 'self'" in politica


def test_nessun_template_contiene_uno_script_scritto_dentro_la_pagina():
    """Nei template non ci sono <script> con dentro del codice.

    Sono quelli che la politica dei contenuti bloccherebbe. Il test legge i
    template invece di guardare una pagina resa, perche' uno script in linea
    puo' comparire in una pagina che nessun test apre - ed e' proprio quella in
    cui si scoprirebbe tardi.

    I `<script src="...">` che tirano un file dal nostro server sono ammessi e
    non contano: e' cosi' che arrivano htmx e aurora.js.
    """
    from app.config import PROJECT_ROOT

    apertura = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
    colpevoli = []

    for percorso in (PROJECT_ROOT / "app" / "templates").rglob("*.html"):
        testo = percorso.read_text(encoding="utf-8")
        # I commenti Jinja ({# ... #}) contengono esempi d'uso, non HTML che
        # arrivi al browser: si tolgono prima di cercare.
        senza_commenti = re.sub(r"\{#.*?#\}", "", testo, flags=re.DOTALL)
        if apertura.search(senza_commenti):
            colpevoli.append(percorso.name)

    assert not colpevoli, (
        "questi template contengono uno script scritto dentro la pagina, che "
        "la politica dei contenuti blocca: "
        + ", ".join(colpevoli)
        + ". Va spostato in app/static/js/aurora.js e agganciato con un "
        "attributo data-qualcosa."
    )


def test_hsts_solo_quando_i_cookie_sono_gia_protetti(client, monkeypatch):
    """Strict-Transport-Security compare solo con COOKIE_SECURE acceso.

    Mandarla su http sarebbe inutile; mandarla da una macchina di prova
    raggiunta per nome sarebbe peggio che inutile, perche' il browser se la
    ricorda per mesi e da quel momento rifiuta di aprire quel nome in http.
    Il legame con COOKIE_SECURE non e' una comodita': e' l'unico parametro che
    dice «qui davanti c'e' https».
    """
    senza = client.get("/entra")
    assert "Strict-Transport-Security" not in senza.headers, (
        "in sviluppo COOKIE_SECURE e' falso: HSTS non deve comparire"
    )

    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    con = client.get("/entra")
    assert con.headers.get("Strict-Transport-Security") == HSTS


# ---------------------------------------------------------------------------
#  2. La protezione dei moduli
# ---------------------------------------------------------------------------


def test_ogni_modulo_dei_template_porta_il_campo_del_gettone():
    """Nessun <form method="post"> senza il campo nascosto csrf.

    La dipendenza globale rifiuterebbe comunque la richiesta con un 400
    (D-028), quindi un modulo dimenticato non e' un buco di sicurezza: e' un
    modulo che non funziona. E' pero' un difetto che si scopre solo quando
    qualcuno preme quel pulsante, e questo test lo scopre prima.
    """
    from app.config import PROJECT_ROOT

    colpevoli = []
    for percorso in (PROJECT_ROOT / "app" / "templates").rglob("*.html"):
        testo = percorso.read_text(encoding="utf-8")
        senza_commenti = re.sub(r"\{#.*?#\}", "", testo, flags=re.DOTALL)

        quanti_moduli = len(
            re.findall(r'<form[^>]*method="post"', senza_commenti, re.IGNORECASE)
        )
        if not quanti_moduli:
            continue

        # Il campo si scrive in due modi, e valgono tutti e due: con il macro
        # `csrf(request)` di components/campi.html, che e' la strada normale,
        # oppure scrivendo l'<input> a mano con `token_csrf(request)` dentro -
        # che e' quello che fa il macro stesso e quello che fanno i due o tre
        # moduli composti dentro un altro componente.
        quanti_gettoni = len(
            re.findall(
                r"\{\{-?\s*csrf\(request\)|token_csrf\(request\)", senza_commenti
            )
        )

        if quanti_gettoni < quanti_moduli:
            colpevoli.append(
                f"{percorso.name} ({quanti_moduli} moduli, "
                f"{quanti_gettoni} gettoni)"
            )

    assert not colpevoli, (
        "questi template hanno un modulo POST senza il campo nascosto csrf: "
        + "; ".join(colpevoli)
    )


def test_un_modulo_senza_gettone_viene_rifiutato_in_italiano(client, db_session):
    """Il rifiuto e' un 400 con una frase che si capisce, non un errore tecnico."""
    crea_utente(db_session, username="prova.csrf.produzione")
    db_session.flush()

    risposta = client.post(
        "/entra",
        data={"username": "prova.csrf.produzione", "password": PASSWORD_DI_PROVA},
        headers={"accept": "text/html"},
    )

    assert risposta.status_code == 400
    testo = contenuto_leggibile(risposta)
    assert "ricarica la pagina" in testo.lower()
    assert "csrf" not in testo.lower(), (
        "il messaggio all'utente non deve nominare il meccanismo"
    )


# ---------------------------------------------------------------------------
#  3. Il limite di dimensione dei caricamenti
# ---------------------------------------------------------------------------


def test_il_limite_del_caricamento_si_verifica_mentre_il_file_arriva(monkeypatch):
    """Un file troppo grande viene fermato **durante** la lettura, non dopo.

    E' la differenza fra un rifiuto e un disco pieno: verificando dopo, un
    file da otto gigabyte finirebbe comunque tutto su disco prima che qualcuno
    dica di no (D-047).

    Il limite si abbassa per il test invece di generare due gigabyte: quello
    che si sta verificando e' che il controllo ci sia e scatti, non quale sia
    il numero. Che il numero venga dalla configurazione lo verifica il test
    qui sotto, che passa dalla rotta.
    """
    limite = 1024
    troppo_grande = io.BytesIO(b"x" * (limite * 4))

    with pytest.raises(storage.FileTroppoGrande) as sollevato:
        storage.deposita(troppo_grande, limite_byte=limite)

    messaggio = str(sollevato.value)
    assert "dimensione massima" in messaggio, (
        "il messaggio e' quello che legge chi carica: deve dire che cosa e' "
        f"successo. Era: {messaggio!r}"
    )


def test_il_file_rifiutato_non_resta_nell_archivio():
    """Il temporaneo del file rifiutato viene tolto: non si accumula niente."""
    prima = len(storage.temporanei_rimasti())

    with pytest.raises(storage.FileTroppoGrande):
        storage.deposita(io.BytesIO(b"y" * 4096), limite_byte=1024)

    assert len(storage.temporanei_rimasti()) == prima, (
        "un caricamento rifiutato non deve lasciare un file a meta' in "
        "storage/tmp"
    )


def test_il_limite_arriva_dalla_configurazione_e_lo_dice_in_italiano(
    client, db_session, monkeypatch
):
    """Dalla rotta di caricamento, il rifiuto e' una frase leggibile.

    E' il limite come lo incontra chi carica: `MAX_UPLOAD_MB` nel file `.env`,
    letto dalla rotta, e un messaggio che dice quant'e' invece di un errore
    tecnico. Chi amministra il server puo' alzarlo o abbassarlo senza toccare
    il programma (regola 8 di CLAUDE.md).
    """
    from tests.conftest import (
        classificazione_di_prova,
        crea_progetto,
        crea_prodotto,
    )

    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)

    nome = f"prova.limite.{uuid.uuid4().hex[:8]}"
    creatore = crea_utente(db_session, username=nome, ruolo=GlobalRole.CREATORE)
    classe = classificazione_di_prova(db_session)
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(db_session, versione, creatore)
    db_session.flush()

    entra(client, nome, PASSWORD_DI_PROVA)

    risposta = client.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto.id),
            "titolo": "Troppo grande",
            "tipo": "Altro",
            "classificazione": str(classe.id),
            "csrf": gettone_csrf(client, f"/documenti/nuovo?progetto={progetto.id}"),
        },
        files={
            "file": (
                "grande.bin",
                io.BytesIO(b"z" * (2 * 1024 * 1024)),
                "application/octet-stream",
            )
        },
        follow_redirects=False,
    )

    assert risposta.status_code == 400
    testo = contenuto_leggibile(risposta)
    assert "1 MB" in testo or "1,0 MB" in testo, (
        "il rifiuto deve dire quant'e' il limite, e il limite viene da "
        f"MAX_UPLOAD_MB. Pagina: {testo[:400]}"
    )


# ---------------------------------------------------------------------------
#  4. La limitazione di frequenza sull'accesso
# ---------------------------------------------------------------------------


def test_dopo_cinque_tentativi_il_nome_utente_e_chiuso(client, db_session):
    """Il blocco esiste, scatta, e lo dice in italiano.

    E' gia' verificato in tests/test_auth.py; qui si ricontrolla dal punto di
    vista della messa in esercizio - cioe' guardando che la difesa ci sia e
    che il numero di tentativi venga dalla configurazione, non da una costante
    scritta dentro il programma.
    """
    nome = f"prova.frequenza.{uuid.uuid4().hex[:8]}"
    crea_utente(db_session, username=nome)
    db_session.flush()

    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        entra(client, nome, "password-sbagliata")

    # Anche con la password giusta, adesso, non si entra.
    risposta = entra(client, nome, PASSWORD_DI_PROVA)
    assert risposta.status_code == 401
    testo = contenuto_leggibile(risposta).lower()
    assert "tentativi" in testo and "riprova" in testo

    # Ogni tentativo e' registrato con il suo indirizzo IP: e' quello che
    # permette di sapere chi sta martellando (D-029).
    tentativi = db_session.scalars(
        select(LoginAttempt).where(LoginAttempt.username == nome)
    ).all()
    assert len(tentativi) > settings.LOGIN_MAX_ATTEMPTS
    assert all(t.ip for t in tentativi), (
        "un tentativo senza indirizzo IP non serve a niente"
    )


# ---------------------------------------------------------------------------
#  5. Niente di riservato nei registri e negli indirizzi
# ---------------------------------------------------------------------------


def test_la_parola_d_ordine_di_salute_non_finisce_nel_registro():
    """Il filtro del registro sostituisce il valore di token= con ***.

    D-089 permette di presentare la parola d'ordine di /salute anche
    nell'indirizzo, perche' non tutti i programmi di sorveglianza sanno
    aggiungere un'intestazione. Uvicorn pero' scrive nel registro degli accessi
    la riga di richiesta per intero, query compresa: senza questo filtro la
    parola d'ordine finirebbe in chiaro dentro logs/aurora.log, che e' il file
    che si manda per posta quando si chiede aiuto.
    """
    filtro = NascondiSegretiNegliIndirizzi()

    riga = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1 - "GET /salute?token=parola-segretissima HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    filtro.filter(riga)

    scritto = riga.getMessage()
    assert "parola-segretissima" not in scritto
    assert "token=***" in scritto
    assert "/salute" in scritto, "il resto della riga deve restare leggibile"


def test_nessuna_password_e_nessun_gettone_sono_leggibili_nel_database(
    client, db_session
):
    """Nel database ci sono impronte, mai il valore in chiaro.

    Le password sono argon2id, i gettoni di sessione SHA-256 (D-025). Il test
    entra davvero e poi va a guardare che cosa e' stato scritto.
    """
    nome = f"prova.segreti.{uuid.uuid4().hex[:8]}"
    utente = crea_utente(db_session, username=nome)
    db_session.flush()
    entra(client, nome, PASSWORD_DI_PROVA, ricordami=True)

    db_session.refresh(utente)
    assert PASSWORD_DI_PROVA not in utente.password_hash
    assert utente.password_hash.startswith("$argon2id$")

    sessioni = db_session.scalars(
        select(UserSession).where(UserSession.user_id == utente.id)
    ).all()
    assert sessioni, "l'accesso doveva aver aperto almeno una sessione"
    for sessione in sessioni:
        assert len(sessione.token_hash) == 64, (
            "nel database va l'impronta SHA-256 del gettone, non il gettone"
        )
        assert re.fullmatch(r"[0-9a-f]{64}", sessione.token_hash)


def test_nel_registro_delle_operazioni_non_finisce_nessuna_password(
    client, db_session
):
    """Nemmeno l'impronta: la password non entra in audit_logs in nessuna forma."""
    nome = f"prova.registro.{uuid.uuid4().hex[:8]}"
    crea_utente(db_session, username=nome)
    db_session.flush()
    entra(client, nome, PASSWORD_DI_PROVA)

    voci = db_session.scalars(
        select(AuditLog).order_by(AuditLog.seq.desc()).limit(20)
    ).all()

    for voce in voci:
        testo = f"{voce.description} {voce.old_value} {voce.new_value}"
        assert PASSWORD_DI_PROVA not in testo
        assert "$argon2" not in testo
        assert "password_hash" not in testo


def test_nessun_indirizzo_di_aurora_porta_una_password_o_un_gettone():
    """Nelle firme delle rotte non c'e' nessun parametro di tipo segreto.

    Le password viaggiano **solo** dentro il corpo di un POST. Un parametro
    nell'indirizzo finisce nella cronologia del browser, nel registro degli
    accessi e nell'intestazione Referer della richiesta successiva: sono tre
    posti in cui una password non deve stare, e nessuno dei tre si ripulisce.

    Il test legge le rotte vere invece dei sorgenti: cosi' vale anche per
    quelle che verranno.
    """
    from app.main import app

    sospetti = ("password", "segreto", "secret", "gettone")
    colpevoli = []

    for rotta in app.routes:
        percorso = getattr(rotta, "path", "")
        dipendente = getattr(rotta, "dependant", None)
        if dipendente is None:
            continue
        nomi = [parametro.name.lower() for parametro in dipendente.query_params]
        for nome in nomi:
            if any(sospetto in nome for sospetto in sospetti):
                colpevoli.append(f"{percorso}?{nome}")

    assert not colpevoli, (
        "queste rotte accettano un segreto come parametro dell'indirizzo: "
        + ", ".join(colpevoli)
    )


# ---------------------------------------------------------------------------
#  6. Gli errori non raccontano niente di tecnico
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "percorso",
    (
        "/prodotti/non-un-uuid",
        "/documenti/123",
        "/progetti/abc/storico",
        "/utenti/xyz",
    ),
)
def test_un_identificativo_storto_nell_indirizzo_da_un_404_in_italiano(
    client, db_session, percorso
):
    """Un indirizzo con dentro un identificativo malfatto risponde come un 404.

    **Che cosa succedeva prima della sessione 13.** FastAPI rispondeva da solo
    con un 422 e un JSON in inglese che diceva anche il nome del parametro
    della rotta:

        {"detail":[{"type":"uuid_parsing","loc":["path","product_id"], ...}]}

    Tre cose sbagliate insieme: la lingua (regola 3 di CLAUDE.md), il dettaglio
    tecnico mostrato a chi usa il programma, e il nome interno del parametro -
    che a chi guarda non serve e a chi prova gli indirizzi serve.

    Adesso e' un 404 con **la stessa identica frase** che riceverebbe chi
    chiede un identificativo ben scritto che non esiste: e' la regola di D-052
    portata fino in fondo. Un messaggio diverso direbbe che la forma era
    quella giusta.
    """
    crea_utente(
        db_session,
        username=f"prova.errori.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    db_session.flush()
    utenti = db_session.scalars(
        select(User).where(User.global_role == GlobalRole.CREATORE)
    ).all()
    entra(client, utenti[-1].username, PASSWORD_DI_PROVA)

    risposta = client.get(percorso, headers={"accept": "text/html"})

    assert risposta.status_code == 404
    testo = contenuto_leggibile(risposta)

    # Le parole si cercano nel **corpo** della pagina e non nell'HTML intero:
    # le icone della barra laterale sono disegni SVG, e dentro un SVG la parola
    # "path" e' il nome di un elemento del disegno.
    corpo = testo.split("<main", 1)[-1]
    for parola in ("uuid_parsing", "Input should be", '"loc"', "product_id",
                   "document_id", "project_id", "user_id"):
        assert parola not in corpo, (
            f"la pagina di errore mostra il dettaglio tecnico «{parola}»"
        )
    assert "non esiste" in corpo.lower()


def test_un_errore_del_programma_mostra_un_riferimento_e_non_la_traccia(
    client, db_session, monkeypatch
):
    """Un guasto imprevisto da' un codice da citare, non lo stack di Python.

    Il codice serve a chi riceve la segnalazione: "e' comparso l'errore
    3f9a2c11" e' una riga da cercare in logs/aurora.log, e non richiede a chi
    la riporta di capire niente.
    """
    from app.routers import home

    nome = f"prova.guasto.{uuid.uuid4().hex[:8]}"
    crea_utente(db_session, username=nome)
    db_session.flush()
    entra(client, nome, PASSWORD_DI_PROVA)

    def esplode(*args, **kwargs):
        raise RuntimeError("dettaglio tecnico che non deve uscire")

    monkeypatch.setattr(home.projects, "cruscotto", esplode)

    risposta = _come_un_browser_vero(client, "/")

    assert risposta.status_code == 500
    testo = contenuto_leggibile(risposta)
    assert "dettaglio tecnico che non deve uscire" not in testo
    assert "RuntimeError" not in testo
    assert "Traceback" not in testo
    assert re.search(r"\b[0-9a-f]{8}\b", testo), (
        "la pagina deve portare il codice di riferimento da citare"
    )


def test_la_pagina_del_database_spento_dice_che_cosa_fare(
    client, db_session, monkeypatch
):
    """Il 503 porta l'istruzione, non la diagnosi, e non il messaggio di psycopg."""
    from sqlalchemy.exc import OperationalError

    from app import main
    from app.routers import home

    nome = f"prova.dbspento.{uuid.uuid4().hex[:8]}"
    crea_utente(db_session, username=nome)
    db_session.flush()
    entra(client, nome, PASSWORD_DI_PROVA)

    def non_risponde(*args, **kwargs):
        raise OperationalError(
            "select 1",
            {},
            Exception(
                "connection to server at 127.0.0.1 failed: password "
                "authentication failed for user aurora_app"
            ),
        )

    monkeypatch.setattr(home.projects, "cruscotto", non_risponde)
    monkeypatch.setattr(main, "database_irraggiungibile", lambda: True)

    risposta = _come_un_browser_vero(client, "/")

    assert risposta.status_code == 503
    testo = contenuto_leggibile(risposta)
    assert "aurora_app" not in testo, (
        "il nome dell'utente del database non deve comparire in una pagina"
    )
    assert "password authentication" not in testo
    assert "Servizi" in testo, (
        "la pagina deve portare l'istruzione, cioe' i nomi veri delle cose "
        "da aprire (D-084)"
    )


# ---------------------------------------------------------------------------
#  7. La diagnostica dice se la connessione e' cifrata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "certificato, cookie_secure, colore_atteso",
    (
        # https e cookie d'accordo: e' la configurazione di produzione.
        (True, True, "verde"),
        # https senza cookie protetti: la cifratura c'e' e non serve alla
        # sessione. E' il difetto peggiore dei tre perche' sembra a posto.
        (True, False, "rosso"),
        # Cookie protetti senza certificato: giallo, perche' e' anche la
        # configurazione giusta di chi ha messo davanti un altro server https.
        (False, True, "giallo"),
        # Niente di niente: e' lo sviluppo, ed e' rosso su un server vero.
        (False, False, "rosso"),
    ),
)
def test_la_diagnostica_dice_se_la_sessione_viaggia_in_chiaro(
    monkeypatch, certificato, cookie_secure, colore_atteso
):
    """Le quattro combinazioni di https e COOKIE_SECURE, con il loro colore.

    E' il difetto piu' probabile di un'installazione nuova ed e' anche quello
    che non si vede: Aurora in http funziona benissimo, nessuno si lamenta, e
    intanto ogni gettone di sessione attraversa la rete aziendale in chiaro.
    """
    from app.services import diagnostics

    monkeypatch.setattr(
        settings, "HTTPS_CERT_FILE", "C:\\certificati\\aurora.crt" if certificato else ""
    )
    monkeypatch.setattr(
        settings, "HTTPS_KEY_FILE", "C:\\certificati\\aurora.key" if certificato else ""
    )
    monkeypatch.setattr(settings, "COOKIE_SECURE", cookie_secure)

    riga = diagnostics._controllo_sicurezza()

    assert riga.colore == colore_atteso
    if colore_atteso != "verde":
        assert riga.che_fare, (
            "una riga che non e' verde deve dire che cosa fare (D-084)"
        )
        assert ".env" in riga.che_fare, (
            "l'istruzione deve nominare le cose vere: il file da aprire"
        )


def test_l_avvio_si_ferma_se_il_certificato_indicato_non_esiste(monkeypatch):
    """Un certificato indicato e mancante ferma l'avvio con una frase chiara.

    Senza questo controllo uvicorn parte, prova ad aprire il file, non lo
    trova e muore: il servizio di Windows risulta «avviato e poi arrestato»,
    che non dice niente a nessuno.
    """
    import importlib

    avvia = importlib.import_module("scripts.avvia")

    monkeypatch.setattr(settings, "HTTPS_CERT_FILE", "C:\\non\\esiste\\aurora.crt")
    monkeypatch.setattr(settings, "HTTPS_KEY_FILE", "C:\\non\\esiste\\aurora.key")

    mancanti = avvia.verifica_i_certificati()

    assert len(mancanti) == 2
    assert any("HTTPS_CERT_FILE" in riga for riga in mancanti)
    assert any("HTTPS_KEY_FILE" in riga for riga in mancanti)


def test_l_avvio_avvisa_quando_https_e_i_cookie_non_vanno_d_accordo(monkeypatch):
    """I due guasti che si riconoscono peggio vengono detti prima di partire."""
    import importlib

    avvia = importlib.import_module("scripts.avvia")

    monkeypatch.setattr(settings, "HTTPS_CERT_FILE", "aurora.crt")
    monkeypatch.setattr(settings, "HTTPS_KEY_FILE", "aurora.key")
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    assert avvia.avvisi_sulla_sicurezza(), (
        "https senza COOKIE_SECURE va detto: la sessione viaggia anche in "
        "chiaro"
    )

    monkeypatch.setattr(settings, "HTTPS_CERT_FILE", "")
    monkeypatch.setattr(settings, "HTTPS_KEY_FILE", "")
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    avvisi = avvia.avvisi_sulla_sicurezza()
    assert avvisi, "COOKIE_SECURE senza https va detto: non si entra piu'"
    assert "entrare" in avvisi[0], (
        "l'avviso deve dire che cosa succede a chi usa il programma, non come "
        "e' scritta la configurazione"
    )

    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    assert not avvia.avvisi_sulla_sicurezza(), (
        "http e cookie in chiaro sono lo sviluppo: qui non c'e' niente da dire"
    )


# ---------------------------------------------------------------------------
#  8. I cookie in produzione
# ---------------------------------------------------------------------------


def test_i_cookie_seguono_il_parametro_di_configurazione(client, db_session, monkeypatch):
    """Con COOKIE_SECURE acceso i cookie escono con l'attributo Secure.

    In sviluppo il parametro e' falso per forza: su http un cookie Secure non
    torna mai indietro e non si riuscirebbe a entrare. In produzione **deve**
    essere vero, e docs/INSTALLAZIONE.md lo fa verificare prima della consegna.
    Questo test verifica il meccanismo, cioe' che il parametro governi davvero
    quello che dice di governare.
    """
    nome = f"prova.cookie.{uuid.uuid4().hex[:8]}"
    crea_utente(db_session, username=nome)
    db_session.flush()

    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    risposta = entra(client, nome, PASSWORD_DI_PROVA, ricordami=True)

    consegnati = risposta.headers.get_list("set-cookie")
    assert consegnati, "l'accesso doveva consegnare almeno un cookie"
    for cookie in consegnati:
        assert "Secure" in cookie, f"cookie senza Secure: {cookie}"
        assert "HttpOnly" in cookie, f"cookie senza HttpOnly: {cookie}"
        assert "samesite=lax" in cookie.lower(), (
            f"cookie senza SameSite: {cookie}"
        )
