"""Test dei prodotti e della scomposizione del codice parlante.

Il criterio di accettazione che questo file verifica per primo:

    "Creo il prodotto RMS1100-24-110SW: la scomposizione appare corretta e i
     campi sono ricercabili."

e insieme a lui la regola che l'azienda ha chiesto di non violare mai: **un
codice che non corrisponde alla regola viene accettato lo stesso**, con
code_parts vuoto e una segnalazione visibile.

    pytest tests/test_prodotti.py -v
"""

import pathlib
import tempfile

from app.models import GlobalRole, LifecycleState
from app.services import product_codes, products
from tests.conftest import (
    PASSWORD_DI_PROVA,
    codice_irripetibile,
    contenuto_leggibile,
    crea_cliente,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
    modello_irripetibile,
)

# Il codice dell'esempio dell'azienda. Si usa **solo nei test che non toccano
# il database**: sul database di sviluppo quel prodotto esiste per davvero, e
# "products.code" e' unico. I test che scrivono si costruiscono il codice con
# codice_irripetibile(), che cambia il solo modello e lascia fissi i numeri.
CODICE_ESEMPIO = "RMS1100-24-110SW"


def crea_creatore(db, username: str = "prova.capo.prodotti"):
    """Un utente con il ruolo di creatore, per le pagine riservate."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


# --- La scomposizione, senza database ---------------------------------------


def test_il_codice_di_esempio_si_scompone_come_previsto():
    """RMS1100-24-110SW letto con la regola di partenza.

    E' il criterio di accettazione della sessione, verificato sul servizio
    prima ancora che sull'interfaccia.
    """
    parti = product_codes.scomponi(CODICE_ESEMPIO)

    assert parti == {
        "modello": "RMS",
        "potenza": "1100",
        "tensione_ingresso": "24",
        "tensione_uscita": "110",
        "variante": "SW",
    }


def test_gli_elementi_hanno_un_etichetta_in_italiano():
    """Ogni gruppo dell'espressione ha il suo nome leggibile."""
    etichette = {e.chiave: e.etichetta for e in product_codes.elementi()}

    assert etichette["tensione_ingresso"] == "Tensione di ingresso"
    assert etichette["modello"] == "Modello"


def test_l_ordine_degli_elementi_e_quello_del_codice():
    """Gli elementi si mostrano nell'ordine in cui compaiono nel codice.

    Non nell'ordine alfabetico e nemmeno in quello in cui sono scritte le
    etichette nel file: l'ordine dei gruppi dentro l'espressione e' l'unico
    che una persona che guarda il codice riconosce.
    """
    coppie = product_codes.scomposizione_leggibile(
        product_codes.scomponi(CODICE_ESEMPIO)
    )

    assert [etichetta for etichetta, _ in coppie] == [
        "Modello",
        "Potenza",
        "Tensione di ingresso",
        "Tensione di uscita",
        "Variante",
    ]


def test_un_codice_che_non_corrisponde_non_solleva_niente():
    """La scomposizione di un codice qualunque restituisce un dizionario vuoto.

    Non solleva, non registra un errore, non rifiuta: chi chiama riceve {} e
    va avanti. E' la regola su cui poggia tutto il resto.
    """
    assert product_codes.scomponi("UN CODICE QUALSIASI") == {}
    assert product_codes.scomponi("") == {}


def test_la_variante_facoltativa_che_manca_non_diventa_una_chiave_vuota():
    """Un gruppo che non ha preso niente resta fuori da code_parts.

    Una chiave con dentro la stringa vuota, nelle ricerche, sembrerebbe un
    valore: "tutti i prodotti la cui variante e' ''".
    """
    parti = product_codes.scomponi("RMS1100-24-110")

    assert "variante" not in parti
    assert parti["modello"] == "RMS"


def test_la_regola_si_puo_cambiare_senza_toccare_il_programma():
    """Cambiando il file di configurazione cambia la scomposizione.

    E' la ragione per cui la regola sta in un file e non nel codice: quando
    l'azienda confermera' come vanno letti i codici, si cambia quel file e si
    riavvia il server (D-038).
    """
    with tempfile.TemporaryDirectory() as cartella:
        altro = pathlib.Path(cartella) / "altra_regola.toml"
        # Nel file finisce  ^(?P<serie>[A-Z]+)-(?P<numero>\d+)$
        # La barra rovesciata e' raddoppiata qui perche' e' Python a doverla
        # scrivere; dentro il TOML, fra tre apici semplici, vale per quello
        # che e' e non va raddoppiata un'altra volta.
        altro.write_text(
            "espressione = '''^(?P<serie>[A-Z]+)-(?P<numero>\\d+)$'''\n"
            "\n"
            "[etichette]\n"
            'serie = "Serie"\n'
            'numero = "Numero progressivo"\n',
            encoding="utf-8",
        )

        try:
            regola = product_codes.ricarica(altro)

            assert regola.utilizzabile
            assert product_codes.scomponi("ABC-42") == {
                "serie": "ABC",
                "numero": "42",
            }
            # Il codice di prima, con questa regola, non si scompone piu': ed
            # e' giusto cosi', perche' la regola e' un'altra.
            assert product_codes.scomponi(CODICE_ESEMPIO) == {}
        finally:
            # Si rimette la regola vera, altrimenti i test successivi
            # lavorerebbero con quella inventata qui dentro.
            product_codes.ricarica()


def test_una_regola_rotta_non_ferma_il_programma():
    """Un file di configurazione sbagliato non impedisce di lavorare.

    Aurora continua a funzionare come se nessun codice fosse riconoscibile, e
    porta con se' la spiegazione da mostrare nelle pagine. Un errore di
    battitura in un file di configurazione non deve poter chiudere fuori tutta
    l'azienda (D-039).
    """
    with tempfile.TemporaryDirectory() as cartella:
        rotto = pathlib.Path(cartella) / "rotta.toml"
        rotto.write_text("espressione = '''^(?P<aperto>[A-Z+$'''\n", encoding="utf-8")

        try:
            regola = product_codes.ricarica(rotto)

            assert not regola.utilizzabile
            assert regola.problema, "deve dire in italiano che cosa non va"
            assert product_codes.scomponi(CODICE_ESEMPIO) == {}
        finally:
            product_codes.ricarica()


def test_un_file_che_non_esiste_non_ferma_il_programma():
    """Stessa cosa se il file di configurazione manca del tutto."""
    try:
        regola = product_codes.ricarica(pathlib.Path("questo/file/non/c/e.toml"))

        assert not regola.utilizzabile
        assert "non e' stato trovato" in regola.problema
    finally:
        product_codes.ricarica()


# --- La creazione, con il database ------------------------------------------


def test_il_prodotto_nasce_con_la_sua_versione_1(db_session):
    """Creando un prodotto nasce anche la versione 1, in sviluppo.

    Un prodotto senza versioni non e' niente su cui si possa lavorare (D-040).
    """
    prodotto, versione = crea_prodotto(db_session)

    assert versione.version_number == 1
    assert versione.lifecycle_state is LifecycleState.IN_SVILUPPO
    assert versione.derived_from_id is None, "la prima non discende da niente"
    assert versione.product_id == prodotto.id


def test_la_scomposizione_finisce_nel_database(db_session):
    """code_parts viene riempito alla creazione."""
    modello = modello_irripetibile()
    prodotto, _versione = crea_prodotto(
        db_session, codice=f"{modello}1100-24-110SW"
    )

    assert prodotto.code_parts["modello"] == modello
    assert prodotto.code_parts["potenza"] == "1100"
    assert prodotto.code_parts["tensione_ingresso"] == "24"
    assert prodotto.code_parts["tensione_uscita"] == "110"
    assert prodotto.code_parts["variante"] == "SW"


def test_un_codice_non_riconosciuto_viene_accettato_lo_stesso(db_session):
    """**Il sistema non rifiuta mai un codice.**

    Il prodotto si crea con code_parts vuoto. E' la regola che l'azienda ha
    chiesto per prima, e questo test e' quello che impedisce a chiunque di
    aggiungere un controllo sulla forma del codice.
    """
    prodotto, versione = crea_prodotto(
        db_session, codice="CODICE FUORI REGOLA " + modello_irripetibile()
    )

    assert prodotto.id is not None
    assert prodotto.code_parts == {}
    assert versione.version_number == 1


def test_i_campi_scomposti_sono_ricercabili(db_session):
    """Si cerca per modello, per potenza, per tensione.

    E' la seconda meta' del criterio di accettazione: non basta che la
    scomposizione appaia, deve servire a trovare il prodotto.
    """
    cliente = crea_cliente(db_session)
    modello = modello_irripetibile()
    altro_modello = modello_irripetibile()

    prodotto, _v = crea_prodotto(
        db_session, cliente=cliente, codice=f"{modello}1100-24-110SW"
    )
    crea_prodotto(
        db_session, cliente=cliente, codice=f"{altro_modello}600-48-24XX"
    )

    # Il modello e' irripetibile, quindi la ricerca puo' dire "esattamente
    # uno" senza doversi anche restringere al cliente: sul database di
    # sviluppo non ci puo' essere nient'altro con quel modello.
    per_modello, totale = products.cerca_prodotti(
        db_session, elementi={"modello": modello}
    )
    assert totale == 1
    assert per_modello[0].id == prodotto.id

    _righe, quante = products.cerca_prodotti(
        db_session,
        cliente_id=cliente.id,
        elementi={"tensione_uscita": "110"},
    )
    assert quante == 1

    # Due elementi insieme restringono ancora.
    _righe, quante = products.cerca_prodotti(
        db_session, elementi={"modello": modello, "potenza": "1100"}
    )
    assert quante == 1

    # Un valore che nessuno ha non trova niente, e non e' un errore.
    _righe, quante = products.cerca_prodotti(
        db_session, elementi={"modello": modello, "potenza": "999999"}
    )
    assert quante == 0


def test_i_valori_dei_filtri_sono_quelli_che_esistono_davvero(db_session):
    """Le tendine della ricerca si costruiscono sui valori presenti."""
    cliente = crea_cliente(db_session)
    primo = modello_irripetibile()
    secondo = modello_irripetibile()
    crea_prodotto(db_session, cliente=cliente, codice=f"{primo}1100-24-110SW")
    crea_prodotto(db_session, cliente=cliente, codice=f"{secondo}600-48-24XX")

    valori = products.valori_degli_elementi(db_session)

    assert primo in valori["modello"]
    assert secondo in valori["modello"]


def test_cambiando_il_codice_la_scomposizione_si_rifa(db_session):
    """code_parts e' un dato ricavato: quando cambia la fonte, si ricalcola."""
    cliente = crea_cliente(db_session)
    creatore = crea_creatore(db_session, "prova.capo.riscomposizione")
    prodotto, _v = crea_prodotto(
        db_session,
        cliente=cliente,
        codice="CODICE SENZA REGOLA " + modello_irripetibile(),
        autore=creatore,
    )
    assert prodotto.code_parts == {}

    modello = modello_irripetibile()
    products.modifica_prodotto(
        db_session,
        prodotto,
        codice=f"{modello}1100-24-110SW",
        cliente=cliente,
        descrizione=None,
        autore=creatore,
    )
    db_session.flush()

    assert prodotto.code_parts["modello"] == modello


def test_riscomporre_aggiorna_i_prodotti_gia_inseriti(db_session):
    """La funzione che servira' il giorno in cui la regola cambiera'."""
    cliente = crea_cliente(db_session)
    modello = modello_irripetibile()
    prodotto, _v = crea_prodotto(
        db_session, cliente=cliente, codice=f"{modello}1100-24-110SW"
    )

    prodotto.code_parts = {}
    db_session.flush()

    products.riscomponi(db_session, prodotto)

    assert prodotto.code_parts["modello"] == modello


# --- Le pagine --------------------------------------------------------------


def test_si_crea_un_prodotto_dall_interfaccia(client, db_session):
    """Il giro completo dal modulo, senza JavaScript.

    Il finto browser dei test non esegue JavaScript: se questo test passa,
    quella pagina funziona anche a script spento (D-036).
    """
    crea_creatore(db_session, "prova.capo.creazione")
    cliente = crea_cliente(db_session)
    entra(client, "prova.capo.creazione", PASSWORD_DI_PROVA)

    modello = modello_irripetibile()
    codice = f"{modello}1100-24-110SW"

    risposta = client.post(
        "/prodotti/nuovo",
        data={
            "codice": codice,
            "cliente": str(cliente.id),
            "descrizione": "Convertitore di prova.",
            "csrf": gettone_csrf(client, "/prodotti/nuovo"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert codice in testo
    assert "Tensione di ingresso" in testo, "la scomposizione deve comparire"
    assert modello in testo
    assert "1100" in testo

    creato = products.trova_per_codice(db_session, codice)
    assert creato is not None
    assert len(products.versioni_di(db_session, creato.id)) == 1


def test_un_codice_fuori_regola_si_crea_e_lo_dice(client, db_session):
    """Accettato, ma con la segnalazione visibile in pagina."""
    crea_creatore(db_session, "prova.capo.fuoriregola")
    cliente = crea_cliente(db_session)
    entra(client, "prova.capo.fuoriregola", PASSWORD_DI_PROVA)

    codice = "QUALCOSA DI DIVERSO " + modello_irripetibile()

    risposta = client.post(
        "/prodotti/nuovo",
        data={
            "codice": codice,
            "cliente": str(cliente.id),
            "descrizione": "",
            "csrf": gettone_csrf(client, "/prodotti/nuovo"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200, "il codice non va rifiutato"
    testo = contenuto_leggibile(risposta)
    assert "non corrisponde alla regola" in testo
    assert products.trova_per_codice(db_session, codice) is not None


def test_due_prodotti_non_possono_avere_lo_stesso_codice(client, db_session):
    """Il codice e' unico, e il rifiuto e' una frase italiana."""
    crea_creatore(db_session, "prova.capo.doppione")
    cliente = crea_cliente(db_session)
    codice = codice_irripetibile()
    prodotto, _v = crea_prodotto(db_session, cliente=cliente, codice=codice)
    entra(client, "prova.capo.doppione", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/prodotti/nuovo",
        data={
            "codice": codice.lower(),
            "cliente": str(cliente.id),
            "csrf": gettone_csrf(client, "/prodotti/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "gia' di un altro prodotto" in contenuto_leggibile(risposta)


def test_l_anteprima_del_codice_risponde_con_un_pezzo_di_pagina(client, db_session):
    """La rotta che alimenta l'anteprima mentre si scrive.

    Risponde con un frammento e non con una pagina intera: se rispondesse con
    una pagina, HTMX ne infilerebbe una dentro l'altra.
    """
    crea_creatore(db_session, "prova.capo.anteprima")
    entra(client, "prova.capo.anteprima", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/prodotti/anteprima-codice",
        data={
            "codice": CODICE_ESEMPIO,
            "csrf": gettone_csrf(client, "/prodotti/nuovo"),
        },
    )

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert "Tensione di uscita" in testo
    assert "110" in testo
    assert "<html" not in risposta.text.lower(), "e' un pezzo, non una pagina"


def test_l_anteprima_avvisa_quando_il_codice_non_si_scompone(client, db_session):
    crea_creatore(db_session, "prova.capo.anteprima2")
    entra(client, "prova.capo.anteprima2", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/prodotti/anteprima-codice",
        data={
            "codice": "NIENTE-DA-FARE",
            "csrf": gettone_csrf(client, "/prodotti/nuovo"),
        },
    )

    assert risposta.status_code == 200
    assert "non corrisponde alla regola" in contenuto_leggibile(risposta)


def test_un_utente_normale_legge_i_prodotti_ma_non_li_crea(client, db_session):
    """La lettura e' di tutti, la scrittura del creatore.

    Sapere che cosa fa l'azienda non e' un'informazione riservata; cambiare
    l'anagrafica si'.
    """
    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    assert client.get("/prodotti").status_code == 200
    assert client.get("/prodotti/nuovo").status_code == 403


def test_l_elenco_dei_prodotti_si_cerca_e_si_filtra(client, db_session):
    """La barra di ricerca funziona come modulo GET, senza JavaScript."""
    crea_creatore(db_session, "prova.capo.elenco")
    cliente = crea_cliente(db_session, nome="Ferrovie di prova")
    modello = modello_irripetibile()
    altro = modello_irripetibile()
    primo = f"{modello}1100-24-110SW"
    secondo = f"{altro}600-48-24XX"
    crea_prodotto(db_session, cliente=cliente, codice=primo)
    crea_prodotto(db_session, cliente=cliente, codice=secondo)
    entra(client, "prova.capo.elenco", PASSWORD_DI_PROVA)

    tutti = client.get(f"/prodotti?cliente={cliente.id}")
    assert primo in tutti.text
    assert secondo in tutti.text

    filtrati = client.get(f"/prodotti?cliente={cliente.id}&modello={modello}")
    assert primo in filtrati.text
    assert secondo not in filtrati.text


def test_un_indirizzo_scritto_male_non_produce_un_errore_tecnico(client, db_session):
    """?pagina=abc e ?cliente=qualcosa si comportano come se non ci fossero."""
    crea_creatore(db_session, "prova.capo.indirizzi")
    entra(client, "prova.capo.indirizzi", PASSWORD_DI_PROVA)

    risposta = client.get("/prodotti?pagina=abc&cliente=non-un-uuid&modello=")

    assert risposta.status_code == 200
