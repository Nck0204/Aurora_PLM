"""Il registro delle operazioni: completezza, non modificabilita', catena, pagine.

I test di questo file rispondono alle quattro domande che si fa chi deve
difendere Aurora davanti a una verifica aziendale.

  1. **Tutto quello che succede lascia traccia?** La prima meta' del file
     esegue un'operazione di ciascun tipo previsto dalla sessione 9 e va a
     cercarla nel registro. Non controlla che la riga esista e basta:
     controlla che dica chi, che cosa, quando, su quale oggetto, da dove, e
     con quali valori prima e dopo.

  2. **Si puo' correggere?** No, e non per gentilezza del programma: l'utente
     con cui Aurora si collega al database non ha il permesso di modificare
     quella tabella. C'e' un test che prova a farlo davvero.

  3. **E se qualcuno la corregge dal database?** Si vede. C'e' un test che
     scrive una voce con l'impronta sbagliata e verifica che
     registro.verifica_catena() la segnali.

  4. **Si riesce a consultarlo?** La seconda meta' del file prova la pagina
     /registro con i suoi filtri, l'esportazione in CSV e le schede "Storico"
     dei cinque tipi di oggetto.
"""

import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.models import AuditLog, DocumentState, GlobalRole, LifecycleState, ProjectRole
from app.services import audit, configuration, customers, documents, lifecycle
from app.services import permissions, phases, products, projects, registro, users
from tests.conftest import (
    PASSWORD_DI_PROVA,
    codice_irripetibile,
    contenuto_irripetibile,
    crea_cliente,
    crea_documento,
    crea_modello_di_fasi,
    crea_prodotto,
    crea_progetto,
    crea_utente,
    entra,
    sigla_irripetibile,
)

RADICE = pathlib.Path(__file__).resolve().parent.parent


# ===========================================================================
#  Aiuti
# ===========================================================================


def voci_di(db: Session, azione: str, entity_id: uuid.UUID | None = None):
    """Le voci del registro per un'azione, dalla piu' recente.

    Si filtra sempre anche per oggetto quando si puo': il database di sviluppo
    contiene le operazioni vere delle sessioni precedenti, e un test che
    cercasse "l'ultima riga con azione document.created" troverebbe quella di
    qualcun altro. E' la stessa precauzione dei codici irripetibili di
    conftest.py, applicata al registro.
    """
    condizioni = [AuditLog.action == azione]
    if entity_id is not None:
        condizioni.append(AuditLog.entity_id == entity_id)

    return list(
        db.scalars(
            select(AuditLog).where(*condizioni).order_by(AuditLog.seq.desc())
        ).all()
    )


def unica_voce(
    db: Session, azione: str, entity_id: uuid.UUID | None = None
) -> AuditLog:
    """La voce piu' recente per quell'azione su quell'oggetto.

    Fallisce con un messaggio leggibile se non c'e': "l'operazione X non e'
    stata registrata" dice quello che serve sapere, mentre un IndexError no.
    """
    trovate = voci_di(db, azione, entity_id)
    assert trovate, (
        f"l'operazione '{azione}' non ha lasciato nessuna riga nel registro"
        + (f" per l'oggetto {entity_id}" if entity_id else "")
    )
    return trovate[0]


def creatore_di_prova(db: Session, prefisso: str = "prova.audit"):
    """Un creatore con un nome utente che nel database non puo' gia' esserci."""
    return crea_utente(
        db,
        username=f"{prefisso}.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )


def ultimo_numero(db: Session) -> int:
    """Il numero di sequenza dell'ultima voce scritta."""
    return int(db.scalar(select(func.max(AuditLog.seq))) or 0)


def inserisci_voce_grezza(
    db: Session,
    *,
    seq: int,
    previous_hash: str,
    entry_hash: str,
    description: str = "Voce scritta a mano da un test",
) -> None:
    """Scrive una riga in audit_logs **senza passare da audit.record()**.

    E' il modo in cui un test simula chi manomette il database: si scrive
    direttamente con SQL, scegliendo le impronte. Il programma non puo' fare
    niente del genere - audit.record() calcola le impronte e non le prende da
    fuori - ma chi ha in mano psql si'.

    L'INSERT e' l'unica cosa che l'utente applicativo puo' ancora fare su
    questa tabella, ed e' quello che rende possibile questo test senza
    permessi speciali: per manomettere davvero servirebbe un UPDATE, che
    invece fallisce (vedi il test piu' sotto).
    """
    db.execute(
        text(
            """
            INSERT INTO audit_logs
                (id, occurred_at, action, entity_type, seq, description,
                 previous_hash, entry_hash)
            VALUES
                (:id, now(), 'user.login', 'users', :seq, :description,
                 :previous_hash, :entry_hash)
            """
        ),
        {
            "id": uuid.uuid4(),
            "seq": seq,
            "description": description,
            "previous_hash": previous_hash,
            "entry_hash": entry_hash,
        },
    )


# ===========================================================================
#  1. IL CATALOGO: quali operazioni Aurora dice di registrare
# ===========================================================================


def sorgenti_python() -> list[pathlib.Path]:
    """Tutti i .py del programma."""
    return [
        percorso
        for percorso in (RADICE / "app").rglob("*.py")
        if "__pycache__" not in percorso.parts
    ]


def test_ogni_azione_del_programma_e_nel_catalogo():
    """Nessuna costante ACTION_* senza la sua riga in audit.CATALOGO.

    E' un test che legge i sorgenti, come quelli dei permessi e delle fasi. Il
    catalogo e' la risposta scritta alla domanda "quali operazioni lasciano
    traccia?": serve al menu dei filtri della pagina /registro e alla frase
    italiana di ogni voce. Un'azione fuori dal catalogo verrebbe registrata lo
    stesso - una voce approssimata e' meglio di un'operazione non registrata -
    ma non comparirebbe fra i tipi di azione, e chi cerca non la troverebbe.
    """
    dichiarazione = re.compile(r'^ACTION_[A-Z_]+ = "([a-z_]+\.[a-z_]+)"', re.MULTILINE)

    mancanti = []
    for percorso in sorgenti_python():
        testo = percorso.read_text(encoding="utf-8")
        for azione in dichiarazione.findall(testo):
            if azione not in audit.CATALOGO:
                mancanti.append((percorso.relative_to(RADICE), azione))

    assert mancanti == [], (
        f"queste azioni non sono in audit.CATALOGO: {mancanti}. Ogni azione "
        "registrabile deve avere li' la sua frase in italiano e il suo gruppo, "
        "altrimenti la pagina /registro non la sa ne' descrivere ne' filtrare"
    )


def test_il_catalogo_copre_tutte_le_operazioni_chieste_dalla_sessione():
    """Le operazioni dell'elenco della sessione 9 sono tutte catalogate.

    E' l'elenco chiesto dall'azienda, scritto qui una seconda volta apposta:
    se un giorno qualcuno togliesse un'azione dal catalogo credendo che non
    servisse piu', questo test direbbe che invece era stata promessa.
    """
    promesse = (
        # accesso riuscito e fallito, disconnessione
        "user.login",
        "user.login_failed",
        "user.logout",
        # creazione, modifica e disattivazione utente, reimpostazione password
        "user.created",
        "user.updated",
        "user.deactivated",
        "user.password_reset",
        # creazione e modifica cliente, prodotto, versione
        "customer.created",
        "customer.updated",
        "product.created",
        "product.updated",
        "product_version.created",
        "product_version.updated",
        # cambio di stato del ciclo di vita
        "product_version.state_changed",
        # creazione progetto, assegnazione e rimozione di utenti
        "project.created",
        "assignment.created",
        "assignment.revoked",
        # documenti
        "document.created",
        "document.version_uploaded",
        "document.state_changed",
        "document.deleted",
        "document.restored",
        "document.download",
        # matrice dei permessi
        "permission_rule.changed",
        # avanzamento di fase
        "project.phase_requested",
        "project.phase_approved",
        "project.phase_rejected",
        # assegnazione manuale di una email (la pagina arriva con la sessione 10)
        "email.assigned_manual",
        # configurazione
        "config.changed",
    )

    mancanti = [azione for azione in promesse if azione not in audit.CATALOGO]
    assert mancanti == [], f"azioni promesse e non catalogate: {mancanti}"


def test_ogni_voce_del_catalogo_ha_una_frase_e_un_gruppo():
    """Nessuna riga del catalogo con l'etichetta vuota o il gruppo vuoto."""
    difettose = [
        codice
        for codice, tipo in audit.CATALOGO.items()
        if not tipo.etichetta.strip() or not tipo.gruppo.strip()
    ]
    assert difettose == [], f"queste voci del catalogo sono incomplete: {difettose}"


# ===========================================================================
#  2. LA FORMA DI UNA VOCE
# ===========================================================================


def test_una_voce_contiene_tutto_quello_che_deve_contenere(db_session, client):
    """Data e ora con fuso, utente, azione, entita', descrizione, IP, catena.

    E' il requisito 2 della sessione, verificato campo per campo su
    un'operazione vera - un accesso - invece che su una riga costruita a mano.
    """
    utente = creatore_di_prova(db_session)
    entra(client, utente.username, PASSWORD_DI_PROVA)

    voce = unica_voce(db_session, audit.ACTION_LOGIN, utente.id)

    assert voce.occurred_at.tzinfo is not None, "l'ora e' senza fuso orario"
    assert voce.user_id == utente.id
    assert voce.action == audit.ACTION_LOGIN
    assert voce.entity_type == audit.ENTITY_USERS
    assert voce.entity_id == utente.id
    assert utente.username in voce.description
    assert voce.description.startswith("Accesso riuscito")
    # Il finto browser dei test si presenta come "testclient": e' un indirizzo
    # finto, ma dimostra che l'indirizzo vero viene letto e scritto.
    assert voce.ip == "testclient"
    assert voce.seq > 0
    assert len(voce.entry_hash) == 64
    assert len(voce.previous_hash) == 64


def test_una_modifica_registra_il_valore_prima_e_quello_dopo(db_session):
    """Requisito 2: per le modifiche servono il valore precedente e successivo."""
    autore = creatore_di_prova(db_session)
    cliente = crea_cliente(db_session, nome="Prima del cambio")

    customers.modifica_cliente(
        db_session,
        cliente,
        nome="Dopo il cambio",
        codice=cliente.code,
        note=None,
        autore=autore,
    )
    db_session.flush()

    voce = unica_voce(db_session, customers.ACTION_CUSTOMER_UPDATED, cliente.id)

    assert voce.old_value == {"name": "Prima del cambio"}
    assert voce.new_value == {"name": "Dopo il cambio"}
    # E la stessa cosa si legge in italiano, senza aprire il JSON.
    assert "Prima del cambio -> Dopo il cambio" in voce.description


def test_le_operazioni_di_sistema_non_hanno_una_persona(db_session):
    """Il superamento automatico di una versione e' un'azione senza utente.

    "user_id" nullo vuol dire "lo ha fatto il programma". E' meglio del nome
    di chi ha premuto il pulsante che ha provocato l'operazione: quella
    persona non ha chiesto di superare la versione precedente, ed e' il
    programma ad aver applicato la regola.
    """
    autore = creatore_di_prova(db_session)
    prodotto, prima = crea_prodotto(db_session, autore=autore)

    lifecycle.cambia_stato(db_session, prima, LifecycleState.RILASCIATO, autore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Seconda versione", autore=autore
    )
    db_session.flush()
    lifecycle.cambia_stato(db_session, seconda, LifecycleState.RILASCIATO, autore)
    db_session.flush()

    voce = unica_voce(db_session, lifecycle.ACTION_SUPERSEDED, prima.id)
    assert voce.user_id is None
    assert registro.nome_autore(voce) == "sistema"


# ===========================================================================
#  3. NON MODIFICABILITA'
# ===========================================================================


def test_l_utente_applicativo_non_puo_modificare_il_registro(db_session):
    """Un UPDATE su audit_logs con le credenziali di Aurora deve fallire.

    E' il criterio di accettazione della sessione 9, ed e' un test e non una
    verifica a mano perche' e' esattamente il genere di garanzia che si perde
    in silenzio: basta un GRANT dato "per un momento" durante una migrazione e
    dimenticato li'.

    **Questo test non si salta se l'ambiente non e' preparato**, a differenza
    di quelli che dipendono dalle migrazioni. La differenza e' che senza
    migrazioni Aurora non funziona affatto - e la mancanza si vede subito -
    mentre senza questi permessi funziona benissimo, e la mancanza si vede il
    giorno della verifica aziendale. Se questo test e' rosso, la procedura da
    eseguire e' scripts/hardening_db.md.
    """
    with pytest.raises(ProgrammingError) as errore:
        db_session.execute(
            text("UPDATE audit_logs SET description = 'manomesso' WHERE seq = 1")
        )

    # Il savepoint e' saltato: si torna indietro, altrimenti tutto quello che
    # viene dopo in questo test fallirebbe sulla transazione interrotta.
    db_session.rollback()

    assert "audit_logs" in str(errore.value)
    assert "permission denied" in str(errore.value).lower() or (
        "permesso negato" in str(errore.value).lower()
    ), (
        "l'UPDATE non e' stato rifiutato per mancanza di permessi. Eseguire "
        "scripts/hardening_db.sql come descritto in scripts/hardening_db.md"
    )


def test_l_utente_applicativo_non_puo_cancellare_dal_registro(db_session):
    """E nemmeno un DELETE. Le voci non si tolgono, mai."""
    with pytest.raises(ProgrammingError):
        db_session.execute(text("DELETE FROM audit_logs WHERE seq = 1"))
    db_session.rollback()


def test_i_permessi_sul_registro_sono_soltanto_due(db_session):
    """Su audit_logs l'utente applicativo ha SELECT e INSERT, e nient'altro.

    Guarda i permessi invece che provare le operazioni: cosi' un permesso
    concesso che oggi nessuno usa - REFERENCES, TRIGGER - viene visto lo
    stesso, prima che qualcuno ci costruisca sopra qualcosa.
    """
    concessi = set(
        db_session.scalars(
            text(
                """
                SELECT privilege_type
                  FROM information_schema.table_privileges
                 WHERE table_name = 'audit_logs'
                   AND grantee = current_user
                """
            )
        ).all()
    )

    assert concessi == {"SELECT", "INSERT"}, (
        f"su audit_logs l'utente applicativo ha {sorted(concessi)}. Deve avere "
        "soltanto SELECT e INSERT: eseguire scripts/hardening_db.sql"
    )


def test_nessun_file_del_programma_modifica_o_cancella_il_registro():
    """In app/ non c'e' nessun UPDATE ne' DELETE su audit_logs.

    Il divieto lo fa rispettare il database, ma un programma che ci provasse
    andrebbe in errore davanti all'utente invece che dire qualcosa di sensato.
    Meglio accorgersene qui.
    """
    sospette = re.compile(
        r"(update\s*\(\s*AuditLog|delete\s*\(\s*AuditLog"
        r"|UPDATE\s+audit_logs|DELETE\s+FROM\s+audit_logs)",
        re.IGNORECASE,
    )

    colpevoli = []
    for percorso in sorgenti_python():
        testo = percorso.read_text(encoding="utf-8")
        # Si guardano le righe di codice, non i commenti: il divieto si spiega
        # in mezzo programma, ed e' giusto cosi'.
        for numero, riga in enumerate(testo.splitlines(), start=1):
            if riga.lstrip().startswith("#"):
                continue
            if sospette.search(riga):
                colpevoli.append((percorso.relative_to(RADICE), numero))

    assert colpevoli == [], (
        f"questi file modificano o cancellano righe del registro: {colpevoli}. "
        "Il registro si scrive e non si tocca piu' (D-018)"
    )


# ===========================================================================
#  4. LA CATENA DELLE IMPRONTE
# ===========================================================================


def test_la_catena_del_registro_e_integra(db_session):
    """Sul database com'e' adesso, verifica_catena() non trova niente.

    E' il criterio di accettazione: lo stesso controllo che esegue
    scripts/verifica_audit.py, fatto qui perche' un controllo che gira solo
    quando qualcuno si ricorda di lanciarlo non e' un controllo.
    """
    esito = registro.verifica_catena(db_session)

    assert esito.integro, (
        f"la catena del registro ha {len(esito.anomalie)} anomalie: "
        f"{[(a.seq, a.genere) for a in esito.anomalie[:5]]}"
    )
    assert esito.voci_esaminate > 0


def test_ogni_voce_nuova_si_aggancia_alla_precedente(db_session):
    """Due operazioni di fila producono due voci incatenate."""
    autore = creatore_di_prova(db_session)
    cliente = crea_cliente(db_session)

    customers.disattiva_cliente(db_session, cliente, autore=autore)
    db_session.flush()
    customers.riattiva_cliente(db_session, cliente, autore=autore)
    db_session.flush()

    prima = unica_voce(db_session, customers.ACTION_CUSTOMER_DEACTIVATED, cliente.id)
    dopo = unica_voce(db_session, customers.ACTION_CUSTOMER_REACTIVATED, cliente.id)

    assert dopo.seq == prima.seq + 1
    assert dopo.previous_hash == prima.entry_hash
    # E ciascuna corrisponde al proprio contenuto.
    assert audit.impronta_della_riga(prima) == prima.entry_hash
    assert audit.impronta_della_riga(dopo) == dopo.entry_hash


def test_una_riga_manomessa_viene_segnalata(db_session):
    """Una voce il cui contenuto non corrisponde all'impronta salta fuori.

    Simula quello che fa chi amministra il database: scrive una riga
    scegliendosi le impronte. Il programma non ci riuscirebbe - le impronte le
    calcola audit.record() - ma chi ha in mano psql si'.
    """
    numero = ultimo_numero(db_session) + 1
    inserisci_voce_grezza(
        db_session,
        seq=numero,
        previous_hash=audit.IMPRONTA_ZERO,
        entry_hash="f" * 64,
        description="Riga con l'impronta sbagliata",
    )
    db_session.flush()

    esito = registro.verifica_catena(db_session)

    assert not esito.integro
    generi = {anomalia.genere for anomalia in esito.anomalie if anomalia.seq == numero}
    assert registro.ANOMALIA_IMPRONTA in generi, (
        "una voce con l'impronta sbagliata non e' stata segnalata: "
        f"anomalie trovate {[(a.seq, a.genere) for a in esito.anomalie]}"
    )


def test_una_riga_scollegata_viene_segnalata(db_session):
    """Una voce che non si aggancia alla precedente salta fuori.

    E' il caso di chi toglie una riga di mezzo e ricalcola l'impronta di
    quella dopo sperando che nessuno guardi l'aggancio.
    """
    numero = ultimo_numero(db_session) + 1
    # L'impronta della voce e' coerente con il suo contenuto, ma la voce dice
    # di agganciarsi a qualcosa che non e' la voce prima.
    descrizione = "Riga agganciata al posto sbagliato"
    aggancio_falso = "a" * 64
    impronta = audit.impronta(
        seq=numero,
        occurred_at=datetime.now(timezone.utc),
        user_id=None,
        action="user.login",
        entity_type="users",
        entity_id=None,
        old_value=None,
        new_value=None,
        ip=None,
        description=descrizione,
        previous_hash=aggancio_falso,
    )
    inserisci_voce_grezza(
        db_session,
        seq=numero,
        previous_hash=aggancio_falso,
        entry_hash=impronta,
        description=descrizione,
    )
    db_session.flush()

    esito = registro.verifica_catena(db_session)

    assert not esito.integro
    generi = {anomalia.genere for anomalia in esito.anomalie if anomalia.seq == numero}
    assert registro.ANOMALIA_COLLEGAMENTO in generi


def test_un_buco_nella_numerazione_viene_segnalato(db_session):
    """Una voce tolta lascia un salto nei numeri, e il salto si vede."""
    numero = ultimo_numero(db_session) + 3  # se ne saltano due
    inserisci_voce_grezza(
        db_session,
        seq=numero,
        previous_hash=audit.IMPRONTA_ZERO,
        entry_hash="b" * 64,
    )
    db_session.flush()

    esito = registro.verifica_catena(db_session)

    generi = {anomalia.genere for anomalia in esito.anomalie if anomalia.seq == numero}
    assert registro.ANOMALIA_BUCO in generi


def test_l_impronta_cambia_se_cambia_un_campo_qualunque(db_session):
    """Ogni campo che racconta il fatto entra nell'impronta.

    Se un campo restasse fuori, si potrebbe cambiare quello senza che la
    catena se ne accorga - e sarebbe il campo che qualcuno cambierebbe.
    """
    base = {
        "seq": 1,
        "occurred_at": datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        "user_id": uuid.uuid4(),
        "action": "user.login",
        "entity_type": "users",
        "entity_id": uuid.uuid4(),
        "old_value": {"a": 1},
        "new_value": {"b": 2},
        "ip": "10.0.0.1",
        "description": "Accesso riuscito: mario.rossi",
        "previous_hash": audit.IMPRONTA_ZERO,
    }
    riferimento = audit.impronta(**base)

    variazioni = {
        "seq": 2,
        "occurred_at": base["occurred_at"] + timedelta(seconds=1),
        "user_id": uuid.uuid4(),
        "action": "user.logout",
        "entity_type": "documents",
        "entity_id": uuid.uuid4(),
        "old_value": {"a": 2},
        "new_value": {"b": 3},
        "ip": "10.0.0.2",
        "description": "Accesso riuscito: mario.bianchi",
        "previous_hash": "c" * 64,
    }

    for campo, valore in variazioni.items():
        cambiato = dict(base)
        cambiato[campo] = valore
        assert audit.impronta(**cambiato) != riferimento, (
            f"cambiando '{campo}' l'impronta non cambia: quel campo si "
            "potrebbe correggere nel database senza spezzare la catena"
        )


def test_l_impronta_si_ricalcola_uguale_rileggendo_dal_database(db_session, client):
    """Il JSON riletto da PostgreSQL produce la stessa impronta.

    E' la trappola vera di una catena di impronte: jsonb non conserva l'ordine
    delle chiavi, e senza la normalizzazione di audit._testo_json() la
    verifica direbbe "manomesso" su un registro intatto.
    """
    utente = creatore_di_prova(db_session)
    users.reimposta_password(db_session, utente, utente)
    db_session.flush()

    voce = unica_voce(db_session, audit.ACTION_PASSWORD_RESET, utente.id)
    # Si butta via l'oggetto in memoria e si rilegge dal database.
    db_session.expire(voce)

    assert audit.impronta_della_riga(voce) == voce.entry_hash


# ===========================================================================
#  5. TUTTE LE OPERAZIONI DELL'ELENCO LASCIANO TRACCIA
# ===========================================================================


def test_accesso_riuscito_fallito_e_disconnessione(db_session, client):
    """Le tre operazioni degli accessi."""
    utente = creatore_di_prova(db_session)

    entra(client, utente.username, "password-sbagliata")
    fallito = unica_voce(db_session, audit.ACTION_LOGIN_FAILED, utente.id)
    assert fallito.new_value["username"] == utente.username

    entra(client, utente.username, PASSWORD_DI_PROVA)
    unica_voce(db_session, audit.ACTION_LOGIN, utente.id)

    client.post("/esci", data={"csrf": _gettone(client, "/")}, follow_redirects=False)
    unica_voce(db_session, audit.ACTION_LOGOUT, utente.id)


def _gettone(client: TestClient, percorso: str) -> str:
    """Il gettone CSRF letto da una pagina qualunque."""
    risposta = client.get(percorso)
    trovato = re.search(r'name="csrf"\s+value="([^"]+)"', risposta.text)
    assert trovato is not None, f"la pagina {percorso} non contiene il campo csrf"
    return trovato.group(1)


def test_creazione_modifica_disattivazione_utente_e_password(db_session):
    """Le quattro operazioni sugli utenti."""
    capo = creatore_di_prova(db_session)

    utente, _password = users.crea_utente(
        db_session,
        first_name="Anna",
        last_name="Verdi",
        email=f"anna.{uuid.uuid4().hex[:8]}@esempio.local",
        username=f"prova.anna.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.UTENTE,
        creato_da=capo,
    )
    db_session.flush()
    creazione = unica_voce(db_session, audit.ACTION_USER_CREATED, utente.id)
    assert "password" not in str(creazione.new_value).lower()

    users.modifica(
        db_session,
        utente,
        first_name="Annamaria",
        last_name="Verdi",
        email=utente.email,
        modificato_da=capo,
    )
    db_session.flush()
    modifica = unica_voce(db_session, audit.ACTION_USER_UPDATED, utente.id)
    assert modifica.old_value == {"first_name": "Anna"}
    assert modifica.new_value == {"first_name": "Annamaria"}

    users.reimposta_password(db_session, utente, capo)
    db_session.flush()
    reimpostata = unica_voce(db_session, audit.ACTION_PASSWORD_RESET, utente.id)
    assert "password" not in str(reimpostata.new_value).lower()

    users.disattiva(db_session, utente, capo)
    db_session.flush()
    disattivazione = unica_voce(db_session, audit.ACTION_USER_DEACTIVATED, utente.id)
    assert disattivazione.old_value == {"is_active": True}


def test_creazione_e_modifica_di_cliente_prodotto_e_versione(db_session):
    """Anagrafiche: cliente, prodotto, versione, in creazione e in modifica."""
    autore = creatore_di_prova(db_session)

    cliente = customers.crea_cliente(
        db_session,
        nome="Cliente del registro",
        codice=sigla_irripetibile(),
        note=None,
        autore=autore,
    )
    db_session.flush()
    unica_voce(db_session, customers.ACTION_CUSTOMER_CREATED, cliente.id)

    customers.modifica_cliente(
        db_session,
        cliente,
        nome="Cliente corretto",
        codice=cliente.code,
        note="Con una nota",
        autore=autore,
    )
    db_session.flush()
    unica_voce(db_session, customers.ACTION_CUSTOMER_UPDATED, cliente.id)

    prodotto, versione = products.crea_prodotto(
        db_session,
        codice=codice_irripetibile(),
        cliente=cliente,
        descrizione="Prodotto del registro",
        autore=autore,
    )
    db_session.flush()
    unica_voce(db_session, products.ACTION_PRODUCT_CREATED, prodotto.id)
    unica_voce(db_session, products.ACTION_VERSION_CREATED, versione.id)

    products.modifica_prodotto(
        db_session,
        prodotto,
        codice=prodotto.code,
        cliente=cliente,
        descrizione="Descrizione corretta",
        autore=autore,
    )
    db_session.flush()
    unica_voce(db_session, products.ACTION_PRODUCT_UPDATED, prodotto.id)

    products.modifica_versione(
        db_session, versione, motivo="Motivo corretto", autore=autore
    )
    db_session.flush()
    modifica = unica_voce(db_session, products.ACTION_VERSION_UPDATED, versione.id)
    assert modifica.new_value == {"derivation_reason": "Motivo corretto"}


def test_cambio_di_stato_del_ciclo_di_vita(db_session):
    """Il ciclo di vita di una versione lascia traccia del prima e del dopo."""
    autore = creatore_di_prova(db_session)
    _prodotto, versione = crea_prodotto(db_session, autore=autore)

    lifecycle.cambia_stato(db_session, versione, LifecycleState.RILASCIATO, autore)
    db_session.flush()

    voce = unica_voce(db_session, lifecycle.ACTION_STATE_CHANGED, versione.id)
    assert voce.old_value["lifecycle_state"] == LifecycleState.IN_SVILUPPO.value
    assert voce.new_value["lifecycle_state"] == LifecycleState.RILASCIATO.value


def test_creazione_progetto_e_assegnazioni(db_session):
    """Progetto aperto, persona assegnata, persona tolta."""
    capo = creatore_di_prova(db_session)
    ingegnere = crea_utente(db_session, username=f"prova.ing.{uuid.uuid4().hex[:8]}")
    _prodotto, versione = crea_prodotto(db_session, autore=capo)

    progetto = crea_progetto(db_session, versione, project_manager=capo, autore=capo)
    unica_voce(db_session, projects.ACTION_PROJECT_CREATED, progetto.id)

    assegnazione = projects.assegna(
        db_session,
        progetto=progetto,
        utente=ingegnere,
        ruolo=ProjectRole.INGEGNERE,
        autore=capo,
    )
    db_session.flush()
    creata = unica_voce(db_session, projects.ACTION_ASSIGNMENT_CREATED, assegnazione.id)
    assert creata.new_value["user"] == ingegnere.username

    projects.revoca(db_session, assegnazione=assegnazione, autore=capo)
    db_session.flush()
    unica_voce(db_session, projects.ACTION_ASSIGNMENT_REVOKED, assegnazione.id)


def test_tutte_le_operazioni_sui_documenti(db_session):
    """Caricamento, versione nuova, stato, ritiro, ripristino, scarico."""
    capo = creatore_di_prova(db_session)
    _prodotto, versione = crea_prodotto(db_session, autore=capo)
    progetto = crea_progetto(db_session, versione, project_manager=capo, autore=capo)
    documento, prima_versione = crea_documento(db_session, progetto, capo)

    unica_voce(db_session, documents.ACTION_DOCUMENT_CREATED, documento.id)

    import io

    from app.services import storage

    contenuto = contenuto_irripetibile()
    deposito = storage.deposita(io.BytesIO(contenuto))
    documents.aggiungi_versione(
        db_session,
        documento=documento,
        caricamento=documents.Caricamento(
            sorgente=io.BytesIO(contenuto),
            nome_file="schema-2.pdf",
            mime_type="application/pdf",
        ),
        deposito=deposito,
        nota="Corretta la piedinatura",
        autore=capo,
    )
    db_session.flush()
    caricata = unica_voce(db_session, documents.ACTION_VERSION_UPLOADED, documento.id)
    assert caricata.new_value["version_number"] == 2

    documents.cambia_stato(
        db_session,
        documento=documento,
        nuovo_stato=DocumentState.IN_VERIFICA,
        autore=capo,
    )
    db_session.flush()
    unica_voce(db_session, documents.ACTION_STATE_CHANGED, documento.id)

    documents.registra_scarico(
        db_session,
        documento=documento,
        versione=prima_versione,
        utente=capo,
        con_filigrana=False,
    )
    db_session.flush()
    scarico = unica_voce(db_session, documents.ACTION_DOCUMENT_DOWNLOADED, documento.id)
    assert scarico.new_value["version_number"] == prima_versione.version_number

    documents.elimina(db_session, documento=documento, autore=capo)
    db_session.flush()
    unica_voce(db_session, documents.ACTION_DOCUMENT_DELETED, documento.id)

    documents.ripristina(db_session, documento=documento, autore=capo)
    db_session.flush()
    unica_voce(db_session, documents.ACTION_DOCUMENT_RESTORED, documento.id)


def test_modifica_della_matrice_dei_permessi(db_session):
    """Una casella corretta produce una riga con il prima e il dopo."""
    capo = creatore_di_prova(db_session)

    caselle = permissions.matrice(db_session)
    casella = caselle[0]
    colonna = "can_view"
    scelte = {f"{casella.nome_campo}:{colonna}": not getattr(casella, colonna)}

    cambiamenti = permissions.confronta_matrice(db_session, scelte)
    assert cambiamenti, "la casella scelta non risulta cambiata"

    permissions.salva_matrice(db_session, cambiamenti, capo)
    db_session.flush()

    voce = unica_voce(db_session, permissions.ACTION_MATRIX_CHANGED)
    assert voce.old_value[colonna] != voce.new_value[colonna]
    assert voce.old_value["classificazione"] == voce.new_value["classificazione"]


def test_richiesta_approvazione_e_rifiuto_di_avanzamento_fase(db_session):
    """Le tre operazioni del flusso di avanzamento."""
    capo = creatore_di_prova(db_session)
    ingegnere = crea_utente(db_session, username=f"prova.ing.{uuid.uuid4().hex[:8]}")
    _prodotto, versione = crea_prodotto(db_session, autore=capo)
    modello = crea_modello_di_fasi(db_session)
    progetto = crea_progetto(
        db_session,
        versione,
        project_manager=capo,
        autore=capo,
        squadra=[ingegnere],
        modello=modello,
    )

    richiesta = phases.richiedi(
        db_session,
        progetto=progetto,
        motivazione="Lo studio e' finito",
        autore=ingegnere,
    )
    db_session.flush()
    unica_voce(db_session, phases.ACTION_PHASE_REQUESTED, progetto.id)

    phases.decidi(
        db_session,
        passaggio=richiesta,
        accolta=False,
        motivazione="Manca la relazione",
        autore=capo,
    )
    db_session.flush()
    respinta = unica_voce(db_session, phases.ACTION_PHASE_REJECTED, richiesta.id)
    assert respinta.new_value["motivazione"] == "Manca la relazione"

    seconda = phases.richiedi(
        db_session,
        progetto=progetto,
        motivazione="Relazione aggiunta",
        autore=ingegnere,
    )
    db_session.flush()
    phases.decidi(
        db_session,
        passaggio=seconda,
        accolta=True,
        motivazione="Va bene",
        autore=capo,
    )
    db_session.flush()
    unica_voce(db_session, phases.ACTION_PHASE_APPROVED, seconda.id)


def test_la_configurazione_cambiata_viene_registrata(db_session):
    """Requisito 1: le modifiche alla configurazione lasciano traccia.

    Aurora non ha una pagina che modifichi la configurazione - sta nel file
    .env, regola 8 di CLAUDE.md - quindi quello che si registra e' il **fatto**
    che sia cambiata rispetto all'avvio precedente. Qui si simula un avvio con
    una configurazione diversa, scrivendo prima una fotografia finta.
    """
    adesso = configuration.configurazione_effettiva()

    finta = dict(adesso)
    finta["PAGE_SIZE"] = 999
    audit.record(
        db_session,
        action=audit.ACTION_CONFIG_LOADED,
        entity_type=audit.ENTITY_SISTEMA,
        user_id=None,
        new_value=finta,
        description="Fotografia finta scritta da un test",
    )
    db_session.flush()

    azione = configuration.registra_configurazione(db_session)
    db_session.flush()

    assert azione == audit.ACTION_CONFIG_CHANGED
    voce = unica_voce(db_session, audit.ACTION_CONFIG_CHANGED)
    assert voce.old_value["PAGE_SIZE"] == 999
    assert voce.new_value["PAGE_SIZE"] == adesso["PAGE_SIZE"]
    assert voce.user_id is None
    assert "PAGE_SIZE: 999 ->" in voce.description


def test_la_configurazione_uguale_non_registra_niente(db_session):
    """Un riavvio che non cambia niente non sporca il registro."""
    configuration.registra_configurazione(db_session)
    db_session.flush()

    assert configuration.registra_configurazione(db_session) is None


def test_i_segreti_non_finiscono_nel_registro(db_session):
    """La chiave di firma e la password del database non si registrano."""
    valori = configuration.configurazione_effettiva()
    testo = str(valori)

    from app.config import settings

    assert settings.SECRET_KEY not in testo
    assert "SECRET_KEY (impronta)" in valori
    assert ":***@" in valori["DATABASE_URL"], (
        "la password del database non e' stata nascosta nella stringa di "
        "connessione registrata"
    )


# ===========================================================================
#  6. LA PAGINA DI CONSULTAZIONE
# ===========================================================================


def test_il_registro_e_riservato_al_creatore(client, db_session):
    """Chi non amministra Aurora non apre /registro.

    Messo insieme, il registro dice anche a che ora entra ed esce ciascuno:
    e' uno strumento di verifica, non un tabellone.
    """
    utente = crea_utente(db_session, username=f"prova.norm.{uuid.uuid4().hex[:8]}")
    entra(client, utente.username, PASSWORD_DI_PROVA)

    risposta = client.get("/registro")
    assert risposta.status_code == 403


def test_il_registro_mostra_le_operazioni_appena_fatte(client, db_session):
    """Un'operazione fatta adesso si ritrova nella pagina, con i suoi dati."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    cliente = customers.crea_cliente(
        db_session,
        nome="Cliente che deve comparire",
        codice=sigla_irripetibile(),
        note=None,
        autore=capo,
    )
    db_session.flush()

    pagina = client.get("/registro")

    assert pagina.status_code == 200
    assert "Cliente creato" in pagina.text
    assert cliente.name in pagina.text
    assert capo.username in pagina.text


def test_la_ricerca_testuale_filtra_sulla_descrizione(client, db_session):
    """Requisito 5: ricerca testuale sulla descrizione."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    nome = f"Cercabile {uuid.uuid4().hex[:8]}"
    customers.crea_cliente(
        db_session, nome=nome, codice=sigla_irripetibile(), note=None, autore=capo
    )
    db_session.flush()

    trovato = client.get("/registro", params={"q": nome})
    assert nome in trovato.text

    non_trovato = client.get("/registro", params={"q": "questo-non-esiste-davvero"})
    assert nome not in non_trovato.text
    assert "Nessuna operazione con questi filtri" in non_trovato.text


def test_i_filtri_del_registro_funzionano(client, db_session):
    """Filtri per utente, tipo di azione, tipo di entita' e intervallo di date."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    cliente = crea_cliente(db_session, nome=f"Filtrabile {uuid.uuid4().hex[:8]}")
    customers.disattiva_cliente(db_session, cliente, autore=capo)
    db_session.flush()

    # Per utente.
    per_utente = client.get("/registro", params={"utente": str(capo.id)})
    assert cliente.name in per_utente.text

    altro = crea_utente(db_session, username=f"prova.altro.{uuid.uuid4().hex[:8]}")
    per_altro = client.get("/registro", params={"utente": str(altro.id)})
    assert cliente.name not in per_altro.text

    # Per tipo di azione.
    per_azione = client.get(
        "/registro", params={"azione": customers.ACTION_CUSTOMER_DEACTIVATED}
    )
    assert cliente.name in per_azione.text

    per_altra_azione = client.get("/registro", params={"azione": audit.ACTION_LOGOUT})
    assert cliente.name not in per_altra_azione.text

    # Per tipo di entita'.
    per_entita = client.get("/registro", params={"entita": "customers"})
    assert cliente.name in per_entita.text

    per_altra_entita = client.get("/registro", params={"entita": "documents"})
    assert cliente.name not in per_altra_entita.text

    # Per intervallo di date: oggi si', il mese scorso no.
    oggi = datetime.now().date()
    di_oggi = client.get(
        "/registro", params={"dal": oggi.isoformat(), "al": oggi.isoformat()}
    )
    assert cliente.name in di_oggi.text, (
        "il filtro «dal ... al ...» sullo stesso giorno esclude le operazioni "
        "di quel giorno: il giorno finale dev'essere compreso"
    )

    vecchio = (oggi - timedelta(days=30)).isoformat()
    di_un_mese_fa = client.get("/registro", params={"dal": vecchio, "al": vecchio})
    assert cliente.name not in di_un_mese_fa.text


def test_il_filtro_per_gruppo_prende_tutte_le_azioni_del_gruppo(db_session):
    """Il gruppo e' una scorciatoia per un elenco di azioni."""
    azioni = audit.azioni_del_gruppo(audit.GRUPPO_DOCUMENTI)

    assert "document.created" in azioni
    assert "document.download" in azioni
    assert "user.login" not in azioni


def test_il_registro_si_impagina(client, db_session):
    """Requisito 5: impaginazione."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    prima = client.get("/registro")
    assert prima.status_code == 200

    # Con quasi cento voci nel database di sviluppo l'impaginazione c'e'; se
    # un giorno il registro fosse cortissimo, questa asserzione direbbe
    # soltanto che non serviva.
    totale = db_session.scalar(select(func.count()).select_from(AuditLog))
    if totale > 25:
        assert "impaginazione-voce" in prima.text
        seconda = client.get("/registro", params={"pagina": 2})
        assert seconda.status_code == 200
        assert seconda.text != prima.text


# ===========================================================================
#  7. L'ESPORTAZIONE IN CSV
# ===========================================================================


def test_l_esportazione_produce_un_csv_con_le_voci_filtrate(client, db_session):
    """Requisito 7: esportazione in CSV dei risultati filtrati."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    nome = f"Esportabile {uuid.uuid4().hex[:8]}"
    customers.crea_cliente(
        db_session, nome=nome, codice=sigla_irripetibile(), note=None, autore=capo
    )
    db_session.flush()

    risposta = client.get("/registro/esporta", params={"q": nome})

    assert risposta.status_code == 200
    assert "text/csv" in risposta.headers["content-type"]
    assert "attachment" in risposta.headers["content-disposition"]

    testo = risposta.content.decode("utf-8-sig")
    righe = testo.splitlines()
    assert righe[0].startswith("N.;Data e ora;Utente;Azione")
    assert any(nome in riga for riga in righe[1:])
    # Le impronte ci sono: un'esportazione senza impronte non si verifica.
    assert "Impronta" in righe[0]


def test_l_esportazione_finisce_essa_stessa_nel_registro(client, db_session):
    """Requisito 7: l'esportazione e' registrata.

    Un'esportazione e' una copia del registro che esce da Aurora: chi l'ha
    fatta e quando e' esattamente il genere di domanda a cui un audit trail
    deve saper rispondere.
    """
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    prima = len(voci_di(db_session, audit.ACTION_AUDIT_EXPORTED))
    client.get("/registro/esporta", params={"q": "documento"})

    voci = voci_di(db_session, audit.ACTION_AUDIT_EXPORTED)
    assert len(voci) == prima + 1

    voce = voci[0]
    assert voce.user_id == capo.id
    assert voce.new_value["filtri"] == {"q": "documento"}
    assert "Registro esportato in CSV" in voce.description


def test_l_esportazione_e_riservata_al_creatore(client, db_session):
    """Chi non apre il registro non lo esporta nemmeno."""
    utente = crea_utente(db_session, username=f"prova.norm.{uuid.uuid4().hex[:8]}")
    entra(client, utente.username, PASSWORD_DI_PROVA)

    assert client.get("/registro/esporta").status_code == 403


# ===========================================================================
#  8. LE SCHEDE "STORICO"
# ===========================================================================


def test_ogni_scheda_ha_la_linguetta_dello_storico(client, db_session):
    """Requisito 6: prodotto, versione, progetto, documento e persona."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    prodotto, versione = crea_prodotto(db_session, autore=capo)
    progetto = crea_progetto(db_session, versione, project_manager=capo, autore=capo)
    documento, _v = crea_documento(db_session, progetto, capo)

    schede = {
        f"/prodotti/{prodotto.id}": f"/prodotti/{prodotto.id}/storico",
        f"/versioni/{versione.id}": f"/versioni/{versione.id}/storico",
        f"/progetti/{progetto.id}": f"/progetti/{progetto.id}/storico",
        f"/documenti/{documento.id}": f"/documenti/{documento.id}/storico",
        f"/utenti/{capo.id}": f"/utenti/{capo.id}/storico",
    }

    for scheda, storico in schede.items():
        pagina = client.get(scheda)
        assert pagina.status_code == 200, f"{scheda} non si apre"
        assert storico in pagina.text, (
            f"la scheda {scheda} non ha la linguetta «Storico»"
        )

        elenco = client.get(storico)
        assert elenco.status_code == 200, f"{storico} non si apre"


def test_lo_storico_di_un_documento_mostra_le_sue_operazioni(client, db_session):
    """Le voci sono quelle di quell'oggetto, non quelle di tutto il registro."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    _prodotto, versione = crea_prodotto(db_session, autore=capo)
    progetto = crea_progetto(db_session, versione, project_manager=capo, autore=capo)
    documento, prima_versione = crea_documento(
        db_session, progetto, capo, titolo="Documento con storia"
    )
    altro, _ = crea_documento(db_session, progetto, capo, titolo="Documento estraneo")

    documents.registra_scarico(
        db_session,
        documento=documento,
        versione=prima_versione,
        utente=capo,
        con_filigrana=False,
    )
    db_session.flush()

    pagina = client.get(f"/documenti/{documento.id}/storico")

    assert "Documento caricato" in pagina.text
    assert "Documento scaricato" in pagina.text
    assert "Documento estraneo" not in pagina.text, (
        "lo storico di un documento mostra le operazioni di un altro documento"
    )
    assert altro.title not in pagina.text


def test_lo_storico_di_un_progetto_comprende_squadra_e_fasi(client, db_session):
    """Le assegnazioni e i passaggi di fase fanno parte della storia del progetto.

    Sono voci con un tipo di entita' diverso - "assignments",
    "phase_transitions" - e senza i loro identificatori non comparirebbero.
    Sono pero' la meta' della storia di un progetto.
    """
    capo = creatore_di_prova(db_session)
    ingegnere = crea_utente(db_session, username=f"prova.ing.{uuid.uuid4().hex[:8]}")
    entra(client, capo.username, PASSWORD_DI_PROVA)

    _prodotto, versione = crea_prodotto(db_session, autore=capo)
    modello = crea_modello_di_fasi(db_session)
    progetto = crea_progetto(
        db_session,
        versione,
        project_manager=capo,
        autore=capo,
        squadra=[ingegnere],
        modello=modello,
    )
    richiesta = phases.richiedi(
        db_session, progetto=progetto, motivazione="Finito", autore=ingegnere
    )
    db_session.flush()
    phases.decidi(
        db_session,
        passaggio=richiesta,
        accolta=True,
        motivazione="Va bene",
        autore=capo,
    )
    db_session.flush()

    pagina = client.get(f"/progetti/{progetto.id}/storico")

    assert "Progetto aperto" in pagina.text
    assert "Persona assegnata al progetto" in pagina.text
    assert "Avanzamento di fase approvato" in pagina.text


def test_lo_storico_di_una_persona_mostra_anche_quello_che_ha_fatto(
    client, db_session
):
    """Le due meta': quello che le hanno fatto e quello che ha fatto lei."""
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    nome = f"Cliente di {capo.username}"
    customers.crea_cliente(
        db_session, nome=nome, codice=sigla_irripetibile(), note=None, autore=capo
    )
    db_session.flush()

    pagina = client.get(f"/utenti/{capo.id}/storico")

    assert "Accesso riuscito" in pagina.text, "manca quello che le e' successo"
    assert nome in pagina.text, "manca quello che ha fatto"


def test_lo_storico_di_un_documento_non_si_apre_a_chi_non_lo_vede(client, db_session):
    """Chi non vede l'oggetto non ne vede la storia, e riceve un 404 (D-052).

    Non un 403: dire "esiste ma non lo puoi vedere" e' gia' dire qualcosa.
    """
    capo = creatore_di_prova(db_session)
    estraneo = crea_utente(db_session, username=f"prova.estr.{uuid.uuid4().hex[:8]}")

    _prodotto, versione = crea_prodotto(db_session, autore=capo)
    progetto = crea_progetto(db_session, versione, project_manager=capo, autore=capo)
    documento, _v = crea_documento(db_session, progetto, capo)

    entra(client, estraneo.username, PASSWORD_DI_PROVA)

    assert client.get(f"/documenti/{documento.id}/storico").status_code == 404


def test_lo_storico_di_una_persona_e_riservato_al_creatore(client, db_session):
    """La scheda di una persona e' materia di amministrazione."""
    capo = creatore_di_prova(db_session)
    normale = crea_utente(db_session, username=f"prova.norm.{uuid.uuid4().hex[:8]}")

    entra(client, normale.username, PASSWORD_DI_PROVA)

    assert client.get(f"/utenti/{capo.id}/storico").status_code == 403


def test_lo_storico_di_un_prodotto_lo_vede_chiunque_sia_entrato(client, db_session):
    """Il catalogo dei prodotti e' il vocabolario comune dell'azienda."""
    capo = creatore_di_prova(db_session)
    prodotto, _versione = crea_prodotto(db_session, autore=capo)
    normale = crea_utente(db_session, username=f"prova.norm.{uuid.uuid4().hex[:8]}")

    entra(client, normale.username, PASSWORD_DI_PROVA)

    assert client.get(f"/prodotti/{prodotto.id}/storico").status_code == 200


# ===========================================================================
#  9. LA MODIFICA DI UN UTENTE DALL'INTERFACCIA
# ===========================================================================


def test_si_modifica_una_persona_dalla_sua_scheda(client, db_session):
    """Il giro completo: si apre la scheda, si salva, la modifica e' registrata."""
    capo = creatore_di_prova(db_session)
    persona = crea_utente(db_session, username=f"prova.mod.{uuid.uuid4().hex[:8]}")
    entra(client, capo.username, PASSWORD_DI_PROVA)

    scheda = client.get(f"/utenti/{persona.id}")
    assert scheda.status_code == 200

    risposta = client.post(
        f"/utenti/{persona.id}",
        data={
            "first_name": "Nome corretto",
            "last_name": persona.last_name,
            "email": persona.email,
            "csrf": _gettone(client, f"/utenti/{persona.id}"),
        },
        follow_redirects=False,
    )

    assert risposta.status_code == 303
    db_session.refresh(persona)
    assert persona.first_name == "Nome corretto"

    voce = unica_voce(db_session, audit.ACTION_USER_UPDATED, persona.id)
    assert voce.user_id == capo.id
    assert voce.new_value == {"first_name": "Nome corretto"}


def test_salvare_senza_cambiare_niente_non_registra_niente(client, db_session):
    """Un registro che segna «modificato» a ogni Salva e' un registro illeggibile."""
    capo = creatore_di_prova(db_session)
    persona = crea_utente(db_session, username=f"prova.mod.{uuid.uuid4().hex[:8]}")
    entra(client, capo.username, PASSWORD_DI_PROVA)

    prima = len(voci_di(db_session, audit.ACTION_USER_UPDATED, persona.id))

    client.post(
        f"/utenti/{persona.id}",
        data={
            "first_name": persona.first_name,
            "last_name": persona.last_name,
            "email": persona.email,
            "csrf": _gettone(client, f"/utenti/{persona.id}"),
        },
        follow_redirects=False,
    )

    assert len(voci_di(db_session, audit.ACTION_USER_UPDATED, persona.id)) == prima


def test_il_nome_utente_non_si_modifica(client, db_session):
    """Nel modulo della scheda non c'e' nessun campo per il nome utente.

    Compare nelle righe del registro di anni e nelle assegnazioni ai progetti:
    cambiarlo renderebbe illeggibile la storia.
    """
    capo = creatore_di_prova(db_session)
    entra(client, capo.username, PASSWORD_DI_PROVA)

    scheda = client.get(f"/utenti/{capo.id}")

    assert 'name="username"' not in scheda.text
    assert 'name="ruolo"' not in scheda.text
