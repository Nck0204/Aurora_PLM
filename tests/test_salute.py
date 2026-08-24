"""Test della rotta di servizio /salute e della pagina di errore.

Come si eseguono, dalla radice del progetto:

    .venv\\Scripts\\activate
    pytest

Nota sui nomi: le funzioni di test hanno nome in inglese, come tutti gli
identificatori del progetto; la spiegazione di cosa verificano sta nel testo
sotto il nome, in italiano.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Un finto browser che parla con l'applicazione senza passare dalla rete.

    Si usa "with" perche' cosi' vengono eseguite anche le operazioni di avvio e
    di chiusura definite in app/main.py (creazione delle cartelle di lavoro,
    chiusura delle connessioni), esattamente come quando parte uvicorn.
    """
    with TestClient(app) as test_client:
        yield test_client


def test_health_check_responds_200(client):
    """/salute risponde sempre 200 e dichiara stato, versione e ora.

    Risponde 200 anche quando il database non e' raggiungibile: in quel caso
    il campo "stato" vale "degradato". La scelta e' voluta, chi interroga
    questa rotta deve poter leggere cosa non va.
    """
    response = client.get("/salute")

    assert response.status_code == 200, "la rotta /salute deve rispondere 200"

    body = response.json()
    assert body["stato"] in ("ok", "degradato")
    assert body["versione"], "manca il numero di versione"
    assert body["ora"], "manca l'ora del server"
    assert "connesso" in body["database"]


def test_health_check_reports_database_connected(client):
    """Con PostgreSQL configurato, /salute deve dichiarare stato "ok".

    Finche' il database non e' stato preparato (vedi scripts/setup_postgres.md)
    questo test viene saltato invece di fallire: segnala che manca un pezzo
    dell'ambiente, non che il codice e' sbagliato.
    """
    body = client.get("/salute").json()

    if not body["database"]["connesso"]:
        pytest.skip(
            "PostgreSQL non raggiungibile, database non ancora preparato. "
            "Dettaglio: " + str(body["database"]["errore"])
        )

    assert body["stato"] == "ok"


def test_unknown_page_shows_italian_error_page(client):
    """Un indirizzo inesistente mostra la pagina di errore in italiano.

    Verifica che il gestore globale delle eccezioni sia attivo e che al
    browser arrivi HTML, non il messaggio predefinito di FastAPI in inglese.
    """
    response = client.get("/indirizzo-che-non-esiste", headers={"accept": "text/html"})

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Pagina non trovata" in response.text
