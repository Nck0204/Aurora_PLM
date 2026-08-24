"""Test della gestione utenti, riservata al ruolo creatore.

In fondo al file c'e' il giro completo previsto dai criteri di accettazione
della sessione 3: creo un utente dall'interfaccia, ricevo la sua password,
entro con quella, sono obbligato a cambiarla, e da quel momento entro
normalmente.

    pytest tests/test_users.py -v
"""

import re

from sqlalchemy import select

from app.models import GlobalRole, User
from app.services import auth, passwords, users
from tests.conftest import (
    PASSWORD_DI_PROVA,
    PASSWORD_NUOVA,
    cognome_irripetibile,
    contenuto_leggibile,
    crea_utente,
    entra,
    gettone_csrf,
)

# La password assegnata compare nella pagina di conferma dentro questo
# elemento. Il test la legge di li' perche' e' l'unico posto in cui esiste: nel
# database c'e' solo l'impronta.
_PASSWORD_MOSTRATA = re.compile(
    r'id="password-assegnata"[^>]*>([^<]+)</code>'
)


def crea_creatore(db, username: str = "prova.capo.progetto") -> User:
    """Un utente con il ruolo di creatore, per le pagine riservate."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


def password_dalla_pagina(risposta) -> str:
    """Estrae la password mostrata nella pagina di conferma."""
    trovata = _PASSWORD_MOSTRATA.search(risposta.text)
    assert trovata is not None, "la pagina di conferma non mostra la password"
    return trovata.group(1).strip()


# --- Chi puo' entrare in questa sezione -------------------------------------


def test_un_utente_normale_non_apre_la_gestione_utenti(client, db_session):
    """Accesso negato a chi non e' creatore.

    E' uno dei criteri di accettazione della sessione.
    """
    crea_utente(db_session, username="prova.mario.rossi", ruolo=GlobalRole.UTENTE)
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    for percorso in ("/utenti", "/utenti/nuovo"):
        risposta = client.get(percorso)
        assert risposta.status_code == 403, f"{percorso} doveva essere negato"
        assert "riservata" in contenuto_leggibile(risposta)


def test_un_utente_normale_non_puo_nemmeno_agire(client, db_session):
    """Il divieto vale anche sui POST, non solo sulle pagine da guardare."""
    bersaglio = crea_utente(db_session, username="prova.luigi.bianchi")
    crea_utente(db_session, username="prova.mario.rossi", ruolo=GlobalRole.UTENTE)
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/utenti/{bersaglio.id}/disattiva",
        data={"csrf": gettone_csrf(client, "/")},
    )

    assert risposta.status_code == 403
    db_session.refresh(bersaglio)
    assert bersaglio.is_active is True, "non doveva succedere niente"


def test_chi_non_e_entrato_viene_mandato_alla_pagina_di_accesso(client):
    """Senza sessione, /utenti rimanda a /entra e non risponde 403."""
    risposta = client.get("/utenti", follow_redirects=False)

    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/entra?dopo=/utenti"


def test_il_creatore_vede_l_elenco(client, db_session):
    """Il creatore apre l'elenco e ci trova tutti, attivi e disattivati."""
    crea_creatore(db_session)
    crea_utente(db_session, username="prova.mario.rossi")
    crea_utente(db_session, username="prova.anna.verdi", attivo=False)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    pagina = client.get("/utenti")

    assert pagina.status_code == 200
    assert "prova.mario.rossi" in pagina.text
    assert "prova.anna.verdi" in pagina.text, "i disattivati si devono vedere"
    assert "disattivato" in pagina.text


# --- Nome utente proposto ---------------------------------------------------


def test_lo_username_si_compone_da_nome_e_cognome(db_session):
    """Mario Rossi diventa mario.rossi."""
    cognome = cognome_irripetibile()

    proposto = users.proponi_username(db_session, "Mario", cognome)

    assert proposto == f"mario.{cognome.lower()}"


def test_lo_username_perde_accenti_spazi_e_apostrofi(db_session):
    """I caratteri che non si ribattono uguali non entrano nel nome utente."""
    cognome = cognome_irripetibile()

    # L'apostrofo sparisce e le due parti si attaccano: D'Angelo -> dangelo.
    con_apostrofo = users.proponi_username(db_session, "Nicolò", f"D'{cognome}")
    assert con_apostrofo == f"nicolo.d{cognome.lower()}"

    # Lo spazio dentro il nome sparisce allo stesso modo, e l'accento cade.
    con_spazi = users.proponi_username(db_session, "Maria Rosa", f"De {cognome}")
    assert con_spazi == f"mariarosa.de{cognome.lower()}"


def test_l_omonimia_aggiunge_un_numero_progressivo(db_session):
    """Il secondo omonimo prende il 2, il terzo il 3."""
    cognome = cognome_irripetibile()
    base = users.proponi_username(db_session, "Mario", cognome)

    crea_utente(db_session, username=base)
    assert users.proponi_username(db_session, "Mario", cognome) == f"{base}2"

    crea_utente(db_session, username=f"{base}2")
    assert users.proponi_username(db_session, "Mario", cognome) == f"{base}3"


def test_l_omonimia_conta_anche_gli_utenti_disattivati(db_session):
    """Un nome utente non si riusa mai, nemmeno quello di un disattivato.

    Riusarlo renderebbe ambigue le vecchie righe del registro delle operazioni:
    direbbero lo stesso nome utente riferendosi a due persone diverse.
    """
    cognome = cognome_irripetibile()
    base = users.proponi_username(db_session, "Mario", cognome)

    crea_utente(db_session, username=base, attivo=False)

    assert users.proponi_username(db_session, "Mario", cognome) == f"{base}2"


# --- Password generata ------------------------------------------------------


def test_la_password_generata_e_quattro_parole_italiane():
    """Quattro parole prese dall'elenco del repository, unite da trattini."""
    password = passwords.generate_password()
    parole = password.split("-")

    assert len(parole) == 4, f"quattro parole, non {len(parole)}: {password}"
    for parola in parole:
        assert parola in passwords.WORDLIST, f"'{parola}' non e' nell'elenco"
    assert len(set(parole)) == 4, "le quattro parole devono essere diverse"


def test_l_elenco_delle_parole_e_abbastanza_lungo():
    """Almeno duecento parole, come chiede la sessione."""
    assert len(passwords.WORDLIST) >= 200


def test_due_password_generate_sono_diverse():
    """Il generatore e' casuale, non ripete la stessa parola d'ordine."""
    generate = {passwords.generate_password() for _ in range(20)}
    assert len(generate) == 20


# --- Creazione di un utente -------------------------------------------------


def test_creazione_utente_mostra_la_password_una_volta(client, db_session):
    """La creazione riesce, propone lo username e mostra la password."""
    crea_creatore(db_session)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    cognome = cognome_irripetibile()
    atteso = f"anna.{cognome.lower()}"

    risposta = client.post(
        "/utenti/nuovo",
        data={
            "first_name": "Anna",
            "last_name": cognome,
            "email": f"{atteso}@esempio.local",
            "ruolo": GlobalRole.UTENTE.value,
            "csrf": gettone_csrf(client, "/utenti/nuovo"),
        },
    )

    assert risposta.status_code == 200
    assert atteso in risposta.text, "lo username proposto va mostrato"

    password = password_dalla_pagina(risposta)
    assert len(password.split("-")) == 4

    creato = db_session.scalar(select(User).where(User.username == atteso))
    assert creato is not None
    assert creato.must_change_password is True, "deve cambiarla al primo accesso"
    assert creato.is_active is True
    assert creato.global_role is GlobalRole.UTENTE

    # Nel database c'e' solo l'impronta, e corrisponde alla password mostrata.
    assert creato.password_hash.startswith("$argon2id$")
    assert password not in creato.password_hash
    assert passwords.verify_password(creato.password_hash, password)


def test_la_password_non_ricompare_da_nessun_altra_parte(client, db_session):
    """Dopo la pagina di conferma, quella password non si rivede piu'."""
    crea_creatore(db_session)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    cognome = cognome_irripetibile()
    conferma = client.post(
        "/utenti/nuovo",
        data={
            "first_name": "Anna",
            "last_name": cognome,
            "email": f"anna.{cognome.lower()}@esempio.local",
            "csrf": gettone_csrf(client, "/utenti/nuovo"),
        },
    )
    password = password_dalla_pagina(conferma)

    assert password not in client.get("/utenti").text
    assert password not in client.get("/").text


def test_non_si_creano_due_utenti_con_la_stessa_posta(client, db_session):
    """L'indirizzo di posta e' unico, e lo si dice in italiano."""
    crea_creatore(db_session)
    # crea_utente() ricava l'indirizzo dal nome utente, quindi questo utente
    # occupa gia' "prova.anna.verdi@esempio.local".
    esistente = crea_utente(db_session, username="prova.anna.verdi")
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/utenti/nuovo",
        data={
            "first_name": "Anna",
            "last_name": cognome_irripetibile(),
            "email": esistente.email,
            "csrf": gettone_csrf(client, "/utenti/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "gia' di un altro utente" in contenuto_leggibile(risposta)


# --- Riassegnazione della password ------------------------------------------


def test_reimpostare_la_password_butta_fuori_l_utente(
    client, secondo_browser, db_session
):
    """Password nuova, must_change_password rimesso, tutte le sessioni chiuse."""
    crea_creatore(db_session)
    bersaglio = crea_utente(db_session, username="prova.mario.rossi")

    entra(secondo_browser, "prova.mario.rossi", PASSWORD_DI_PROVA)
    assert secondo_browser.get("/").status_code == 200
    assert auth.conta_sessioni_attive(db_session, bersaglio.id) == 1

    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/utenti/{bersaglio.id}/reimposta",
        data={"csrf": gettone_csrf(client, "/utenti")},
    )

    assert risposta.status_code == 200
    nuova = password_dalla_pagina(risposta)

    db_session.refresh(bersaglio)
    assert bersaglio.must_change_password is True
    assert passwords.verify_password(bersaglio.password_hash, nuova)
    assert not passwords.verify_password(bersaglio.password_hash, PASSWORD_DI_PROVA)

    assert auth.conta_sessioni_attive(db_session, bersaglio.id) == 0
    assert secondo_browser.get("/", follow_redirects=False).status_code == 303


# --- Disattivazione e riattivazione -----------------------------------------


def test_disattivare_un_utente_lo_butta_fuori_subito(
    client, secondo_browser, db_session
):
    """Disattivato, l'utente perde tutte le sessioni e non rientra."""
    crea_creatore(db_session)
    bersaglio = crea_utente(db_session, username="prova.mario.rossi")

    entra(secondo_browser, "prova.mario.rossi", PASSWORD_DI_PROVA)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/utenti/{bersaglio.id}/disattiva",
        data={"csrf": gettone_csrf(client, "/utenti")},
        follow_redirects=False,
    )

    assert risposta.status_code == 303
    db_session.refresh(bersaglio)
    assert bersaglio.is_active is False
    assert auth.conta_sessioni_attive(db_session, bersaglio.id) == 0

    # La sessione che aveva non vale piu'.
    assert secondo_browser.get("/", follow_redirects=False).status_code == 303

    # E non riesce nemmeno a rientrare.
    rifiutato = entra(secondo_browser, "prova.mario.rossi", PASSWORD_DI_PROVA)
    assert rifiutato.status_code == 401


def test_riattivare_un_utente_lo_fa_rientrare(client, db_session):
    """Riattivato, l'utente rientra con la password che aveva."""
    crea_creatore(db_session)
    bersaglio = crea_utente(db_session, username="prova.mario.rossi", attivo=False)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    client.post(
        f"/utenti/{bersaglio.id}/riattiva",
        data={"csrf": gettone_csrf(client, "/utenti")},
    )

    db_session.refresh(bersaglio)
    assert bersaglio.is_active is True


def test_il_creatore_non_puo_disattivare_se_stesso(client, db_session):
    """Altrimenti l'ultimo creatore potrebbe chiudersi fuori da solo."""
    creatore = crea_creatore(db_session)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/utenti/{creatore.id}/disattiva",
        data={"csrf": gettone_csrf(client, "/utenti")},
    )

    assert risposta.status_code == 400
    assert "tuo stesso profilo" in contenuto_leggibile(risposta)

    db_session.refresh(creatore)
    assert creatore.is_active is True


def test_non_esiste_nessun_modo_di_cancellare_un_utente(client, db_session):
    """Regola 5 di CLAUDE.md: la cancellazione non deve esistere da nessuna parte."""
    crea_creatore(db_session)
    bersaglio = crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    # Nell'interfaccia non c'e' nessun comando che cancelli. Si guardano le
    # azioni dei moduli e le scritte sui pulsanti, non il testo della pagina:
    # la pagina **parla** di cancellazione, per dire che non si fa.
    elenco = contenuto_leggibile(client.get("/utenti"))

    azioni = re.findall(r'<form[^>]*action="([^"]*)"', elenco)
    assert azioni, "l'elenco deve contenere almeno un modulo"
    for azione in azioni:
        assert not re.search(r"cancella|elimina|rimuovi|delete", azione, re.I), (
            f"il modulo punta a {azione}: sembra una cancellazione"
        )

    pulsanti = re.findall(r"<button[^>]*>(.*?)</button>", elenco, re.S)
    for scritta in pulsanti:
        assert not re.search(r"cancella|elimina|rimuovi", scritta, re.I), (
            f"c'e' un pulsante che dice '{scritta.strip()}'"
        )

    # E le rotte che qualcuno potrebbe provare a indovinare non esistono.
    assert client.delete(f"/utenti/{bersaglio.id}").status_code in (404, 405)
    assert (
        client.post(
            f"/utenti/{bersaglio.id}/cancella",
            data={"csrf": gettone_csrf(client, "/utenti")},
        ).status_code
        == 404
    )

    db_session.refresh(bersaglio)
    assert bersaglio is not None


# --- Il giro completo dei criteri di accettazione ---------------------------


def test_giro_completo_dalla_creazione_al_primo_accesso(
    client, secondo_browser, db_session
):
    """Creo un utente, ricevo la password, entro, la cambio, poi entro normale.

    E' lo scenario di accettazione scritto nella sessione 3, dal principio alla
    fine, passando ogni volta dalle pagine vere.

    "client" e' il browser del creatore, "secondo_browser" quello della persona
    appena creata.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.progetto", PASSWORD_DI_PROVA)

    # 1. Il creatore crea l'utente e riceve la password, una volta sola.
    cognome = cognome_irripetibile()
    anna = f"anna.{cognome.lower()}"

    conferma = client.post(
        "/utenti/nuovo",
        data={
            "first_name": "Anna",
            "last_name": cognome,
            "email": f"{anna}@esempio.local",
            "ruolo": GlobalRole.UTENTE.value,
            "csrf": gettone_csrf(client, "/utenti/nuovo"),
        },
    )
    assert conferma.status_code == 200
    assert anna in conferma.text, "lo username proposto va mostrato al creatore"
    password_assegnata = password_dalla_pagina(conferma)

    # 2. Anna entra con quella password.
    accesso = entra(secondo_browser, anna, password_assegnata)
    assert accesso.status_code == 303, "la password consegnata deve funzionare"

    # 3. Qualunque pagina apra, viene dirottata al cambio password.
    dirottata = secondo_browser.get("/", follow_redirects=False)
    assert dirottata.status_code == 303
    assert dirottata.headers["location"] == "/cambio-password"

    dirottata = secondo_browser.get("/utenti", follow_redirects=False)
    assert dirottata.headers["location"] == "/cambio-password"

    # 4. Cambia la password, indicando quella assegnata come attuale.
    cambio = secondo_browser.post(
        "/cambio-password",
        data={
            "password_attuale": password_assegnata,
            "password_nuova": PASSWORD_NUOVA,
            "password_ripetuta": PASSWORD_NUOVA,
            "csrf": gettone_csrf(secondo_browser, "/cambio-password"),
        },
        follow_redirects=False,
    )
    assert cambio.status_code == 303

    # 5. Da adesso naviga normalmente.
    home = secondo_browser.get("/")
    assert home.status_code == 200
    assert anna in home.text

    # 6. Esce e rientra con la password nuova, senza piu' dirottamenti.
    secondo_browser.post(
        "/esci", data={"csrf": gettone_csrf(secondo_browser, "/")}
    )
    rientro = entra(secondo_browser, anna, PASSWORD_NUOVA)
    assert rientro.status_code == 303
    assert rientro.headers["location"] == "/"
    assert secondo_browser.get("/").status_code == 200

    # 7. E la vecchia password assegnata non vale piu'.
    secondo_browser.post(
        "/esci", data={"csrf": gettone_csrf(secondo_browser, "/")}
    )
    assert entra(secondo_browser, anna, password_assegnata).status_code == 401
