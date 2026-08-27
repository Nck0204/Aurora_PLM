"""Test dell'interfaccia: sistema grafico, barra laterale, vetrina /stile.

Sono i test della sessione 4. Verificano tre famiglie di cose diverse.

**Le regole del foglio di stile.** Che nessun colore sia scritto a mano fuori
dalle variabili, ne' nel CSS ne' nei template. E' una regola che si viola per
distrazione, non per scelta: nessuno decide di scrivere `#4a9eff` dentro un
componente, ci si arriva copiando una riga. Un test la fa notare il giorno
stesso invece che alla sessione 9.

**Il menu filtrato per ruolo.** Che chi non e' creatore non veda le voci
riservate. Non e' il controllo che protegge - quello e' `richiedi_creatore` -
ma e' quello che evita di andare a sbattere.

**Il funzionamento senza JavaScript.** E' il criterio di accettazione piu'
importante di questa sessione, ed e' anche quello che si perde piu' facilmente:
basta che una sessione futura sostituisca un modulo con una finestra modale.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import navigation, templating
from app.config import PROJECT_ROOT
from app.models import GlobalRole
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_utente,
    entra,
    gettone_csrf,
)

CARTELLA_TEMPLATE = PROJECT_ROOT / "app" / "templates"
FOGLIO_DI_STILE = PROJECT_ROOT / "app" / "static" / "css" / "aurora.css"

# Un colore scritto per esteso: #fff, #4a9eff, rgb(...), hsl(...).
#
# Il "(?<!&)" davanti serve a non prendere le entita' HTML come &#9650; (la
# freccina dell'ordinamento), che cominciano per & e non sono colori.
COLORE_SCRITTO = re.compile(
    r"(?<!&)#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])|\brgba?\s*\(|\bhsla?\s*\("
)


# Le pagine di errore arrivano in HTML solo a chi dichiara di accettarlo: a un
# programma che chiama una rotta risponde invece un JSON, che e' piu' facile da
# trattare (vedi wants_html in app/main.py). I test che guardano la pagina
# devono quindi presentarsi come si presenta un browser.
COME_UN_BROWSER = {"accept": "text/html,application/xhtml+xml"}


def crea_creatore(db, username: str = "prova.capo.stile"):
    """Un utente con il ruolo di creatore, per le pagine riservate."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


# --- Il foglio di stile -----------------------------------------------------


def test_i_colori_stanno_tutti_nelle_variabili():
    """Fuori dal blocco :root non c'e' nemmeno un colore scritto per esteso.

    E' la regola su cui poggia tutto il resto: cambiare la tinta di Aurora deve
    voler dire cambiare una riga sola. Se un colore finisce dentro un
    componente, quella riga smette di bastare e nessuno se ne accorge finche'
    non prova a cambiarla.
    """
    css = FOGLIO_DI_STILE.read_text(encoding="utf-8")

    inizio = css.index(":root {")
    fine = css.index("}", inizio)
    fuori_dalle_variabili = css[:inizio] + css[fine:]

    trovati = COLORE_SCRITTO.findall(fuori_dalle_variabili)

    assert not trovati, (
        "colori scritti a mano fuori da :root: "
        f"{trovati}. Vanno dichiarati come variabili in cima al foglio."
    )


def test_nessun_colore_scritto_dentro_i_template():
    """Nei template non si scrivono colori: si usano le classi.

    Vale per tutti, vetrina /stile compresa: quella mostra la palette
    richiamando le variabili per nome, non ricopiandone il valore.
    """
    colpevoli = []

    for file_html in CARTELLA_TEMPLATE.rglob("*.html"):
        testo = file_html.read_text(encoding="utf-8")
        for numero, riga in enumerate(testo.splitlines(), start=1):
            if COLORE_SCRITTO.search(riga):
                percorso = file_html.relative_to(CARTELLA_TEMPLATE)
                colpevoli.append(f"{percorso}:{numero}  {riga.strip()}")

    assert not colpevoli, "colori scritti dentro i template:\n" + "\n".join(colpevoli)


def test_il_foglio_di_stile_viene_servito_da_noi(client: TestClient):
    """Nessuna CDN: il foglio di stile lo serve questo programma."""
    risposta = client.get("/static/css/aurora.css")

    assert risposta.status_code == 200
    assert "--colore-accento" in risposta.text


def test_htmx_e_nel_repository_e_lo_serviamo_noi(client: TestClient):
    """HTMX sta in app/static/vendor/ e arriva dal nostro server.

    Se un giorno qualcuno lo sostituisse con un collegamento a unpkg.com,
    Aurora si presenterebbe senza interattivita' il primo giorno in cui il
    server aziendale resta senza internet. Questo test lo impedisce.
    """
    risposta = client.get("/static/vendor/htmx.min.js")

    assert risposta.status_code == 200
    assert "htmx" in risposta.text[:200]


def test_nessun_template_punta_a_un_indirizzo_esterno():
    """Regola 1 di CLAUDE.md: niente risorse caricate da fuori."""
    colpevoli = []

    for file_html in CARTELLA_TEMPLATE.rglob("*.html"):
        testo = file_html.read_text(encoding="utf-8")
        for pezzo in ('src="http', "src='http", 'href="http', "href='http"):
            if pezzo in testo:
                colpevoli.append(str(file_html.relative_to(CARTELLA_TEMPLATE)))
                break

    assert not colpevoli, f"template che caricano da fuori: {colpevoli}"


# --- La barra laterale ------------------------------------------------------


def test_il_menu_mostra_le_voci_riservate_solo_al_creatore(client, db_session):
    """Chi non e' creatore non vede "Utenti" nella barra laterale."""
    crea_creatore(db_session)
    crea_utente(db_session, username="prova.mario.rossi")

    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)
    normale = client.get("/").text

    assert 'href="/utenti"' not in normale
    assert 'href="/stile"' not in normale


def test_il_creatore_vede_le_voci_riservate(client, db_session):
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    pagina = client.get("/").text

    assert 'href="/utenti"' in pagina
    assert 'href="/stile"' in pagina


def test_non_ci_sono_piu_sezioni_spente(client, db_session):
    """Dalla sessione 12 tutte le voci del menu portano da qualche parte.

    **Questo test ha cambiato bersaglio a ogni sezione realizzata**: fino alla
    4 guardava "Prodotti", dalla 5 alla 6 "Documenti", dalla 7 alla 9 "Posta",
    dalla 10 alla 11 "Diagnostica". La sessione 12 ha acceso l'ultima luce, e
    da allora il test dice un'altra cosa: che non ne e' rimasta nessuna spenta.

    Se una sessione futura aggiungera' una voce ancora da fare, questo test
    diventera' rosso e chi lo legge dovra' decidere fra due cose: e' una voce
    spenta per **scelta** (e allora si aggiunge qui il suo nome), oppure e'
    rimasta spenta per **dimenticanza** (e allora si toglie `attiva=False`).
    E' esattamente la domanda che il test serviva a far fare.

    Il meccanismo con cui una voce spenta si disegna - uno <span> e non un
    <a> - resta provato dal test qui sotto.
    """
    spente = [
        voce.etichetta
        for voce in navigation.MENU_PRINCIPALE + navigation.MENU_SERVIZIO
        if not voce.attiva
    ]

    assert spente == [], (
        f"queste voci di menu sono ancora spente: {spente}. Se e' una scelta, "
        "vanno elencate qui; se e' una dimenticanza, va tolto attiva=False"
    )


def test_una_voce_spenta_si_vede_ma_non_si_puo_premere(
    client, db_session, monkeypatch
):
    """Le voci spente sono <span> e non <a>, e lo dicono anche a chi non vede.

    La tastiera non ci si ferma, perche' non c'e' niente da aprire; dire "in
    arrivo" e' piu' onesto che nascondere.

    Non essendoci piu' nessuna voce spenta nel menu vero (vedi il test qui
    sopra), il meccanismo si prova aggiungendone una finta. E' l'unico modo
    che resta di verificarlo, ed e' meglio di lasciarlo senza prova: la
    prossima sessione che ne spegnera' una si aspetta che funzioni.
    """
    finta = navigation.VoceMenu(
        etichetta="Distinte base",
        percorso="/distinte",
        icona="prodotti",
        attiva=False,
        nota="rilascio R3",
    )
    monkeypatch.setattr(
        templating, "MENU_PRINCIPALE", navigation.MENU_PRINCIPALE + (finta,)
    )

    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    pagina = client.get("/").text

    assert "Distinte base" in pagina, "la voce spenta si deve comunque vedere"
    assert 'href="/distinte"' not in pagina, "ma non deve essere un collegamento"
    assert 'aria-disabled="true"' in pagina
    assert "rilascio R3" in pagina, "la nota dice quando arrivera'"


def test_la_voce_del_menu_resta_accesa_nelle_sottopagine(client, db_session):
    """Stando su /utenti/nuovo, la voce "Utenti" e' ancora quella corrente."""
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    pagina = client.get("/utenti/nuovo").text

    assert 'aria-current="page"' in pagina
    assert "menu-voce--corrente" in pagina


# --- La vetrina /stile ------------------------------------------------------


def test_la_vetrina_e_riservata_al_creatore(client, db_session):
    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.get("/stile", headers=COME_UN_BROWSER)

    assert risposta.status_code == 403
    assert "riservata" in contenuto_leggibile(risposta)


def test_la_vetrina_chiede_di_entrare_a_chi_non_e_entrato(client, db_session):
    risposta = client.get("/stile", follow_redirects=False)

    assert risposta.status_code == 303
    assert risposta.headers["location"].startswith("/entra")


@pytest.mark.parametrize(
    "componente",
    [
        "pulsante--primario",
        "pulsante--pericolo",
        "campo-errore",
        "campo-spunta",
        "tabella-contenitore",
        "riga-vuota",
        "etichetta--rilasciato",
        "etichetta--obsoleto",
        "etichetta--attenzione",
        "riquadro-testata",
        "dialogo",
        "notifica",
        "ricerca-campo",
        "impaginazione-voce",
        "scheda-corpo",
        "avanzamento-fase",
        "descrizione",
        "area-file",
        "barra-caricamento",
        "vuoto",
        "avviso--errore",
        # Aggiunti dalla sessione 9, insieme al registro delle operazioni.
        "ricerca-date",
        "registro-dettaglio",
    ],
)
def test_la_vetrina_mostra_tutti_i_componenti(client, db_session, componente):
    """Ogni componente compare in vetrina.

    E' il criterio di accettazione della sessione 4: /stile e' il riferimento
    delle sessioni successive, e un componente che non c'e' non lo trova
    nessuno e viene riscritto da capo.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    pagina = client.get("/stile")

    assert pagina.status_code == 200
    assert componente in pagina.text, f"'{componente}' non compare in vetrina"


def test_la_ricerca_della_vetrina_funziona_anche_senza_htmx(client, db_session):
    """La casella di ricerca e' un modulo GET: senza JavaScript filtra lo stesso.

    HTMX si limita a sostituire il pezzo di tabella. Se non arrivasse, si preme
    Invio e la pagina si ricarica filtrata: e' cosi' che va usato dappertutto
    in Aurora.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    pagina = client.get("/stile?q=alimentatore")

    assert pagina.status_code == 200
    assert "ALI-B220-R01" in pagina.text
    assert "SCH-A100-R02" not in pagina.text


def test_il_pezzo_di_pagina_per_htmx_non_e_una_pagina_intera(client, db_session):
    """La risposta di /stile/esempio-ricerca e' un frammento, non un documento.

    E' la forma che avranno tutte le risposte HTMX di Aurora: quello che torna
    va infilato dentro un elemento che gia' esiste, quindi non deve portarsi
    dietro <html> e <body>.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    risposta = client.get("/stile/esempio-ricerca?q=sensore")

    assert risposta.status_code == 200
    assert "<html" not in risposta.text
    assert "SEN-C310-R01" in risposta.text
    assert "ALI-B220-R01" not in risposta.text


# --- Funzionamento senza JavaScript -----------------------------------------


def test_la_pagina_di_accesso_non_ha_bisogno_di_javascript(client, db_session):
    """Criterio di accettazione: con JavaScript spento si entra lo stesso.

    Il modulo di accesso e' un <form method="post"> senza nessun attributo
    HTMX: quello che lo invia e' il browser, non uno script. La pagina non
    carica nemmeno un file JavaScript.
    """
    pagina = client.get("/entra")

    assert pagina.status_code == 200
    assert '<form method="post" action="/entra"' in pagina.text
    assert "hx-" not in pagina.text, "l'accesso non deve dipendere da HTMX"
    assert "<script" not in pagina.text, "l'accesso non carica nessuno script"


def test_si_entra_davvero_senza_javascript(client, db_session):
    """Il giro completo dell'accesso, fatto con il solo modulo.

    Il finto browser dei test non esegue JavaScript: se questo passa, passa
    anche con lo script disattivato nel browser vero.
    """
    crea_utente(db_session, username="prova.mario.rossi")

    risposta = entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    assert risposta.status_code == 303
    assert client.get("/").status_code == 200


def test_si_crea_un_utente_senza_javascript(client, db_session):
    """Anche la creazione di un utente e' un modulo normale.

    Nessuna finestra modale, nessuna chiamata scritta a mano: si compila e si
    invia. Il modulo non ha attributi HTMX.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    modulo = client.get("/utenti/nuovo")
    assert '<form method="post" action="/utenti/nuovo"' in modulo.text
    assert "hx-" not in modulo.text

    risposta = client.post(
        "/utenti/nuovo",
        data={
            "first_name": "Giulia",
            "last_name": "Neri",
            "email": "giulia.neri@esempio.local",
            "ruolo": "utente",
            "csrf": gettone_csrf(client, "/utenti/nuovo"),
        },
    )

    assert risposta.status_code == 200
    assert 'id="password-assegnata"' in risposta.text


def test_ogni_campo_ha_la_sua_etichetta_collegata(client, db_session):
    """Accessibilita': for e id si corrispondono, in ogni modulo.

    Un campo senza etichetta collegata e' un campo che chi usa un lettore di
    schermo non sa che cosa contenga. Il controllo si fa qui una volta per
    tutte perche' i macro di components/campi.html lo garantiscono: se qualcuno
    scrivesse un <input> a mano dimenticandosi l'etichetta, questo test lo
    fermerebbe.
    """
    crea_creatore(db_session)
    entra(client, "prova.capo.stile", PASSWORD_DI_PROVA)

    for percorso in ("/entra", "/cambio-password", "/utenti/nuovo", "/stile"):
        testo = client.get(percorso).text

        etichettati = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', testo))
        # Si guardano i campi che l'utente compila: i nascosti non hanno
        # etichetta e non devono averla.
        campi = set(
            re.findall(
                r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', testo
            )
        )
        nascosti = set(
            re.findall(r'<input[^>]*type="hidden"[^>]*\bid="([^"]+)"', testo)
        )

        senza_etichetta = campi - etichettati - nascosti

        assert not senza_etichetta, (
            f"in {percorso} questi campi non hanno un'etichetta collegata: "
            f"{sorted(senza_etichetta)}"
        )


# --- Pagine di errore -------------------------------------------------------


def test_la_pagina_404_e_nel_tema(client, db_session):
    """L'indirizzo sbagliato porta a una pagina scura come tutte le altre."""
    risposta = client.get("/questo-indirizzo-non-c-e-mai-stato", headers=COME_UN_BROWSER)

    assert risposta.status_code == 404
    assert "pagina-errore" in risposta.text
    assert "/static/css/aurora.css" in risposta.text
    assert "Torna alla pagina iniziale" in risposta.text


def test_la_pagina_di_accesso_negato_e_nel_tema(client, db_session):
    """Il 403 si distingue a colpo d'occhio dal 500: e' giallo, non rosso."""
    crea_utente(db_session, username="prova.mario.rossi")
    entra(client, "prova.mario.rossi", PASSWORD_DI_PROVA)

    risposta = client.get("/utenti", headers=COME_UN_BROWSER)

    assert risposta.status_code == 403
    assert "pagina-errore--negato" in risposta.text
    assert "pagina-errore--guasto" not in risposta.text


def test_la_pagina_di_errore_non_mostra_dettagli_tecnici(client, db_session):
    """Sulla pagina di errore non compare mai niente di tecnico."""
    risposta = client.get("/questo-indirizzo-non-c-e-mai-stato", headers=COME_UN_BROWSER)

    for parola in ("Traceback", "Exception", "File \"", "sqlalchemy"):
        assert parola not in risposta.text
