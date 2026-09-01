"""Il giro intero, dall'inizio alla fine, come lo farebbe una persona.

Gli altri file di test provano un pezzo per volta: l'accesso, i permessi, il
ciclo di vita, l'archiviazione della posta. Questo prova **la strada che li
attraversa tutti**, dal cliente che non c'era fino alla versione 2 rilasciata
con la 1 superata, passando dai documenti, dalle fasi e dalla posta.

PERCHE' SERVE UN TEST COSI', SE CI SONO GIA' GLI ALTRI
------------------------------------------------------

Perche' i difetti che restano dopo dodici sessioni non stanno dentro una
funzione: stanno **fra** due funzioni che, prese una per volta, fanno
esattamente quello che devono. Un documento che si carica benissimo su un
progetto e non si vede piu' quando il progetto cambia fase; una versione che
si rilascia e non supera la precedente perche' la precedente era stata portata
in uno stato da cui il grafo non ammette il passaggio; un messaggio che si
attribuisce alla versione giusta ma finisce in un progetto che nel frattempo
si e' chiuso.

Nessuno di quei casi si vede provando un servizio per volta, e tutti si
vedono percorrendo la strada intera.

COME SONO SCRITTI
-----------------

**Tutto passa dal finto browser**, non dai servizi: si aprono le pagine, si
inviano i moduli, si seguono i rimandi. E' l'unico modo per provare anche
quello che sta fra la rotta e il servizio - i permessi dichiarati sulla rotta,
il gettone dei moduli, i messaggi mostrati - che chiamando i servizi
direttamente non si esercita.

**Il finto browser non esegue JavaScript**, quindi ogni passo che riesce qui
e' anche la prova che quel passo funziona senza (D-036).

**I dati se li sceglie il test**, dentro lo spazio di nomi che il programma
vero non raggiunge: nomi utente con due punti, codici prodotto con il modello
casuale, contenuti di file irripetibili. Le ragioni sono scritte in
tests/conftest.py e sono costate quarantasei test rossi nella sessione 5.
"""

import io
import uuid

from sqlalchemy import select

from app.models import (
    AuditLog,
    Document,
    DocumentState,
    EmailAssignmentState,
    GlobalRole,
    LifecycleState,
    Project,
)
from app.services import emails, mail_source, phases, products
from tests.conftest import (
    PASSWORD_DI_PROVA,
    classificazione_di_prova,
    codice_irripetibile,
    contenuto_irripetibile,
    contenuto_leggibile,
    crea_utente,
    entra,
    gettone_csrf,
    sigla_irripetibile,
)


# ---------------------------------------------------------------------------
#  Attrezzi del giro
# ---------------------------------------------------------------------------


def _apri_la_sessione(client, db_session, suffisso: str):
    """Crea un creatore e lo fa entrare. Restituisce lui e il suo nome utente.

    Il nome utente porta un pezzo casuale perche' questi test creano davvero
    l'utente sul database di sviluppo, dentro la transazione annullata: due
    test dello stesso file che scegliessero lo stesso nome si romperebbero a
    vicenda il giorno in cui qualcuno li fa girare in parallelo.
    """
    nome = f"prova.giro.{suffisso}.{uuid.uuid4().hex[:8]}"
    creatore = crea_utente(db_session, username=nome, ruolo=GlobalRole.CREATORE)
    db_session.flush()
    risposta = entra(client, nome, PASSWORD_DI_PROVA)
    assert risposta.status_code == 303, "l'accesso doveva riuscire"
    return creatore, nome


def _invia(client, percorso: str, dati: dict, pagina_col_modulo: str):
    """Invia un modulo prendendo il gettone dalla pagina che lo contiene.

    Il gettone si legge dalla pagina invece di inventarlo: cosi' il test
    verifica anche che il template il campo nascosto ce l'abbia davvero, ed e'
    il modo in cui un modulo dimenticato si scopre subito (D-028).
    """
    dati = dict(dati)
    dati["csrf"] = gettone_csrf(client, pagina_col_modulo)
    return client.post(percorso, data=dati, follow_redirects=True)


def _id_dall_indirizzo(risposta, prefisso: str) -> uuid.UUID:
    """L'identificativo dell'oggetto appena creato, letto dall'indirizzo finale.

    Dopo la creazione Aurora rimanda alla scheda dell'oggetto: l'indirizzo di
    arrivo e' /prodotti/<uuid>, /progetti/<uuid> e cosi' via. Leggerlo di li'
    e' quello che farebbe una persona, e verifica per giunta che il rimando
    porti dove deve.
    """
    percorso = str(risposta.url.path)
    assert percorso.startswith(prefisso), (
        f"dopo la creazione ci si aspettava di arrivare su {prefisso}<id>, "
        f"si e' arrivati su {percorso}"
    )
    return uuid.UUID(percorso[len(prefisso) :].split("/")[0])


# ---------------------------------------------------------------------------
#  1. Il giro intero
# ---------------------------------------------------------------------------


def test_dal_cliente_nuovo_alla_v2_rilasciata_con_la_v1_superata(
    client, db_session
):
    """Il percorso completo chiesto dalla sessione 13, dal browser.

    Sono nove passi, e ciascuno e' quello che una persona farebbe davvero:

      1. si crea il cliente;
      2. si crea il prodotto, che nasce con la sua versione 1;
      3. si apre il progetto sulla V1, con la squadra;
      4. si carica un documento;
      5. lo si porta fino a «rilasciato»;
      6. si fa avanzare il progetto di una fase;
      7. si rilascia la V1;
      8. si deriva la V2 e la si rilascia: **la V1 passa da sola a superato**;
      9. si controlla che di tutto questo sia rimasta traccia nel registro.
    """
    creatore, _nome = _apri_la_sessione(client, db_session, "intero")
    classificazione_di_prova(db_session)

    # --- 1. Il cliente -----------------------------------------------------
    sigla = sigla_irripetibile()
    risposta = _invia(
        client,
        "/clienti/nuovo",
        {
            "nome": "Ferrovie di Prova",
            "codice": sigla,
            "note": "Cliente creato dal test del percorso completo.",
        },
        "/clienti/nuovo",
    )
    assert risposta.status_code == 200
    cliente_id = _id_dall_indirizzo(risposta, "/clienti/")

    # --- 2. Il prodotto, che nasce con la V1 -------------------------------
    codice = codice_irripetibile()
    risposta = _invia(
        client,
        "/prodotti/nuovo",
        {
            "codice": codice,
            "cliente": str(cliente_id),
            "descrizione": "Convertitore di prova.",
        },
        "/prodotti/nuovo",
    )
    assert risposta.status_code == 200
    prodotto_id = _id_dall_indirizzo(risposta, "/prodotti/")

    versioni = products.versioni_di(db_session, prodotto_id)
    assert len(versioni) == 1, "un prodotto nasce con la sua versione 1 (D-040)"
    prima = versioni[0]
    assert prima.lifecycle_state is LifecycleState.IN_SVILUPPO

    # Il codice si e' scomposto: e' quello che rende ricercabili gli elementi.
    prodotto = products.trova_prodotto(db_session, prodotto_id)
    assert prodotto.code_parts.get("potenza") == "1100"
    assert prodotto.code_parts.get("tensione_uscita") == "110"

    # --- 3. Il progetto sulla V1, con la squadra ---------------------------
    ingegnere = crea_utente(
        db_session, username=f"prova.giro.ing.{uuid.uuid4().hex[:8]}"
    )
    db_session.flush()

    modelli = phases.modelli_di_fasi(db_session)
    assert modelli, "serve un modello di fasi proponibile: esegui scripts/seed.py"
    modello = modelli[0]

    risposta = _invia(
        client,
        "/progetti/nuovo",
        {
            "versione": str(prima.id),
            "project_manager": str(creatore.id),
            "modello": str(modello.id),
            "norme": "EN 50155",
            "ingegneri": str(ingegnere.id),
        },
        f"/progetti/nuovo?versione={prima.id}",
    )
    assert risposta.status_code == 200
    progetto_id = _id_dall_indirizzo(risposta, "/progetti/")

    progetto = db_session.get(Project, progetto_id)
    assert progetto.current_phase_id is not None, (
        "aprendo il progetto si entra subito nella prima fase del modello"
    )
    fase_di_partenza = progetto.current_phase_id

    # --- 4. Il documento ----------------------------------------------------
    contenuto = contenuto_irripetibile(b"schema del percorso completo")
    risposta = client.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto_id),
            "titolo": "Schema elettrico del percorso completo",
            "tipo": "Schema elettrico",
            "classificazione": str(
                classificazione_di_prova(db_session).id
            ),
            "csrf": gettone_csrf(client, f"/documenti/nuovo?progetto={progetto_id}"),
        },
        files={"file": ("schema.pdf", io.BytesIO(contenuto), "application/pdf")},
        follow_redirects=True,
    )
    assert risposta.status_code == 200

    documento = db_session.scalars(
        select(Document).where(Document.project_id == progetto_id)
    ).first()
    assert documento is not None, "il documento doveva essere creato"
    assert documento.state is DocumentState.BOZZA

    # --- 5. Il documento arriva a «rilasciato» -----------------------------
    for passo in (DocumentState.IN_VERIFICA, DocumentState.RILASCIATO):
        _invia(
            client,
            f"/documenti/{documento.id}/stato",
            {"nuovo": passo.value},
            f"/documenti/{documento.id}/stato?nuovo={passo.value}",
        )
        db_session.refresh(documento)
        assert documento.state is passo

    # La scheda dice chi lo ha rilasciato e quando, letto dal registro.
    scheda = client.get(f"/documenti/{documento.id}")
    assert "Rilasciato da" in contenuto_leggibile(scheda)

    # --- 6. Il progetto avanza di una fase ---------------------------------
    risposta = _invia(
        client,
        f"/progetti/{progetto_id}/fase/avanza",
        {"motivazione": "Riesame concluso, si prosegue."},
        f"/progetti/{progetto_id}/fase",
    )
    assert risposta.status_code == 200

    db_session.refresh(progetto)
    assert progetto.current_phase_id != fase_di_partenza, (
        "il progetto doveva essere passato alla fase successiva"
    )

    # --- 7. La V1 va in campo ----------------------------------------------
    _invia(
        client,
        f"/versioni/{prima.id}/stato",
        {"nuovo": LifecycleState.RILASCIATO.value},
        f"/versioni/{prima.id}",
    )
    db_session.refresh(prima)
    assert prima.lifecycle_state is LifecycleState.RILASCIATO

    # --- 8. La V2, e il superamento automatico -----------------------------
    risposta = _invia(
        client,
        f"/versioni/{prima.id}/deriva",
        {
            "origine": str(prima.id),
            "motivazione": "Il cliente ha chiesto un connettore diverso.",
        },
        f"/versioni/{prima.id}/deriva",
    )
    assert risposta.status_code == 200

    versioni = products.versioni_di(db_session, prodotto_id)
    assert len(versioni) == 2
    seconda = versioni[1]
    assert seconda.derived_from_id == prima.id
    assert seconda.lifecycle_state is LifecycleState.IN_SVILUPPO

    # La conferma dice, **prima** di procedere, che cosa succedera' alla V1.
    conferma = client.get(f"/versioni/{seconda.id}/stato?nuovo=rilasciato")
    testo = contenuto_leggibile(conferma)
    assert "versione 1" in testo.lower()
    assert "superato" in testo

    _invia(
        client,
        f"/versioni/{seconda.id}/stato",
        {"nuovo": LifecycleState.RILASCIATO.value},
        f"/versioni/{seconda.id}",
    )

    db_session.refresh(prima)
    db_session.refresh(seconda)
    assert seconda.lifecycle_state is LifecycleState.RILASCIATO
    assert prima.lifecycle_state is LifecycleState.SUPERATO, (
        "rilasciando la V2, la V1 doveva passare da sola a «superato» (D-042)"
    )

    # --- 9. Di tutto questo e' rimasta traccia ------------------------------
    azioni = set(
        db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.entity_id.in_(
                    [cliente_id, prodotto_id, progetto_id, documento.id,
                     prima.id, seconda.id]
                )
            )
        ).all()
    )
    attese = {
        "customer.created",
        "product.created",
        "product_version.created",
        "project.created",
        "document.created",
        "document.state_changed",
        "project.phase_entered",
        "product_version.state_changed",
    }
    assert attese <= azioni, (
        "il registro non ha tenuto traccia di tutto il giro; mancano: "
        f"{sorted(attese - azioni)}"
    )

    # Il superamento risulta come **azione di sistema**: chi ha premuto il
    # pulsante ha rilasciato la V2, non ha superato la V1 (D-042).
    #
    # L'azione ha un nome suo, "product_version.superseded", diverso da quello
    # del cambio di stato chiesto da una persona: sono due fatti diversi e nel
    # registro si devono distinguere senza dover guardare chi li ha fatti.
    superamento = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_id == prima.id,
            AuditLog.action == "product_version.superseded",
        )
        .order_by(AuditLog.seq.desc())
    ).first()
    assert superamento is not None
    assert superamento.new_value["lifecycle_state"] == LifecycleState.SUPERATO.value
    assert superamento.user_id is None, (
        "il superamento automatico e' un'azione di sistema, non di chi ha "
        "premuto il pulsante"
    )


# ---------------------------------------------------------------------------
#  2. Il giro visto da chi non e' il creatore
# ---------------------------------------------------------------------------


def test_l_ingegnere_percorre_la_sua_meta_del_giro(client, db_session, secondo_browser):
    """Chi e' assegnato vede il progetto, carica, e non puo' amministrare.

    E' il giro dall'altro lato del muro dei permessi: le stesse pagine, con la
    persona che in azienda le usa davvero. Serve a verificare che il percorso
    completo non funzioni **solo** per il creatore, che di permessi non ne ha
    nessuno da rispettare.
    """
    creatore, _ = _apri_la_sessione(client, db_session, "duelati")
    classe = classificazione_di_prova(db_session)

    nome_ingegnere = f"prova.giro.ing2.{uuid.uuid4().hex[:8]}"
    ingegnere = crea_utente(db_session, username=nome_ingegnere)
    db_session.flush()

    # Il creatore prepara prodotto e progetto.
    sigla = sigla_irripetibile()
    risposta = _invia(
        client,
        "/clienti/nuovo",
        {"nome": "Cliente due lati", "codice": sigla, "note": ""},
        "/clienti/nuovo",
    )
    cliente_id = _id_dall_indirizzo(risposta, "/clienti/")

    risposta = _invia(
        client,
        "/prodotti/nuovo",
        {
            "codice": codice_irripetibile(),
            "cliente": str(cliente_id),
            "descrizione": "",
        },
        "/prodotti/nuovo",
    )
    prodotto_id = _id_dall_indirizzo(risposta, "/prodotti/")
    prima = products.versioni_di(db_session, prodotto_id)[0]

    modello = phases.modelli_di_fasi(db_session)[0]
    risposta = _invia(
        client,
        "/progetti/nuovo",
        {
            "versione": str(prima.id),
            "project_manager": str(creatore.id),
            "modello": str(modello.id),
            "norme": "EN 50155",
            "ingegneri": str(ingegnere.id),
        },
        f"/progetti/nuovo?versione={prima.id}",
    )
    progetto_id = _id_dall_indirizzo(risposta, "/progetti/")

    # Adesso entra l'ingegnere, con il suo browser.
    entra(secondo_browser, nome_ingegnere, PASSWORD_DI_PROVA)

    # Vede il progetto nel cruscotto.
    cruscotto = secondo_browser.get("/")
    assert str(progetto_id) in cruscotto.text, (
        "chi e' assegnato deve vedere il progetto nel proprio cruscotto"
    )

    # Carica un documento, perche' la matrice glielo consente.
    contenuto = contenuto_irripetibile(b"documento dell ingegnere")
    caricamento = secondo_browser.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto_id),
            "titolo": "Calcolo termico",
            "tipo": "Specifica",
            "classificazione": str(classe.id),
            "csrf": gettone_csrf(
                secondo_browser, f"/documenti/nuovo?progetto={progetto_id}"
            ),
        },
        files={"file": ("calcolo.txt", io.BytesIO(contenuto), "text/plain")},
        follow_redirects=True,
    )
    assert caricamento.status_code == 200

    # Puo' **chiedere** il passaggio di fase, non farlo (D-056).
    pagina_fase = secondo_browser.get(f"/progetti/{progetto_id}/fase")
    testo = contenuto_leggibile(pagina_fase)
    assert "Chiedi" in testo or "richiesta" in testo.lower()

    avanzamento = secondo_browser.post(
        f"/progetti/{progetto_id}/fase/avanza",
        data={
            "motivazione": "Provo ad avanzare senza esserne il responsabile.",
            "csrf": gettone_csrf(secondo_browser, f"/progetti/{progetto_id}/fase"),
        },
        follow_redirects=False,
    )
    assert avanzamento.status_code == 403, (
        "chi non governa il progetto non lo fa avanzare: chiede (D-056)"
    )

    # E le sezioni riservate restano chiuse, anche scrivendone l'indirizzo.
    for riservata in ("/utenti", "/permessi", "/fasi", "/registro", "/diagnostica"):
        risposta = secondo_browser.get(riservata)
        assert risposta.status_code == 403, (
            f"{riservata} doveva essere riservata al creatore"
        )


# ---------------------------------------------------------------------------
#  3. La posta entra nel giro
# ---------------------------------------------------------------------------


def test_un_messaggio_arriva_e_si_attacca_alla_versione_del_giro(
    client, db_session, tmp_path
):
    """Dalla creazione del prodotto al messaggio archiviato sulla sua versione.

    E' il pezzo di percorso che unisce la sessione 5 e la sessione 10: un
    messaggio con il codice prodotto nell'oggetto deve finire sulla versione
    giusta di un prodotto **appena creato**, senza che nessuno lo assegni a
    mano.
    """
    creatore, _ = _apri_la_sessione(client, db_session, "posta")

    sigla = sigla_irripetibile()
    risposta = _invia(
        client,
        "/clienti/nuovo",
        {"nome": "Cliente della posta", "codice": sigla, "note": ""},
        "/clienti/nuovo",
    )
    cliente_id = _id_dall_indirizzo(risposta, "/clienti/")

    codice = codice_irripetibile()
    risposta = _invia(
        client,
        "/prodotti/nuovo",
        {"codice": codice, "cliente": str(cliente_id), "descrizione": ""},
        "/prodotti/nuovo",
    )
    prodotto_id = _id_dall_indirizzo(risposta, "/prodotti/")
    prima = products.versioni_di(db_session, prodotto_id)[0]

    # Un messaggio con il codice nell'oggetto, scritto in una cartella tutta
    # sua: la fonte locale si puo' puntare dove si vuole, ed e' per questo che
    # il motore si collauda senza toccare la casella aziendale (D-076).
    cartella = tmp_path / "posta"
    cartella.mkdir()
    identificativo = f"<giro-{uuid.uuid4().hex}@prova.aurora.local>"
    (cartella / "messaggio.eml").write_bytes(
        (
            f"Message-ID: {identificativo}\r\n"
            "From: cliente@esempio.local\r\n"
            "To: ufficio.tecnico@esempio.local\r\n"
            f"Subject: [{codice}][V1][SPECS] Richiesta di chiarimento\r\n"
            "Date: Mon, 1 Sep 2025 09:00:00 +0000\r\n"
            "\r\n"
            "Buongiorno, avremmo un dubbio sullo schema di potenza.\r\n"
        ).encode("utf-8")
    )

    fonte = mail_source.FonteLocale(cartella)
    fonte.prepara()
    riepilogo = emails.acquisisci(db_session, fonte, autore=creatore)

    assert riepilogo.letti == 1
    assert riepilogo.archiviati == 1, (
        "il messaggio nomina il prodotto e la versione: doveva essere "
        f"attribuito. Errori: {riepilogo.messaggi_di_errore()}"
    )

    # Nel database l'identificativo sta **senza** parentesi angolari: quelle
    # appartengono all'intestazione, non all'identificativo
    # (email_parsing.normalizza_identificativo).
    messaggio = emails.trova_per_identificativo(
        db_session, identificativo.strip("<>")
    )
    assert messaggio is not None
    assert messaggio.product_version_id == prima.id
    assert messaggio.assignment_state is EmailAssignmentState.AUTOMATICA

    # E si vede dalla pagina, con il permesso che decide come per un documento.
    scheda = client.get(f"/posta/{messaggio.id}")
    assert scheda.status_code == 200
    assert "chiarimento" in contenuto_leggibile(scheda).lower()


# ---------------------------------------------------------------------------
#  4. Il giro finisce dove deve: il progetto si chiude
# ---------------------------------------------------------------------------


def test_il_progetto_arriva_in_fondo_e_diventa_di_sola_lettura(
    client, db_session, secondo_browser
):
    """Percorrendo tutte le fasi il progetto si chiude, e smette di cambiare.

    La chiusura non e' un'operazione a parte: e' la conseguenza di essere
    entrati nell'ultima casella del percorso (D-058). Da quel momento nessuno
    ci carica piu' niente - **tranne il creatore**, che e' anche l'unico che
    lo possa riaprire riportandolo a una fase precedente.

    Il caricamento rifiutato lo prova quindi l'ingegnere e non il creatore: la
    prima stesura di questo test lo provava con il creatore, riceveva un 303 e
    sembrava un difetto. Non lo era, ed e' la ragione per cui questa riga sta
    scritta qui.
    """
    creatore, _ = _apri_la_sessione(client, db_session, "chiusura")
    classe = classificazione_di_prova(db_session)

    nome_ingegnere = f"prova.giro.chiuso.{uuid.uuid4().hex[:8]}"
    ingegnere = crea_utente(db_session, username=nome_ingegnere)
    db_session.flush()

    sigla = sigla_irripetibile()
    risposta = _invia(
        client,
        "/clienti/nuovo",
        {"nome": "Cliente della chiusura", "codice": sigla, "note": ""},
        "/clienti/nuovo",
    )
    cliente_id = _id_dall_indirizzo(risposta, "/clienti/")

    risposta = _invia(
        client,
        "/prodotti/nuovo",
        {
            "codice": codice_irripetibile(),
            "cliente": str(cliente_id),
            "descrizione": "",
        },
        "/prodotti/nuovo",
    )
    prodotto_id = _id_dall_indirizzo(risposta, "/prodotti/")
    prima = products.versioni_di(db_session, prodotto_id)[0]

    modello = phases.modelli_di_fasi(db_session)[0]
    risposta = _invia(
        client,
        "/progetti/nuovo",
        {
            "versione": str(prima.id),
            "project_manager": str(creatore.id),
            "modello": str(modello.id),
            "norme": "",
            "ingegneri": str(ingegnere.id),
        },
        f"/progetti/nuovo?versione={prima.id}",
    )
    progetto_id = _id_dall_indirizzo(risposta, "/progetti/")
    progetto = db_session.get(Project, progetto_id)

    # Si avanza finche' c'e' dove andare. Il numero di fasi lo decide il
    # modello: non si scrive qui, altrimenti questo test si romperebbe il
    # giorno in cui qualcuno cambia il percorso - e le fasi sono dati (D-055).
    quante = len(phases.fasi_del_progetto(db_session, progetto))
    for _ in range(quante):
        if phases.fase_successiva(db_session, progetto) is None:
            break
        _invia(
            client,
            f"/progetti/{progetto_id}/fase/avanza",
            {"motivazione": "Avanti."},
            f"/progetti/{progetto_id}/fase",
        )
        db_session.refresh(progetto)

    assert progetto.closed_at is not None, (
        "arrivando nell'ultima fase il progetto doveva chiudersi (D-058)"
    )

    # Da qui in avanti l'ingegnere non ci carica piu' niente.
    entra(secondo_browser, nome_ingegnere, PASSWORD_DI_PROVA)

    contenuto = contenuto_irripetibile(b"documento su progetto chiuso")
    caricamento = secondo_browser.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto_id),
            "titolo": "Tardivo",
            "tipo": "Altro",
            "classificazione": str(classe.id),
            "csrf": gettone_csrf(secondo_browser, "/documenti"),
        },
        files={"file": ("tardivo.txt", io.BytesIO(contenuto), "text/plain")},
        follow_redirects=False,
        headers={"accept": "text/html"},
    )
    assert caricamento.status_code == 403
    assert "chiuso" in contenuto_leggibile(caricamento).lower(), (
        "il rifiuto deve dire che il progetto e' chiuso, non che manca un "
        "permesso: e' vero per tutti allo stesso modo (D-058)"
    )

    # La scheda pero' si apre: un progetto chiuso e' un archivio, e un
    # archivio si consulta.
    scheda = secondo_browser.get(f"/progetti/{progetto_id}")
    assert scheda.status_code == 200

    # Il creatore invece continua a poter tutto, ed e' l'unico che possa
    # riaprire il progetto riportandolo indietro (D-058).
    caricamento_del_creatore = client.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto_id),
            "titolo": "Aggiunta tardiva del creatore",
            "tipo": "Altro",
            "classificazione": str(classe.id),
            "csrf": gettone_csrf(client, "/documenti"),
        },
        files={
            "file": (
                "creatore.txt",
                io.BytesIO(contenuto_irripetibile(b"aggiunta del creatore")),
                "text/plain",
            )
        },
        follow_redirects=False,
    )
    assert caricamento_del_creatore.status_code == 303


# ---------------------------------------------------------------------------
#  5. Quello che il giro non deve poter fare
# ---------------------------------------------------------------------------


def test_la_versione_rilasciata_di_un_documento_non_si_sostituisce(
    client, db_session
):
    """Caricare su un rilasciato crea la versione successiva, non la sostituisce.

    E' D-045 percorso dal browser: la versione rilasciata resta in tabella con
    la sua impronta, il documento torna in bozza e dovra' rifare il giro della
    verifica.
    """
    creatore, _ = _apri_la_sessione(client, db_session, "immutabile")
    classe = classificazione_di_prova(db_session)

    sigla = sigla_irripetibile()
    risposta = _invia(
        client,
        "/clienti/nuovo",
        {"nome": "Cliente immutabile", "codice": sigla, "note": ""},
        "/clienti/nuovo",
    )
    cliente_id = _id_dall_indirizzo(risposta, "/clienti/")

    risposta = _invia(
        client,
        "/prodotti/nuovo",
        {
            "codice": codice_irripetibile(),
            "cliente": str(cliente_id),
            "descrizione": "",
        },
        "/prodotti/nuovo",
    )
    prodotto_id = _id_dall_indirizzo(risposta, "/prodotti/")
    prima = products.versioni_di(db_session, prodotto_id)[0]

    modello = phases.modelli_di_fasi(db_session)[0]
    risposta = _invia(
        client,
        "/progetti/nuovo",
        {
            "versione": str(prima.id),
            "project_manager": str(creatore.id),
            "modello": str(modello.id),
            "norme": "",
        },
        f"/progetti/nuovo?versione={prima.id}",
    )
    progetto_id = _id_dall_indirizzo(risposta, "/progetti/")

    contenuto_uno = contenuto_irripetibile(b"prima stesura")
    client.post(
        "/documenti/nuovo",
        data={
            "progetto": str(progetto_id),
            "titolo": "Documento immutabile",
            "tipo": "Altro",
            "classificazione": str(classe.id),
            "csrf": gettone_csrf(client, f"/documenti/nuovo?progetto={progetto_id}"),
        },
        files={"file": ("uno.txt", io.BytesIO(contenuto_uno), "text/plain")},
        follow_redirects=True,
    )
    documento = db_session.scalars(
        select(Document).where(Document.project_id == progetto_id)
    ).first()

    for passo in (DocumentState.IN_VERIFICA, DocumentState.RILASCIATO):
        _invia(
            client,
            f"/documenti/{documento.id}/stato",
            {"nuovo": passo.value},
            f"/documenti/{documento.id}/stato?nuovo={passo.value}",
        )
    db_session.refresh(documento)
    assert documento.state is DocumentState.RILASCIATO

    impronta_di_prima = documento.versions[0].storage_hash

    contenuto_due = contenuto_irripetibile(b"seconda stesura")
    client.post(
        f"/documenti/{documento.id}/versione",
        data={
            "nota": "Corrette le quote dopo il riesame.",
            "csrf": gettone_csrf(client, f"/documenti/{documento.id}/versione"),
        },
        files={"file": ("due.txt", io.BytesIO(contenuto_due), "text/plain")},
        follow_redirects=True,
    )

    db_session.refresh(documento)
    assert len(documento.versions) == 2, "doveva nascere una versione nuova"
    assert documento.state is DocumentState.BOZZA, (
        "una versione nuova non e' verificata da nessuno: il documento torna "
        "in bozza e rifa' il giro (D-045)"
    )

    prima_versione = next(
        v for v in documento.versions if v.version_number == 1
    )
    assert prima_versione.storage_hash == impronta_di_prima, (
        "la versione rilasciata non si tocca: stessa impronta, stesso file"
    )
