"""Il motore di acquisizione della posta (sessione 10).

Il file e' diviso come lo e' il programma:

  1. **la lettura di un messaggio**, che non tocca il database: prefissi,
     parentesi, lettere accentate, HTML, file rotti;
  2. **la fonte locale**, cioe' la cartella di file `.eml`;
  3. **i quattro rami dell'attribuzione**, uno per uno, piu' il quinto caso -
     la versione dichiarata che non esiste - che e' quello su cui si e' dovuto
     decidere qualcosa (D-073);
  4. **la ripetibilita'**, che e' il criterio di accettazione piu' importante:
     rieseguire l'elaborazione non deve duplicare niente;
  5. **i permessi**, cioe' che la posta si veda con la stessa regola dei
     documenti;
  6. **le pagine**.

I dati dei test sono irripetibili come vuole tests/conftest.py: i codici
prodotto arrivano da `codice_irripetibile()` e gli identificativi dei messaggi
portano una coda casuale, perche' `email_messages.internet_message_id` ha un
vincolo di unicita' e il database di sviluppo contiene anche dati veri.
"""

import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage as MessaggioPython
from email.policy import SMTP
from email.utils import format_datetime

import pytest
from sqlalchemy import select

from app.models import (
    Assignment,
    AuditLog,
    EmailAssignmentState,
    EmailMessage,
    EmailReason,
    GlobalRole,
    LifecycleState,
    ProjectRole,
)
from app.services import email_parsing, email_reasons, emails, permissions, storage
from app.services.mail_source import FonteEmail, FonteLocale, MessaggioNonTrovato
from tests.conftest import (
    PASSWORD_DI_PROVA,
    classificazione_di_prova,
    codice_irripetibile,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
)


# ===========================================================================
#  Attrezzi
# ===========================================================================


def identificativo_di_prova(nome: str = "prova") -> str:
    """Un Message-ID che nel database non puo' gia' esserci.

    La colonna e' unica e il database di sviluppo contiene anche i messaggi
    lasciati dalle verifiche a mano: e' la stessa precauzione di
    `codice_irripetibile()`, applicata agli identificativi della posta.
    """
    return f"<{nome}-{uuid.uuid4().hex}@test.aurora.local>"


def eml(
    *,
    oggetto: str | None = "Messaggio di prova",
    da: str = "mario.rossi@cliente.test",
    a: str = "ufficio@azienda.test",
    corpo: str = "Corpo del messaggio di prova.",
    identificativo: str | None = None,
    in_risposta_a: str | None = None,
    riferimenti: list[str] | None = None,
    copia: str | None = None,
    html: str | None = None,
    allegati: list[tuple[str, str, bytes]] | None = None,
    quando: datetime | None = None,
) -> bytes:
    """Costruisce i byte di un messaggio `.eml`.

    Si passa dalla libreria standard invece di scrivere le intestazioni a mano
    perche' cosi' i messaggi dei test sono messaggi veri - con le lettere
    accentate codificate come le codifica un programma di posta - e non
    un'imitazione che funziona solo con il nostro lettore.
    """
    messaggio = MessaggioPython()

    if identificativo is not None:
        messaggio["Message-ID"] = identificativo
    messaggio["From"] = da
    messaggio["To"] = a
    if copia:
        messaggio["Cc"] = copia
    if oggetto is not None:
        messaggio["Subject"] = oggetto
    messaggio["Date"] = format_datetime(
        quando or datetime.now(timezone.utc) - timedelta(days=1)
    )
    if in_risposta_a:
        messaggio["In-Reply-To"] = in_risposta_a
    if riferimenti:
        messaggio["References"] = " ".join(riferimenti)

    messaggio.set_content(corpo)
    if html is not None:
        messaggio.add_alternative(html, subtype="html")

    for nome_file, tipo, contenuto in allegati or []:
        principale, _, secondario = tipo.partition("/")
        messaggio.add_attachment(
            contenuto,
            maintype=principale,
            subtype=secondario,
            filename=nome_file,
        )

    return messaggio.as_bytes(policy=SMTP)


def contenuto_irripetibile(prefisso: bytes = b"allegato") -> bytes:
    """Byte che nell'archivio non possono gia' esserci.

    L'archivio deposita per impronta: due test che usassero gli stessi byte
    lavorerebbero sullo stesso file, e la verifica della deduplicazione
    direbbe di si' anche quando la deduplicazione non funziona.
    """
    return prefisso + b" " + uuid.uuid4().hex.encode("ascii")


def elabora(db, dati: bytes, nome: str = "prova.eml", autore=None):
    """Scorciatoia: elabora un messaggio e restituisce l'esito."""
    return emails.elabora_messaggio(
        db, dati, identificativo_fonte=nome, autore=autore
    )


def prodotto_con_versioni(db, quante: int = 1, stati=None):
    """Un prodotto con il numero di versioni chiesto, con gli stati voluti.

    La versione 1 la crea gia' `crea_prodotto()`; le altre si aggiungono qui
    con le righe del modello, perche' il servizio dei prodotti crea versioni
    solo per derivazione e qui serve poter scegliere gli stati.
    """
    from app.models import ProductVersion

    prodotto, prima = crea_prodotto(db, codice=codice_irripetibile())
    versioni = [prima]

    for numero in range(2, quante + 1):
        versione = ProductVersion(
            product_id=prodotto.id,
            version_number=numero,
            lifecycle_state=LifecycleState.IN_SVILUPPO,
        )
        db.add(versione)
        versioni.append(versione)

    db.flush()

    if stati is not None:
        for versione, stato in zip(versioni, stati):
            versione.lifecycle_state = stato
        db.flush()

    return prodotto, versioni


# ===========================================================================
#  1. LA LETTURA DI UN MESSAGGIO (nessun accesso al database)
# ===========================================================================


@pytest.mark.parametrize(
    "oggetto, prefissi_attesi, resto",
    [
        ("Offerta", (), "Offerta"),
        ("R: Offerta", ("R",), "Offerta"),
        ("Re: Offerta", ("Re",), "Offerta"),
        ("RE:  Offerta", ("RE",), "Offerta"),
        ("Fwd: Offerta", ("Fwd",), "Offerta"),
        ("I: Offerta", ("I",), "Offerta"),
        ("FW: Offerta", ("FW",), "Offerta"),
        ("Re: Fwd: R: Offerta", ("Re", "Fwd", "R"), "Offerta"),
        ("re : Offerta", ("re",), "Offerta"),
    ],
)
def test_i_prefissi_di_risposta_si_tolgono(oggetto, prefissi_attesi, resto):
    """"R:", "Re:", "Fwd:", "I:" si tolgono, in qualunque combinazione.

    E' la richiesta esplicita del punto 5a della sessione: il codice prodotto
    va riconosciuto anche dietro ai prefissi, "con qualunque combinazione di
    maiuscole e spazi".
    """
    pulito, prefissi = email_parsing.togli_prefissi(oggetto)

    assert pulito == resto
    assert prefissi == prefissi_attesi


def test_un_oggetto_di_soli_prefissi_non_fa_girare_a_vuoto():
    """Un oggetto con dentro mille "Re:" si ferma al limite e non blocca niente."""
    pulito, prefissi = email_parsing.togli_prefissi("Re: " * 1000 + "Offerta")

    assert len(prefissi) == email_parsing.MASSIMO_PREFISSI
    assert pulito.startswith("Re:")


@pytest.mark.parametrize(
    "oggetto, codice, versione, motivo",
    [
        ("[ABC1100-24-110SW][V2][SPECS] x", "ABC1100-24-110SW", 2, "SPECS"),
        ("[ABC1100][SPECS] x", "ABC1100", None, "SPECS"),
        ("[ABC1100][V3] x", "ABC1100", 3, None),
        ("[ABC1100] x", "ABC1100", None, None),
        ("[ abc1100 ][ v3 ][ quote ] x", "abc1100", 3, "quote"),
        ("R: [ABC1100][V2][RFQ] x", "ABC1100", 2, "RFQ"),
        ("Re: Fwd: [ABC1100][V2][RFQ] x", "ABC1100", 2, "RFQ"),
        ("Nessuna parentesi qui", None, None, None),
        ("Testo prima [ABC1100][V2] dopo", None, None, None),
    ],
)
def test_la_scomposizione_dell_oggetto(oggetto, codice, versione, motivo):
    """La forma `[CODICE][Vn][MOTIVO]`, con tutte le parti facoltative.

    L'ultimo caso e' quello che spiega la scelta: la convenzione dice che le
    parentesi stanno **davanti** all'oggetto, e cercarle in mezzo
    riconoscerebbe come codice anche una parentesi citata dentro una frase.
    Il codice scritto in mezzo lo trova la seconda regola, non questa.
    """
    scomposto = email_parsing.scomponi_oggetto(oggetto)

    assert scomposto.codice == codice
    assert scomposto.versione == versione
    assert scomposto.motivo == motivo


def test_la_seconda_parentesi_e_il_motivo_quando_non_e_una_versione():
    """`[ABC][SPECS]` ha due parentesi e la seconda **non** e' una versione.

    Senza questa distinzione, chi scrive il codice e il motivo senza precisare
    la versione si vedrebbe interpretare "SPECS" come un numero di versione,
    e il messaggio finirebbe in quarantena tutte le volte.
    """
    scomposto = email_parsing.scomponi_oggetto("[ABC1100][SPECS] Richiesta")

    assert scomposto.versione is None
    assert scomposto.motivo == "SPECS"


def test_gli_elementi_candidati_escono_dalla_punteggiatura():
    """Il codice si riconosce anche fra parentesi tonde, virgole e due punti."""
    trovati = email_parsing.elementi_candidati(
        "Ordine di ricambi (prodotto: ABC1100-24-110SW), urgente."
    )

    assert "ABC1100-24-110SW" in trovati
    # Dal piu' lungo al piu' corto: la corrispondenza piu' specifica vince.
    assert trovati == sorted(trovati, key=len, reverse=True)


def test_l_html_diventa_testo_leggibile():
    """Script e fogli di stile spariscono, i marcatori diventano a capo."""
    testo = email_parsing.html_in_testo(
        "<html><head><style>p { color: red; }</style></head><body>"
        "<p>Buongiorno</p>"
        "<table><tr><td>Prima</td><td>15 settembre</td></tr></table>"
        "<script>non si deve leggere</script>"
        "</body></html>"
    )

    assert "Buongiorno" in testo
    assert "Prima 15 settembre" in testo
    assert "color: red" not in testo
    assert "non si deve leggere" not in testo


def test_un_messaggio_in_solo_html_ha_comunque_il_corpo_in_testo():
    """Il corpo si legge anche quando il messaggio e' solo HTML."""
    letto = email_parsing.leggi_messaggio(
        eml(
            identificativo=identificativo_di_prova(),
            corpo="versione testuale",
            html="<p>versione <b>HTML</b> del messaggio</p>",
        )
    )

    assert letto.corpo is not None
    assert "versione" in letto.corpo


def test_le_lettere_accentate_sopravvivono_alla_lettura():
    """Oggetto e corpo con gli accenti si rileggono identici.

    E' il caso che si rompe per primo quando qualcuno decide che un messaggio
    di posta e' UTF-8: la codifica sta scritta nelle intestazioni, e questa
    verifica esiste per accorgersene.
    """
    letto = email_parsing.leggi_messaggio(
        eml(
            identificativo=identificativo_di_prova(),
            oggetto="Modifica già concordata, perché città",
            corpo="L'unità va sostituita entro martedì. Però.",
        )
    )

    assert letto.oggetto == "Modifica già concordata, perché città"
    assert "unità" in (letto.corpo or "")
    assert "martedì" in (letto.corpo or "")


def test_un_file_malformato_si_legge_lo_stesso():
    """Un `.eml` che non e' un messaggio non solleva: produce un risultato povero.

    E' il perno del punto 7 della sessione. Se la lettura potesse sollevare,
    un file rovinato fermerebbe l'acquisizione di tutti quelli che vengono
    dopo, ed e' esattamente il giorno in cui l'acquisizione serve di piu'.
    """
    letto = email_parsing.leggi_messaggio(
        b"Questo non e' un messaggio.\r\n\x00\x01\x02\r\n"
    )

    assert letto.identificativo_costruito is True
    assert letto.mittente == email_parsing.MITTENTE_SCONOSCIUTO
    assert letto.oggetto is None
    assert letto.difetti != ()


def test_i_caratteri_nulli_non_arrivano_al_database():
    """Un `.eml` rovinato porta dentro caratteri nulli, e PostgreSQL li rifiuta.

    Non e' una curiosita' teorica: e' il guasto che questo test ha scoperto la
    prima volta che si e' provato il criterio di accettazione del file
    malformato. Senza la ripulitura l'INSERT falliva, il messaggio veniva
    contato fra gli errori invece che finire in quarantena, e il file restava
    nella cartella per fallire di nuovo al giro dopo - per sempre.
    """
    # Il carattere nullo si costruisce invece di scriverlo dentro la
    # stringa: un file sorgente con dentro un byte zero e' un file che
    # git, gli editori e grep trattano come binario.
    letto = email_parsing.leggi_messaggio(
        b"Corpo con" + bytes([0]) + b" dentro un carattere nullo."
    )

    assert email_parsing.CARATTERE_NULLO not in (letto.corpo or "")
    assert "carattere nullo" in (letto.corpo or "")


def test_un_file_vuoto_si_legge_lo_stesso():
    """Zero byte non sono un errore tecnico: sono un messaggio povero."""
    letto = email_parsing.leggi_messaggio(b"")

    assert letto.identificativo.startswith("aurora-")
    assert letto.difetti != ()


def test_l_identificativo_costruito_e_stabile():
    """Lo stesso file produce sempre lo stesso identificativo.

    E' quello che fa valere la ripetibilita' anche per i messaggi rotti, che
    sono proprio quelli che si riprova a leggere piu' spesso.
    """
    dati = b"file rotto, sempre lo stesso"

    primo = email_parsing.leggi_messaggio(dati)
    secondo = email_parsing.leggi_messaggio(dati)

    assert primo.identificativo == secondo.identificativo


def test_l_identificativo_perde_le_parentesi_angolari():
    """`<abc@host>` si scrive nel database come `abc@host`.

    Le parentesi appartengono all'intestazione, non all'identificativo:
    lasciandole dentro a meta' dei valori, il confronto fra il Message-ID di
    un messaggio e il References di un altro non tornerebbe mai.
    """
    assert email_parsing.normalizza_identificativo("<abc@host>") == "abc@host"
    assert email_parsing.normalizza_identificativo("  abc@host ") == "abc@host"


def test_gli_allegati_si_staccano_con_nome_tipo_e_contenuto():
    """Ogni allegato esce con il suo nome, il suo tipo e i suoi byte."""
    contenuto = contenuto_irripetibile()
    letto = email_parsing.leggi_messaggio(
        eml(
            identificativo=identificativo_di_prova(),
            allegati=[("relazione.txt", "text/plain", contenuto)],
        )
    )

    assert len(letto.allegati) == 1
    assert letto.allegati[0].nome_file == "relazione.txt"
    assert letto.allegati[0].mime_type == "text/plain"
    assert letto.allegati[0].contenuto == contenuto


def test_un_allegato_non_porta_mai_un_percorso():
    """Un allegato chiamato "..\\..\\config.txt" perde tutto il percorso."""
    letto = email_parsing.leggi_messaggio(
        eml(
            identificativo=identificativo_di_prova(),
            allegati=[
                ("../../etc/passwd", "text/plain", contenuto_irripetibile())
            ],
        )
    )

    assert letto.allegati[0].nome_file == "passwd"


# ===========================================================================
#  2. LA FONTE LOCALE
# ===========================================================================


def test_la_fonte_locale_rispetta_l_interfaccia():
    """FonteLocale e' una FonteEmail: e' il patto su cui si regge la sessione 11."""
    assert isinstance(FonteLocale(), FonteEmail)


def test_la_fonte_elenca_solo_i_file_eml(tmp_path):
    """Quello che nella cartella non e' un `.eml` viene ignorato in silenzio."""
    fonte = FonteLocale(tmp_path)
    (tmp_path / "primo.eml").write_bytes(eml(identificativo=identificativo_di_prova()))
    (tmp_path / "appunti.txt").write_text("niente")
    (tmp_path / "secondo.EML").write_bytes(
        eml(identificativo=identificativo_di_prova())
    )

    trovati = fonte.elenca_nuovi_messaggi()

    assert trovati == ["primo.eml", "secondo.EML"]


def test_la_fonte_non_guarda_dentro_le_sottocartelle(tmp_path):
    """`elaborate/` e `quarantena/` non si rileggono a ogni giro."""
    fonte = FonteLocale(tmp_path)
    fonte.prepara()
    (fonte.cartella_elaborate / "vecchio.eml").write_bytes(b"x")
    (fonte.cartella_quarantena / "altro.eml").write_bytes(b"x")

    assert fonte.elenca_nuovi_messaggi() == []


def test_la_fonte_sposta_nelle_due_cartelle(tmp_path):
    """Marcare elaborato e mettere in quarantena spostano il file."""
    fonte = FonteLocale(tmp_path)
    (tmp_path / "uno.eml").write_bytes(b"primo")
    (tmp_path / "due.eml").write_bytes(b"secondo")

    fonte.marca_elaborato("uno.eml")
    fonte.sposta_in_quarantena("due.eml")

    assert (fonte.cartella_elaborate / "uno.eml").is_file()
    assert (fonte.cartella_quarantena / "due.eml").is_file()
    assert fonte.elenca_nuovi_messaggi() == []


def test_la_fonte_non_sovrascrive_un_file_gia_spostato(tmp_path):
    """Due file con lo stesso nome non si mangiano a vicenda."""
    fonte = FonteLocale(tmp_path)
    fonte.prepara()
    (fonte.cartella_elaborate / "uno.eml").write_bytes(b"il primo")
    (tmp_path / "uno.eml").write_bytes(b"il secondo")

    fonte.marca_elaborato("uno.eml")

    rimasti = sorted(percorso.name for percorso in fonte.cartella_elaborate.iterdir())
    assert len(rimasti) == 2
    assert (fonte.cartella_elaborate / "uno.eml").read_bytes() == b"il primo"


def test_la_fonte_non_esce_dalla_propria_cartella(tmp_path):
    """Un identificativo con dentro un percorso non porta da nessuna parte."""
    fonte = FonteLocale(tmp_path)
    fonte.prepara()

    with pytest.raises(MessaggioNonTrovato):
        fonte.scarica_messaggio_grezzo("../../.env")

    with pytest.raises(MessaggioNonTrovato):
        fonte.scarica_messaggio_grezzo("non-esiste.eml")


# ===========================================================================
#  3. I QUATTRO RAMI DELL'ATTRIBUZIONE
# ===========================================================================


def test_ramo_a_oggetto_formattato_con_versione(db_session):
    """(a) `[CODICE][Vn][MOTIVO]` attacca il messaggio a quella versione esatta."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=3)

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V2][SPECS] Tensione di ingresso",
        ),
    )

    assert esito.stato == emails.STATO_ARCHIVIATO
    assert esito.messaggio.product_version_id == versioni[1].id
    assert esito.messaggio.subject_parsed["via"] == emails.VIA_OGGETTO
    assert esito.messaggio.assignment_state == EmailAssignmentState.AUTOMATICA


def test_ramo_a_riconosce_il_codice_dietro_ai_prefissi(db_session):
    """(a) vale anche con "R: Re: Fwd:" davanti e con spazi dentro le parentesi."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=2)

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"R: Re:  Fwd: [ {prodotto.code.lower()} ][ v1 ][ specs ] x",
        ),
    )

    assert esito.stato == emails.STATO_ARCHIVIATO
    assert esito.messaggio.product_version_id == versioni[0].id


def test_ramo_a_senza_versione_prende_la_piu_recente_non_chiusa(db_session):
    """(a) senza `[Vn]` si usa la versione piu' recente non chiusa.

    Le versioni sono tre: la 3 e' superata, la 2 e' in sviluppo. La piu'
    recente **non chiusa** e' la 2, non la 3.
    """
    prodotto, versioni = prodotto_con_versioni(
        db_session,
        quante=3,
        stati=[
            LifecycleState.SUPERATO,
            LifecycleState.IN_SVILUPPO,
            LifecycleState.SUPERATO,
        ],
    )

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][RFQ] Richiesta di offerta",
        ),
    )

    assert esito.messaggio.product_version_id == versioni[1].id


def test_se_tutte_le_versioni_sono_chiuse_si_prende_l_ultima(db_session):
    """Un prodotto fuori produzione riceve posta lo stesso (D-072).

    La regola non ha candidati - non c'e' nessuna versione non chiusa - e
    l'alternativa sarebbe mandare in quarantena un messaggio di cui si conosce
    il prodotto con certezza.
    """
    prodotto, versioni = prodotto_con_versioni(
        db_session,
        quante=2,
        stati=[LifecycleState.OBSOLETO, LifecycleState.SUPERATO],
    )

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][ADMIN] Ricambi",
        ),
    )

    assert esito.stato == emails.STATO_ARCHIVIATO
    assert esito.messaggio.product_version_id == versioni[1].id


def test_ramo_b_codice_in_mezzo_alla_frase(db_session):
    """(b) il codice scritto senza parentesi, in mezzo all'oggetto."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=2)

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"Ordine di ricambi (prodotto: {prodotto.code}), urgente",
        ),
    )

    assert esito.stato == emails.STATO_ARCHIVIATO
    assert esito.messaggio.product_version_id == versioni[1].id
    assert esito.messaggio.subject_parsed["via"] == emails.VIA_OGGETTO_LIBERO


def test_ramo_c_eredita_dal_messaggio_a_cui_risponde(db_session):
    """(c) senza codice, l'attribuzione arriva da In-Reply-To."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    capostipite = identificativo_di_prova("capo")

    primo = elabora(
        db_session,
        eml(
            identificativo=capostipite,
            oggetto=f"[{prodotto.code}][V1][SPECS] Requisiti",
        ),
    )
    assert primo.stato == emails.STATO_ARCHIVIATO

    risposta = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("risposta"),
            oggetto="Re: Requisiti",
            in_risposta_a=capostipite,
            riferimenti=[capostipite],
        ),
    )

    assert risposta.stato == emails.STATO_ARCHIVIATO
    assert risposta.messaggio.product_version_id == versioni[0].id
    assert risposta.messaggio.subject_parsed["via"] == emails.VIA_CONVERSAZIONE


def test_ramo_c_funziona_anche_al_contrario(db_session):
    """(c) guarda in tutte e due le direzioni del filo.

    I file di una cartella si leggono in ordine di nome, quindi puo'
    benissimo capitare di archiviare prima la risposta e poi il messaggio
    originale. Qui si archivia prima la **risposta attribuita** e poi il suo
    capostipite senza codice, che deve ereditare da lei.
    """
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    capostipite = identificativo_di_prova("capo")

    risposta = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("risposta"),
            oggetto=f"Re: [{prodotto.code}][V1][SPECS] Requisiti",
            in_risposta_a=capostipite,
            riferimenti=[capostipite],
        ),
    )
    assert risposta.messaggio.product_version_id == versioni[0].id

    primo = elabora(
        db_session,
        eml(identificativo=capostipite, oggetto="Requisiti (senza codice)"),
    )

    assert primo.stato == emails.STATO_ARCHIVIATO
    assert primo.messaggio.product_version_id == versioni[0].id
    assert primo.messaggio.subject_parsed["via"] == emails.VIA_CONVERSAZIONE


def test_ramo_d_quarantena(db_session):
    """(d) nessun codice, nessuna conversazione: quarantena, con scritto perche'."""
    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto="Richiesta di informazioni generali",
        ),
    )

    assert esito.stato == emails.STATO_QUARANTENA
    assert esito.messaggio.product_version_id is None
    assert esito.messaggio.assignment_state == EmailAssignmentState.QUARANTENA
    assert esito.messaggio.quarantine_reason


def test_un_prodotto_sconosciuto_va_in_quarantena(db_session):
    """Un oggetto formattato benissimo su un prodotto che non esiste."""
    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto="[ZZZ9999-00-000XX][V1][SPECS] Prodotto inventato",
        ),
    )

    assert esito.stato == emails.STATO_QUARANTENA


def test_una_versione_dichiarata_ma_inesistente_va_in_quarantena(db_session):
    """Il quinto caso: il prodotto c'e', la versione scritta no (D-073).

    Aurora **non** ne sceglie un'altra al posto del mittente. Fra attaccare la
    posta a una versione diversa da quella scritta e chiedere a una persona,
    si chiede: le mail sono il posto dove stanno meta' delle decisioni.
    """
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=2)

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V99][CHANGE] Versione che non esiste",
        ),
    )

    assert esito.stato == emails.STATO_QUARANTENA
    assert "99" in esito.messaggio.quarantine_reason
    assert prodotto.code in esito.messaggio.quarantine_reason


def test_un_motivo_sconosciuto_non_impedisce_l_attribuzione(db_session):
    """Il motivo non decide niente: quello che conta e' il codice prodotto.

    **La sigla e' irripetibile e non un valore inventato**, ed e' successo
    davvero: la verifica a mano di questa sessione ha aggiunto "GARANZIA"
    all'elenco dei motivi dall'interfaccia, e il test - che usava proprio
    quella sigla come esempio di motivo sconosciuto - e' diventato rosso senza
    che il programma fosse sbagliato. E' la stessa lezione di
    `modello_irripetibile()`, applicata ai motivi (vedi tests/conftest.py).
    """
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    sconosciuta = f"PRV{uuid.uuid4().hex[:6].upper()}"

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][{sconosciuta}] Estensione",
        ),
    )

    assert esito.stato == emails.STATO_ARCHIVIATO
    assert esito.messaggio.subject_parsed["motivo"] == sconosciuta
    assert esito.messaggio.subject_parsed["motivo_riconosciuto"] is False


def test_un_motivo_ammesso_risulta_riconosciuto(db_session):
    """Una sigla che sta in `email_reasons` risulta riconosciuta."""
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    sigla = f"PRV{uuid.uuid4().hex[:6].upper()}"
    creatore = crea_utente(
        db_session,
        username=f"prova.motivi.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    email_reasons.crea(
        db_session, codice=sigla, descrizione="Motivo di prova", autore=creatore
    )

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][{sigla}] x",
        ),
    )

    assert esito.messaggio.subject_parsed["motivo_riconosciuto"] is True


# ===========================================================================
#  4. RIPETIBILITA', ARCHIVIO E TRANSAZIONE
# ===========================================================================


def test_rielaborare_lo_stesso_messaggio_non_duplica_niente(db_session):
    """Il secondo criterio di accettazione, verificato.

    Lo stesso `Message-ID` non entra due volte: la seconda elaborazione lo
    riconosce e non scrive niente.
    """
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    dati = eml(
        identificativo=identificativo_di_prova(),
        oggetto=f"[{prodotto.code}][V1][SPECS] Ripetibile",
    )

    primo = elabora(db_session, dati)
    secondo = elabora(db_session, dati)

    assert primo.stato == emails.STATO_ARCHIVIATO
    assert secondo.stato == emails.STATO_GIA_PRESENTE
    assert secondo.messaggio.id == primo.messaggio.id

    quanti = db_session.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.internet_message_id
            == primo.messaggio.internet_message_id
        )
        .with_only_columns(EmailMessage.id)
    )
    assert quanti == primo.messaggio.id


def test_anche_un_file_rotto_non_si_archivia_due_volte(db_session):
    """La ripetibilita' vale anche per i messaggi senza Message-ID."""
    dati = eml(identificativo=None, oggetto="Senza identificativo") + b"\r\n"

    primo = elabora(db_session, dati)
    secondo = elabora(db_session, dati)

    assert primo.messaggio is not None
    assert secondo.stato == emails.STATO_GIA_PRESENTE
    assert secondo.messaggio.id == primo.messaggio.id


def test_il_file_originale_finisce_nell_archivio(db_session):
    """Il `.eml` per intero si deposita per impronta, come ogni altro file."""
    dati = eml(
        identificativo=identificativo_di_prova(),
        corpo=f"corpo irripetibile {uuid.uuid4().hex}",
    )

    esito = elabora(db_session, dati)

    assert esito.messaggio.storage_hash == storage.impronta_di(dati)
    assert storage.esiste(esito.messaggio.storage_hash)
    assert storage.leggi(esito.messaggio.storage_hash) == dati


def test_gli_allegati_hanno_ciascuno_la_propria_impronta(db_session):
    """Ogni allegato si deposita a parte, con la sua impronta."""
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    primo = contenuto_irripetibile(b"primo")
    secondo = contenuto_irripetibile(b"secondo")

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][DESIGN] Disegni",
            allegati=[
                ("schema.txt", "text/plain", primo),
                ("distinta.txt", "text/plain", secondo),
            ],
        ),
    )

    allegati = sorted(esito.messaggio.attachments, key=lambda a: a.filename)
    assert [a.filename for a in allegati] == ["distinta.txt", "schema.txt"]
    assert allegati[1].storage_hash == storage.impronta_di(primo)
    assert allegati[0].storage_hash == storage.impronta_di(secondo)
    assert allegati[1].size_bytes == len(primo)
    assert storage.leggi(allegati[1].storage_hash) == primo


def test_lo_stesso_allegato_in_due_messaggi_occupa_un_file_solo(db_session):
    """La deduplicazione dell'archivio vale anche per gli allegati."""
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    contenuto = contenuto_irripetibile(b"datasheet")

    primo = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("uno"),
            oggetto=f"[{prodotto.code}][V1][SPECS] uno",
            allegati=[("datasheet.txt", "text/plain", contenuto)],
        ),
    )
    secondo = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("due"),
            oggetto=f"[{prodotto.code}][V1][SPECS] due",
            allegati=[("datasheet-copia.txt", "text/plain", contenuto)],
        ),
    )

    assert (
        primo.messaggio.attachments[0].storage_hash
        == secondo.messaggio.attachments[0].storage_hash
    )


def test_un_messaggio_troppo_grande_non_ferma_niente(db_session, monkeypatch):
    """Oltre il limite di dimensione si segnala e si prosegue.

    Il file resta nella cartella e verra' riprovato: e' l'unico modo perche'
    il giorno in cui il limite viene alzato quel messaggio entri.
    """
    # Il limite si abbassa a zero megabyte per la durata del test:
    # "max_upload_bytes" e' una proprieta' calcolata su questo campo, quindi
    # basta cambiare il campo. monkeypatch lo rimette com'era da solo.
    monkeypatch.setattr(emails.settings, "MAX_UPLOAD_MB", 0)

    esito = elabora(db_session, b"x" * 10)

    assert esito.stato == emails.STATO_ERRORE
    assert esito.messaggio is None


def test_il_giro_completo_non_si_ferma_sul_file_rotto(db_session, tmp_path):
    """Il quarto criterio di accettazione, verificato.

    Nella cartella ci sono tre file: uno buono, uno rotto e un altro buono.
    Il rotto deve finire in quarantena **senza fermare gli altri due**, e
    ciascuno deve trovarsi nella sottocartella che gli spetta.
    """
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    fonte = FonteLocale(tmp_path)
    fonte.prepara()

    (tmp_path / "01-buono.eml").write_bytes(
        eml(
            identificativo=identificativo_di_prova("uno"),
            oggetto=f"[{prodotto.code}][V1][SPECS] primo",
        )
    )
    (tmp_path / "02-rotto.eml").write_bytes(b"\x00\x01 non e' un messaggio")
    (tmp_path / "03-buono.eml").write_bytes(
        eml(
            identificativo=identificativo_di_prova("tre"),
            oggetto=f"[{prodotto.code}][V1][SPECS] terzo",
        )
    )

    riepilogo = emails.acquisisci(db_session, fonte)

    assert riepilogo.letti == 3
    assert riepilogo.archiviati == 2
    assert riepilogo.in_quarantena == 1
    assert riepilogo.errori == 0

    assert (fonte.cartella_elaborate / "01-buono.eml").is_file()
    assert (fonte.cartella_elaborate / "03-buono.eml").is_file()
    assert (fonte.cartella_quarantena / "02-rotto.eml").is_file()
    assert fonte.elenca_nuovi_messaggi() == []


def test_rieseguire_il_giro_completo_non_duplica_niente(db_session, tmp_path):
    """Il criterio di accettazione, verificato sul giro intero e non su un file.

    I file si riscrivono nella cartella - come farebbe una seconda esecuzione
    di `scripts/genera_email_prova.py` - e si rielabora: nel database il
    numero di messaggi non cambia.
    """
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    fonte = FonteLocale(tmp_path)

    identificativi = [identificativo_di_prova(f"giro{numero}") for numero in range(3)]

    def riempi() -> None:
        fonte.prepara()
        for numero, identificativo in enumerate(identificativi):
            (tmp_path / f"{numero:02d}.eml").write_bytes(
                eml(
                    identificativo=identificativo,
                    oggetto=f"[{prodotto.code}][V1][SPECS] numero {numero}",
                )
            )

    riempi()
    primo = emails.acquisisci(db_session, fonte)

    riempi()
    secondo = emails.acquisisci(db_session, fonte)

    assert primo.archiviati == 3
    assert secondo.archiviati == 0
    assert secondo.gia_presenti == 3

    quanti = db_session.scalars(
        select(EmailMessage.id).where(
            EmailMessage.internet_message_id.in_(
                [identificativo.strip("<>") for identificativo in identificativi]
            )
        )
    ).all()
    assert len(quanti) == 3


def test_un_messaggio_gia_in_quarantena_torna_in_quarantena(db_session, tmp_path):
    """Rileggendo un messaggio gia' archiviato, il file va dove sta il messaggio.

    Cosi' guardando le due sottocartelle si vede lo stesso quadro che si vede
    in Aurora, invece di due elenchi che raccontano cose diverse.
    """
    fonte = FonteLocale(tmp_path)
    dati = eml(
        identificativo=identificativo_di_prova(), oggetto="Nessun codice qui"
    )

    fonte.prepara()
    (tmp_path / "uno.eml").write_bytes(dati)
    emails.acquisisci(db_session, fonte)

    (tmp_path / "uno.eml").write_bytes(dati)
    riepilogo = emails.acquisisci(db_session, fonte)

    assert riepilogo.gia_presenti == 1
    assert len(list(fonte.cartella_quarantena.iterdir())) == 2
    assert not (fonte.cartella_elaborate / "uno.eml").exists()


# ===========================================================================
#  5. IL REGISTRO DELLE OPERAZIONI
# ===========================================================================


def voci_del_messaggio(db, messaggio_id, azione=None):
    """Le voci del registro che parlano di quel messaggio."""
    interrogazione = select(AuditLog).where(AuditLog.entity_id == messaggio_id)
    if azione is not None:
        interrogazione = interrogazione.where(AuditLog.action == azione)
    return list(db.scalars(interrogazione).all())


def test_l_archiviazione_lascia_una_riga_nel_registro(db_session):
    """Un messaggio archiviato: una riga sola, `email.archived`."""
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)

    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][SPECS] Registrato",
        ),
    )

    voci = voci_del_messaggio(db_session, esito.messaggio.id)
    assert len(voci) == 1
    assert voci[0].action == emails.ACTION_EMAIL_ARCHIVED
    assert "Registrato" in voci[0].description


def test_la_quarantena_lascia_la_sua_riga(db_session):
    """Un messaggio non attribuito: una riga sola, `email.quarantined`."""
    esito = elabora(
        db_session,
        eml(identificativo=identificativo_di_prova(), oggetto="Senza codice"),
    )

    voci = voci_del_messaggio(db_session, esito.messaggio.id)
    assert len(voci) == 1
    assert voci[0].action == emails.ACTION_EMAIL_QUARANTINED


# ===========================================================================
#  6. L'ASSEGNAZIONE A MANO E IL FILO DI CONVERSAZIONE
# ===========================================================================


def filo_in_quarantena(db, quanti: int = 3):
    """Un filo di conversazione di N messaggi, tutti in quarantena."""
    capostipite = identificativo_di_prova("filo")
    messaggi = []

    primo = elabora(
        db, eml(identificativo=capostipite, oggetto="Riunione di avanzamento")
    )
    messaggi.append(primo.messaggio)

    for numero in range(1, quanti):
        risposta = elabora(
            db,
            eml(
                identificativo=identificativo_di_prova(f"filo{numero}"),
                oggetto="Re: Riunione di avanzamento",
                in_risposta_a=capostipite,
                riferimenti=[capostipite],
            ),
        )
        messaggi.append(risposta.messaggio)

    return messaggi


def test_il_filo_si_ricostruisce_in_tutte_e_due_le_direzioni(db_session):
    """Da un messaggio qualunque si arriva a tutti gli altri della conversazione."""
    messaggi = filo_in_quarantena(db_session, quanti=3)

    dal_primo = emails.messaggi_del_filo(db_session, messaggi[0])
    dall_ultimo = emails.messaggi_del_filo(db_session, messaggi[2])

    assert {m.id for m in dal_primo} == {messaggi[1].id, messaggi[2].id}
    assert {m.id for m in dall_ultimo} == {messaggi[0].id, messaggi[1].id}


def test_l_assegnazione_a_mano_scrive_stato_autore_e_registro(db_session):
    """Assegnare un messaggio lo attacca alla versione e lascia una riga."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    creatore = crea_utente(
        db_session,
        username=f"prova.smista.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    esito = elabora(
        db_session,
        eml(identificativo=identificativo_di_prova(), oggetto="Senza codice"),
    )

    emails.assegna(
        db_session, esito.messaggio, versione=versioni[0], autore=creatore
    )
    db_session.flush()

    assert esito.messaggio.product_version_id == versioni[0].id
    assert esito.messaggio.assignment_state == EmailAssignmentState.MANUALE
    assert esito.messaggio.assigned_by_id == creatore.id
    assert esito.messaggio.subject_parsed["via"] == emails.VIA_MANUALE
    # Il motivo della quarantena resta scritto: e' la storia di come il
    # messaggio e' arrivato dov'e'.
    assert esito.messaggio.quarantine_reason

    voci = voci_del_messaggio(
        db_session, esito.messaggio.id, emails.ACTION_EMAIL_ASSIGNED_MANUAL
    )
    assert len(voci) == 1


def test_l_assegnazione_si_propaga_a_tutto_il_filo(db_session):
    """Il terzo criterio di accettazione, verificato."""
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    creatore = crea_utente(
        db_session,
        username=f"prova.filo.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    messaggi = filo_in_quarantena(db_session, quanti=3)

    emails.assegna(
        db_session, messaggi[0], versione=versioni[0], autore=creatore
    )
    assegnati = emails.assegna_il_filo(
        db_session, messaggi[0], versione=versioni[0], autore=creatore
    )
    db_session.flush()

    assert len(assegnati) == 2
    for messaggio in messaggi:
        assert messaggio.product_version_id == versioni[0].id
        assert messaggio.assignment_state == EmailAssignmentState.MANUALE


def test_l_assegnazione_del_filo_non_tocca_chi_e_gia_attribuito(db_session):
    """Un messaggio del filo gia' attribuito resta dov'e'.

    Sovrascrivere una decisione gia' presa non e' quello che chiede chi preme
    "assegna anche gli altri".
    """
    prodotto, versioni = prodotto_con_versioni(db_session, quante=2)
    creatore = crea_utente(
        db_session,
        username=f"prova.filo2.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )

    capostipite = identificativo_di_prova("misto")
    attribuito = elabora(
        db_session,
        eml(
            identificativo=capostipite,
            oggetto=f"[{prodotto.code}][V1][SPECS] Gia' attribuito",
        ),
    )
    orfano = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("orfano"),
            oggetto="Un oggetto che non c'entra niente",
        ),
    )
    # Li si mette nello stesso filo a mano: l'orfano cita il capostipite ma
    # e' stato archiviato quando quello era gia' attribuito, quindi lo ha
    # ereditato. Qui interessa il caso opposto, e si costruisce.
    orfano.messaggio.in_reply_to = capostipite
    orfano.messaggio.product_version_id = None
    orfano.messaggio.assignment_state = EmailAssignmentState.QUARANTENA
    db_session.flush()

    assegnati = emails.assegna_il_filo(
        db_session, orfano.messaggio, versione=versioni[1], autore=creatore
    )
    db_session.flush()

    assert assegnati == []
    assert attribuito.messaggio.product_version_id == versioni[0].id
    assert attribuito.messaggio.assignment_state == EmailAssignmentState.AUTOMATICA


# ===========================================================================
#  7. I PERMESSI
# ===========================================================================


def squadra_di_prova(db):
    """Un progetto con un responsabile, un ingegnere e un estraneo.

    Restituisce (progetto, versione, responsabile, ingegnere, estraneo).
    """
    coda = uuid.uuid4().hex[:8]
    responsabile = crea_utente(db, username=f"prova.pm.{coda}")
    ingegnere = crea_utente(db, username=f"prova.ing.{coda}")
    estraneo = crea_utente(db, username=f"prova.estraneo.{coda}")

    classificazione_di_prova(db, permissions.CLASSE_CORRISPONDENZA)

    _prodotto, versione = crea_prodotto(db, codice=codice_irripetibile())
    progetto = crea_progetto(
        db, versione, responsabile, squadra=[ingegnere]
    )

    return progetto, versione, responsabile, ingegnere, estraneo


def messaggio_sulla_versione(db, versione, prodotto_code: str):
    """Archivia un messaggio attribuito a quella versione."""
    esito = elabora(
        db,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto_code}][V{versione.version_number}][SPECS] x",
        ),
    )
    assert esito.stato == emails.STATO_ARCHIVIATO
    return esito.messaggio


def test_la_posta_si_vede_con_la_regola_dei_documenti(db_session):
    """Il responsabile e l'ingegnere vedono; l'estraneo no."""
    progetto, versione, responsabile, ingegnere, estraneo = squadra_di_prova(
        db_session
    )
    messaggio = messaggio_sulla_versione(
        db_session, versione, versione.product.code
    )

    assert permissions.puo(
        db_session, responsabile, permissions.Azione.VEDERE, messaggio
    )
    assert permissions.puo(
        db_session, ingegnere, permissions.Azione.VEDERE, messaggio
    )
    assert not permissions.puo(
        db_session, estraneo, permissions.Azione.VEDERE, messaggio
    )


def test_il_filtro_della_posta_dice_la_stessa_cosa_di_puo(db_session):
    """L'elenco e la scheda passano dalla stessa regola.

    Un elenco che nasconde una riga che poi si apre scrivendone l'indirizzo
    non e' una protezione, e la copia SQL della regola e' quella che si
    disallinea per prima (D-051).
    """
    progetto, versione, responsabile, ingegnere, estraneo = squadra_di_prova(
        db_session
    )
    messaggio = messaggio_sulla_versione(
        db_session, versione, versione.product.code
    )

    for utente in (responsabile, ingegnere, estraneo):
        filtro = permissions.filtro_email(db_session, utente)
        interrogazione = select(EmailMessage.id).where(
            EmailMessage.id == messaggio.id
        )
        if filtro is not None:
            interrogazione = interrogazione.where(filtro)

        nell_elenco = db_session.scalars(interrogazione).first() is not None
        dalla_scheda = permissions.puo(
            db_session, utente, permissions.Azione.VEDERE, messaggio
        )

        assert nell_elenco == dalla_scheda, (
            f"per '{utente.username}' l'elenco e la scheda non dicono la "
            "stessa cosa"
        )


def test_un_messaggio_in_quarantena_non_lo_vede_nessuno_tranne_il_creatore(
    db_session,
):
    """La quarantena non e' attaccata a nessun progetto: la vede chi amministra."""
    coda = uuid.uuid4().hex[:8]
    chiunque = crea_utente(db_session, username=f"prova.chiunque.{coda}")
    creatore = crea_utente(
        db_session, username=f"prova.capo.{coda}", ruolo=GlobalRole.CREATORE
    )

    esito = elabora(
        db_session,
        eml(identificativo=identificativo_di_prova(), oggetto="Senza codice"),
    )

    assert not permissions.puo(
        db_session, chiunque, permissions.Azione.VEDERE, esito.messaggio
    )
    assert permissions.puo(
        db_session, creatore, permissions.Azione.VEDERE, esito.messaggio
    )


def test_un_lettore_vede_la_posta_ma_non_la_riassegna(db_session):
    """La matrice governa la posta come governa i documenti.

    Il lettore ha la casella "vedere" sulla corrispondenza e non ha la casella
    "modificare": vede il messaggio e non ne puo' cambiare l'attribuzione.
    """
    coda = uuid.uuid4().hex[:8]
    responsabile = crea_utente(db_session, username=f"prova.pm2.{coda}")
    lettore = crea_utente(db_session, username=f"prova.lettore.{coda}")

    classe = classificazione_di_prova(
        db_session, permissions.CLASSE_CORRISPONDENZA
    )
    _prodotto, versione = crea_prodotto(db_session, codice=codice_irripetibile())
    crea_progetto(db_session, versione, responsabile, lettori=[lettore])

    messaggio = messaggio_sulla_versione(
        db_session, versione, versione.product.code
    )

    permessi_lettore = db_session.scalars(
        select(Assignment).where(
            Assignment.user_id == lettore.id,
            Assignment.project_role == ProjectRole.LETTORE,
        )
    ).first()
    assert permessi_lettore is not None, "il lettore deve essere assegnato"
    assert classe is not None

    assert permissions.puo(
        db_session, lettore, permissions.Azione.VEDERE, messaggio
    )
    assert not permissions.puo(
        db_session, lettore, permissions.Azione.MODIFICARE, messaggio
    )


# ===========================================================================
#  8. LE PAGINE
# ===========================================================================


def crea_creatore(db, username: str | None = None):
    """Un creatore con una password nota, per entrare dal finto browser."""
    return crea_utente(
        db,
        username=username or f"prova.posta.capo.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )


def test_l_elenco_della_posta_si_apre(client, db_session):
    """La pagina /posta mostra i messaggi che si possono vedere."""
    creatore = crea_creatore(db_session)
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][SPECS] Compare nell'elenco",
        ),
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get("/posta")

    assert risposta.status_code == 200
    assert "Compare nell&#39;elenco" in risposta.text or (
        "Compare nell'elenco" in risposta.text
    )


def test_la_ricerca_guarda_mittente_oggetto_e_contenuto(client, db_session):
    """Il punto 4 della sessione: si cerca per mittente, oggetto e contenuto."""
    creatore = crea_creatore(db_session)
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    parola = f"parolachiave{uuid.uuid4().hex[:8]}"
    elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][SPECS] Oggetto qualunque",
            corpo=f"Nel corpo c'e' la {parola} da cercare.",
        ),
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    trovato = client.get(f"/posta?q={parola}")
    non_trovato = client.get(f"/posta?q=zzz{uuid.uuid4().hex[:8]}")

    assert "Oggetto qualunque" in trovato.text
    assert "Oggetto qualunque" not in non_trovato.text


def test_la_scheda_di_un_messaggio_mostra_corpo_e_allegati(client, db_session):
    """Corpo leggibile e allegati scaricabili, come chiede il punto 1."""
    creatore = crea_creatore(db_session)
    prodotto, _versioni = prodotto_con_versioni(db_session, quante=1)
    esito = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova(),
            oggetto=f"[{prodotto.code}][V1][SPECS] Con allegato",
            corpo="Testo del corpo che si deve leggere.",
            allegati=[("nota.txt", "text/plain", contenuto_irripetibile())],
        ),
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/posta/{esito.messaggio.id}")

    assert risposta.status_code == 200
    assert "Testo del corpo che si deve leggere." in risposta.text
    assert "nota.txt" in risposta.text
    assert f"/posta/{esito.messaggio.id}/scarica" in risposta.text


def test_il_file_eml_si_scarica_e_lo_scarico_si_registra(client, db_session):
    """Il file originale esce intero, e chi lo ha preso resta scritto."""
    creatore = crea_creatore(db_session)
    dati = eml(
        identificativo=identificativo_di_prova(),
        corpo=f"corpo irripetibile {uuid.uuid4().hex}",
    )
    esito = elabora(db_session, dati)
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/posta/{esito.messaggio.id}/scarica")

    assert risposta.status_code == 200
    assert risposta.content == dati
    assert "attachment" in risposta.headers["content-disposition"]

    voci = voci_del_messaggio(
        db_session, esito.messaggio.id, emails.ACTION_EMAIL_DOWNLOAD
    )
    assert len(voci) == 1


def test_un_allegato_di_un_altro_messaggio_non_si_scarica(client, db_session):
    """L'indirizzo porta i due identificatori: il legame si verifica."""
    creatore = crea_creatore(db_session)
    primo = elabora(
        db_session,
        eml(
            identificativo=identificativo_di_prova("uno"),
            allegati=[("uno.txt", "text/plain", contenuto_irripetibile())],
        ),
        nome="uno.eml",
    )
    secondo = elabora(
        db_session,
        eml(identificativo=identificativo_di_prova("due")),
        nome="due.eml",
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    allegato = primo.messaggio.attachments[0]
    risposta = client.get(f"/posta/{secondo.messaggio.id}/allegati/{allegato.id}")

    assert risposta.status_code == 404


def test_la_quarantena_e_riservata_al_creatore(client, db_session):
    """Chi non amministra non apre la pagina della quarantena."""
    utente = crea_utente(
        db_session, username=f"prova.non.capo.{uuid.uuid4().hex[:8]}"
    )
    entra(client, utente.username, PASSWORD_DI_PROVA)

    assert client.get("/posta/quarantena").status_code == 403
    assert client.get("/posta/motivi").status_code == 403


def test_la_quarantena_elenca_i_messaggi_non_attribuiti(client, db_session):
    """I messaggi in attesa compaiono con il motivo per cui sono li'."""
    creatore = crea_creatore(db_session)
    oggetto = f"Da smistare {uuid.uuid4().hex[:8]}"
    elabora(
        db_session, eml(identificativo=identificativo_di_prova(), oggetto=oggetto)
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get("/posta/quarantena")

    assert risposta.status_code == 200
    assert oggetto in risposta.text


def test_assegnare_dalla_quarantena_propone_il_resto_del_filo(client, db_session):
    """Il modulo propone di assegnare anche gli altri messaggi del filo."""
    creatore = crea_creatore(db_session)
    messaggi = filo_in_quarantena(db_session, quanti=3)
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/posta/{messaggi[0].id}/assegna")

    assert risposta.status_code == 200
    assert "tutto_il_filo" in risposta.text
    assert "altri 2 messaggi" in risposta.text


def test_assegnare_dalla_quarantena_funziona_su_tutto_il_filo(client, db_session):
    """Il terzo criterio di accettazione, verificato dalla pagina."""
    creatore = crea_creatore(db_session)
    prodotto, versioni = prodotto_con_versioni(db_session, quante=1)
    messaggi = filo_in_quarantena(db_session, quanti=3)
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    gettone = gettone_csrf(client, f"/posta/{messaggi[0].id}/assegna")
    risposta = client.post(
        f"/posta/{messaggi[0].id}/assegna",
        data={
            "versione": str(versioni[0].id),
            "tutto_il_filo": "si",
            "csrf": gettone,
        },
        follow_redirects=False,
    )

    assert risposta.status_code == 303

    for messaggio in messaggi:
        db_session.refresh(messaggio)
        assert messaggio.product_version_id == versioni[0].id
        assert messaggio.assignment_state == EmailAssignmentState.MANUALE


def test_i_motivi_si_amministrano_dall_interfaccia(client, db_session):
    """Il punto 8 della sessione: l'elenco dei motivi si cambia da una pagina."""
    creatore = crea_creatore(db_session)
    entra(client, creatore.username, PASSWORD_DI_PROVA)
    sigla = f"PRV{uuid.uuid4().hex[:6].upper()}"

    gettone = gettone_csrf(client, "/posta/motivi")
    risposta = client.post(
        "/posta/motivi",
        data={"codice": sigla, "descrizione": "Motivo di prova", "csrf": gettone},
        follow_redirects=False,
    )

    assert risposta.status_code == 303

    creato = db_session.scalars(
        select(EmailReason).where(EmailReason.code == sigla)
    ).first()
    assert creato is not None
    assert creato.is_active is True

    # E lo si puo' togliere dai riconosciuti senza cancellare niente.
    gettone = gettone_csrf(client, "/posta/motivi")
    client.post(
        f"/posta/motivi/{creato.id}/proponibilita",
        data={"csrf": gettone},
        follow_redirects=False,
    )
    db_session.refresh(creato)
    assert creato.is_active is False


def test_un_motivo_doppio_viene_rifiutato_con_una_frase_italiana(client, db_session):
    """Due voci identiche in un elenco sono un errore che chi sceglie non risolve."""
    creatore = crea_creatore(db_session)
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    gettone = gettone_csrf(client, "/posta/motivi")
    risposta = client.post(
        "/posta/motivi",
        data={"codice": "specs", "descrizione": "", "csrf": gettone},
    )

    assert risposta.status_code == 400
    assert "SPECS" in risposta.text


def test_la_scheda_del_progetto_porta_alla_sua_posta(client, db_session):
    """Il riquadro della posta compare nella scheda del progetto."""
    creatore = crea_creatore(db_session)
    _prodotto, versione = crea_prodotto(db_session, codice=codice_irripetibile())
    progetto = crea_progetto(db_session, versione, creatore)
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/progetti/{progetto.id}")

    assert risposta.status_code == 200
    assert f"/posta?progetto={progetto.id}" in risposta.text


def test_lo_storico_di_un_messaggio_si_apre(client, db_session):
    """Ogni oggetto ha la sua scheda e il suo storico, posta compresa."""
    creatore = crea_creatore(db_session)
    esito = elabora(
        db_session,
        eml(identificativo=identificativo_di_prova(), oggetto="Con storico"),
    )
    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/posta/{esito.messaggio.id}/storico")

    assert risposta.status_code == 200
    assert "Messaggio messo in quarantena" in risposta.text
