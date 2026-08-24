"""Test dell'accesso: entrata, uscita, blocco, cambio password, ricordami.

Sono i criteri di accettazione della sessione 3. Ogni test parte da un
database pulito - la transazione della fixture viene annullata alla fine - e
usa l'applicazione vera: stesse rotte, stesse dipendenze, stessi template.

Come si eseguono, dalla radice del progetto:

    .venv\\Scripts\\activate
    pytest tests/test_auth.py -v
"""

from sqlalchemy import select

from app.config import settings
from app.models import SessionKind, User, UserSession
from app.services import auth
from app.services.cookies import COOKIE_RICORDAMI, COOKIE_SESSIONE
from tests.conftest import (
    PASSWORD_DI_PROVA,
    PASSWORD_NUOVA,
    crea_utente,
    entra,
    gettone_csrf,
    contenuto_leggibile,
)


# --- Entrata ----------------------------------------------------------------


def test_login_riuscito_apre_una_sessione(client, db_session):
    """Con le credenziali giuste si entra e si riceve il cookie di sessione."""
    utente = crea_utente(db_session, username="prova.mario.rossi")

    risposta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    assert risposta.status_code == 303, "dopo l'accesso si viene rimandati"
    assert risposta.headers["location"] == "/"
    assert COOKIE_SESSIONE in risposta.cookies, "manca il cookie di sessione"

    # Nel database c'e' la sessione, e del gettone c'e' solo l'impronta.
    sessione = db_session.scalar(
        select(UserSession).where(UserSession.user_id == utente.id)
    )
    assert sessione is not None
    assert sessione.kind is SessionKind.SESSIONE
    assert sessione.revoked_at is None
    assert len(sessione.token_hash) == 64, "il gettone va salvato come SHA-256"
    assert sessione.token_hash != risposta.cookies[COOKIE_SESSIONE], (
        "nel database non deve finire il gettone consegnato al browser"
    )

    # E adesso la pagina iniziale si apre.
    pagina = client.get("/")
    assert pagina.status_code == 200
    assert "prova.mario.rossi" in pagina.text


def test_login_sbagliato_da_un_messaggio_generico(client, db_session):
    """La password sbagliata non fa entrare e non dice perche'."""
    crea_utente(db_session, username="prova.mario.rossi")

    risposta = entra(client, "prova.mario.rossi", "password-sbagliata")

    assert risposta.status_code == 401
    assert COOKIE_SESSIONE not in risposta.cookies
    assert "Credenziali non valide" in risposta.text


def test_login_di_un_utente_inesistente_dice_la_stessa_cosa(client, db_session):
    """Il nome utente che non esiste riceve lo stesso identico messaggio.

    E' il requisito di sicurezza: mai "utente inesistente". Chi prova a
    indovinare non deve poter capire quali nomi utente esistono.
    """
    crea_utente(db_session, username="prova.mario.rossi")

    inesistente = entra(client, "prova.nessuno.qui", "una-password-qualunque")

    assert inesistente.status_code == 401
    assert "Credenziali non valide" in inesistente.text
    assert "inesistente" not in inesistente.text.lower()
    assert "non esiste" not in inesistente.text.lower()


def test_utente_disattivato_non_entra(client, db_session):
    """Un profilo disattivato riceve lo stesso messaggio di uno sbagliato."""
    crea_utente(db_session, username="prova.mario.rossi", attivo=False)

    risposta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    assert risposta.status_code == 401
    assert "Credenziali non valide" in risposta.text
    assert "disattiv" not in risposta.text.lower()


def test_pagina_protetta_rimanda_alla_pagina_di_accesso(client, db_session):
    """Chi non e' entrato viene mandato a /entra, con l'indirizzo di ritorno."""
    risposta = client.get("/", follow_redirects=False)

    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/entra?dopo=/"


# --- Blocco dopo troppi tentativi -------------------------------------------


def test_blocco_dopo_cinque_tentativi_falliti(client, db_session):
    """Al sesto tentativo il nome utente e' bloccato, anche con la password giusta.

    Verifica il requisito 5: cinque tentativi falliti sullo stesso nome utente
    nella finestra di quindici minuti, poi si chiude.
    """
    crea_utente(db_session, username="prova.mario.rossi")

    for numero in range(settings.LOGIN_MAX_ATTEMPTS):
        risposta = entra(client, "prova.mario.rossi", "sbagliata")
        assert risposta.status_code == 401, f"tentativo {numero + 1}"
        assert "Credenziali non valide" in risposta.text

    # Sesto tentativo: adesso il messaggio cambia, ed e' il blocco.
    bloccato = entra(client, "prova.mario.rossi", "sbagliata")
    assert bloccato.status_code == 401
    assert "Troppi tentativi" in bloccato.text

    # E la password giusta non serve piu' a niente: e' il punto del blocco.
    con_password_giusta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    assert con_password_giusta.status_code == 401
    assert "Troppi tentativi" in con_password_giusta.text
    assert COOKIE_SESSIONE not in con_password_giusta.cookies


def test_il_blocco_riguarda_un_nome_utente_solo(client, db_session):
    """Bloccare "prova.mario.rossi" non deve chiudere fuori "prova.luigi.bianchi"."""
    crea_utente(db_session, username="prova.mario.rossi")
    crea_utente(db_session, username="prova.luigi.bianchi")

    for _ in range(settings.LOGIN_MAX_ATTEMPTS + 1):
        entra(client, "prova.mario.rossi", "sbagliata")

    altro = entra(client, "prova.luigi.bianchi", PASSWORD_DI_PROVA)
    assert altro.status_code == 303, "l'altro utente deve poter entrare"


def test_ogni_tentativo_finisce_in_login_attempt(client, db_session):
    """Riusciti e falliti: la tabella li tiene tutti."""
    from app.models import LoginAttempt

    crea_utente(db_session, username="prova.mario.rossi")

    entra(client, "prova.mario.rossi", "sbagliata")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    tentativi = db_session.scalars(
        select(LoginAttempt).where(LoginAttempt.username == "prova.mario.rossi")
    ).all()

    assert len(tentativi) == 2
    assert sorted(t.success for t in tentativi) == [False, True]


# --- Cambio password obbligatorio -------------------------------------------


def test_primo_accesso_obbliga_a_cambiare_la_password(client, db_session):
    """Con must_change_password ogni pagina rimanda al cambio password.

    Verifica il requisito 6.
    """
    crea_utente(db_session, username="prova.mario.rossi", deve_cambiare=True)

    accesso = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    assert accesso.status_code == 303, "l'accesso riesce comunque"

    # La pagina iniziale non si apre: si viene dirottati.
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/cambio-password"

    # La pagina del cambio, invece, si apre.
    cambio = client.get("/cambio-password")
    assert cambio.status_code == 200
    assert "Devi cambiare la password" in cambio.text


def test_dopo_il_cambio_si_entra_normalmente(client, db_session):
    """Cambiata la password, il dirottamento smette e si naviga."""
    utente = crea_utente(db_session, username="prova.mario.rossi", deve_cambiare=True)
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/cambio-password",
        data={
            "password_attuale": PASSWORD_DI_PROVA,
            "password_nuova": PASSWORD_NUOVA,
            "password_ripetuta": PASSWORD_NUOVA,
            "csrf": gettone_csrf(client, "/cambio-password"),
        },
        follow_redirects=False,
    )

    assert risposta.status_code == 303
    assert risposta.headers["location"].startswith("/")

    db_session.refresh(utente)
    assert utente.must_change_password is False

    home = client.get("/")
    assert home.status_code == 200, "adesso la pagina iniziale si apre"


def test_il_cambio_password_richiede_quella_attuale(client, db_session):
    """Senza la password attuale il cambio viene rifiutato.

    Verifica il requisito 7: chi trovasse un calcolatore lasciato aperto non
    deve potersi prendere il profilo.
    """
    utente = crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/cambio-password",
        data={
            "password_attuale": "questa-non-e-quella-giusta",
            "password_nuova": PASSWORD_NUOVA,
            "password_ripetuta": PASSWORD_NUOVA,
            "csrf": gettone_csrf(client, "/cambio-password"),
        },
    )

    assert risposta.status_code == 400
    assert "password attuale non e' corretta" in contenuto_leggibile(risposta)

    # La password nel database non e' cambiata.
    db_session.refresh(utente)
    assert auth.passwords.verify_password(utente.password_hash, PASSWORD_DI_PROVA)


def test_il_cambio_password_revoca_le_altre_sessioni(
    client, secondo_browser, db_session
):
    """Chi cambia password butta fuori tutti gli altri dispositivi.

    Verifica il requisito 7. Il browser da cui si fa il cambio resta dentro,
    gli altri no.
    """
    utente = crea_utente(db_session, username="prova.mario.rossi")

    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    entra(secondo_browser, "prova.mario.rossi", PASSWORD_DI_PROVA)

    assert secondo_browser.get("/").status_code == 200, "il secondo e' dentro"
    assert auth.conta_sessioni_attive(db_session, utente.id) == 2

    client.post(
        "/cambio-password",
        data={
            "password_attuale": PASSWORD_DI_PROVA,
            "password_nuova": PASSWORD_NUOVA,
            "password_ripetuta": PASSWORD_NUOVA,
            "csrf": gettone_csrf(client, "/cambio-password"),
        },
    )

    assert client.get("/").status_code == 200, "chi ha cambiato resta dentro"

    buttato_fuori = secondo_browser.get("/", follow_redirects=False)
    assert buttato_fuori.status_code == 303
    assert buttato_fuori.headers["location"].startswith("/entra")

    assert auth.conta_sessioni_attive(db_session, utente.id) == 1


# --- Uscita -----------------------------------------------------------------


def test_uscita_revoca_la_sessione(client, db_session):
    """Uscendo la sessione viene revocata e i cookie tolti."""
    utente = crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/esci",
        data={"csrf": gettone_csrf(client, "/")},
        follow_redirects=False,
    )

    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/entra"
    assert auth.conta_sessioni_attive(db_session, utente.id) == 0

    # La riga resta: si revoca, non si cancella (D-006).
    sessione = db_session.scalar(
        select(UserSession).where(UserSession.user_id == utente.id)
    )
    assert sessione is not None
    assert sessione.revoked_at is not None


def test_uscita_da_tutti_i_dispositivi(client, secondo_browser, db_session):
    """L'uscita globale chiude anche le sessioni degli altri calcolatori."""
    utente = crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    entra(secondo_browser, "prova.mario.rossi", PASSWORD_DI_PROVA)

    client.post("/esci-ovunque", data={"csrf": gettone_csrf(client, "/")})

    assert auth.conta_sessioni_attive(db_session, utente.id) == 0
    assert secondo_browser.get("/", follow_redirects=False).status_code == 303


# --- Ricordami --------------------------------------------------------------


def test_ricordami_fa_rientrare_dopo_la_chiusura_del_browser(client, db_session):
    """Con "Ricordami" si rientra anche senza il cookie di sessione.

    Chiudere il browser si simula buttando via il solo cookie di sessione: e'
    esattamente quello che fa un browser vero, perche' quel cookie non ha
    scadenza e il "ricordami" ne ha una di trenta giorni.

    Verifica il requisito 3, prima meta'.
    """
    crea_utente(db_session, username="prova.mario.rossi")

    accesso = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=True)
    assert COOKIE_RICORDAMI in accesso.cookies, "manca il cookie del ricordami"

    ricordami_iniziale = client.cookies[COOKIE_RICORDAMI]
    del client.cookies[COOKIE_SESSIONE]

    pagina = client.get("/")

    assert pagina.status_code == 200, "il ricordami deve far rientrare"
    assert "prova.mario.rossi" in pagina.text
    assert client.cookies.get(COOKIE_SESSIONE), "va aperta una sessione nuova"
    assert client.cookies[COOKIE_RICORDAMI] != ricordami_iniziale, (
        "il gettone lungo deve ruotare a ogni utilizzo"
    )


def test_il_gettone_ricordami_usato_non_vale_piu(client, db_session):
    """Il gettone vecchio viene revocato: se qualcuno l'aveva copiato, e' inutile.

    Verifica il requisito 3, seconda meta': la rotazione con revoca del
    precedente.
    """
    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=True)

    gettone_vecchio = client.cookies[COOKIE_RICORDAMI]
    del client.cookies[COOKIE_SESSIONE]
    client.get("/")  # qui avviene la rotazione

    # Il gettone vecchio nel database c'e' ancora, ma revocato.
    assert (
        auth.trova_sessione(db_session, gettone_vecchio, SessionKind.RICORDAMI) is None
    ), "il gettone gia' usato non deve piu' valere"


def test_senza_ricordami_non_si_rientra(client, db_session):
    """Chi non spunta la casella, chiuso il browser, deve rientrare."""
    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=False)

    assert COOKIE_RICORDAMI not in client.cookies
    del client.cookies[COOKIE_SESSIONE]

    assert client.get("/", follow_redirects=False).status_code == 303


def test_la_password_non_viene_mai_mandata_al_browser(client, db_session):
    """Nessuna pagina dell'accesso contiene la password scritta.

    Verifica il requisito 3: "non memorizzare MAI la password lato client".
    """
    crea_utente(db_session, username="prova.mario.rossi")

    sbagliato = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA + "-storta")
    assert PASSWORD_DI_PROVA not in sbagliato.text

    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=True)
    home = client.get("/")
    assert PASSWORD_DI_PROVA not in home.text

    # E nemmeno dentro i cookie: li' c'e' solo il gettone casuale.
    for valore in client.cookies.values():
        assert PASSWORD_DI_PROVA not in valore


# --- Stato dell'utente riletto a ogni richiesta -----------------------------


def test_la_disattivazione_chiude_subito_le_sessioni(client, db_session):
    """Disattivato un utente, la sua sessione smette di funzionare.

    Verifica il requisito 11: lo stato si rilegge dal database a ogni
    richiesta, non ci si fida del cookie.
    """
    utente = crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    assert client.get("/").status_code == 200

    # Disattivazione fatta direttamente sul database, senza toccare le
    # sessioni: e' il caso peggiore, quello in cui nessuno le ha revocate.
    utente.is_active = False
    db_session.flush()

    buttato_fuori = client.get("/", follow_redirects=False)
    assert buttato_fuori.status_code == 303
    assert buttato_fuori.headers["location"].startswith("/entra")


def test_il_cambio_di_ruolo_ha_effetto_subito(client, db_session):
    """Tolto il ruolo di creatore, le pagine riservate si chiudono.

    Verifica l'altra meta' del requisito 11.
    """
    from app.models import GlobalRole

    utente = crea_utente(
        db_session, username="prova.capo.progetto", ruolo=GlobalRole.CREATORE
    )
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)
    assert client.get("/utenti").status_code == 200

    utente.global_role = GlobalRole.UTENTE
    db_session.flush()

    assert client.get("/utenti").status_code == 403, (
        "il ruolo si rilegge dal database, non dal cookie"
    )


# --- Protezione dei moduli --------------------------------------------------


def test_un_post_senza_gettone_csrf_viene_rifiutato(client, db_session):
    """Un modulo senza il campo nascosto non passa."""
    crea_utente(db_session, username="prova.mario.rossi")

    risposta = client.post(
        "/entra",
        data={"username": "prova.mario.rossi", "password": PASSWORD_DI_PROVA},
    )

    assert risposta.status_code == 400
    assert COOKIE_SESSIONE not in risposta.cookies


def test_un_post_con_gettone_csrf_sbagliato_viene_rifiutato(client, db_session):
    """Un gettone inventato non vale: deve coincidere con quello del cookie."""
    crea_utente(db_session, username="prova.mario.rossi")
    gettone_csrf(client, "/entra")  # il cookie viene consegnato

    risposta = client.post(
        "/entra",
        data={
            "username": "prova.mario.rossi",
            "password": PASSWORD_DI_PROVA,
            "csrf": "gettone-inventato-di-sana-pianta",
        },
    )

    assert risposta.status_code == 400
    assert COOKIE_SESSIONE not in risposta.cookies


def test_il_modulo_di_accesso_aiuta_i_gestori_di_password(client):
    """I due campi hanno gli attributi autocomplete giusti.

    Verifica il requisito 4. Senza questi attributi il gestore di password del
    browser non riconosce il modulo, e le persone finiscono per scriversi le
    password su un foglietto.
    """
    pagina = client.get("/entra").text

    assert 'autocomplete="username"' in pagina
    assert 'autocomplete="current-password"' in pagina


# --- Cookie -----------------------------------------------------------------


def cookie_consegnati(risposta) -> dict[str, str]:
    """I "Set-Cookie" della risposta, uno per uno, indicizzati per nome.

    Va usato multi_items() e non items(): quando una risposta porta piu'
    intestazioni con lo stesso nome - e i Set-Cookie sono sempre piu' d'una -
    httpx le unisce in una stringa sola separata da virgole, e si finirebbe per
    controllare gli attributi di un cookie credendo di controllare quelli di un
    altro.
    """
    return {
        valore.split("=", 1)[0]: valore
        for nome, valore in risposta.headers.multi_items()
        if nome.lower() == "set-cookie"
    }


def test_i_cookie_hanno_gli_attributi_di_sicurezza(client, db_session):
    """HttpOnly, SameSite=Lax e Secure secondo configurazione."""
    crea_utente(db_session, username="prova.mario.rossi")
    risposta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=True)

    cookie = cookie_consegnati(risposta)
    assert COOKIE_SESSIONE in cookie, "il cookie di sessione deve essere consegnato"
    assert COOKIE_RICORDAMI in cookie, "manca il cookie del ricordami"

    for nome, intestazione in cookie.items():
        assert "HttpOnly" in intestazione, f"manca HttpOnly su {nome}"
        assert "SameSite=lax" in intestazione.lower().replace(
            "samesite=lax", "SameSite=lax"
        ), f"manca SameSite=Lax su {nome}"

        if settings.COOKIE_SECURE:
            assert "Secure" in intestazione, f"manca Secure su {nome}"
        else:
            # In sviluppo Secure deve restare spento, altrimenti su http il
            # browser non rimanderebbe mai il cookie e non si entrerebbe.
            assert "Secure" not in intestazione, f"Secure di troppo su {nome}"


def test_il_cookie_di_sessione_muore_con_il_browser(client, db_session):
    """Il cookie di sessione non ha scadenza, quello del ricordami si'."""
    crea_utente(db_session, username="prova.mario.rossi")
    risposta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA, ricordami=True)

    cookie = cookie_consegnati(risposta)

    assert "Max-Age" not in cookie[COOKIE_SESSIONE], (
        "il cookie di sessione deve morire alla chiusura del browser"
    )
    assert "Max-Age" in cookie[COOKIE_RICORDAMI], (
        "il ricordami deve sopravvivere alla chiusura del browser"
    )
    durata_attesa = settings.REMEMBER_ME_DAYS * 24 * 60 * 60
    assert f"Max-Age={durata_attesa}" in cookie[COOKIE_RICORDAMI]


# --- Le password non si possono rileggere -----------------------------------


def test_nel_database_non_c_e_nessuna_password_leggibile(client, db_session):
    """L'impronta e' argon2 e non contiene la password."""
    crea_utente(db_session, username="prova.mario.rossi")

    utente = db_session.scalar(select(User).where(User.username == "prova.mario.rossi"))
    assert utente is not None
    assert utente.password_hash.startswith("$argon2id$")
    assert PASSWORD_DI_PROVA not in utente.password_hash
