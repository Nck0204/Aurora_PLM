"""Test della diagnostica, della rotta /salute e della pagina del database giu'.

Come si eseguono, dalla radice del progetto:

    .venv\\Scripts\\activate
    pytest tests/test_diagnostica.py -v

**Il criterio di accettazione della sessione 12 e' uno solo e sta qui:** spengo
PostgreSQL, e la diagnostica lo segnala in rosso con un'istruzione utile invece
di rispondere con un errore tecnico. PostgreSQL non lo si puo' spegnere davvero
in un test - sarebbe spegnerlo anche a chi sta lavorando sulla stessa macchina -
quindi lo si simula sostituendo la sessione con una che rifiuta di rispondere.
E' la stessa scelta di `tests/test_posta_graph.py`, che simula Microsoft invece
di chiamarla.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Backup, GlobalRole
from app.models.backup import ESITO_FALLITO, ESITO_RIUSCITO
from app.services import diagnostics
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_utente,
    entra,
)


# ===========================================================================
#  Aiuti
# ===========================================================================


def creatore(db: Session):
    """Un creatore con un nome utente che non puo' gia' esserci."""
    return crea_utente(
        db,
        username=f"prova.diagnostica.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )


def entra_come(client: TestClient, utente) -> None:
    """Fa entrare quel finto browser con quell'utente."""
    risposta = entra(client, utente.username, PASSWORD_DI_PROVA)
    assert risposta.status_code == 303, "l'accesso non e' riuscito"


class DatabaseSpento:
    """Una finta sessione che si comporta come un PostgreSQL spento.

    Non e' un oggetto di comodo con dentro `pass`: rifiuta ogni interrogazione
    con la stessa eccezione che solleverebbe SQLAlchemy davanti a un servizio
    fermo. E' quello che permette di provare per davvero il ramo che nessuno
    riesce a far scattare quando gli serve.
    """

    def execute(self, *_argomenti, **_parole):
        raise OperationalError("select 1", {}, Exception("il servizio non risponde"))

    def scalars(self, *_argomenti, **_parole):
        raise OperationalError("select", {}, Exception("il servizio non risponde"))

    def scalar(self, *_argomenti, **_parole):
        raise OperationalError("select", {}, Exception("il servizio non risponde"))

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def get_bind(self):
        raise OperationalError("bind", {}, Exception("il servizio non risponde"))


# ===========================================================================
#  1. IL DATABASE SPENTO
# ===========================================================================


def test_il_database_spento_diventa_una_riga_rossa():
    """Il criterio di accettazione: rosso, con un'istruzione utile."""
    stato = diagnostics.stato_del_sistema(DatabaseSpento())

    riga = stato.voce("database")
    assert riga is not None, "la riga del database deve esserci sempre"
    assert riga.colore == diagnostics.ROSSO
    assert stato.colore == diagnostics.ROSSO


def test_l_istruzione_del_database_dice_che_cosa_fare_non_che_cosa_e_successo():
    """La frase rossa nomina il servizio di Windows e il parametro del .env.

    E' il test che protegge la regola: «ogni riga che non e' verde dice che
    cosa fare». Una diagnosi ("il database non risponde") la sa dare chiunque;
    quello che serve a chi e' stato chiamato di sabato mattina e' sapere dove
    premere.
    """
    riga = diagnostics.stato_del_sistema(DatabaseSpento()).voce("database")

    istruzione = riga.che_fare.lower()
    assert istruzione, "una riga rossa senza istruzione non serve a nessuno"
    assert "servizi" in istruzione, "manca dove guardare in Windows"
    assert "postgresql" in istruzione, "manca il nome del servizio"
    assert "database_url" in istruzione, "manca il parametro da controllare"


def test_con_il_database_spento_gli_altri_controlli_non_si_ripetono():
    """Una riga rossa che spiega, non sette righe rosse fra cui cercarla."""
    stato = diagnostics.stato_del_sistema(DatabaseSpento())

    assert len(stato.voci) == 1, (
        "con il database spento si mostra solo la riga del database: tutti gli "
        "altri controlli lo interrogherebbero e direbbero sette volte la stessa "
        "cosa"
    )


def test_nessun_controllo_solleva_mai(db_session):
    """Neanche uno: la pagina che serve durante un guasto non deve rompersi."""
    stato = diagnostics.stato_del_sistema(db_session)

    assert stato.voci, "la diagnostica non ha prodotto nessuna riga"
    for riga in stato.voci:
        assert riga.colore in (
            diagnostics.VERDE,
            diagnostics.GIALLO,
            diagnostics.ROSSO,
        ), f"la riga «{riga.chiave}» ha un colore che non esiste: {riga.colore}"


# ===========================================================================
#  2. LA PAGINA
# ===========================================================================


def test_la_diagnostica_e_riservata_al_creatore(client, db_session):
    """Chi non amministra non la apre."""
    utente = crea_utente(
        db_session, username=f"prova.normale.{uuid.uuid4().hex[:8]}"
    )
    entra_come(client, utente)

    risposta = client.get("/diagnostica")
    assert risposta.status_code == 403


def test_la_diagnostica_chiede_di_entrare_a_chi_non_e_entrato(client, db_session):
    """Senza sessione si finisce alla pagina di accesso."""
    risposta = client.get("/diagnostica", follow_redirects=False)
    assert risposta.status_code == 303
    assert "/entra" in risposta.headers["location"]


def test_la_pagina_mostra_una_riga_per_controllo(client, db_session):
    """Tutti i controlli compaiono, con il loro titolo."""
    entra_come(client, creatore(db_session))

    testo = contenuto_leggibile(client.get("/diagnostica"))

    for atteso in (
        "Collegamento al database",
        "Collegamento alla casella di posta",
        "Messaggi in quarantena",
        "Copia di sicurezza",
        "Spazio sul disco",
        "Integrita' dell'archivio dei file",
        "Registro delle operazioni",
        "Quanto c'e' dentro Aurora",
        "Errori nelle ultime 24 ore",
    ):
        assert atteso in testo, f"nella pagina manca il controllo «{atteso}»"


def test_la_pagina_mostra_il_semaforo_a_parole(client, db_session):
    """Il colore non e' mai l'unica informazione: dentro c'e' la parola."""
    entra_come(client, creatore(db_session))

    testo = contenuto_leggibile(client.get("/diagnostica"))
    assert "verde" in testo, "le etichette del semaforo devono portare la parola"


def test_il_dettaglio_degli_errori_si_apre(client, db_session):
    """La pagina collegata dalla riga degli errori esiste e si apre."""
    entra_come(client, creatore(db_session))

    risposta = client.get("/diagnostica/errori")
    assert risposta.status_code == 200
    assert "Errori delle ultime 24 ore" in contenuto_leggibile(risposta)


# ===========================================================================
#  3. LA ROTTA /salute
# ===========================================================================


def test_salute_risponde_a_chi_non_e_entrato(client):
    """La interroga un programma di sorveglianza, che non ha una password."""
    risposta = client.get("/salute")
    assert risposta.status_code == 200


def test_salute_conserva_i_campi_di_prima_della_sessione_12(client):
    """Chi la stesse gia' leggendo continua a trovare quello che trovava.

    E' il patto che rende sensato aver spostato la rotta: la forma vecchia
    resta, e i controlli si aggiungono accanto.
    """
    corpo = client.get("/salute").json()

    assert corpo["stato"] in ("ok", "degradato")
    assert corpo["applicazione"]
    assert corpo["versione"]
    assert corpo["ora"]
    assert "connesso" in corpo["database"]


def test_salute_porta_il_semaforo_e_tutti_i_controlli(client):
    """I campi nuovi: il verdetto complessivo e una voce per controllo."""
    corpo = client.get("/salute").json()

    assert corpo["semaforo"] in ("verde", "giallo", "rosso")
    assert corpo["riassunto"]

    nomi = {controllo["nome"] for controllo in corpo["controlli"]}
    assert {"database", "disco", "archivio", "backup", "posta"} <= nomi

    for controllo in corpo["controlli"]:
        assert controllo["semaforo"] in ("verde", "giallo", "rosso")
        assert controllo["titolo"]
        assert controllo["valore"]


def test_i_numeri_del_disco_escono_come_numeri(client):
    """Chi sorveglia non deve rileggere una frase per ricavarne una cifra."""
    corpo = client.get("/salute").json()
    disco = next(c for c in corpo["controlli"] if c["nome"] == "disco")

    if not disco["dati"].get("misurabile"):
        pytest.skip("il disco non e' misurabile su questa macchina")

    assert isinstance(disco["dati"]["libero_byte"], int)
    assert isinstance(disco["dati"]["libero_percento"], (int, float))


def test_ogni_riga_non_verde_di_salute_dice_che_cosa_fare(client):
    """La regola vale anche in JSON, non solo nella pagina."""
    corpo = client.get("/salute").json()

    senza_istruzione = [
        controllo["nome"]
        for controllo in corpo["controlli"]
        if controllo["semaforo"] != "verde" and not controllo["che_fare"].strip()
    ]
    assert senza_istruzione == [], (
        f"questi controlli non sono verdi e non dicono che cosa fare: "
        f"{senza_istruzione}"
    )


def test_salute_si_puo_chiudere_con_una_parola_d_ordine(client, monkeypatch):
    """Con HEALTH_TOKEN scritto nel .env, la rotta pretende quel valore."""
    from app.config import settings

    monkeypatch.setattr(settings, "HEALTH_TOKEN", "parola-di-prova")

    assert client.get("/salute").status_code == 401
    assert client.get("/salute?token=sbagliata").status_code == 401
    assert client.get("/salute?token=parola-di-prova").status_code == 200
    assert (
        client.get(
            "/salute", headers={"X-Aurora-Salute": "parola-di-prova"}
        ).status_code
        == 200
    )


# ===========================================================================
#  4. LA COPIA DI SICUREZZA VISTA DALLA DIAGNOSTICA
# ===========================================================================


def test_senza_nessuna_copia_la_riga_e_rossa(db_session, monkeypatch):
    """Un sistema senza copie di sicurezza e' un sistema in pericolo.

    Le copie eventualmente presenti sul database di sviluppo si nascondono
    facendo rispondere "niente" all'interrogazione: il test deve provare il
    caso "non ne e' mai stata fatta nessuna", non dipendere da che cosa c'e'
    sulla macchina di chi lo esegue.
    """
    esito = _riga_backup_con(db_session, monkeypatch, ultima=None)

    assert esito.colore == diagnostics.ROSSO
    assert "BACKUP_E_RIPRISTINO" in esito.che_fare, (
        "l'istruzione deve dire dove sta scritta la procedura"
    )


def test_una_copia_riuscita_di_stanotte_e_verde(db_session, monkeypatch):
    """Il caso normale."""
    copia = Backup(
        started_at=datetime.now(timezone.utc) - timedelta(hours=6),
        finished_at=datetime.now(timezone.utc) - timedelta(hours=6),
        outcome=ESITO_RIUSCITO,
        destination="D:/CopieAurora",
        database_bytes=102049,
        files_bytes=23675867,
        files_copied=12,
        files_skipped=3733,
    )
    esito = _riga_backup_con(db_session, monkeypatch, ultima=copia)

    assert esito.colore == diagnostics.VERDE
    assert not esito.che_fare, "una riga verde non ha niente da far fare"


def test_una_copia_fallita_e_rossa_e_riporta_il_motivo(db_session, monkeypatch):
    """Il motivo scritto dallo script arriva fino alla pagina."""
    copia = Backup(
        started_at=datetime.now(timezone.utc) - timedelta(hours=3),
        finished_at=datetime.now(timezone.utc) - timedelta(hours=3),
        outcome=ESITO_FALLITO,
        destination="D:/CopieAurora",
        message="pg_dump non e' stato trovato.",
    )
    esito = _riga_backup_con(db_session, monkeypatch, ultima=copia)

    assert esito.colore == diagnostics.ROSSO
    assert "pg_dump" in esito.che_fare


def test_una_copia_riuscita_ma_vecchia_e_gialla(db_session, monkeypatch):
    """La copia c'e' ma l'operazione pianificata non sta girando."""
    copia = Backup(
        started_at=datetime.now(timezone.utc) - timedelta(days=5),
        finished_at=datetime.now(timezone.utc) - timedelta(days=5),
        outcome=ESITO_RIUSCITO,
        destination="D:/CopieAurora",
    )
    esito = _riga_backup_con(db_session, monkeypatch, ultima=copia)

    assert esito.colore == diagnostics.GIALLO
    assert "pianificazione" in esito.che_fare.lower()


def _riga_backup_con(db_session, monkeypatch, *, ultima):
    """Calcola la riga «Copia di sicurezza» con quell'ultima copia.

    Si sostituisce l'ultima copia invece di scriverne una nel database perche'
    il test deve poter provare anche il caso "nessuna copia", che sul database
    di sviluppo - dove le copie di prova ci sono - non capiterebbe mai.
    """

    class FintaRisposta:
        def first(self):
            return ultima

    def finte_scalars(*_argomenti, **_parole):
        return FintaRisposta()

    monkeypatch.setattr(db_session, "scalars", finte_scalars, raising=False)
    return diagnostics._controllo_backup(db_session)


# ===========================================================================
#  5. I NUMERI SCRITTI PERCHE' SI LEGGANO
# ===========================================================================


@pytest.mark.parametrize(
    "byte, atteso",
    [
        (0, "0 byte"),
        (512, "512 byte"),
        (1024, "1,00 KB"),
        (1536, "1,50 KB"),
        (20 * 1024, "20,0 KB"),
        (5 * 1024 * 1024, "5,00 MB"),
        (2 * 1024**3, "2,00 GB"),
        (None, "non disponibile"),
    ],
)
def test_i_byte_si_scrivono_come_li_scriverebbe_una_persona(byte, atteso):
    """Due cifre sotto il dieci, una sopra: "1837,29 MB" non si legge."""
    assert diagnostics.misura(byte) == atteso


@pytest.mark.parametrize(
    "secondi, atteso",
    [
        (30, "meno di un minuto fa"),
        (60, "un minuto fa"),
        (600, "10 minuti fa"),
        (3600, "un'ora fa"),
        (7200, "2 ore fa"),
        (5 * 86400, "5 giorni fa"),
    ],
)
def test_il_tempo_passato_si_dice_come_lo_direbbe_una_persona(secondi, atteso):
    """"tre ore fa" e non "10847 secondi"."""
    momento = datetime.now(timezone.utc) - timedelta(seconds=secondi)
    assert diagnostics.da_quanto(momento) == atteso


def test_la_stima_dei_mesi_smette_di_contare_dopo_due_anni():
    """"bastano ancora 74 mesi" e' una precisione finta, e chi legge lo sa."""
    assert diagnostics._mesi_scritti(90) == "piu' di due anni"
    assert diagnostics._mesi_scritti(0.5) == "meno di un mese"
    assert diagnostics._mesi_scritti(1.4) == "circa un mese"
    assert diagnostics._mesi_scritti(7.2) == "circa 7 mesi"


# ===========================================================================
#  6. L'INTEGRITA' DELL'ARCHIVIO
# ===========================================================================


def test_la_verifica_dell_archivio_conta_le_due_direzioni(db_session):
    """Quanti file ci sono e non servono, quanti servono e non ci sono."""
    esito = diagnostics.verifica_archivio(db_session)

    assert esito.oggetti_su_disco >= 0
    assert esito.impronte_nel_database >= 0
    assert esito.mancanti_su_disco >= 0
    assert esito.orfani_su_disco >= 0


def test_un_file_che_manca_rende_rossa_la_riga(db_session, monkeypatch):
    """E' il guasto piu' grave che Aurora possa avere, e va detto in rosso.

    Si simula facendo credere alla verifica che manchi un file, invece di
    togliere per davvero un oggetto dall'archivio: cancellare un file
    dall'archivio di sviluppo lo toglierebbe anche a chi ci sta lavorando, e
    la regola 5 di CLAUDE.md dice che dall'archivio non si toglie niente.
    """
    finta = diagnostics.Integrita(
        oggetti_su_disco=100,
        impronte_nel_database=102,
        orfani_su_disco=0,
        mancanti_su_disco=2,
        temporanei_rimasti=0,
        esempi_mancanti=("3f9a2c11deadbeef", "aa00bb11cc22dd33"),
    )
    monkeypatch.setattr(
        diagnostics, "verifica_archivio", lambda *a, **k: finta
    )

    riga = diagnostics._controllo_archivio(db_session)

    assert riga.colore == diagnostics.ROSSO
    assert "BACKUP_E_RIPRISTINO" in riga.che_fare
    assert "3f9a2c11" in riga.che_fare, (
        "l'istruzione deve dire quali impronte mancano: senza, non si sa da "
        "dove cominciare a cercare"
    )


# ===========================================================================
#  7. LA PAGINA CHE COMPARE QUANDO IL DATABASE E' GIU'
# ===========================================================================


def test_la_pagina_del_database_giu_porta_la_stessa_istruzione():
    """La frase e' scritta una volta sola, in diagnostics.CHE_FARE_DATABASE.

    Chi la legge sulla pagina di errore la riconosce nella diagnostica quando
    il database sara' tornato. Se un giorno qualcuno ne scrivesse una seconda
    copia, questo test non se ne accorgerebbe - ma il test qui sotto, che legge
    i sorgenti, si'.
    """
    riga = diagnostics.stato_del_sistema(DatabaseSpento()).voce("database")
    assert riga.che_fare == diagnostics.CHE_FARE_DATABASE


def test_l_istruzione_del_database_e_scritta_in_un_posto_solo():
    """Nessun file ripete a mano la frase del database irraggiungibile."""
    import pathlib
    import re

    radice = pathlib.Path(__file__).resolve().parent.parent

    # Una frase riconoscibile presa dall'istruzione. Se ricompare altrove, e'
    # perche' qualcuno l'ha ricopiata invece di importare la costante.
    pezzo = "apri «Servizi» di Windows"

    colpevoli = []
    for percorso in list((radice / "app").rglob("*.py")) + list(
        (radice / "app").rglob("*.html")
    ):
        if percorso.name == "diagnostics.py":
            continue
        if "__pycache__" in percorso.parts:
            continue
        if pezzo in percorso.read_text(encoding="utf-8"):
            colpevoli.append(percorso.relative_to(radice))

    assert colpevoli == [], (
        f"questi file ripetono a mano l'istruzione del database: {colpevoli}. "
        "La frase sta in diagnostics.CHE_FARE_DATABASE e si importa da li'"
    )
    assert re.search(r"CHE_FARE_DATABASE", (radice / "app" / "main.py").read_text(encoding="utf-8")), (
        "app/main.py deve usare la costante, non una frase sua"
    )


def test_la_pagina_del_database_giu_si_disegna(client, db_session, monkeypatch):
    """Il criterio di accettazione, visto dal browser.

    PostgreSQL non lo si puo' spegnere davvero in un test - sarebbe spegnerlo
    anche a chi sta lavorando sulla stessa macchina - quindi si fa in due mosse:
    si fa fallire una rotta con l'errore che solleverebbe un database spento, e
    si fa rispondere «e' spento» alla funzione che il gestore usa per
    distinguere quel caso dagli altri.

    Quello che si verifica e' proprio la cosa che l'azienda ha chiesto: **non
    un errore tecnico**, ma una pagina in italiano con dentro l'istruzione.
    """
    from app import main

    def rotta_che_cade(*_argomenti, **_parole):
        raise OperationalError("select 1", {}, Exception("il servizio non risponde"))

    monkeypatch.setattr(main, "database_irraggiungibile", lambda: True)
    monkeypatch.setattr(diagnostics, "stato_del_sistema", rotta_che_cade)

    risposta = client.get("/salute", headers={"accept": "text/html"})

    assert risposta.status_code == 503, (
        "un database irraggiungibile non e' un errore del programma: 503, non 500"
    )

    testo = contenuto_leggibile(risposta)
    assert "non riesce a parlare con il database" in testo
    assert diagnostics.CHE_FARE_DATABASE in testo, (
        "la pagina deve portare la stessa identica istruzione della diagnostica"
    )
    assert "Non si e' perso nulla" in testo
    assert "Traceback" not in testo, "non esce mai un dettaglio tecnico"
    assert "OperationalError" not in testo


def test_un_errore_sql_che_non_e_il_database_spento_resta_un_500(
    client, db_session, monkeypatch
):
    """Un'interrogazione scritta male e' un difetto del programma.

    Mostrarla come "il database non risponde" manderebbe chi indaga a riavviare
    un servizio che sta benissimo.
    """
    from app import main

    def rotta_che_cade(*_argomenti, **_parole):
        raise OperationalError("select storto", {}, Exception("colonna inesistente"))

    monkeypatch.setattr(main, "database_irraggiungibile", lambda: False)
    monkeypatch.setattr(diagnostics, "stato_del_sistema", rotta_che_cade)

    risposta = client.get("/salute", headers={"accept": "text/html"})

    assert risposta.status_code == 500
    assert "non riesce a parlare con il database" not in contenuto_leggibile(risposta)


def test_a_un_programma_il_database_giu_risponde_in_json(
    client, db_session, monkeypatch
):
    """Chi sorveglia non sa leggere una pagina HTML."""
    from app import main

    def rotta_che_cade(*_argomenti, **_parole):
        raise OperationalError("select 1", {}, Exception("il servizio non risponde"))

    monkeypatch.setattr(main, "database_irraggiungibile", lambda: True)
    monkeypatch.setattr(diagnostics, "stato_del_sistema", rotta_che_cade)

    risposta = client.get("/salute", headers={"accept": "application/json"})

    assert risposta.status_code == 503
    corpo = risposta.json()
    assert corpo["stato"] == "degradato"
    assert corpo["messaggio"] == diagnostics.CHE_FARE_DATABASE
    assert corpo["riferimento"], "serve il codice per ritrovare la riga nel registro"
