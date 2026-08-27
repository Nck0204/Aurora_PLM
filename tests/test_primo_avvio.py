"""Test della configurazione guidata del primo avvio.

    pytest tests/test_primo_avvio.py -v

**Il criterio di accettazione:** svuoto il database, parte la configurazione
guidata, e mi porta fino a un sistema utilizzabile senza toccare nessun file di
testo.

Un database non lo si puo' svuotare in un test - sarebbe svuotarlo anche a chi
sta lavorando sulla stessa macchina, e la regola 5 di CLAUDE.md dice che dalle
tabelle di Aurora non si cancella niente. Quindi il "database vuoto" si
**simula**, sostituendo la sola risposta che decide tutto:
`setup.sistema_da_configurare()`. E' il perno della procedura, e' una funzione
sola, e sostituendola si prova esattamente il ramo che su un database in uso non
scatterebbe mai. La regola che quella funzione contiene si prova a parte, sul
database vero (vedi la fixture `sistema_vuoto`).

Il resto - i sei passi, la verifica dell'archivio, la creazione delle
classificazioni e delle fasi - si prova sul database vero dentro la transazione
annullata di sempre.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Classification, GlobalRole, PhaseTemplate
from app.routers import setup as rotte_setup
from app.services import diagnostics, initial_data, setup, users
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_utente,
    entra,
    gettone_csrf,
)


# ===========================================================================
#  Aiuti
# ===========================================================================


@pytest.fixture
def sistema_vuoto(monkeypatch):
    """Fa credere ad Aurora che il sistema sia ancora da configurare.

    **Si sostituisce una funzione sola**, `setup.sistema_da_configurare()`, che
    e' il perno da cui dipende tutto: se e' vera la procedura si apre a
    chiunque, se e' falsa pretende un amministratore. La sostituzione vale in
    tutti i punti che la chiamano - la dipendenza della rotta, la pagina di
    accesso, il controllo ripetuto prima di scrivere - perche' e' un modulo
    solo.

    **La regola che quella funzione contiene si prova a parte**, sul database
    vero, in `test_un_sistema_pieno_di_documenti_non_e_da_configurare`: e' la
    divisione fra "che cosa decide" e "che cosa succede quando ha deciso", e
    serve perche' il database di sviluppo e' pieno di documenti e non si
    svuota per fare un test (regola 5 di CLAUDE.md).

    Tutto il resto della procedura - i conteggi, le verifiche, le scritture -
    lavora sul database vero, dentro la transazione annullata di sempre.
    """
    monkeypatch.setattr(setup, "sistema_da_configurare", lambda _db: True)


def creatore(db):
    """Un creatore con un nome utente che non puo' gia' esserci."""
    return crea_utente(
        db,
        username=f"prova.avvio.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )


# ===========================================================================
#  1. QUANDO SI APRE, E QUANDO NON SI APRE
# ===========================================================================


def test_su_un_sistema_in_uso_la_procedura_non_si_apre_a_chi_passa(
    client, db_session
):
    """Il database di sviluppo ha dei documenti: non e' da configurare."""
    risposta = client.get("/primo-avvio", follow_redirects=False)

    assert risposta.status_code == 303
    assert "/entra" in risposta.headers["location"], (
        "chi non e' entrato va mandato all'accesso, non alla procedura"
    )


def test_su_un_sistema_vuoto_la_procedura_si_apre_a_chiunque(
    client, db_session, sistema_vuoto
):
    """Non c'e' nessuno a cui chiedere il permesso: e' il primo avvio."""
    risposta = client.get("/primo-avvio")

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert "Benvenuto" in testo


def test_la_pagina_di_accesso_manda_alla_procedura_se_il_sistema_e_vuoto(
    client, db_session, sistema_vuoto
):
    """E' il punto in cui la sessione 12 si innesta sul resto del programma.

    Chi apre qualunque pagina di un'Aurora vuota finisce sull'accesso, perche'
    tutte le rotte protette rimandano li'. Da li' si viene mandati avanti.
    """
    risposta = client.get("/entra", follow_redirects=False)

    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/primo-avvio"


def test_su_un_sistema_gia_configurato_serve_essere_creatore(client, db_session):
    """Chi e' entrato ma non amministra riceve un 403 con la spiegazione."""
    utente = crea_utente(
        db_session, username=f"prova.normale.{uuid.uuid4().hex[:8]}"
    )
    entra(client, utente.username, PASSWORD_DI_PROVA)

    risposta = client.get("/primo-avvio")
    assert risposta.status_code == 403
    assert "gia' configurata" in contenuto_leggibile(risposta)


def test_il_creatore_puo_rivedere_la_procedura(client, db_session):
    """Serve a rileggere che cosa c'e' e che cosa manca, anche dopo mesi."""
    entra(client, creatore(db_session).username, PASSWORD_DI_PROVA)

    risposta = client.get("/primo-avvio")
    assert risposta.status_code == 200


def test_un_sistema_pieno_di_documenti_non_e_da_configurare(db_session, monkeypatch):
    """Anche senza nessun amministratore attivo.

    E' la seconda condizione di `sistema_da_configurare`, e sembra ridondante
    finche' non si pensa a che cosa succederebbe senza: un sistema in uso da
    due anni in cui qualcuno ha disattivato per sbaglio l'ultimo
    amministratore riaprirebbe a chiunque arrivi al server una pagina che crea
    amministratori senza chiedere credenziali.
    """
    monkeypatch.setattr(setup.users, "esiste_un_creatore", lambda _db: False)

    from app.models import Document

    documenti = db_session.scalar(select(func.count()).select_from(Document)) or 0
    if documenti == 0:
        pytest.skip("il database di sviluppo non ha documenti: caso non provabile")

    assert setup.sistema_da_configurare(db_session) is False, (
        "un sistema con dei documenti dentro non e' un sistema da configurare, "
        "e' un sistema rotto: la procedura guidata deve restare chiusa"
    )


# ===========================================================================
#  2. I SEI PASSI E LO STATO CHE SI RICAVA
# ===========================================================================


def test_i_passi_sono_sei_e_in_quest_ordine(db_session):
    """L'ordine non e' modificabile e non deve esserlo."""
    passi = setup.stato_dei_passi(db_session)

    assert [passo.chiave for passo in passi] == [
        "database",
        "creator",
        "storage",
        "classifications",
        "phases",
        "mail",
    ]
    assert [passo.numero for passo in passi] == [1, 2, 3, 4, 5, 6]


def test_solo_la_posta_e_rimandabile(db_session):
    """Gli altri cinque servono per avere un sistema utilizzabile."""
    passi = setup.stato_dei_passi(db_session)

    rimandabili = [passo.chiave for passo in passi if passo.rimandabile]
    assert rimandabili == ["mail"]


def test_ogni_passo_spiega_a_che_cosa_serve(db_session):
    """La spiegazione e' la parte che rende la procedura una guida.

    Un modulo lungo con sei campi lo compila chi sa gia' che cosa sta facendo.
    Questa procedura la apre chi non lo sa.
    """
    for passo in setup.stato_dei_passi(db_session):
        assert len(passo.perche) > 120, (
            f"il passo «{passo.chiave}» non spiega abbastanza: sono "
            f"{len(passo.perche)} caratteri"
        )


def test_lo_stato_dei_passi_si_ricava_e_non_si_salva(db_session):
    """E' quello che rende la procedura interrompibile senza scriverlo.

    Le classificazioni e le fasi ci sono gia' sul database di sviluppo, quindi
    i loro passi devono risultare fatti senza che nessuno l'abbia mai
    annotato da nessuna parte.
    """
    passi = {passo.chiave: passo for passo in setup.stato_dei_passi(db_session)}

    assert passi["database"].fatto, "il database c'e': il passo 1 e' fatto"
    assert passi["classifications"].fatto, "le classificazioni ci sono"
    assert passi["phases"].fatto, "il modello di fasi c'e'"


def test_un_passo_che_non_esiste_risponde_404(client, db_session):
    """L'indirizzo di un passo inventato e' un indirizzo che non esiste."""
    entra(client, creatore(db_session).username, PASSWORD_DI_PROVA)

    assert client.get("/primo-avvio/inventato").status_code == 404


# ===========================================================================
#  3. LE VERIFICHE
# ===========================================================================


def test_la_verifica_del_database_e_verde_quando_le_tabelle_ci_sono(db_session):
    """Il caso normale."""
    esito = setup.prova_database(db_session)

    assert esito.colore == diagnostics.VERDE
    assert esito.a_posto


def test_la_verifica_del_database_non_mostra_la_password(db_session):
    """Chi guarda deve sapere a quale server si collega, non la password."""
    esito = setup.prova_database(db_session)

    collegamento = dict(esito.dettagli).get("Collegamento", "")
    assert "***" in collegamento, "la password va nascosta"
    assert "@" in collegamento, "il server invece va detto: sbagliarlo e' facile"


def test_la_verifica_dell_archivio_prova_a_scrivere_davvero(tmp_path):
    """Non basta guardare i permessi: su Windows l'unica prova e' scrivere."""
    cartella = tmp_path / "archivio-di-prova"

    esito = setup.prova_archivio(str(cartella))

    assert esito.colore == diagnostics.VERDE
    assert cartella.is_dir(), "la cartella va creata se non c'e'"
    assert not (cartella / setup.FILE_DI_PROVA).exists(), (
        "il file di prova non deve restare li' a confondere chi guarda"
    )


def test_un_percorso_vuoto_non_va_bene():
    """Con l'istruzione che dice che cosa scrivere."""
    esito = setup.prova_archivio("")

    assert esito.colore == diagnostics.ROSSO
    assert esito.che_fare


def test_una_cartella_che_non_si_crea_lo_dice_in_italiano(tmp_path):
    """Un file al posto di una cartella: il caso piu' facile da provocare."""
    ostacolo = tmp_path / "sono-un-file"
    ostacolo.write_bytes(b"non sono una cartella")

    esito = setup.prova_archivio(str(ostacolo / "dentro"))

    assert esito.colore == diagnostics.ROSSO
    assert "permesso" in esito.che_fare.lower() or "disco" in esito.che_fare.lower()


def test_ogni_verifica_non_verde_dice_che_cosa_fare(db_session):
    """La stessa regola della diagnostica, applicata ai passi."""
    for chiave in (
        setup.PASSO_DATABASE,
        setup.PASSO_CREATORE,
        setup.PASSO_CLASSIFICAZIONI,
        setup.PASSO_FASI,
        setup.PASSO_POSTA,
    ):
        esito = setup.prova_passo(db_session, chiave)
        if esito.colore != diagnostics.VERDE:
            assert esito.che_fare.strip(), (
                f"la verifica del passo «{chiave}» non e' verde e non dice "
                "che cosa fare"
            )


# ===========================================================================
#  4. IL PRIMO CREATORE
# ===========================================================================


def test_si_crea_il_primo_creatore_e_si_entra_subito(
    client, db_session, sistema_vuoto
):
    """Il passo che rende la procedura continua.

    Senza l'accesso automatico, chi ha appena creato il proprio profilo si
    troverebbe davanti la pagina di accesso e dovrebbe riscrivere quello che
    ha appena scritto.
    """
    gettone = gettone_csrf(client, "/primo-avvio/creator")
    cognome = f"Diprova{uuid.uuid4().hex[:8]}"
    posta = f"{uuid.uuid4().hex[:10]}@esempio.local"

    risposta = client.post(
        "/primo-avvio/creator",
        data={
            "nome": "Giulia",
            "cognome": cognome,
            "email": posta,
            "username": "",
            "password": "una-password-lunga-abbastanza",
            "password_ripetuta": "una-password-lunga-abbastanza",
            "csrf": gettone,
        },
        follow_redirects=False,
    )

    assert risposta.status_code == 303
    assert "/primo-avvio/storage" in risposta.headers["location"]

    from app.models import User

    creato = db_session.scalars(
        select(User).where(User.email == posta)
    ).first()
    assert creato is not None, "l'utente non e' stato scritto"
    assert creato.is_active
    assert not creato.must_change_password, (
        "la password l'ha scelta l'interessato: non c'e' niente da cambiare"
    )
    assert creato.username == f"giulia.{cognome.lower()}"


def test_la_password_troppo_corta_viene_rifiutata(client, db_session, sistema_vuoto):
    """Con la stessa lunghezza minima dell'accesso normale."""
    gettone = gettone_csrf(client, "/primo-avvio/creator")

    risposta = client.post(
        "/primo-avvio/creator",
        data={
            "nome": "Marco",
            "cognome": f"Diprova{uuid.uuid4().hex[:8]}",
            "email": f"{uuid.uuid4().hex[:10]}@esempio.local",
            "username": "",
            "password": "corta",
            "password_ripetuta": "corta",
            "csrf": gettone,
        },
    )

    assert risposta.status_code == 400
    assert "almeno" in contenuto_leggibile(risposta)


def test_due_password_diverse_vengono_rifiutate(client, db_session, sistema_vuoto):
    """Il campo ripetuto serve a questo."""
    gettone = gettone_csrf(client, "/primo-avvio/creator")

    risposta = client.post(
        "/primo-avvio/creator",
        data={
            "nome": "Marco",
            "cognome": f"Diprova{uuid.uuid4().hex[:8]}",
            "email": f"{uuid.uuid4().hex[:10]}@esempio.local",
            "username": "",
            "password": "una-password-lunga-abbastanza",
            "password_ripetuta": "un-altra-password-lunga",
            "csrf": gettone,
        },
    )

    assert risposta.status_code == 400
    assert "non coincidono" in contenuto_leggibile(risposta)


def test_su_un_sistema_gia_configurato_non_si_crea_un_secondo_creatore(
    client, db_session
):
    """La porta e' chiusa anche a chi conosce l'indirizzo del modulo."""
    utente = creatore(db_session)
    entra(client, utente.username, PASSWORD_DI_PROVA)
    gettone = gettone_csrf(client, "/primo-avvio/creator")

    risposta = client.post(
        "/primo-avvio/creator",
        data={
            "nome": "Intruso",
            "cognome": f"Diprova{uuid.uuid4().hex[:8]}",
            "email": f"{uuid.uuid4().hex[:10]}@esempio.local",
            "username": "",
            "password": "una-password-lunga-abbastanza",
            "password_ripetuta": "una-password-lunga-abbastanza",
            "csrf": gettone,
        },
    )

    assert risposta.status_code == 403


def test_il_primo_creatore_lascia_la_sua_riga_nel_registro(db_session, sistema_vuoto):
    """Senza autore, come le voci scritte dal programma all'avvio.

    Inventare una persona sarebbe la peggiore delle bugie da mettere in un
    audit trail: al primo avvio non c'e' nessuno.
    """
    from app.models import AuditLog

    creato = users.crea_primo_creatore(
        db_session,
        first_name="Anna",
        last_name=f"Diprova{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:10]}@esempio.local",
        username=f"prova.primo.{uuid.uuid4().hex[:8]}",
        password="una-password-lunga-abbastanza",
    )
    db_session.flush()

    voce = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_id == creato.id)
        .order_by(AuditLog.seq.desc())
        .limit(1)
    ).first()

    assert voce is not None, "la creazione non e' stata registrata"
    assert voce.user_id is None, "al primo avvio non c'e' nessun autore"
    assert "configurazione guidata" in voce.description


# ===========================================================================
#  5. I DATI INIZIALI
# ===========================================================================


def test_i_dati_iniziali_si_leggono_dal_file_di_configurazione():
    """Il file c'e', si legge, e contiene quello che deve contenere.

    Prima della sessione 12 questi elenchi erano scritti dentro
    `scripts/seed.py` **e** dentro il servizio del primo avvio, e bastava
    correggerne uno perche' due installazioni dessero due sistemi diversi.
    Adesso il posto e' uno solo, e i due lo leggono.
    """
    letti = initial_data.ricarica()

    assert letti.leggibili, f"i dati iniziali non si leggono: {letti.problema}"
    assert letti.classificazioni, "mancano le classificazioni"
    assert letti.fasi, "manca il percorso delle fasi"
    assert letti.modello_fasi, "il percorso non ha un nome"


def test_la_griglia_di_partenza_ha_tutte_le_caselle():
    """Tre ruoli per ogni classificazione, senza buchi.

    Una casella che dice "no" e' una decisione, una casella che manca e' una
    dimenticanza, e a distanza di mesi non si distinguono piu'.
    """
    from app.models import ProjectRole

    letti = initial_data.ricarica()
    caselle = letti.caselle()

    attese = {
        (ruolo.value, classe.nome)
        for ruolo in ProjectRole
        for classe in letti.classificazioni
    }
    mancanti = attese - set(caselle)

    assert mancanti == set(), f"nella griglia di partenza mancano: {mancanti}"


def test_le_tre_regole_chieste_dall_azienda_sono_nella_griglia():
    """L'ingegnere non vede il Commerciale; il lettore vede solo il Tecnico.

    Sono le tre regole che l'azienda ha chiesto espressamente. Il resto della
    griglia e' la scelta ragionevole che ne discende e si corregge
    dall'interfaccia; queste tre no, e vanno verificate.
    """
    caselle = initial_data.ricarica().caselle()

    assert caselle[("ingegnere", "Commerciale")] == (False, False, False)
    assert caselle[("lettore", "Tecnico")] == (True, False, False)
    assert caselle[("lettore", "Commerciale")] == (False, False, False)
    assert all(caselle[("project_manager", classe)] == (True, True, True)
               for classe in ("Tecnico", "Commerciale", "Qualità"))


def test_il_percorso_di_partenza_ha_le_due_proprieta_che_contano():
    """Una fase che blocca il ritorno e una che chiude il progetto.

    Sono le sole due cose che il programma sappia di una fase (D-055). Un
    percorso senza nessuna delle due sarebbe un percorso da cui si puo' sempre
    tornare indietro e che non finisce mai.
    """
    fasi = initial_data.ricarica().fasi

    assert sum(1 for fase in fasi if fase.blocca_ritorno) == 1
    assert sum(1 for fase in fasi if fase.chiude_progetto) == 1
    assert fasi[-1].chiude_progetto, "l'ultima fase deve chiudere il progetto"


def test_nessun_nome_di_fase_e_scritto_dentro_il_programma():
    """La ragione principale per cui i dati iniziali stanno in un file.

    C'e' gia' un test in tests/test_fasi.py che lo verifica leggendo tutti i
    sorgenti; questo lo dice dal punto di vista opposto - i nomi stanno nel
    file di configurazione - cosi' chi legge questo file capisce perche' quel
    file esiste.
    """
    import pathlib

    radice = pathlib.Path(__file__).resolve().parent.parent
    sorgente_setup = (radice / "app" / "services" / "setup.py").read_text(
        encoding="utf-8"
    )

    for fase in initial_data.ricarica().fasi:
        assert fase.nome not in sorgente_setup, (
            f"il nome della fase «{fase.nome}» e' scritto dentro "
            "app/services/setup.py: le fasi sono dati e stanno in "
            "config/dati_iniziali.toml"
        )


def test_seed_e_il_primo_avvio_leggono_lo_stesso_file():
    """Un test che legge i sorgenti: due strade, un file solo.

    Se un giorno qualcuno riscrivesse gli elenchi dentro `scripts/seed.py`
    "per non dipendere da un file", questo test lo direbbe subito.
    """
    import pathlib

    radice = pathlib.Path(__file__).resolve().parent.parent
    sorgente_seed = (radice / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "initial_data" in sorgente_seed, (
        "scripts/seed.py deve leggere config/dati_iniziali.toml, non avere "
        "elenchi propri"
    )
    for fase in initial_data.ricarica().fasi:
        assert fase.nome not in sorgente_seed, (
            f"il nome della fase «{fase.nome}» e' tornato dentro seed.py"
        )


def test_creare_le_classificazioni_e_ripetibile(db_session):
    """Sul database di sviluppo ci sono gia': non se ne creano di doppie."""
    autore = creatore(db_session)

    prima = db_session.scalar(select(func.count()).select_from(Classification)) or 0
    create = setup.crea_classificazioni_di_partenza(db_session, autore=autore)
    db_session.flush()
    dopo = db_session.scalar(select(func.count()).select_from(Classification)) or 0

    assert dopo == prima + len(create)
    if not create:
        assert dopo == prima, "c'erano gia' tutte: non doveva cambiare niente"


def test_creare_il_percorso_di_partenza_e_ripetibile(db_session):
    """Se «Standard» c'e' gia', non se ne crea un secondo."""
    autore = creatore(db_session)

    prima = db_session.scalar(select(func.count()).select_from(PhaseTemplate)) or 0
    modello = setup.crea_percorso_di_partenza(db_session, autore=autore)
    db_session.flush()
    dopo = db_session.scalar(select(func.count()).select_from(PhaseTemplate)) or 0

    if modello is None:
        assert dopo == prima
    else:
        assert dopo == prima + 1
        assert modello.name == setup.MODELLO_DI_PARTENZA


# ===========================================================================
#  6. LA PROCEDURA FUNZIONA SENZA JAVASCRIPT
# ===========================================================================


def test_ogni_pagina_dei_passi_si_apre_e_ha_i_suoi_moduli(
    client: TestClient, db_session
):
    """Sei pagine, sei moduli con il loro gettone. Nessuno script."""
    entra(client, creatore(db_session).username, PASSWORD_DI_PROVA)

    for passo in setup.stato_dei_passi(db_session):
        risposta = client.get(f"/primo-avvio/{passo.chiave}")
        assert risposta.status_code == 200, f"il passo «{passo.chiave}» non si apre"

        testo = risposta.text
        assert '<form method="post"' in testo, (
            f"il passo «{passo.chiave}» non ha nessun modulo"
        )
        assert 'name="csrf"' in testo, (
            f"il modulo del passo «{passo.chiave}» non porta il gettone"
        )


def test_i_pulsanti_di_verifica_non_sono_script(client, db_session):
    """Sono normali pulsanti di invio. Senza JavaScript funziona tutto.

    E' la regola D-036 applicata dove conta di piu': un primo avvio che avesse
    bisogno di uno script non si completerebbe su un server con un browser
    severo, che e' esattamente la macchina su cui si fa un primo avvio.
    """
    entra(client, creatore(db_session).username, PASSWORD_DI_PROVA)

    testo = client.get("/primo-avvio/database").text
    assert "hx-post" not in testo, (
        "la configurazione guidata non usa HTMX: deve funzionare da sola"
    )


def test_la_verifica_non_cambia_niente(client, db_session):
    """Si puo' premere Verifica quante volte si vuole senza paura."""
    entra(client, creatore(db_session).username, PASSWORD_DI_PROVA)

    prima = db_session.scalar(select(func.count()).select_from(Classification)) or 0

    gettone = gettone_csrf(client, "/primo-avvio/classifications")
    risposta = client.post(
        "/primo-avvio/classifications/verifica", data={"csrf": gettone}
    )

    assert risposta.status_code == 200
    dopo = db_session.scalar(select(func.count()).select_from(Classification)) or 0
    assert dopo == prima, "la verifica ha scritto qualcosa: non deve"


def test_il_messaggio_di_porta_chiusa_non_dice_troppo(client, db_session):
    """A un estraneo non si dice "il sistema e' gia' configurato" e basta.

    Gli si dice che serve entrare, che e' l'informazione utile e non ne
    regala nessuna.
    """
    assert "entrare" in rotte_setup.MESSAGGIO_GIA_CONFIGURATO
