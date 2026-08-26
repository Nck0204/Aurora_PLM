"""Test delle fasi di progetto: i modelli, l'avanzamento, il ritorno, la chiusura.

I quattro criteri di accettazione della sessione 8 sono verificati qui:

  1. creo un modello di fasi nuovo con fasi diverse, lo assegno a un progetto
     nuovo, e i progetti esistenti restano invariati;
  2. un ingegnere richiede l'avanzamento, il project manager lo vede nel
     cruscotto e lo approva: la fase cambia e lo storico riporta entrambi i
     nomi;
  3. un tentativo di tornare indietro da una fase che blocca viene rifiutato
     con il messaggio corretto e il collegamento alla creazione di versione;
  4. le regole di autorizzazione.

C'e' anche un test che non guarda il comportamento ma **i sorgenti**, ed e' il
piu' importante del file: verifica che da nessuna parte del programma ci sia un
confronto fra il nome di una fase e una stringa scritta a mano. E' il principio
vincolante della sessione - le fasi sono dati, non codice - e i principi senza
un test durano fino alla prossima fretta.

    pytest tests/test_fasi.py -v
"""

import ast
import pathlib
import re
import uuid

from app.models import GlobalRole, PhaseTransitionState
from app.services import permissions, phases
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_modello_di_fasi,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
)

MODIFICARE = permissions.Azione.MODIFICARE
RICHIEDERE = permissions.Azione.RICHIEDERE
VEDERE = permissions.Azione.VEDERE
CARICARE = permissions.Azione.CARICARE


def coda(prefisso: str) -> str:
    """Un nome utente che nel database non puo' gia' esserci.

    I test di questo file ne creano parecchi e girano sul database di
    sviluppo, dove ci sono anche gli utenti veri lasciati dalle verifiche a
    mano: due punti nel nome e una coda casuale sono la stessa medicina di
    cognome_irripetibile() in conftest.
    """
    return f"prova.{prefisso}.{uuid.uuid4().hex[:8]}"


def squadra_di_prova(db, *, fasi=None):
    """Un progetto con il suo responsabile, un ingegnere e un estraneo.

    Restituisce (progetto, creatore, responsabile, ingegnere, estraneo). E'
    l'apparecchiatura che serve a quasi tutti i test di questo file, e sta in
    una funzione perche' cinque copie della stessa preparazione divergono alla
    prima aggiunta.

    Il modello di fasi e' quello di prova, con le sue quattro fasi: i test
    devono sapere quale blocca il ritorno e quale chiude il progetto.
    """
    creatore = crea_utente(db, username=coda("capo"), ruolo=GlobalRole.CREATORE)
    responsabile = crea_utente(db, username=coda("pm"))
    ingegnere = crea_utente(db, username=coda("ing"))
    estraneo = crea_utente(db, username=coda("estraneo"))

    _prodotto, versione = crea_prodotto(db, autore=creatore)

    modello = (
        crea_modello_di_fasi(db, fasi=fasi)
        if fasi is not None
        else crea_modello_di_fasi(db)
    )

    progetto = crea_progetto(
        db,
        versione,
        project_manager=responsabile,
        autore=creatore,
        squadra=[ingegnere],
        modello=modello,
    )
    db.flush()

    return progetto, creatore, responsabile, ingegnere, estraneo


def nomi_delle_fasi(db, progetto) -> list[str]:
    """I nomi delle fasi del percorso di un progetto, in ordine."""
    return [fase.name for fase in phases.fasi_del_progetto(db, progetto)]


# ===========================================================================
#  1. LE FASI SONO DATI, NON CODICE
# ===========================================================================

# I nomi delle fasi del modello "Standard" di scripts/seed.py. Compaiono qui
# perche' e' un test che li cerca nei sorgenti: sono l'elenco di quello che
# **non** deve comparire dentro il programma.
NOMI_DELLE_FASI_VERE = (
    "Idea screening",
    "Concept",
    "Feasibility",
    "Quoted",
    "Development",
    "Chiuso",
)

RADICE = pathlib.Path(__file__).resolve().parent.parent / "app"


def test_nessun_file_del_programma_confronta_il_nome_di_una_fase(db_session):
    """**Il test piu' importante di questa sessione.**

    Le fasi sono dati: aggiungerne una, rinominarla o riordinarla non deve
    costare una riga di programma. Il modo in cui questo principio si perde e'
    sempre lo stesso - qualcuno, di fretta, scrive `if fase.name ==
    "Development"` - e da quel momento rinominare una fase e' una modifica al
    codice.

    Quello che il programma guarda sono le **proprieta'** della fase
    (`blocks_return`, `closes_project`), che stanno nel database e le mette
    chi crea il modello. I nomi veri delle fasi dell'azienda compaiono in due
    posti soli, e tutti e due sono dati: `scripts/seed.py`, che li scrive, e
    la migrazione che ha tradotto in spunte la regola di prima.

    Il test guarda le **stringhe che il programma usa**, non i commenti e non
    le docstring: la docstring di `app/models/phase.py` nomina "Concept" e
    "Development" come esempi, ed e' giusto cosi'. Per distinguerle si legge
    l'albero sintattico invece del testo, che e' anche l'unico modo di non
    inciampare in una parola che compare dentro una frase.
    """
    colpevoli = []

    for percorso in RADICE.rglob("*.py"):
        if "__pycache__" in percorso.parts:
            continue

        albero = ast.parse(percorso.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                continue
            if nodo.value in NOMI_DELLE_FASI_VERE and not _e_una_docstring(
                albero, nodo
            ):
                colpevoli.append((percorso.relative_to(RADICE.parent), nodo.value))

    assert colpevoli == [], (
        f"questi file nominano una fase per nome: {colpevoli}. Il programma "
        "non deve sapere come si chiamano le fasi: quello che guarda sono le "
        "proprieta' blocks_return e closes_project, che stanno nel database"
    )


def _docstring_di(albero: ast.AST) -> set[int]:
    """Gli identificatori delle costanti che sono docstring, non valori.

    Una docstring, per Python, e' una stringa scritta da sola come prima
    istruzione di un modulo, di una classe o di una funzione: nell'albero e'
    un `Expr` che contiene una `Constant`. Si riconoscono cosi', e non
    cercando le virgolette triple, perche' una docstring puo' essere scritta
    anche su una riga sola.
    """
    docstring = set()
    for nodo in ast.walk(albero):
        corpo = getattr(nodo, "body", None)
        if not isinstance(corpo, list):
            continue
        for istruzione in corpo:
            if isinstance(istruzione, ast.Expr) and isinstance(
                istruzione.value, ast.Constant
            ):
                docstring.add(id(istruzione.value))
    return docstring


def _e_una_docstring(albero: ast.AST, nodo: ast.Constant) -> bool:
    """Dice se quella costante e' una docstring o un commento scritto a parte."""
    return id(nodo) in _docstring_di(albero)


def test_nessun_template_confronta_il_nome_di_una_fase(db_session):
    """La stessa regola dalla parte delle pagine.

    Un `{% if fase.name == "..." %}` dentro un template e' peggio dello stesso
    confronto in Python, perche' non lo trova nemmeno chi cerca nel codice.
    Le pagine ricevono le proprieta' gia' pronte e le usano per decidere che
    cosa scrivere.
    """
    confronto = re.compile(r"\.name\s*(==|!=)")

    colpevoli = []
    for percorso in (RADICE / "templates").rglob("*.html"):
        testo = percorso.read_text(encoding="utf-8")
        if confronto.search(testo):
            colpevoli.append(percorso.relative_to(RADICE.parent))

    assert colpevoli == [], (
        f"questi template confrontano un nome: {colpevoli}. Una regola scritta "
        "dentro l'HTML non si prova con un test e non si riusa"
    )


def test_le_proprieta_di_una_fase_stanno_nel_dato(db_session):
    """Il percorso di prova ha una fase che blocca e una che chiude."""
    modello = crea_modello_di_fasi(db_session)
    fasi = phases.fasi_del_modello(db_session, modello.id)

    assert [fase.blocks_return for fase in fasi] == [False, False, True, False]
    assert [fase.closes_project for fase in fasi] == [False, False, False, True]


# ===========================================================================
#  2. I MODELLI: IMMUTABILI, VERSIONATI, CONTATI
# ===========================================================================


def test_un_modello_nuovo_non_tocca_i_progetti_gia_aperti(db_session):
    """**Primo criterio di accettazione.**

    Creo un modello con fasi diverse, ci apro sopra un progetto nuovo, e il
    progetto che c'era prima continua per la sua strada: stesse fasi, stessa
    fase corrente, stesso modello.
    """
    vecchio, creatore, _pm, _ing, _estraneo = squadra_di_prova(db_session)
    fasi_di_prima = nomi_delle_fasi(db_session, vecchio)
    modello_di_prima = vecchio.phase_template_id
    fase_di_prima = vecchio.current_phase_id

    # Un percorso completamente diverso: altri nomi, altro numero di fasi.
    altro = crea_modello_di_fasi(
        db_session,
        fasi=(
            ("Raccolta requisiti", False, False),
            ("Prototipo", False, False),
            ("Collaudo", True, False),
            ("Archiviato", False, True),
        ),
    )

    responsabile = crea_utente(db_session, username=coda("pm2"))
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    nuovo = crea_progetto(
        db_session,
        versione,
        project_manager=responsabile,
        autore=creatore,
        modello=altro,
    )
    db_session.flush()

    assert nomi_delle_fasi(db_session, nuovo)[0] == "Raccolta requisiti"
    assert nuovo.current_phase.name == "Raccolta requisiti"

    db_session.refresh(vecchio)
    assert vecchio.phase_template_id == modello_di_prima
    assert vecchio.current_phase_id == fase_di_prima
    assert nomi_delle_fasi(db_session, vecchio) == fasi_di_prima


def test_correggere_un_modello_ne_crea_una_versione_nuova(db_session):
    """I modelli non si modificano: se ne scrive la versione successiva.

    Quella di partenza resta identica - stesse fasi, stesso numero di versione
    - e smette soltanto di essere proponibile per i progetti nuovi (D-016).
    """
    creatore = crea_utente(db_session, username=coda("capo"), ruolo=GlobalRole.CREATORE)
    partenza = crea_modello_di_fasi(db_session)
    fasi_di_partenza = [
        fase.name for fase in phases.fasi_del_modello(db_session, partenza.id)
    ]

    nuova = phases.nuova_versione(
        db_session,
        partenza=partenza,
        descrizione="Con una fase in piu'.",
        norme=["EN 50155", "ISO 9001"],
        fasi=[
            phases.FaseScritta(nome="Studio"),
            phases.FaseScritta(nome="Offerta"),
            phases.FaseScritta(nome="Riesame"),
            phases.FaseScritta(nome="Costruzione", blocca_ritorno=True),
            phases.FaseScritta(nome="Consegnato", chiude_progetto=True),
        ],
        autore=creatore,
    )
    db_session.flush()

    assert nuova.version == partenza.version + 1
    assert nuova.name == partenza.name
    assert nuova.id != partenza.id

    # Quella di prima e' intatta.
    db_session.refresh(partenza)
    assert [
        fase.name for fase in phases.fasi_del_modello(db_session, partenza.id)
    ] == fasi_di_partenza
    assert partenza.is_active is False, "la vecchia non si propone piu'"

    # Quella nuova ha le fasi nuove, numerate in ordine.
    fasi_nuove = phases.fasi_del_modello(db_session, nuova.id)
    assert [fase.name for fase in fasi_nuove] == [
        "Studio",
        "Offerta",
        "Riesame",
        "Costruzione",
        "Consegnato",
    ]
    assert [fase.sort_order for fase in fasi_nuove] == [1, 2, 3, 4, 5]


def test_l_elenco_dice_quanti_progetti_usano_ciascuna_versione(db_session):
    """Il numero che rende leggibile la pagina dei modelli."""
    progetto, creatore, _pm, _ing, _estraneo = squadra_di_prova(db_session)

    usi = phases.progetti_per_modello(db_session)
    assert usi.get(progetto.phase_template_id) == 1

    # Un secondo progetto sullo stesso modello.
    altro_pm = crea_utente(db_session, username=coda("pm3"))
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    crea_progetto(
        db_session,
        versione,
        project_manager=altro_pm,
        autore=creatore,
        modello=progetto.phase_template,
    )
    db_session.flush()

    usi = phases.progetti_per_modello(db_session)
    assert usi.get(progetto.phase_template_id) == 2


def test_un_modello_senza_fase_che_chiude_viene_rifiutato(client, db_session):
    """Senza una fase che chiude, un progetto non si chiuderebbe mai."""
    crea_utente(db_session, username="prova.capo.modelli", ruolo=GlobalRole.CREATORE)
    db_session.flush()
    entra(client, "prova.capo.modelli", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/fasi/nuovo",
        data={
            "nome_modello": f"Senza chiusura {uuid.uuid4().hex[:6]}",
            "descrizione": "",
            "norme": "",
            "fase_nome": ["Prima", "Seconda"],
            "fase_descrizione": ["", ""],
            "csrf": gettone_csrf(client, "/fasi/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "quale fase chiude il progetto" in contenuto_leggibile(risposta)


def test_due_fasi_con_lo_stesso_nome_vengono_rifiutate(client, db_session):
    """Nello storico di un progetto due fasi omonime non si distinguerebbero."""
    crea_utente(db_session, username="prova.capo.omonime", ruolo=GlobalRole.CREATORE)
    db_session.flush()
    entra(client, "prova.capo.omonime", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/fasi/nuovo",
        data={
            "nome_modello": f"Omonime {uuid.uuid4().hex[:6]}",
            "descrizione": "",
            "norme": "",
            "fase_nome": ["Studio", "Studio"],
            "fase_descrizione": ["", ""],
            "fase_chiude_1": "si",
            "csrf": gettone_csrf(client, "/fasi/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "chiamarsi allo stesso modo" in contenuto_leggibile(risposta)


def test_la_fase_che_chiude_deve_essere_l_ultima(client, db_session):
    """Una fase dopo quella che chiude non si raggiungerebbe mai.

    Il progetto si e' chiuso entrando nella penultima, e un progetto chiuso
    non avanza piu': l'ultima resterebbe li' senza che nessuno ci passi. E'
    stato trovato nella verifica a mano, costruendo un modello con la spunta
    sulla terza fase di quattro.
    """
    crea_utente(db_session, username="prova.capo.ordine", ruolo=GlobalRole.CREATORE)
    db_session.flush()
    entra(client, "prova.capo.ordine", PASSWORD_DI_PROVA)

    risposta = client.post(
        "/fasi/nuovo",
        data={
            "nome_modello": f"Chiusura in mezzo {uuid.uuid4().hex[:6]}",
            "descrizione": "",
            "norme": "",
            "fase_nome": ["Prima", "Seconda", "Terza"],
            "fase_descrizione": ["", "", ""],
            # La spunta e' sulla seconda di tre.
            "fase_chiude_1": "si",
            "csrf": gettone_csrf(client, "/fasi/nuovo"),
        },
    )

    assert risposta.status_code == 400
    assert "non e' l'ultima fase" in contenuto_leggibile(risposta)


def test_si_crea_un_modello_dall_interfaccia(client, db_session):
    """Il giro completo dal modulo, spunte comprese."""
    crea_utente(db_session, username="prova.capo.creamod", ruolo=GlobalRole.CREATORE)
    db_session.flush()
    entra(client, "prova.capo.creamod", PASSWORD_DI_PROVA)

    nome = f"Percorso {uuid.uuid4().hex[:8]}"
    risposta = client.post(
        "/fasi/nuovo",
        data={
            "nome_modello": nome,
            "descrizione": "Creato da un test.",
            "norme": "EN 50155\nISO 9001",
            # Tre righe piene e una vuota in mezzo: le vuote si saltano, e il
            # numero della spunta e' quello della **riga del modulo**.
            "fase_nome": ["Avvio", "", "Lavorazione", "Fine"],
            "fase_descrizione": ["", "", "", ""],
            "fase_blocca_2": "si",
            "fase_chiude_3": "si",
            "csrf": gettone_csrf(client, "/fasi/nuovo"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200

    modelli = [
        modello
        for modello in phases.modelli_di_fasi(db_session, comprese_disattivate=True)
        if modello.name == nome
    ]
    assert len(modelli) == 1

    fasi = phases.fasi_del_modello(db_session, modelli[0].id)
    assert [fase.name for fase in fasi] == ["Avvio", "Lavorazione", "Fine"]
    assert [fase.sort_order for fase in fasi] == [1, 2, 3]
    assert [fase.blocks_return for fase in fasi] == [False, True, False]
    assert [fase.closes_project for fase in fasi] == [False, False, True]
    assert modelli[0].standards == ["EN 50155", "ISO 9001"]


def test_solo_il_creatore_amministra_i_modelli(client, db_session):
    """Le fasi sono anagrafica: le governa chi amministra Aurora."""
    crea_utente(db_session, username="prova.ing.modelli")
    db_session.flush()
    entra(client, "prova.ing.modelli", PASSWORD_DI_PROVA)

    for indirizzo in ("/fasi", "/fasi/nuovo"):
        risposta = client.get(indirizzo)
        assert risposta.status_code == 403, indirizzo


# ===========================================================================
#  3. L'AVANZAMENTO: CHI AVANZA, CHI CHIEDE
# ===========================================================================


def test_chi_puo_avanzare_e_chi_puo_soltanto_chiedere(db_session):
    """Le regole di autorizzazione, chieste alla funzione che le decide."""
    progetto, creatore, responsabile, ingegnere, estraneo = squadra_di_prova(
        db_session
    )

    # Avanzare, tornare indietro, decidere: il responsabile e il creatore.
    assert permissions.puo(db_session, creatore, MODIFICARE, progetto)
    assert permissions.puo(db_session, responsabile, MODIFICARE, progetto)
    assert not permissions.puo(db_session, ingegnere, MODIFICARE, progetto)
    assert not permissions.puo(db_session, estraneo, MODIFICARE, progetto)

    # Chiedere: chi e' nella squadra ma non la governa.
    assert permissions.puo(db_session, ingegnere, RICHIEDERE, progetto)
    assert not permissions.puo(db_session, estraneo, RICHIEDERE, progetto)
    assert not permissions.puo(db_session, responsabile, RICHIEDERE, progetto), (
        "chi governa il progetto non chiede: fa"
    )


def test_il_project_manager_avanza_direttamente(db_session):
    """Un passaggio diretto: chi chiede e chi decide sono la stessa persona."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    partenza = progetto.current_phase_id

    passaggio = phases.avanza(
        db_session,
        progetto=progetto,
        motivazione="I requisiti sono chiusi.",
        autore=responsabile,
    )
    db_session.flush()

    assert progetto.current_phase.name == "Offerta"
    assert passaggio.state is PhaseTransitionState.APPROVATA
    assert passaggio.from_phase_id == partenza
    assert passaggio.requested_by_id == responsabile.id
    assert passaggio.decided_by_id == responsabile.id
    assert passaggio.decided_at is not None


def test_l_avanzamento_vuole_una_motivazione(client, db_session):
    """Senza motivazione il modulo torna indietro e la fase non cambia."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    prima = progetto.current_phase_id
    db_session.flush()

    entra(client, responsabile.username, PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/progetti/{progetto.id}/fase/avanza",
        data={
            "motivazione": "   ",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
    )

    assert risposta.status_code == 400
    assert "Scrivi perche'" in contenuto_leggibile(risposta)

    db_session.refresh(progetto)
    assert progetto.current_phase_id == prima


def test_un_ingegnere_non_avanza_direttamente(client, db_session):
    """Il permesso di avanzare non ce l'ha, e la rotta risponde 403."""
    progetto, _creatore, _pm, ingegnere, _estraneo = squadra_di_prova(db_session)
    prima = progetto.current_phase_id
    db_session.flush()

    entra(client, ingegnere.username, PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/progetti/{progetto.id}/fase/avanza",
        data={
            "motivazione": "Secondo me si puo'.",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
    )

    assert risposta.status_code == 403

    db_session.refresh(progetto)
    assert progetto.current_phase_id == prima


def test_un_estraneo_non_chiede_nemmeno_l_avanzamento(client, db_session):
    """Chi non e' nella squadra non vede il progetto: 404, non 403 (D-052)."""
    progetto, _creatore, _pm, _ing, estraneo = squadra_di_prova(db_session)
    db_session.flush()

    entra(client, estraneo.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/progetti/{progetto.id}/fase")
    assert risposta.status_code == 404


# ===========================================================================
#  4. LA RICHIESTA, L'APPROVAZIONE, IL RIFIUTO
# ===========================================================================


def test_la_richiesta_non_cambia_la_fase(db_session):
    """Una richiesta e' una domanda: finche' nessuno risponde non succede niente."""
    progetto, _creatore, _pm, ingegnere, _estraneo = squadra_di_prova(db_session)
    prima = progetto.current_phase_id

    passaggio = phases.richiedi(
        db_session,
        progetto=progetto,
        motivazione="Il prototipo funziona.",
        autore=ingegnere,
    )
    db_session.flush()

    assert passaggio.state is PhaseTransitionState.RICHIESTA
    assert passaggio.decided_by_id is None
    assert passaggio.decided_at is None
    assert progetto.current_phase_id == prima


def test_una_seconda_richiesta_non_si_apre(db_session):
    """Due domande identiche in attesa costringono a rispondere due volte."""
    progetto, _creatore, _pm, ingegnere, _estraneo = squadra_di_prova(db_session)

    phases.richiedi(
        db_session, progetto=progetto, motivazione="Prima.", autore=ingegnere
    )
    db_session.flush()

    try:
        phases.richiedi(
            db_session, progetto=progetto, motivazione="Seconda.", autore=ingegnere
        )
    except phases.PassaggioNonAmmesso as errore:
        assert "gia' una richiesta" in errore.messaggio
    else:
        raise AssertionError("la seconda richiesta doveva essere rifiutata")


def test_l_ingegnere_chiede_il_pm_lo_vede_e_approva(client, db_session):
    """**Secondo criterio di accettazione**, dal principio alla fine.

    L'ingegnere chiede dall'interfaccia, il project manager trova la richiesta
    nel suo cruscotto, la approva, e lo storico riporta **tutti e due i nomi**.
    """
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )
    db_session.flush()

    # --- L'ingegnere chiede -------------------------------------------------
    entra(client, ingegnere.username, PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/progetti/{progetto.id}/fase/richiedi",
        data={
            "motivazione": "Le prove elettriche sono finite.",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
        follow_redirects=True,
    )
    assert risposta.status_code == 200

    db_session.refresh(progetto)
    assert progetto.current_phase.name == "Studio", "la fase non e' cambiata"

    richiesta = phases.richiesta_in_attesa(db_session, progetto)
    assert richiesta is not None

    # --- Il project manager la trova nel cruscotto --------------------------
    entra(client, responsabile.username, PASSWORD_DI_PROVA)
    cruscotto = client.get("/")
    testo = contenuto_leggibile(cruscotto)
    assert ingegnere.full_name in testo
    assert "Le prove elettriche sono finite" in testo

    # --- E la approva -------------------------------------------------------
    risposta = client.post(
        f"/progetti/{progetto.id}/richieste/{richiesta.id}",
        data={
            "esito": "approva",
            "motivazione": "Verificate, si va avanti.",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
        follow_redirects=True,
    )
    assert risposta.status_code == 200

    db_session.refresh(progetto)
    assert progetto.current_phase.name == "Offerta"

    # --- Lo storico riporta i due nomi --------------------------------------
    storico = phases.storico(db_session, progetto)
    ultima = storico[0]
    assert ultima.a == "Offerta"
    assert ingegnere.full_name in ultima.chi
    assert responsabile.full_name in ultima.chi
    assert ultima.motivazione == "Le prove elettriche sono finite."
    assert ultima.motivazione_decisione == "Verificate, si va avanti."

    scheda = client.get(f"/progetti/{progetto.id}")
    pagina = contenuto_leggibile(scheda)
    assert ingegnere.full_name in pagina
    assert responsabile.full_name in pagina


def test_il_rifiuto_non_cambia_la_fase_e_resta_scritto(db_session):
    """Un progetto fermo ha una ragione, e questa e' la riga che la conserva."""
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )
    prima = progetto.current_phase_id

    richiesta = phases.richiedi(
        db_session, progetto=progetto, motivazione="Direi che ci siamo.",
        autore=ingegnere,
    )
    db_session.flush()

    phases.decidi(
        db_session,
        passaggio=richiesta,
        accolta=False,
        motivazione="Manca il rapporto di prova.",
        autore=responsabile,
    )
    db_session.flush()

    db_session.refresh(progetto)
    assert progetto.current_phase_id == prima
    assert richiesta.state is PhaseTransitionState.RESPINTA
    assert richiesta.decided_by_id == responsabile.id
    assert richiesta.decision_reason == "Manca il rapporto di prova."

    storico = phases.storico(db_session, progetto)
    assert storico[0].esito == "respinta"


def test_una_richiesta_gia_decisa_non_si_decide_due_volte(db_session):
    """Due schermi aperti sulla stessa pagina, due clic: la seconda si ferma."""
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )

    richiesta = phases.richiedi(
        db_session, progetto=progetto, motivazione="Pronti.", autore=ingegnere
    )
    db_session.flush()
    phases.decidi(
        db_session, passaggio=richiesta, accolta=True, motivazione="Va bene.",
        autore=responsabile,
    )
    db_session.flush()

    try:
        phases.decidi(
            db_session, passaggio=richiesta, accolta=False, motivazione="No.",
            autore=responsabile,
        )
    except phases.PassaggioNonAmmesso as errore:
        assert "gia' stata decisa" in errore.messaggio
    else:
        raise AssertionError("la seconda decisione doveva essere rifiutata")


def test_il_richiedente_viene_informato_dell_esito(client, db_session):
    """La notifica dentro l'applicazione: chi ha chiesto sa com'e' andata."""
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )

    richiesta = phases.richiedi(
        db_session, progetto=progetto, motivazione="Finito.", autore=ingegnere
    )
    db_session.flush()
    phases.decidi(
        db_session,
        passaggio=richiesta,
        accolta=True,
        motivazione="Confermo, avanti.",
        autore=responsabile,
    )
    db_session.flush()

    esiti = phases.esiti_da_leggere(db_session, ingegnere)
    assert len(esiti) == 1
    assert "approvata" in esiti[0].titolo
    assert responsabile.full_name in esiti[0].frase

    # Chi ha deciso non riceve la notifica di se' stesso.
    assert phases.esiti_da_leggere(db_session, responsabile) == []

    # E dall'interfaccia si legge e si chiude.
    entra(client, ingegnere.username, PASSWORD_DI_PROVA)
    cruscotto = client.get("/")
    assert "Confermo, avanti" in contenuto_leggibile(cruscotto)

    risposta = client.post(
        f"/progetti/{progetto.id}/esiti/{richiesta.id}",
        data={"ritorno": "/", "csrf": gettone_csrf(client, "/")},
        follow_redirects=True,
    )
    assert risposta.status_code == 200
    assert phases.esiti_da_leggere(db_session, ingegnere) == []


def test_l_esito_di_un_altro_non_si_chiude(client, db_session):
    """La notifica di qualcun altro non esiste: 404, non 403."""
    progetto, _creatore, responsabile, ingegnere, estraneo = squadra_di_prova(
        db_session
    )

    richiesta = phases.richiedi(
        db_session, progetto=progetto, motivazione="Fatto.", autore=ingegnere
    )
    db_session.flush()
    phases.decidi(
        db_session, passaggio=richiesta, accolta=True, motivazione="Bene.",
        autore=responsabile,
    )
    db_session.flush()

    entra(client, estraneo.username, PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/progetti/{progetto.id}/esiti/{richiesta.id}",
        data={"ritorno": "/", "csrf": gettone_csrf(client, "/")},
    )

    assert risposta.status_code == 404
    assert len(phases.esiti_da_leggere(db_session, ingegnere)) == 1


def test_il_cruscotto_mostra_solo_le_richieste_dei_propri_progetti(db_session):
    """Una richiesta di un progetto che non e' tuo non esce dal database."""
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )
    phases.richiedi(
        db_session, progetto=progetto, motivazione="Pronti.", autore=ingegnere
    )
    db_session.flush()

    assert len(phases.richieste_da_decidere(db_session, responsabile)) == 1
    assert phases.richieste_da_decidere(db_session, ingegnere) == []

    altro_pm = crea_utente(db_session, username=coda("pm4"))
    assert phases.richieste_da_decidere(db_session, altro_pm) == []


# ===========================================================================
#  5. IL RITORNO A UNA FASE PRECEDENTE
# ===========================================================================


def test_il_project_manager_torna_a_una_fase_precedente(db_session):
    """Un passo indietro e' un fatto come tutti gli altri: resta scritto."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)

    phases.avanza(
        db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
    )
    db_session.flush()
    assert progetto.current_phase.name == "Offerta"

    prima_fase = phases.fasi_del_progetto(db_session, progetto)[0]
    passaggio = phases.torna_a(
        db_session,
        progetto=progetto,
        destinazione=prima_fase,
        motivazione="Il cliente ha cambiato i requisiti.",
        autore=responsabile,
    )
    db_session.flush()

    assert progetto.current_phase.name == "Studio"
    assert passaggio.reason == "Il cliente ha cambiato i requisiti."

    storico = phases.storico(db_session, progetto)
    assert storico[0].esito == "ritorno"
    assert storico[0].da == "Offerta"
    assert storico[0].a == "Studio"


def test_un_ingegnere_non_torna_indietro(client, db_session):
    """Il ritorno e' di chi governa il progetto: project manager e creatore."""
    progetto, _creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )
    phases.avanza(
        db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
    )
    db_session.flush()
    prima_fase = phases.fasi_del_progetto(db_session, progetto)[0]

    entra(client, ingegnere.username, PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/progetti/{progetto.id}/fase/indietro",
        data={
            "destinazione": str(prima_fase.id),
            "motivazione": "Torniamo indietro.",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
    )

    assert risposta.status_code == 403

    db_session.refresh(progetto)
    assert progetto.current_phase.name == "Offerta"


def test_da_una_fase_che_blocca_non_si_torna_indietro(client, db_session):
    """**Terzo criterio di accettazione.**

    Il progetto e' nella fase che blocca il ritorno. Il project manager prova
    a riportarlo indietro: il sistema rifiuta, spiega perche' e propone la
    creazione di una versione nuova di prodotto **con il collegamento**.
    """
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)

    # Fino a "Costruzione", che e' la fase con blocks_return.
    for _ in range(2):
        phases.avanza(
            db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
        )
    db_session.flush()
    assert progetto.current_phase.name == "Costruzione"
    assert progetto.current_phase.blocks_return is True

    prima_fase = phases.fasi_del_progetto(db_session, progetto)[0]

    entra(client, responsabile.username, PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/progetti/{progetto.id}/fase/indietro",
        data={
            "destinazione": str(prima_fase.id),
            "motivazione": "Ci siamo accorti di un errore.",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
    )

    assert risposta.status_code == 400

    testo = contenuto_leggibile(risposta)
    assert "non si torna a una fase precedente" in testo
    assert "versione nuova del prodotto" in testo
    # Il collegamento diretto alla funzione che si deve usare invece.
    assert f"/versioni/{progetto.product_version_id}/deriva" in risposta.text

    db_session.refresh(progetto)
    assert progetto.current_phase.name == "Costruzione", "niente si e' mosso"


def test_il_divieto_di_tornare_indietro_vale_anche_per_il_creatore(db_session):
    """Non e' un permesso: e' una proprieta' della fase.

    Il creatore puo' tutto, dappertutto - ma "tutto" vuol dire tutto quello
    che si puo' fare, e riavvolgere un progetto arrivato in costruzione non e'
    fra quelle cose. Se questo divieto fosse un permesso, lo scavalcherebbe.
    """
    progetto, creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)

    for _ in range(2):
        phases.avanza(
            db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
        )
    db_session.flush()

    prima_fase = phases.fasi_del_progetto(db_session, progetto)[0]

    try:
        phases.torna_a(
            db_session,
            progetto=progetto,
            destinazione=prima_fase,
            motivazione="Sono il creatore.",
            autore=creatore,
        )
    except phases.PassaggioNonAmmesso as errore:
        assert errore.rimedio == f"/versioni/{progetto.product_version_id}/deriva"
    else:
        raise AssertionError("il divieto doveva valere anche per il creatore")


def test_il_ritorno_vuole_una_motivazione(client, db_session):
    """Un passo indietro senza ragione scritta e' inspiegabile fra un anno."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    phases.avanza(
        db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
    )
    db_session.flush()
    prima_fase = phases.fasi_del_progetto(db_session, progetto)[0]

    entra(client, responsabile.username, PASSWORD_DI_PROVA)
    risposta = client.post(
        f"/progetti/{progetto.id}/fase/indietro",
        data={
            "destinazione": str(prima_fase.id),
            "motivazione": "",
            "csrf": gettone_csrf(client, f"/progetti/{progetto.id}/fase"),
        },
    )

    assert risposta.status_code == 400

    db_session.refresh(progetto)
    assert progetto.current_phase.name == "Offerta"


# ===========================================================================
#  6. LA CHIUSURA
# ===========================================================================


def porta_alla_chiusura(db_session, progetto, responsabile):
    """Avanza il progetto fino a entrare nella fase che lo chiude."""
    while phases.fase_successiva(db_session, progetto) is not None:
        phases.avanza(
            db_session,
            progetto=progetto,
            motivazione="Avanti.",
            autore=responsabile,
        )
    db_session.flush()


def test_entrare_nell_ultima_fase_chiude_il_progetto(db_session):
    """La chiusura non e' un'operazione a parte: e' l'arrivo in fondo."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    assert progetto.closed_at is None

    porta_alla_chiusura(db_session, progetto, responsabile)

    assert progetto.current_phase.name == "Consegnato"
    assert progetto.current_phase.closes_project is True
    assert progetto.closed_at is not None


def test_un_progetto_chiuso_e_in_sola_lettura(db_session):
    """Si legge, non si cambia. Vale anche per il suo responsabile."""
    progetto, creatore, responsabile, ingegnere, _estraneo = squadra_di_prova(
        db_session
    )
    porta_alla_chiusura(db_session, progetto, responsabile)

    # Vedere: si', per chi lo vedeva prima.
    assert permissions.puo(db_session, responsabile, VEDERE, progetto)
    assert permissions.puo(db_session, ingegnere, VEDERE, progetto)

    # Cambiare: nessuno, tranne il creatore.
    assert not permissions.puo(db_session, responsabile, MODIFICARE, progetto)
    assert not permissions.puo(db_session, ingegnere, RICHIEDERE, progetto)
    assert not permissions.puo(db_session, responsabile, CARICARE, progetto)
    assert permissions.puo(db_session, creatore, MODIFICARE, progetto)


def test_su_un_progetto_chiuso_non_si_carica(client, db_session):
    """La sola lettura vale anche per i documenti, da tutte e tre le strade."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    porta_alla_chiusura(db_session, progetto, responsabile)

    entra(client, responsabile.username, PASSWORD_DI_PROVA)

    risposta = client.get(f"/documenti/nuovo?progetto={progetto.id}")
    assert risposta.status_code == 403
    assert "chiuso" in contenuto_leggibile(risposta)


def test_il_ritorno_riapre_un_progetto_chiuso(db_session):
    """La chiusura sbagliata si corregge: e' il caso raro ma reale."""
    progetto, creatore, responsabile, _ing, _estraneo = squadra_di_prova(
        db_session,
        # Senza la fase che blocca il ritorno: da "Costruzione" non si
        # tornerebbe indietro, e questo test parla di un'altra cosa.
        fasi=(
            ("Studio", False, False),
            ("Offerta", False, False),
            ("Consegnato", False, True),
        ),
    )
    porta_alla_chiusura(db_session, progetto, responsabile)
    assert progetto.closed_at is not None

    # Il progetto e' chiuso: lo riapre il creatore, che e' l'unico che possa
    # ancora toccarlo.
    seconda_fase = phases.fasi_del_progetto(db_session, progetto)[1]
    phases.torna_a(
        db_session,
        progetto=progetto,
        destinazione=seconda_fase,
        motivazione="Chiuso per sbaglio.",
        autore=creatore,
    )
    db_session.flush()

    assert progetto.closed_at is None
    assert progetto.current_phase.name == "Offerta"
    assert permissions.puo(db_session, responsabile, MODIFICARE, progetto)


# ===========================================================================
#  7. LA BARRA E LO STORICO
# ===========================================================================


def test_l_apertura_scrive_il_primo_passaggio(db_session):
    """La storia comincia dall'ingresso nella prima fase, non dal secondo passo."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)

    passaggi = phases.tutti_i_passaggi(db_session, progetto)
    assert len(passaggi) == 1
    assert passaggi[0].from_phase_id is None
    assert passaggi[0].to_phase.name == "Studio"
    assert passaggi[0].state is PhaseTransitionState.APPROVATA

    storico = phases.storico(db_session, progetto)
    assert storico[0].esito == "apertura"
    assert storico[0].da is None


def test_la_barra_marca_le_concluse_la_corrente_e_le_future(db_session):
    """Comprensibile in un secondo: fatte, in corso, da fare."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)
    phases.avanza(
        db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
    )
    db_session.flush()

    barra = phases.barra_avanzamento(db_session, progetto)

    assert [voce["nome"] for voce in barra] == [
        "Studio",
        "Offerta",
        "Costruzione",
        "Consegnato",
    ]
    assert [voce["stato"] for voce in barra] == ["conclusa", "corrente", "", ""]
    # La fase conclusa porta la data in cui e' stata chiusa.
    assert barra[0]["data"] is not None
    assert barra[2]["data"] is None


def test_lo_storico_dice_quanto_e_durata_ciascuna_fase(db_session):
    """La durata sta sulla riga che chiude la fase: e' li' che si conosce."""
    progetto, _creatore, responsabile, _ing, _estraneo = squadra_di_prova(db_session)

    phases.avanza(
        db_session, progetto=progetto, motivazione="Avanti.", autore=responsabile
    )
    db_session.flush()

    storico = phases.storico(db_session, progetto)

    # La riga dell'avanzamento chiude "Studio": ha una durata.
    assert storico[0].durata is not None
    # Quella dell'apertura non chiude niente: non ne ha.
    assert storico[-1].durata is None

    # E la fase corrente ha un "in corso da".
    assert phases.in_corso_da(db_session, progetto) is not None


def test_la_durata_si_legge_come_la_direbbe_una_persona(db_session):
    """Sotto l'ora non si scende: un progetto non si misura in minuti."""
    from datetime import timedelta

    assert phases.durata_leggibile(None) is None
    assert phases.durata_leggibile(timedelta(minutes=12)) == "meno di un'ora"
    assert phases.durata_leggibile(timedelta(hours=1)) == "1 ora"
    assert phases.durata_leggibile(timedelta(hours=5)) == "5 ore"
    assert phases.durata_leggibile(timedelta(days=1)) == "1 giorno"
    assert phases.durata_leggibile(timedelta(days=40)) == "40 giorni"
