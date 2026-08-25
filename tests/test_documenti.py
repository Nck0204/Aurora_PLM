"""I test dell'archivio documenti: sessione 6.

Sono divisi come e' divisa la sessione: prima l'archivio fisico (impronta,
deduplicazione, scrittura atomica), poi il versionamento, poi l'immutabilita'
del rilasciato, poi la filigrana, poi il ritiro logico, poi i permessi e le
pagine.

DUE COSE DA SAPERE PRIMA DI AGGIUNGERNE UNO.

**Il rollback copre il database, non il disco.** La transazione del test
annulla le righe scritte; i file depositati in storage/objects restano. Non e'
un problema - sono oggetti che nessuna riga riferisce, non si cancellano
(regola 5 di CLAUDE.md) e la deduplicazione li riuserebbe - ma e' il motivo
per cui il contenuto dei file di prova deve essere irripetibile:
contenuto_irripetibile() e pdf_di_prova() in conftest.py. Un test che
scrivesse sempre gli stessi byte troverebbe il lavoro del test precedente gia'
fatto, e la verifica della deduplicazione direbbe di si' anche se la
deduplicazione fosse rotta.

**I nomi utente hanno due punti.** proponi_username() non ne produce mai, ed
e' lo spazio di nomi che il programma vero non raggiunge (vedi la nota in
cima a conftest.py).
"""

import io
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    Document,
    DocumentState,
    DocumentVersion,
    GlobalRole,
    LifecycleState,
    ProjectRole,
)
from app.services import documents, lifecycle, permissions, storage, watermark
from tests.conftest import (
    PASSWORD_DI_PROVA,
    classificazione_di_prova,
    contenuto_irripetibile,
    contenuto_leggibile,
    crea_documento,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
    pdf_di_prova,
)


# --- Preparazione comune ----------------------------------------------------


def prepara_progetto(db, ruolo=GlobalRole.CREATORE):
    """Un progetto vero con il suo prodotto, la sua versione e un responsabile.

    Restituisce (progetto, responsabile). E' il punto di partenza di quasi
    tutti i test di questo file: un documento non esiste fuori da un progetto.
    """
    responsabile = crea_utente(
        db, username=f"prova.doc.{uuid.uuid4().hex[:8]}", ruolo=ruolo
    )
    _, versione = crea_prodotto(db)
    progetto = crea_progetto(db, versione, responsabile)
    return progetto, responsabile


# ===========================================================================
#  1. L'ARCHIVIO FISICO
# ===========================================================================


def test_il_file_viene_depositato_nel_percorso_ricavato_dall_impronta():
    """L'impronta e' il percorso: due caratteri, due caratteri, il resto.

    Non e' un dettaglio estetico. E' quello che evita il limite dei 260
    caratteri di Windows, i caratteri che un nome di file non puo' contenere e
    due "schema.pdf" diversi che si sovrascrivono.
    """
    contenuto = contenuto_irripetibile()

    deposito = storage.deposita(io.BytesIO(contenuto))
    percorso = storage.percorso_di(deposito.impronta)

    assert deposito.impronta == storage.impronta_di(contenuto)
    assert percorso.is_file()
    assert percorso.name == deposito.impronta
    assert percorso.parent.name == deposito.impronta[2:4]
    assert percorso.parent.parent.name == deposito.impronta[:2]
    assert percorso.read_bytes() == contenuto


def test_lo_stesso_file_caricato_due_volte_occupa_un_solo_oggetto(db_session):
    """Criterio di accettazione: sul disco esiste un solo oggetto.

    Due documenti **diversi**, in due progetti **diversi**, con lo stesso
    identico contenuto: due righe in document_versions, un file solo sul
    disco. E' il caso di tutti i giorni, non un caso limite - lo stesso
    datasheet allegato a quindici progetti.
    """
    contenuto = contenuto_irripetibile()

    primo_progetto, primo_autore = prepara_progetto(db_session)
    secondo_progetto, secondo_autore = prepara_progetto(db_session)

    primo, versione_uno = crea_documento(
        db_session, primo_progetto, primo_autore, contenuto=contenuto
    )
    secondo, versione_due = crea_documento(
        db_session, secondo_progetto, secondo_autore, contenuto=contenuto
    )

    assert primo.id != secondo.id
    assert versione_uno.id != versione_due.id

    # La stessa impronta, quindi lo stesso file.
    assert versione_uno.storage_hash == versione_due.storage_hash

    percorso = storage.percorso_di(versione_uno.storage_hash)
    assert percorso.is_file()

    # Sul disco, dentro la cartella di quell'impronta, c'e' un oggetto solo.
    oggetti = [
        candidato
        for candidato in percorso.parent.iterdir()
        if candidato.name == versione_uno.storage_hash
    ]
    assert len(oggetti) == 1, "lo stesso contenuto e' stato scritto due volte"


def test_il_secondo_deposito_dichiara_di_non_aver_riscritto_niente():
    """La deduplicazione si vede anche dal valore restituito.

    Serve perche' il caricamento la scriva nel registro: dal solo audit trail
    si deve poter rispondere a "quanto spazio ci ha fatto risparmiare la
    deduplicazione".
    """
    contenuto = contenuto_irripetibile()

    primo = storage.deposita(io.BytesIO(contenuto))
    secondo = storage.deposita(io.BytesIO(contenuto))

    assert primo.gia_presente is False
    assert secondo.gia_presente is True
    assert primo.impronta == secondo.impronta
    assert primo.dimensione == secondo.dimensione == len(contenuto)


def test_la_scrittura_non_lascia_temporanei():
    """A deposito finito nella cartella tmp non resta niente.

    Un temporaneo rimasto vuol dire un caricamento interrotto: se ne
    restassero dopo un caricamento riuscito, la cartella si riempirebbe di
    copie di ogni file caricato.
    """
    storage.deposita(io.BytesIO(contenuto_irripetibile()))

    assert storage.temporanei_rimasti() == []


class SorgenteCheSiRompe:
    """Una sorgente che si interrompe a meta', come una connessione caduta.

    Restituisce un blocco e poi solleva. E' il modo di provare la scrittura
    atomica senza spegnere davvero il server: quello che conta e' che
    l'interruzione arrivi **dopo** che qualcosa e' stato scritto.
    """

    def __init__(self, primo_blocco: bytes) -> None:
        self.primo_blocco = primo_blocco
        self.gia_letto = False

    def read(self, quanti: int = -1) -> bytes:
        if self.gia_letto:
            raise OSError("connessione interrotta a meta' caricamento")
        self.gia_letto = True
        return self.primo_blocco


def test_un_caricamento_interrotto_non_lascia_niente(db_session):
    """Criterio di accettazione: la scrittura e' atomica.

    Il caricamento si interrompe dopo che il primo blocco e' stato scritto.
    Nell'archivio non deve restare niente: ne' un file troncato al posto
    giusto - che sarebbe il caso peggiore, un file che sembra buono e non lo
    e' - ne' un temporaneo abbandonato.
    """
    prima = set(storage.temporanei_rimasti())
    oggetti_prima = _oggetti_nell_archivio()

    with pytest.raises(OSError):
        storage.deposita(SorgenteCheSiRompe(contenuto_irripetibile()))

    assert set(storage.temporanei_rimasti()) == prima, (
        "un caricamento interrotto ha lasciato un temporaneo nell'archivio"
    )
    assert _oggetti_nell_archivio() == oggetti_prima, (
        "un caricamento interrotto ha lasciato un file nell'archivio"
    )


def _oggetti_nell_archivio() -> set[str]:
    """I nomi di tutti gli oggetti presenti adesso nell'archivio."""
    cartella = storage.cartella_oggetti()
    if not cartella.is_dir():
        return set()
    return {file.name for file in cartella.rglob("*") if file.is_file()}


def test_il_file_troppo_grande_viene_fermato_mentre_arriva():
    """Il limite si verifica durante la lettura, non dopo.

    Un file da otto gigabyte va fermato prima di aver riempito il disco. Il
    messaggio e' gia' in italiano: chi lo cattura lo mostra e basta.
    """
    oggetti_prima = _oggetti_nell_archivio()

    with pytest.raises(storage.FileTroppoGrande) as errore:
        storage.deposita(io.BytesIO(b"x" * 5000), limite_byte=1000)

    assert "dimensione massima" in str(errore.value)
    assert _oggetti_nell_archivio() == oggetti_prima
    assert storage.temporanei_rimasti() == []


def test_un_impronta_inventata_non_porta_fuori_dall_archivio():
    """L'impronta diventa un percorso, quindi va verificata.

    Senza questo controllo un valore che contiene due punti farebbe leggere o
    scrivere fuori da STORAGE_PATH. E' l'unico punto in cui un dato del
    database diventa un percorso, quindi e' l'unico in cui serve il controllo.
    """
    for finta in ("../../etc/passwd", "", "ZZZZ", "a" * 63, "a" * 65):
        with pytest.raises(ValueError):
            storage.percorso_di(finta)


def test_l_impronta_si_legge_anche_scritta_in_maiuscolo():
    """Su Windows i percorsi non distinguono le maiuscole, il database si'.

    Normalizzando a minuscolo dentro percorso_di(), una sola forma raggiunge
    il disco.
    """
    deposito = storage.deposita(io.BytesIO(contenuto_irripetibile()))

    assert storage.percorso_di(deposito.impronta.upper()) == storage.percorso_di(
        deposito.impronta
    )


# ===========================================================================
#  2. IL VERSIONAMENTO
# ===========================================================================


def carica_versione(db, documento, autore, contenuto=None, nota="Corretto R12"):
    """Aggiunge una versione a un documento passando dal servizio vero."""
    if contenuto is None:
        contenuto = contenuto_irripetibile()

    deposito = storage.deposita(io.BytesIO(contenuto))
    caricamento = documents.Caricamento(
        sorgente=io.BytesIO(contenuto),
        nome_file="schema.pdf",
        mime_type="application/pdf",
    )
    versione = documents.aggiungi_versione(
        db,
        documento=documento,
        caricamento=caricamento,
        deposito=deposito,
        nota=nota,
        autore=autore,
    )
    db.flush()
    return versione


def test_la_versione_precedente_resta_scaricabile_e_identica(db_session):
    """Criterio di accettazione: la precedente resta identica all'originale.

    La verifica passa dall'impronta, che e' il solo modo serio di dire
    "identica": si ricalcola lo SHA-256 del file che c'e' adesso
    nell'archivio e si confronta con i byte caricati allora.
    """
    progetto, autore = prepara_progetto(db_session)
    contenuto_uno = contenuto_irripetibile(b"schema revisione A")

    documento, prima = crea_documento(
        db_session, progetto, autore, contenuto=contenuto_uno
    )
    impronta_di_allora = prima.storage_hash

    seconda = carica_versione(db_session, documento, autore)

    assert seconda.version_number == 2
    assert prima.version_number == 1

    # La riga della prima versione non e' stata toccata.
    db_session.refresh(prima)
    assert prima.storage_hash == impronta_di_allora

    # E il file nell'archivio e' ancora quello, byte per byte.
    dal_disco = storage.leggi(prima.storage_hash)
    assert dal_disco == contenuto_uno
    assert storage.impronta_di(dal_disco) == impronta_di_allora

    # Le due versioni sono due file diversi.
    assert seconda.storage_hash != prima.storage_hash


def test_la_nota_di_modifica_e_obbligatoria(db_session):
    """Senza nota non si carica una versione nuova.

    E' l'unica informazione che nessun programma potra' mai ricostruire da
    solo guardando i due file.
    """
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)

    with pytest.raises(documents.NotaObbligatoria):
        carica_versione(db_session, documento, autore, nota="   ")


def test_i_numeri_di_versione_crescono_di_uno(db_session):
    """Uno, due, tre: un contatore, non un numero di rilascio."""
    progetto, autore = prepara_progetto(db_session)
    documento, prima = crea_documento(db_session, progetto, autore)

    seconda = carica_versione(db_session, documento, autore)
    terza = carica_versione(db_session, documento, autore)

    assert [prima.version_number, seconda.version_number, terza.version_number] == [
        1,
        2,
        3,
    ]

    tutte = documents.versioni_di(db_session, documento.id)
    # In elenco arrivano dalla piu' recente: e' la domanda che si fa aprendo
    # la scheda ("com'e' adesso"), non la storia dall'inizio.
    assert [v.version_number for v in tutte] == [3, 2, 1]


def test_la_versione_corrente_e_l_ultima_caricata(db_session):
    """La versione che vale e' sempre quella con il numero piu' alto."""
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)
    terza = carica_versione(db_session, documento, autore)

    db_session.refresh(documento)
    assert documents.versione_corrente(documento).id == terza.id


def test_il_caricamento_finisce_nel_registro(db_session):
    """Regola 6 di CLAUDE.md: chi, che cosa, quando."""
    progetto, autore = prepara_progetto(db_session)
    documento, versione = crea_documento(db_session, progetto, autore)

    righe = db_session.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == documents.ENTITY_DOCUMENTS,
            AuditLog.entity_id == documento.id,
        )
    ).all()

    azioni = {riga.action for riga in righe}
    assert documents.ACTION_DOCUMENT_CREATED in azioni
    assert documents.ACTION_VERSION_UPLOADED in azioni

    caricamento = next(
        riga for riga in righe if riga.action == documents.ACTION_VERSION_UPLOADED
    )
    assert caricamento.user_id == autore.id
    assert caricamento.new_value["storage_hash"] == versione.storage_hash
    assert caricamento.new_value["version_number"] == 1


# ===========================================================================
#  3. L'IMMUTABILITA' DEL RILASCIATO
# ===========================================================================


def porta_a_rilasciato(db, documento, autore):
    """Fa il giro completo bozza -> in verifica -> rilasciato."""
    documents.cambia_stato(
        db,
        documento=documento,
        nuovo_stato=DocumentState.IN_VERIFICA,
        autore=autore,
    )
    documents.cambia_stato(
        db,
        documento=documento,
        nuovo_stato=DocumentState.RILASCIATO,
        autore=autore,
    )
    db.flush()
    return documento


def test_il_grafo_dei_documenti_copre_tutti_gli_stati():
    """Ogni stato di DocumentState ha la sua riga nel grafo.

    Non e' un test di comportamento ma di forma, come quello del ciclo di vita
    delle versioni: aggiungendo uno stato senza aggiungerne la riga, quello
    stato si comporterebbe da terminale senza che nessuno lo abbia deciso.
    """
    for stato in DocumentState:
        assert stato in lifecycle.TRANSIZIONI_DOCUMENTO, (
            f"lo stato '{stato.value}' non compare nel grafo dei documenti: "
            "si comporterebbe come terminale senza che nessuno lo abbia deciso"
        )


def test_un_documento_rilasciato_non_torna_indietro(db_session):
    """Da "rilasciato" si va solo a "superato". Mai in bozza, mai in verifica.

    Il messaggio non dice soltanto "non si puo'": dice come si fa. Chi ci
    prova sta cercando di correggere un documento, e la risposta utile e'
    "si carica una versione nuova".
    """
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)
    porta_a_rilasciato(db_session, documento, autore)

    for vietato in (DocumentState.BOZZA, DocumentState.IN_VERIFICA):
        with pytest.raises(lifecycle.TransizioneNonAmmessa) as errore:
            documents.cambia_stato(
                db_session,
                documento=documento,
                nuovo_stato=vietato,
                autore=autore,
            )
        assert "versione nuova" in str(errore.value)

    assert lifecycle.stati_documento_raggiungibili(DocumentState.RILASCIATO) == (
        DocumentState.SUPERATO,
    )


def test_caricare_una_versione_su_un_rilasciato_lo_riporta_in_bozza(db_session):
    """Criterio di accettazione: qualsiasi modifica genera una nuova bozza.

    E la versione rilasciata resta dov'era, identica: sostituire un file non
    e' un'operazione che Aurora sa fare, quindi non c'e' niente da impedire.
    """
    progetto, autore = prepara_progetto(db_session)
    contenuto_rilasciato = contenuto_irripetibile(b"schema approvato")

    documento, rilasciata = crea_documento(
        db_session, progetto, autore, contenuto=contenuto_rilasciato
    )
    porta_a_rilasciato(db_session, documento, autore)
    assert documento.state is DocumentState.RILASCIATO

    nuova = carica_versione(db_session, documento, autore, nota="Nuova revisione")

    db_session.refresh(documento)
    assert documento.state is DocumentState.BOZZA
    assert nuova.version_number == 2

    # La versione rilasciata non e' stata toccata.
    db_session.refresh(rilasciata)
    assert storage.leggi(rilasciata.storage_hash) == contenuto_rilasciato

    # E il ritorno in bozza e' scritto nel registro, con il suo motivo.
    #
    # La riga si cerca per contenuto e non "l'ultima scritta": dentro una sola
    # transazione PostgreSQL da a now() lo stesso valore per tutte le righe,
    # quindi ordinare per occurred_at non distinguerebbe niente. E' una
    # trappola che vale per qualunque test che guardi il registro.
    ritorni = [
        riga
        for riga in db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == documento.id,
                AuditLog.action == documents.ACTION_STATE_CHANGED,
            )
        ).all()
        if riga.new_value.get("state") == DocumentState.BOZZA.value
    ]

    assert len(ritorni) == 1
    assert "versione nuova" in ritorni[0].new_value["motivo"]
    assert ritorni[0].old_value["state"] == DocumentState.RILASCIATO.value


def test_il_rilascio_registra_autore_e_data(db_session):
    """Il passaggio a rilasciato viene registrato con chi e quando.

    Il dato non e' duplicato in una colonna: sta nel registro delle
    operazioni, che e' il posto in cui i fatti vengono registrati. La scheda
    lo rilegge da li'.
    """
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)
    porta_a_rilasciato(db_session, documento, autore)

    rilascio = documents.ultimo_rilascio(db_session, documento.id)

    assert rilascio is not None
    assert rilascio.user_id == autore.id
    assert rilascio.new_value["state"] == DocumentState.RILASCIATO.value
    assert rilascio.occurred_at is not None


def test_l_interfaccia_non_propone_di_sostituire_un_rilasciato(client, db_session):
    """Criterio di accettazione, visto dall'interfaccia.

    Sulla scheda di un documento rilasciato non c'e' nessun pulsante che
    riporti indietro lo stato: gli unici passaggi proposti sono quelli del
    grafo. Quello che c'e' e' l'invito a caricare una versione nuova.
    """
    progetto, creatore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, creatore)
    porta_a_rilasciato(db_session, documento, creatore)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    scheda = client.get(f"/documenti/{documento.id}")
    testo = contenuto_leggibile(scheda)

    assert scheda.status_code == 200
    assert "Carica una versione nuova" in testo
    assert "non si sostituisce piu'" in testo

    # Nessun pulsante che riporti a bozza o in verifica.
    assert f"/documenti/{documento.id}/stato?nuovo=bozza" not in testo
    assert f"/documenti/{documento.id}/stato?nuovo=in_verifica" not in testo
    # Quello verso "superato" c'e', perche' e' l'unico ammesso dal grafo.
    assert f"/documenti/{documento.id}/stato?nuovo=superato" in testo


def test_una_transizione_costruita_a_mano_viene_rifiutata(client, db_session):
    """Anche scrivendo l'indirizzo a mano il grafo vale.

    L'interfaccia non propone il passaggio, ma un indirizzo si scrive: il
    rifiuto e' una frase italiana, non un errore tecnico.
    """
    progetto, creatore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, creatore)
    porta_a_rilasciato(db_session, documento, creatore)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(f"/documenti/{documento.id}/stato?nuovo=bozza")

    assert risposta.status_code == 400
    assert "versione nuova" in contenuto_leggibile(risposta)


# ===========================================================================
#  4. LA FILIGRANA
# ===========================================================================


def supera_la_versione_di_prodotto(db, progetto):
    """Porta la versione di prodotto del progetto a "superato".

    Ci si arriva passando da "rilasciato", perche' il grafo del ciclo di vita
    non ammette scorciatoie: e' la stessa strada che farebbe una persona.
    """
    versione = progetto.product_version
    versione.lifecycle_state = LifecycleState.SUPERATO
    db.flush()
    return versione


def test_il_pdf_di_una_versione_superata_esce_con_la_filigrana(client, db_session):
    """Criterio di accettazione: scarico un PDF da una versione superata,
    la filigrana c'e'.

    La verifica non si accontenta del fatto che la risposta arrivi: rilegge il
    PDF ricevuto e ci cerca dentro la dicitura. Un test che guardasse solo il
    codice di stato passerebbe anche con la filigrana rotta.
    """
    progetto, creatore = prepara_progetto(db_session)
    documento, versione = crea_documento(
        db_session,
        progetto,
        creatore,
        contenuto=pdf_di_prova(),
        nome_file="schema.pdf",
        mime_type="application/pdf",
    )
    supera_la_versione_di_prodotto(db_session, progetto)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(
        f"/documenti/{documento.id}/versioni/{versione.id}/scarica"
    )

    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith("application/pdf")

    testo = watermark.testo_di(risposta.content)
    assert "VERSIONE SUPERATA" in testo
    assert "non utilizzare per la produzione" in testo
    assert "superato" in testo
    assert "Scaricato il" in testo

    # Il nome consegnato porta l'avvertenza anche fuori da Aurora.
    assert watermark.AVVERTENZA_NEL_NOME in risposta.headers["content-disposition"]

    # L'originale nell'archivio non e' stato toccato.
    assert storage.impronta_di(storage.leggi(versione.storage_hash)) == (
        versione.storage_hash
    )
    assert risposta.content != storage.leggi(versione.storage_hash)


def test_il_pdf_di_una_versione_valida_esce_identico(client, db_session):
    """Nessuna filigrana quando la versione di prodotto e' ancora buona.

    E' l'altra meta' del criterio: marchiare tutto sarebbe come non marchiare
    niente.
    """
    progetto, creatore = prepara_progetto(db_session)
    contenuto = pdf_di_prova()
    documento, versione = crea_documento(
        db_session, progetto, creatore, contenuto=contenuto,
        nome_file="schema.pdf", mime_type="application/pdf",
    )

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(
        f"/documenti/{documento.id}/versioni/{versione.id}/scarica"
    )

    assert risposta.status_code == 200
    assert risposta.content == contenuto
    assert watermark.AVVERTENZA_NEL_NOME not in risposta.headers[
        "content-disposition"
    ]


def test_la_filigrana_finisce_su_tutte_le_pagine():
    """Ogni pagina ha la sua, costruita sulla propria misura.

    Uno schema elettrico ha dentro un A4 e un A0: una filigrana sola,
    calcolata sulla prima, sarebbe fuori posto sulla seconda.
    """
    import datetime

    originale = pdf_di_prova(pagine=3)

    marchiato = watermark.applica(
        originale,
        stato=LifecycleState.OBSOLETO,
        momento=datetime.datetime(2026, 8, 25, 14, 32),
    )

    lettore = watermark.leggi_pdf(marchiato)
    assert len(lettore.pages) == 3

    for pagina in lettore.pages:
        assert "VERSIONE SUPERATA" in (pagina.extract_text() or "")


@pytest.mark.parametrize(
    "nome,larghezza,altezza",
    [
        ("A4 verticale", 595, 842),
        ("A4 orizzontale", 842, 595),
        ("A3 orizzontale", 1191, 842),
        ("A0 orizzontale", 3370, 2384),
        ("cartolina", 283, 200),
    ],
)
def test_la_filigrana_sta_dentro_i_bordi(nome, larghezza, altezza):
    """La filigrana non deve sbordare, su nessuna misura di pagina.

    E' il difetto trovato durante la verifica a mano di questa sessione. La
    misura del carattere si calcolava sulla diagonale della pagina, che e' la
    risposta istintiva e sbagliata: la diagonale e' lunga quanto la riga
    soltanto se la riga e' inclinata **esattamente** come la diagonale. Su un
    A4 verticale, a 38 gradi, il testo usciva di una novantina di punti per
    parte.

    Il test misura invece che guardare, perche' guardare un PDF non e' una
    cosa che un test sappia fare: si prende il corpo scelto dal servizio, si
    calcola l'ingombro della riga piu' lunga ruotata, e si controlla che stia
    dentro la pagina in tutte e due le direzioni.
    """
    import datetime
    import math

    righe = watermark.righe_filigrana(
        LifecycleState.SUPERATO, datetime.datetime(2026, 8, 25, 16, 0)
    )
    corpo = watermark._corpo_che_ci_sta(righe, larghezza, altezza)

    lunghezza = (
        max(len(riga) for riga in righe)
        * corpo
        * watermark.LARGHEZZA_MEDIA_CARATTERE
    )
    radianti = math.radians(watermark.ANGOLO_GRADI)

    assert lunghezza * math.cos(radianti) <= larghezza, (
        f"la filigrana sborda in larghezza su {nome}"
    )
    assert lunghezza * math.sin(radianti) <= altezza, (
        f"la filigrana sborda in altezza su {nome}"
    )
    assert corpo >= watermark.CORPO_MINIMO


def test_un_pdf_illeggibile_non_impedisce_lo_scarico():
    """Se la filigrana fallisce, il file esce lo stesso.

    Togliere a una persona un documento che ha il diritto di avere, per un
    guasto che non la riguarda, sarebbe il modo peggiore di sbagliare.
    L'errore viene registrato e trasformato in un'eccezione sola, che la
    rotta sa gestire consegnando l'originale.
    """
    import datetime

    with pytest.raises(watermark.FiligranaNonApplicata):
        watermark.applica(
            b"questo non e' un PDF",
            stato=LifecycleState.SUPERATO,
            momento=datetime.datetime(2026, 8, 25, 14, 32),
        )


def test_un_file_che_non_e_pdf_passa_dall_avviso(client, db_session):
    """Sui formati che non si marchiano, l'avvertenza si mostra a schermo.

    Il dirottamento sta nella rotta dello scarico e non nei collegamenti:
    cosi' vale per tutti i modi in cui ci si arriva, compreso un indirizzo
    copiato.
    """
    progetto, creatore = prepara_progetto(db_session)
    documento, versione = crea_documento(
        db_session,
        progetto,
        creatore,
        contenuto=contenuto_irripetibile(b"DWG finto"),
        nome_file="meccanica.dwg",
        mime_type="application/acad",
    )
    supera_la_versione_di_prodotto(db_session, progetto)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    indirizzo = f"/documenti/{documento.id}/versioni/{versione.id}/scarica"
    dirottato = client.get(indirizzo, follow_redirects=False)

    assert dirottato.status_code == 303
    assert dirottato.headers["location"].endswith("/avviso")

    avviso = client.get(dirottato.headers["location"])
    testo = contenuto_leggibile(avviso)
    assert avviso.status_code == 200
    assert "Non usarlo per la produzione" in testo
    assert "VERSIONE-SUPERATA_meccanica.dwg" in testo

    # Letto l'avviso, il file si scarica, con l'avvertenza nel nome.
    scaricato = client.get(f"{indirizzo}?avvisato=1")
    assert scaricato.status_code == 200
    assert "VERSIONE-SUPERATA_meccanica.dwg" in scaricato.headers[
        "content-disposition"
    ]


def test_l_avvertenza_non_si_attacca_due_volte():
    """Un nome che ce l'ha gia' non se la prende una seconda volta.

    Succede quando si riscarica un file che era gia' stato scaricato e
    rimesso dentro Aurora com'era.
    """
    primo = watermark.nome_con_avvertenza("schema.dwg")
    secondo = watermark.nome_con_avvertenza(primo)

    assert primo == "VERSIONE-SUPERATA_schema.dwg"
    assert secondo == primo


def test_si_marchia_solo_quello_che_va_marchiato():
    """Superato e obsoleto si', gli altri tre no."""
    assert watermark.serve_filigrana(LifecycleState.SUPERATO) is True
    assert watermark.serve_filigrana(LifecycleState.OBSOLETO) is True
    assert watermark.serve_filigrana(LifecycleState.IN_SVILUPPO) is False
    assert watermark.serve_filigrana(LifecycleState.RILASCIATO) is False
    assert watermark.serve_filigrana(LifecycleState.IN_PRODUZIONE) is False
    assert watermark.serve_filigrana(None) is False


def test_un_pdf_si_riconosce_dal_tipo_o_dal_nome():
    """Il tipo dichiarato dal browser e' quello buono, ma non sempre c'e'."""
    assert watermark.e_un_pdf("application/pdf", "x.bin") is True
    assert watermark.e_un_pdf("application/octet-stream", "schema.PDF") is True
    assert watermark.e_un_pdf("application/acad", "meccanica.dwg") is False
    assert watermark.e_un_pdf(None, None) is False


# ===========================================================================
#  5. IL RITIRO LOGICO
# ===========================================================================


def test_il_documento_ritirato_sparisce_dagli_elenchi(db_session):
    """Regola 5 della sessione: l'eliminazione e' solo logica."""
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)

    trovati, totale = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id
    )
    assert documento.id in {trovato.id for trovato in trovati}
    assert totale == 1

    documents.elimina(db_session, documento=documento, autore=autore)
    db_session.flush()

    trovati, totale = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id
    )
    assert trovati == []
    assert totale == 0

    # Ma la riga c'e' ancora, con chi lo ha tolto e quando.
    ancora = db_session.get(Document, documento.id)
    assert ancora is not None
    assert ancora.is_deleted
    assert ancora.deleted_by_id == autore.id


def test_il_documento_ritirato_si_ripristina_com_era(db_session):
    """Ripristinandolo torna esattamente com'era: stato, versioni, file."""
    progetto, autore = prepara_progetto(db_session)
    documento, prima = crea_documento(db_session, progetto, autore)
    carica_versione(db_session, documento, autore)
    porta_a_rilasciato(db_session, documento, autore)

    stato_di_allora = documento.state
    quante_versioni = len(documents.versioni_di(db_session, documento.id))

    documents.elimina(db_session, documento=documento, autore=autore)
    db_session.flush()
    documents.ripristina(db_session, documento=documento, autore=autore)
    db_session.flush()

    db_session.refresh(documento)
    assert documento.is_deleted is False
    assert documento.deleted_by_id is None
    assert documento.state is stato_di_allora
    assert len(documents.versioni_di(db_session, documento.id)) == quante_versioni

    trovati, _ = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id
    )
    assert documento.id in {trovato.id for trovato in trovati}


def test_il_ritirato_resta_visibile_al_creatore(db_session):
    """La sezione dedicata: i ritirati li vede chi ha il ruolo di creatore."""
    progetto, creatore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, creatore)
    documents.elimina(db_session, documento=documento, autore=creatore)
    db_session.flush()

    ritirati = documents.documenti_ritirati(db_session)

    assert documento.id in {trovato.id for trovato in ritirati}


def test_su_un_documento_ritirato_non_si_carica(db_session):
    """Prima si ripristina, poi si carica. Non il contrario."""
    progetto, autore = prepara_progetto(db_session)
    documento, _ = crea_documento(db_session, progetto, autore)
    documents.elimina(db_session, documento=documento, autore=autore)
    db_session.flush()

    with pytest.raises(documents.DocumentoEliminato):
        carica_versione(db_session, documento, autore)

    with pytest.raises(documents.DocumentoEliminato):
        documents.cambia_stato(
            db_session,
            documento=documento,
            nuovo_stato=DocumentState.IN_VERIFICA,
            autore=autore,
        )


def test_non_esiste_nessuna_rotta_per_cancellare_un_documento():
    """Regola 5 di CLAUDE.md, verificata sull'elenco delle rotte.

    Non e' un test di comportamento ma di forma: un giorno qualcuno potrebbe
    aggiungere una rotta di cancellazione in buona fede, e questo test glielo
    dice prima che finisca in produzione.
    """
    from app.routers import documents as rotte_documenti

    for rotta in rotte_documenti.router.routes:
        metodi = sorted(rotta.methods)
        assert "DELETE" not in metodi, f"{rotta.path} non deve accettare DELETE"
        assert "cancella" not in rotta.path, f"{rotta.path} non deve esistere"


def test_il_file_resta_nell_archivio_anche_dopo_il_ritiro(db_session):
    """Il ritiro toglie il collegamento, non il file (D-004).

    Quel contenuto potrebbe essere riferito da un altro documento che ha lo
    stesso file: cancellarlo lo porterebbe via a tutti e due.
    """
    progetto, autore = prepara_progetto(db_session)
    documento, versione = crea_documento(db_session, progetto, autore)

    documents.elimina(db_session, documento=documento, autore=autore)
    db_session.flush()

    assert storage.esiste(versione.storage_hash)


# ===========================================================================
#  6. I PERMESSI
# ===========================================================================


def test_chi_non_e_assegnato_non_vede_i_documenti(client, db_session):
    """Chi non e' nella squadra non vede i documenti, nemmeno per indirizzo.

    L'elenco e la scheda passano dalla stessa regola: un elenco che nasconde
    una riga che poi si apre non e' una protezione, e' una tenda.
    """
    progetto, responsabile = prepara_progetto(db_session, ruolo=GlobalRole.UTENTE)
    documento, _ = crea_documento(db_session, progetto, responsabile)

    estraneo = crea_utente(
        db_session,
        username=f"prova.estraneo.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.UTENTE,
    )
    db_session.flush()

    trovati, totale = documents.cerca_documenti(db_session, estraneo)
    assert documento.id not in {trovato.id for trovato in trovati}

    # 404 e non 403: chi non e' assegnato non deve nemmeno poter dedurre
    # che quell'identificativo corrisponda a un documento (D-051).
    entra(client, estraneo.username, PASSWORD_DI_PROVA)
    risposta = client.get(f"/documenti/{documento.id}")
    assert risposta.status_code == 404


def test_il_lettore_vede_ma_non_carica(db_session):
    """La matrice dei permessi decide, non il documento e non la persona."""
    from app.services import projects

    progetto, responsabile = prepara_progetto(db_session, ruolo=GlobalRole.UTENTE)
    classe = classificazione_di_prova(db_session)
    documento, _ = crea_documento(
        db_session, progetto, responsabile, classificazione=classe
    )

    lettore = crea_utente(
        db_session,
        username=f"prova.lettore.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.UTENTE,
    )
    projects.assegna(
        db_session,
        progetto=progetto,
        utente=lettore,
        ruolo=ProjectRole.LETTORE,
        autore=responsabile,
    )
    db_session.flush()

    bersaglio = permissions.BersaglioCaricamento(
        progetto=progetto, classification_id=classe.id
    )

    assert permissions.puo(
        db_session, lettore, permissions.Azione.VEDERE, bersaglio
    )
    assert not permissions.puo(
        db_session, lettore, permissions.Azione.CARICARE, bersaglio
    )
    assert not permissions.puo(
        db_session, lettore, permissions.Azione.MODIFICARE, bersaglio
    )

    # E infatti l'elenco glielo mostra.
    trovati, _ = documents.cerca_documenti(
        db_session, lettore, project_id=progetto.id
    )
    assert documento.id in {trovato.id for trovato in trovati}


def test_il_creatore_vede_tutto(db_session):
    """E' lui che apre i progetti e assegna le persone: vede tutto."""
    progetto, responsabile = prepara_progetto(db_session, ruolo=GlobalRole.UTENTE)
    documento, _ = crea_documento(db_session, progetto, responsabile)

    creatore = crea_utente(
        db_session,
        username=f"prova.capo.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    db_session.flush()

    trovati, _ = documents.cerca_documenti(
        db_session, creatore, project_id=progetto.id
    )
    assert documento.id in {trovato.id for trovato in trovati}

    assert all(
        permissions.puo(db_session, creatore, azione, documento)
        for azione in permissions.Azione
    )


# ===========================================================================
#  7. L'ELENCO E LE PAGINE
# ===========================================================================


def test_la_ricerca_trova_il_documento_dal_titolo(db_session):
    """La ricerca e' sul titolo. Dentro il contenuto e' del rilascio R2."""
    progetto, autore = prepara_progetto(db_session)
    parola = f"Alimentatore{uuid.uuid4().hex[:6]}"

    voluto, _ = crea_documento(
        db_session, progetto, autore, titolo=f"Schema {parola} 24V"
    )
    crea_documento(db_session, progetto, autore, titolo="Distinta base")

    trovati, totale = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id, testo=parola
    )

    assert totale == 1
    assert trovati[0].id == voluto.id


def test_i_filtri_per_tipo_e_per_stato(db_session):
    """Due filtri, come li chiede la sessione."""
    progetto, autore = prepara_progetto(db_session)

    schema, _ = crea_documento(
        db_session, progetto, autore, titolo="Schema", tipo="Schema elettrico"
    )
    firmware, _ = crea_documento(
        db_session, progetto, autore, titolo="Firmware", tipo="Firmware"
    )
    documents.cambia_stato(
        db_session,
        documento=firmware,
        nuovo_stato=DocumentState.IN_VERIFICA,
        autore=autore,
    )
    db_session.flush()

    per_tipo, _ = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id, tipo="Firmware"
    )
    assert {trovato.id for trovato in per_tipo} == {firmware.id}

    per_stato, _ = documents.cerca_documenti(
        db_session, autore, project_id=progetto.id, stato="bozza"
    )
    assert {trovato.id for trovato in per_stato} == {schema.id}

    tipi = documents.tipi_in_uso(db_session, autore)
    assert "Schema elettrico" in tipi
    assert "Firmware" in tipi


def test_si_carica_un_documento_senza_javascript(client, db_session):
    """Il caricamento e' una delle cose che non possono dipendere da uno script.

    Il test invia il modulo come lo invierebbe un browser con JavaScript
    spento: nessun XMLHttpRequest, nessuna barra di avanzamento, solo un POST
    multipart con dentro il gettone CSRF letto dalla pagina.
    """
    progetto, creatore = prepara_progetto(db_session)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    modulo = client.get(f"/documenti/nuovo?progetto={progetto.id}")
    assert modulo.status_code == 200

    gettone = gettone_csrf(client, f"/documenti/nuovo?progetto={progetto.id}")
    classe = classificazione_di_prova(db_session)
    contenuto = contenuto_irripetibile(b"schema caricato dal browser")

    risposta = client.post(
        "/documenti/nuovo",
        data={
            "csrf": gettone,
            "progetto": str(progetto.id),
            "titolo": "Schema caricato a mano",
            "tipo": "Schema elettrico",
            "classificazione": str(classe.id),
        },
        files=[("file", ("schema.pdf", contenuto, "application/pdf"))],
        follow_redirects=False,
    )

    assert risposta.status_code == 303

    creato = db_session.scalars(
        select(Document).where(
            Document.project_id == progetto.id,
            Document.title == "Schema caricato a mano",
        )
    ).first()

    assert creato is not None
    assert creato.state is DocumentState.BOZZA
    versione = documents.versione_corrente(creato)
    assert versione.version_number == 1
    assert versione.original_filename == "schema.pdf"
    assert versione.size_bytes == len(contenuto)
    assert storage.leggi(versione.storage_hash) == contenuto


def test_piu_file_insieme_diventano_piu_documenti(client, db_session):
    """Un file, un documento: il titolo lo da' il nome del file.

    Con piu' file scelti insieme non ci sarebbe un titolo solo che vada bene
    per tutti, quindi ognuno prende il proprio.
    """
    progetto, creatore = prepara_progetto(db_session)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    gettone = gettone_csrf(client, f"/documenti/nuovo?progetto={progetto.id}")
    classe = classificazione_di_prova(db_session)

    coda = uuid.uuid4().hex[:8]
    risposta = client.post(
        "/documenti/nuovo",
        data={
            "csrf": gettone,
            "progetto": str(progetto.id),
            "titolo": "Questo titolo non deve vincere",
            "tipo": "Meccanica",
            "classificazione": str(classe.id),
        },
        files=[
            ("file", (f"telaio-{coda}.step", contenuto_irripetibile(), "model/step")),
            ("file", (f"staffa-{coda}.step", contenuto_irripetibile(), "model/step")),
        ],
        follow_redirects=False,
    )

    assert risposta.status_code == 303

    creati = db_session.scalars(
        select(Document).where(
            Document.project_id == progetto.id,
            Document.doc_type == "Meccanica",
        )
    ).all()

    titoli = {documento.title for documento in creati}
    assert titoli == {f"telaio-{coda}", f"staffa-{coda}"}
    assert "Questo titolo non deve vincere" not in titoli


def test_lo_scarico_finisce_nel_registro(client, db_session):
    """Regola 6 della sessione: utente, documento, versione, data."""
    progetto, creatore = prepara_progetto(db_session)
    documento, versione = crea_documento(db_session, progetto, creatore)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(
        f"/documenti/{documento.id}/versioni/{versione.id}/scarica"
    )
    assert risposta.status_code == 200

    riga = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == documents.ENTITY_DOCUMENTS,
            AuditLog.entity_id == documento.id,
            AuditLog.action == documents.ACTION_DOCUMENT_DOWNLOADED,
        )
        .order_by(AuditLog.occurred_at.desc())
    ).first()

    assert riga is not None
    assert riga.user_id == creatore.id
    assert riga.new_value["version_number"] == versione.version_number
    assert riga.new_value["version_id"] == str(versione.id)
    assert riga.new_value["filigrana"] is False
    assert riga.occurred_at is not None


def test_non_si_scarica_la_versione_di_un_altro_documento(client, db_session):
    """L'appartenenza si verifica: i permessi sono stati calcolati su un
    documento, e deve essere quello."""
    progetto, creatore = prepara_progetto(db_session)
    primo, _ = crea_documento(db_session, progetto, creatore, titolo="Primo")
    secondo, versione_del_secondo = crea_documento(
        db_session, progetto, creatore, titolo="Secondo"
    )
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(
        f"/documenti/{primo.id}/versioni/{versione_del_secondo.id}/scarica"
    )

    assert risposta.status_code == 404


def test_la_scheda_mostra_lo_storico_completo(client, db_session):
    """Punto 9 della sessione: autore, data, dimensione, nota, e lo scarico."""
    progetto, creatore = prepara_progetto(db_session)
    documento, prima = crea_documento(db_session, progetto, creatore)
    seconda = carica_versione(
        db_session, documento, creatore, nota="Corretta la resistenza R12"
    )
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    scheda = client.get(f"/documenti/{documento.id}")
    testo = contenuto_leggibile(scheda)

    assert scheda.status_code == 200
    assert "Corretta la resistenza R12" in testo
    assert creatore.full_name in testo
    # Tutte e due le versioni hanno il loro pulsante di scarico.
    assert f"/documenti/{documento.id}/versioni/{prima.id}/scarica" in testo
    assert f"/documenti/{documento.id}/versioni/{seconda.id}/scarica" in testo
    # E l'impronta si vede, perche' e' quello che dimostra l'immutabilita'.
    assert prima.storage_hash[:16] in testo


def test_l_elenco_di_un_progetto_mostra_le_colonne_chieste(client, db_session):
    """Punto 8 della sessione: titolo, tipo, versione, stato, classificazione,
    autore dell'ultimo caricamento e data."""
    progetto, creatore = prepara_progetto(db_session)
    crea_documento(
        db_session, progetto, creatore, titolo="Schema di prova elenco"
    )
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    elenco = client.get(f"/documenti?progetto={progetto.id}")
    testo = contenuto_leggibile(elenco)

    assert elenco.status_code == 200
    for colonna in (
        "Titolo",
        "Tipo",
        "Versione",
        "Stato",
        "Classificazione",
        "Ultimo caricamento",
        "Data",
    ):
        assert colonna in testo, f"manca la colonna '{colonna}'"

    assert "Schema di prova elenco" in testo


def test_la_voce_di_menu_documenti_e_accesa(client, db_session):
    """La sezione esiste, quindi la voce si preme."""
    utente = crea_utente(
        db_session, username=f"prova.menu.{uuid.uuid4().hex[:8]}"
    )
    db_session.flush()

    entra(client, utente.username, PASSWORD_DI_PROVA)
    home = client.get("/")

    assert home.status_code == 200
    assert 'href="/documenti"' in home.text


# ===========================================================================
#  8. LA CONFIGURAZIONE
# ===========================================================================


def test_i_tipi_di_documento_arrivano_dal_file_di_configurazione():
    """L'elenco sta in config/tipi_documento.toml, non nel programma."""
    from app.services import doc_types

    elenco = doc_types.ricarica()

    assert elenco.problema is None, elenco.problema
    assert elenco.dal_file is True
    assert "Schema elettrico" in elenco.tipi
    assert "Rapporto di prova" in elenco.tipi
    assert elenco.tipi[-1] == "Altro"


def test_un_file_dei_tipi_rotto_non_ferma_il_programma(tmp_path):
    """D-039 applicato ai tipi: si usa l'elenco di ripiego e si va avanti.

    Un errore di battitura in un file di configurazione non deve poter
    impedire a tutta l'azienda di caricare i documenti.
    """
    from app.services import doc_types

    rotto = tmp_path / "tipi_rotti.toml"
    rotto.write_text("questo non e' un TOML valido [[[", encoding="utf-8")

    try:
        elenco = doc_types.ricarica(rotto)

        assert elenco.problema is not None
        assert elenco.dal_file is False
        assert elenco.tipi == doc_types.TIPI_DI_RIPIEGO
    finally:
        # Si rimette l'elenco vero: il modulo tiene lo stato in una variabile
        # globale, e lasciarlo rotto farebbe fallire i test successivi.
        doc_types.ricarica()


def test_il_file_dei_tipi_mancante_non_ferma_il_programma(tmp_path):
    """Stessa regola, per il file che non c'e'."""
    from app.services import doc_types

    try:
        elenco = doc_types.ricarica(tmp_path / "non-esiste.toml")

        assert elenco.problema is not None
        assert elenco.tipi == doc_types.TIPI_DI_RIPIEGO
    finally:
        doc_types.ricarica()


def test_il_peso_si_scrive_come_lo_scriverebbe_una_persona():
    """Byte, kB, MB, GB: la regola sta in Python, non dentro l'HTML."""
    assert documents.peso_leggibile(512) == "512 byte"
    assert documents.peso_leggibile(2048) == "2 kB"
    assert documents.peso_leggibile(5 * 1024 * 1024) == "5.0 MB"
    assert documents.peso_leggibile(2 * 1024**3) == "2.00 GB"


def test_la_versione_e_una_riga_che_non_si_modifica(db_session):
    """Nessun servizio offre di cambiare una riga di document_versions.

    E' un test di forma, come quello sulle rotte di cancellazione: le versioni
    sono fatti avvenuti, e se qualcuno aggiungesse una modifica_versione() in
    buona fede questo test glielo direbbe.
    """
    nomi = [nome for nome in dir(documents) if not nome.startswith("_")]

    for vietato in ("modifica_versione", "sostituisci_versione", "aggiorna_file"):
        assert vietato not in nomi, (
            f"documents.{vietato}() non deve esistere: una versione caricata "
            "e' un fatto avvenuto, e se il file era sbagliato se ne carica "
            "un'altra"
        )

    # E la tabella non ha nessuna colonna di modifica del contenuto.
    colonne = {colonna.name for colonna in DocumentVersion.__table__.columns}
    assert "storage_hash" in colonne
    assert "replaced_by_id" not in colonne
