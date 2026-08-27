"""Test della guida in linea: le pagine, la ricerca, le icone «?».

    pytest tests/test_guida.py -v

**Il criterio di accettazione:** la guida si apre e la ricerca funziona.

Due gruppi di test meritano una parola prima di essere letti.

**Quelli sul Markdown** provano un trasformatore scritto a mano (D-085). Non
provano "che il Markdown funzioni" - il Markdown e' un formato, non una
libreria - ma che il **sottoinsieme deciso da noi** produca l'HTML che ci
aspettiamo, e soprattutto che quello che sta fuori da quel sottoinsieme
compaia lo stesso come testo normale invece di sparire.

**Quelli sulle icone «?»** leggono le destinazioni vere e verificano che ogni
ancora esista davvero dentro la pagina che dice. E' il test che rende sicuro
rinominare un titolo della guida: chi lo fa scopre subito quali collegamenti ha
rotto, invece di scoprirlo un anno dopo quando qualcuno preme il punto
interrogativo e finisce in cima alla pagina sbagliata.
"""

import uuid

import pytest

from app.models import GlobalRole
from app.services import guida
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_utente,
    entra,
)


def utente_qualunque(db):
    """Una persona senza nessun ruolo speciale: la guida la vedono tutti."""
    return crea_utente(db, username=f"prova.guida.{uuid.uuid4().hex[:8]}")


# ===========================================================================
#  1. LE PAGINE CI SONO E SI LEGGONO
# ===========================================================================


def test_ci_sono_tutte_le_pagine_che_la_sessione_ha_chiesto():
    """L'elenco chiesto dall'azienda, scritto qui una seconda volta apposta.

    Se un giorno qualcuno togliesse un file dalla cartella della guida
    credendo che non servisse, questo test direbbe che invece era stato
    promesso.
    """
    nomi = {pagina.nome for pagina in guida.pagine()}

    promesse = {
        "primi-passi",
        "caricare-un-documento",
        "versioni-e-stati",
        "far-avanzare-un-progetto",
        "oggetto-delle-email",
        "messaggi-in-quarantena",
        "chi-vede-che-cosa",
        "glossario",
    }
    mancanti = promesse - nomi
    assert mancanti == set(), f"pagine di guida promesse e mancanti: {mancanti}"


def test_ogni_pagina_ha_un_titolo_un_sommario_e_delle_sezioni():
    """Senza il sommario l'indice non dice di che cosa parla una pagina."""
    for pagina in guida.pagine():
        assert pagina.titolo, f"la pagina {pagina.nome} non ha titolo"
        assert pagina.sommario, f"la pagina {pagina.nome} non ha sommario"
        assert pagina.sezioni, f"la pagina {pagina.nome} non ha sezioni"
        assert pagina.html, f"la pagina {pagina.nome} e' vuota"


def test_le_pagine_sono_in_ordine():
    """L'ordine lo da' il numero nel nome del file, non l'alfabeto."""
    ordini = [pagina.ordine for pagina in guida.pagine()]
    assert ordini == sorted(ordini)
    assert ordini[0] == 1, "la prima pagina dev'essere «primi passi»"


def test_il_numero_del_file_non_finisce_nell_indirizzo():
    """Riordinare la guida non deve rompere i collegamenti gia' scritti."""
    for pagina in guida.pagine():
        assert not pagina.nome[0].isdigit(), (
            f"l'indirizzo della pagina «{pagina.nome}» contiene il numero del "
            "file: riordinandola cambierebbe indirizzo"
        )


def test_una_pagina_che_non_esiste_e_None():
    assert guida.pagina("non-esiste-questa") is None


@pytest.mark.parametrize(
    "cattivo",
    ["../../.env", "..\\..\\.env", "/etc/passwd", "primi passi", "PRIMI-PASSI!"],
)
def test_un_nome_di_pagina_storto_non_apre_niente(cattivo):
    """Il nome arriva dall'indirizzo, quindi da fuori.

    Senza il controllo sulla forma, un nome con dentro due punti
    trasformerebbe la guida in un modo di leggere qualunque file del server.
    """
    assert guida.pagina(cattivo) is None


# ===========================================================================
#  2. DAL MARKDOWN ALL'HTML
# ===========================================================================


def componi(sorgente: str) -> str:
    """Il corpo HTML di un pezzo di Markdown, senza passare da un file."""
    return guida._componi(nome="prova", ordine=1, sorgente=sorgente).html


def test_i_titoli_diventano_intestazioni_con_la_loro_ancora():
    corpo = componi("## Come si carica\n\ntesto\n")

    assert '<h2 id="come-si-carica">Come si carica</h2>' in corpo


def test_il_titolo_di_primo_livello_non_si_ripete_nel_corpo():
    """Lo disegna gia' il template, nella testata della pagina."""
    corpo = componi("# Titolo della pagina\n\ntesto\n")

    assert "Titolo della pagina" not in corpo
    assert "<p>testo</p>" in corpo


def test_le_righe_contigue_diventano_un_paragrafo_solo():
    """Un a capo dentro un paragrafo del file non e' un a capo nella pagina."""
    corpo = componi("prima riga\nseconda riga\n\naltro paragrafo\n")

    assert "<p>prima riga seconda riga</p>" in corpo
    assert "<p>altro paragrafo</p>" in corpo


def test_gli_elenchi_puntati_e_numerati():
    corpo = componi("- uno\n- due\n\n1. primo\n2. secondo\n")

    assert "<ul><li>uno</li><li>due</li></ul>" in corpo
    assert "<ol><li>primo</li><li>secondo</li></ol>" in corpo


def test_grassetto_corsivo_e_codice():
    corpo = componi("una parola **grossa**, una *storta* e un `comando`\n")

    assert "<strong>grossa</strong>" in corpo
    assert "<em>storta</em>" in corpo
    assert "<code>comando</code>" in corpo


def test_un_asterisco_dentro_il_codice_non_diventa_un_corsivo():
    """Il codice si riconosce per primo, ed e' il motivo per cui lo fa."""
    corpo = componi("scrivi `SELECT * FROM x` e premi invio\n")

    assert "<code>SELECT * FROM x</code>" in corpo
    assert "<em>" not in corpo


def test_le_tabelle_escono_con_le_classi_di_aurora():
    """Una tabella nella guida deve somigliare alle tabelle del programma."""
    corpo = componi("| Stato | Vuol dire |\n|---|---|\n| bozza | ci si lavora |\n")

    assert 'class="tabella"' in corpo
    assert '<th scope="col">Stato</th>' in corpo
    assert "<td>bozza</td>" in corpo


def test_i_blocchi_di_codice_non_vengono_formattati():
    corpo = componi("```\nalembic upgrade head\n**non e' grassetto**\n```\n")

    assert "<pre><code>" in corpo
    assert "**non e' grassetto**" in corpo
    assert "<strong>" not in corpo


def test_le_citazioni_diventano_blockquote():
    corpo = componi("> una frase riportata\n")
    assert "<blockquote><p>una frase riportata</p></blockquote>" in corpo


def test_l_html_dentro_il_testo_diventa_innocuo():
    """Anche se i file della guida sono nostri.

    Un giorno qualcuno ci incollera' dentro un messaggio di errore vero, e
    quel giorno non deve succedere niente.
    """
    corpo = componi("attenzione a <script>alert(1)</script> e a <b>questo</b>\n")

    assert "<script>" not in corpo
    assert "&lt;script&gt;" in corpo
    assert "<b>" not in corpo


def test_i_collegamenti_dentro_aurora_funzionano():
    corpo = componi("vedi [la quarantena](/aiuto/messaggi-in-quarantena)\n")

    assert '<a href="/aiuto/messaggi-in-quarantena">la quarantena</a>' in corpo


def test_un_collegamento_a_internet_resta_solo_testo():
    """Aurora deve funzionare con la connessione staccata (regola 1).

    Un collegamento a un sito esterno dentro la guida e' una promessa che non
    si puo' mantenere: resta scritto il testo, sparisce il collegamento.
    """
    corpo = componi("vedi [il sito](https://esempio.example/pagina)\n")

    assert "il sito" in corpo
    assert "esempio.example" not in corpo
    assert "<a href=" not in corpo


def test_una_riga_che_il_programma_non_conosce_non_sparisce():
    """Una guida che perde una riga e' peggio di una guida con una riga brutta."""
    corpo = componi("::: qualcosa che non e' Markdown di Aurora :::\n")

    assert "qualcosa che non e" in corpo


def test_un_blocco_di_codice_mai_chiuso_non_perde_il_contenuto():
    """La riga che manca e' un difetto del file, non un motivo per perdere testo."""
    corpo = componi("prima\n\n```\nalembic upgrade head\n")

    assert "alembic upgrade head" in corpo


# ===========================================================================
#  3. LA RICERCA
# ===========================================================================


def test_la_ricerca_trova_una_parola_del_testo():
    risultati = guida.cerca("quarantena")

    assert risultati, "«quarantena» deve trovare qualcosa"
    assert any(
        esito.pagina.nome == "messaggi-in-quarantena" for esito in risultati
    )


def test_la_ricerca_vuole_tutte_le_parole_scritte():
    """Chi scrive due parole cerca la pagina che parla di tutte e due."""
    insieme = {esito.pagina.nome for esito in guida.cerca("quarantena versione")}
    solo_una = {esito.pagina.nome for esito in guida.cerca("quarantena")}

    assert insieme <= solo_una, (
        "cercando due parole non si possono trovare piu' pagine che cercandone una"
    )


def test_la_ricerca_non_distingue_maiuscole_e_minuscole():
    assert guida.cerca("QUARANTENA")
    assert guida.cerca("Quarantena")


def test_la_ricerca_trova_anche_quello_che_e_scritto_in_grassetto():
    """Chi cerca non sa - e non deve sapere - come sono scritti i file."""
    pagina = guida.pagina("versioni-e-stati")

    assert "**" not in pagina.testo, (
        "il testo su cui si cerca deve essere senza i segni del Markdown"
    )


def test_chi_cerca_riceve_il_pezzo_di_testo_intorno_alla_parola():
    """Serve a capire se e' la pagina giusta senza doverla aprire."""
    risultati = guida.cerca("quarantena")

    assert risultati[0].contesto
    assert "quarantena" in risultati[0].contesto.lower()


def test_una_ricerca_vuota_non_trova_niente():
    assert guida.cerca("") == []
    assert guida.cerca("   ") == []


def test_una_parola_che_non_c_e_non_trova_niente():
    assert guida.cerca("zxqwvfmpk") == []


def test_le_pagine_con_la_parola_nel_titolo_vengono_prima():
    """L'ordinamento e' semplice apposta, ma c'e'."""
    risultati = guida.cerca("glossario")

    assert risultati, "«glossario» deve trovare la pagina che si chiama cosi'"
    assert risultati[0].pagina.nome == "glossario"


# ===========================================================================
#  4. LE PAGINE NEL BROWSER
# ===========================================================================


def test_la_guida_la_vede_chiunque_sia_entrato(client, db_session):
    """Non e' riservata: spiega come si usa il programma."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    assert client.get("/aiuto").status_code == 200
    assert client.get("/aiuto/primi-passi").status_code == 200


def test_la_guida_chiede_di_entrare_a_chi_non_e_entrato(client, db_session):
    risposta = client.get("/aiuto", follow_redirects=False)

    assert risposta.status_code == 303
    assert "/entra" in risposta.headers["location"]


def test_l_indice_elenca_tutte_le_pagine(client, db_session):
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    testo = contenuto_leggibile(client.get("/aiuto"))
    for pagina in guida.pagine():
        assert pagina.titolo in testo, f"nell'indice manca «{pagina.titolo}»"


def test_la_ricerca_funziona_anche_senza_javascript(client, db_session):
    """E' un modulo GET: si preme Invio e la pagina si ricarica filtrata."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    risposta = client.get("/aiuto?q=quarantena")

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert "Messaggi in quarantena" in testo
    assert "Trovato in" in testo


def test_la_ricerca_senza_risultati_lo_dice_e_lascia_l_indice(client, db_session):
    """Chi non trova niente deve avere l'indice da cui ripartire."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    testo = contenuto_leggibile(client.get("/aiuto?q=zxqwvfmpk"))

    assert "Nessuna pagina parla di" in testo
    assert "Tutte le pagine" in testo, "l'indice deve restare"


def test_htmx_riceve_solo_il_pezzo_dei_risultati(client, db_session):
    """Non una pagina intera dentro un'altra pagina."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    risposta = client.get(
        "/aiuto?q=quarantena", headers={"HX-Request": "true"}
    )

    assert risposta.status_code == 200
    assert "<!DOCTYPE html>" not in risposta.text
    assert 'id="risultati-guida"' in risposta.text


def test_una_pagina_della_guida_mostra_il_suo_indice(client, db_session):
    """Le sezioni in colonna, per saltare al punto."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    testo = contenuto_leggibile(client.get("/aiuto/versioni-e-stati"))

    assert "In questa pagina" in testo
    assert "Gli stati di un documento" in testo


def test_una_pagina_che_non_esiste_dice_dove_sta_l_indice(client, db_session):
    """Chi ci arriva viene quasi sempre da un'icona «?» rimasta indietro."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    risposta = client.get("/aiuto/questa-non-esiste")

    assert risposta.status_code == 404
    assert "/aiuto" in contenuto_leggibile(risposta)


def test_la_voce_aiuto_compare_nella_barra_laterale(client, db_session):
    """E' l'unica voce di servizio che vedono tutti."""
    entra(client, utente_qualunque(db_session).username, PASSWORD_DI_PROVA)

    testo = client.get("/").text
    assert 'href="/aiuto"' in testo


# ===========================================================================
#  5. LE ICONE «?»
# ===========================================================================


def test_ogni_icona_punta_a_una_pagina_che_esiste():
    """Un'icona che non porta da nessuna parte e' peggio di un'icona assente."""
    rotti = []
    for chiave, (nome, _ancora, _spiegazione) in guida.AIUTI.items():
        if guida.pagina(nome) is None:
            rotti.append((chiave, nome))

    assert rotti == [], f"queste icone «?» puntano a pagine che non esistono: {rotti}"


def test_ogni_icona_punta_a_una_sezione_che_esiste():
    """E' il test che rende sicuro rinominare un titolo della guida.

    Chi lo rinomina scopre subito quali collegamenti ha rotto, invece di
    scoprirlo un anno dopo quando qualcuno preme il punto interrogativo e
    finisce in cima alla pagina sbagliata.
    """
    rotti = []
    for chiave, (nome, ancora, _spiegazione) in guida.AIUTI.items():
        pagina = guida.pagina(nome)
        if pagina is None:
            continue
        if not any(sezione.ancora == ancora for sezione in pagina.sezioni):
            disponibili = [sezione.ancora for sezione in pagina.sezioni]
            rotti.append((chiave, f"{nome}#{ancora}", disponibili))

    assert rotti == [], (
        f"queste icone «?» puntano a sezioni che non esistono piu': {rotti}"
    )


def test_ogni_icona_ha_una_spiegazione():
    """E' il testo del suggerimento e quello che leggono i lettori di schermo."""
    for chiave, (_nome, _ancora, spiegazione) in guida.AIUTI.items():
        assert spiegazione.strip(), f"l'icona «{chiave}» non ha spiegazione"


def test_una_chiave_sconosciuta_non_fa_cadere_la_pagina():
    """Si risponde con esiste=False e il componente non disegna niente."""
    esito = guida.aiuto("questa-chiave-non-esiste")

    assert esito.esiste is False
    assert esito.indirizzo == "/aiuto"


def test_nessun_template_scrive_a_mano_un_indirizzo_della_guida():
    """Le destinazioni stanno in guida.AIUTI e in nessun altro posto.

    Un template che scrivesse a mano `/aiuto/versioni-e-stati#gli-stati...`
    sarebbe un collegamento che nessuno si accorgerebbe di aver rotto
    rinominando un titolo: il test qui sopra non lo vedrebbe.
    """
    import pathlib
    import re

    radice = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"

    # Due posti sono esenti, e per due ragioni diverse. Le pagine della guida
    # compongono i propri collegamenti **dai dati veri** - il nome della pagina
    # e l'ancora della sezione arrivano da guida.py, quindi non possono essere
    # sbagliati. Il componente che disegna il punto interrogativo nomina un
    # indirizzo dentro il commento che spiega perche' non bisogna scriverne.
    esenti = {radice / "components" / "aiuto.html"}
    esenti |= set((radice / "aiuto").glob("*.html"))

    # Un indirizzo scritto per esteso: lettere e trattini, non una variabile.
    scritto_a_mano = re.compile(r"/aiuto/[a-z-]+#[a-z0-9-]+")

    colpevoli = []
    for percorso in radice.rglob("*.html"):
        if percorso in esenti:
            continue
        for riga in percorso.read_text(encoding="utf-8").splitlines():
            if scritto_a_mano.search(riga):
                colpevoli.append((percorso.name, riga.strip()[:70]))

    assert colpevoli == [], (
        f"questi template scrivono a mano un indirizzo della guida: {colpevoli}. "
        "Si usa il macro aiuto(\"chiave\"), e la destinazione sta in guida.AIUTI"
    )


def test_le_icone_compaiono_dove_devono(client, db_session):
    """Un paio di posti veri, per essere sicuri che il macro sia agganciato."""
    from app.models import GlobalRole as Ruoli

    creatore = crea_utente(
        db_session,
        username=f"prova.icone.{uuid.uuid4().hex[:8]}",
        ruolo=Ruoli.CREATORE,
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    testo = client.get("/posta/quarantena").text
    assert "punto-aiuto" in testo, (
        "sulla pagina della quarantena manca il punto interrogativo"
    )
    assert "/aiuto/messaggi-in-quarantena#" in testo


def test_il_punto_interrogativo_dice_a_che_cosa_serve(client, db_session):
    """Ai lettori di schermo, non "punto interrogativo"."""
    creatore = crea_utente(
        db_session,
        username=f"prova.vocale.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    testo = contenuto_leggibile(client.get("/posta/quarantena"))
    assert "Aiuto: Perche' un messaggio finisce in quarantena" in testo
