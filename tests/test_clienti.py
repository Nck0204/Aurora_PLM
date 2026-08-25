"""Test dell'anagrafica clienti e dei contatti.

La regola che questo file protegge, oltre al funzionamento normale: **niente
si cancella**. Non esiste nessuna rotta per cancellare un cliente o un
contatto, e non deve comparirne una.

    pytest tests/test_clienti.py -v
"""

from sqlalchemy import select

from app.models import Contact, Customer, GlobalRole
from app.services import customers
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_cliente,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
    sigla_irripetibile,
)


def crea_creatore(db, username: str = "prova.capo.clienti"):
    """Un utente con il ruolo di creatore."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


# --- Chi puo' entrare in questa sezione -------------------------------------


def test_un_utente_normale_non_apre_i_clienti(client, db_session):
    """L'anagrafica dei clienti la tiene il creatore."""
    crea_utente(db_session, username="prova.mario.clienti")
    entra(client, "prova.mario.clienti", PASSWORD_DI_PROVA)

    for percorso in ("/clienti", "/clienti/nuovo"):
        assert client.get(percorso).status_code == 403, percorso


# --- Creazione e modifica ---------------------------------------------------


def test_si_crea_un_cliente_dall_interfaccia(client, db_session):
    crea_creatore(db_session, "prova.capo.crea")
    entra(client, "prova.capo.crea", PASSWORD_DI_PROVA)

    sigla = sigla_irripetibile()
    risposta = client.post(
        "/clienti/nuovo",
        data={
            "nome": "Officine di prova",
            "codice": sigla,
            "note": "Cliente inventato da un test.",
            "csrf": gettone_csrf(client, "/clienti/nuovo"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200
    assert "Officine di prova" in contenuto_leggibile(risposta)

    creato = db_session.scalars(
        select(Customer).where(Customer.code == sigla)
    ).first()
    assert creato is not None
    assert creato.is_active


def test_la_sigla_non_si_puo_ripetere(client, db_session):
    """Nemmeno cambiando maiuscole e minuscole."""
    crea_creatore(db_session, "prova.capo.sigla")
    cliente = crea_cliente(db_session)
    entra(client, "prova.capo.sigla", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/clienti/nuovo",
        data={
            "nome": "Un altro cliente",
            "codice": cliente.code.lower(),
            "csrf": gettone_csrf(client, "/clienti/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "gia' di un altro cliente" in contenuto_leggibile(risposta)


def test_il_nome_e_obbligatorio(client, db_session):
    crea_creatore(db_session, "prova.capo.nomevuoto")
    entra(client, "prova.capo.nomevuoto", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/clienti/nuovo",
        data={
            "nome": "   ",
            "codice": sigla_irripetibile(),
            "csrf": gettone_csrf(client, "/clienti/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "nome del cliente e' obbligatorio" in contenuto_leggibile(risposta)


def test_si_modifica_un_cliente(client, db_session):
    crea_creatore(db_session, "prova.capo.modifica")
    cliente = crea_cliente(db_session, nome="Nome di prima")
    entra(client, "prova.capo.modifica", PASSWORD_DI_PROVA)

    client.post(
        f"/clienti/{cliente.id}",
        data={
            "nome": "Nome di dopo",
            "codice": cliente.code,
            "note": "",
            "csrf": gettone_csrf(client, f"/clienti/{cliente.id}"),
        },
        follow_redirects=True,
    )

    db_session.refresh(cliente)
    assert cliente.name == "Nome di dopo"


# --- Disattivazione, mai cancellazione --------------------------------------


def test_il_cliente_si_disattiva_e_si_riattiva(client, db_session):
    crea_creatore(db_session, "prova.capo.disattiva")
    cliente = crea_cliente(db_session)
    entra(client, "prova.capo.disattiva", PASSWORD_DI_PROVA)

    client.post(
        f"/clienti/{cliente.id}/disattiva",
        data={"csrf": gettone_csrf(client, f"/clienti/{cliente.id}")},
        follow_redirects=True,
    )
    db_session.refresh(cliente)
    assert not cliente.is_active

    client.post(
        f"/clienti/{cliente.id}/riattiva",
        data={"csrf": gettone_csrf(client, f"/clienti/{cliente.id}")},
        follow_redirects=True,
    )
    db_session.refresh(cliente)
    assert cliente.is_active


def test_un_cliente_disattivato_non_si_propone_per_i_prodotti(db_session):
    """Resta nell'anagrafica, ma non fra le scelte."""
    creatore = crea_creatore(db_session, "prova.capo.propone")
    cliente = crea_cliente(db_session)
    customers.disattiva_cliente(db_session, cliente, creatore)
    db_session.flush()

    tutti = customers.elenco_clienti(db_session)
    proponibili = customers.elenco_clienti(db_session, solo_attivi=True)

    assert cliente.id in [c.id for c in tutti], "nell'elenco si vede ancora"
    assert cliente.id not in [c.id for c in proponibili]


def test_non_esiste_nessuna_rotta_per_cancellare_un_cliente():
    """Regola 5 di CLAUDE.md, verificata sull'elenco delle rotte.

    Non e' un test di comportamento ma di forma: un giorno qualcuno potrebbe
    aggiungere una rotta di cancellazione in buona fede, e questo test glielo
    dice prima che finisca in produzione.
    """
    from app.main import app
    from app.routers import customers as rotte_clienti

    percorsi = [
        (rotta.path, sorted(rotta.methods))
        for rotta in rotte_clienti.router.routes
    ]

    for percorso, metodi in percorsi:
        assert "DELETE" not in metodi, f"{percorso} non deve accettare DELETE"
        assert "cancella" not in percorso, f"{percorso} non deve esistere"
        assert "elimina" not in percorso, f"{percorso} non deve esistere"

    assert app is not None


# --- Contatti ---------------------------------------------------------------


def test_si_aggiunge_una_persona_di_riferimento(client, db_session):
    crea_creatore(db_session, "prova.capo.contatti")
    cliente = crea_cliente(db_session)
    entra(client, "prova.capo.contatti", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/clienti/{cliente.id}/contatti",
        data={
            "nome_contatto": "Giulia Bianchi",
            "email": "giulia.bianchi@cliente.local",
            "ruolo": "responsabile acquisti",
            "csrf": gettone_csrf(client, f"/clienti/{cliente.id}"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert "Giulia Bianchi" in testo
    assert "giulia.bianchi@cliente.local" in testo


def test_piu_persone_possono_avere_lo_stesso_indirizzo(db_session):
    """L'indirizzo di posta non e' unico: e' una casella condivisa.

    Vedi docs/MODELLO_DATI.md, 4.2.
    """
    creatore = crea_creatore(db_session, "prova.capo.posta")
    cliente = crea_cliente(db_session)

    customers.aggiungi_contatto(
        db_session,
        cliente,
        nome="Prima persona",
        email="ufficio.tecnico@cliente.local",
        ruolo=None,
        autore=creatore,
    )
    customers.aggiungi_contatto(
        db_session,
        cliente,
        nome="Seconda persona",
        email="ufficio.tecnico@cliente.local",
        ruolo=None,
        autore=creatore,
    )
    db_session.flush()

    quanti = db_session.scalars(
        select(Contact).where(
            Contact.customer_id == cliente.id,
            Contact.email == "ufficio.tecnico@cliente.local",
        )
    ).all()
    assert len(quanti) == 2


def test_il_contatto_si_disattiva_e_non_si_cancella(client, db_session):
    creatore = crea_creatore(db_session, "prova.capo.contattofuori")
    cliente = crea_cliente(db_session)
    contatto = customers.aggiungi_contatto(
        db_session,
        cliente,
        nome="Chi ha cambiato lavoro",
        email=None,
        ruolo=None,
        autore=creatore,
    )
    db_session.flush()

    entra(client, "prova.capo.contattofuori", PASSWORD_DI_PROVA)

    client.post(
        f"/contatti/{contatto.id}/disattiva",
        data={"csrf": gettone_csrf(client, f"/clienti/{cliente.id}")},
        follow_redirects=True,
    )

    db_session.refresh(contatto)
    assert not contatto.is_active
    assert db_session.get(Contact, contatto.id) is not None, "non si cancella"


def test_la_scheda_del_cliente_mostra_i_suoi_prodotti(client, db_session):
    crea_creatore(db_session, "prova.capo.schedaprodotti")
    creatore = crea_utente(
        db_session, username="prova.capo.schedaprodotti2", ruolo=GlobalRole.CREATORE
    )
    cliente = crea_cliente(db_session)
    prodotto, _v = crea_prodotto(db_session, cliente=cliente, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.schedaprodotti", PASSWORD_DI_PROVA)

    scheda = client.get(f"/clienti/{cliente.id}")

    assert scheda.status_code == 200
    assert prodotto.code in scheda.text
