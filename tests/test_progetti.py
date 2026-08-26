"""Test dei progetti e del cruscotto.

Il criterio di accettazione verificato qui e' l'ultimo dei cinque:

    "Un utente non assegnato a un progetto non lo vede nel cruscotto."

e insieme a lui la regola che lo rende una porta e non una tenda: chi non lo
vede nell'elenco non lo apre nemmeno scrivendone l'indirizzo.

    pytest tests/test_progetti.py -v
"""

import uuid

from app.models import GlobalRole, LifecycleState, ProjectRole
from app.services import lifecycle, permissions, phases, projects
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
)


def crea_creatore(db, username: str = "prova.capo.progetti"):
    """Un utente con il ruolo di creatore."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


# --- L'apertura -------------------------------------------------------------


def test_il_progetto_nasce_nella_prima_fase_del_modello(db_session):
    """Aprendo un progetto si entra subito nella prima fase."""
    creatore = crea_creatore(db_session, "prova.capo.fasi")
    responsabile = crea_utente(db_session, username="prova.pm.fasi")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    assert progetto.current_phase_id is not None
    fasi = phases.fasi_del_modello(db_session, progetto.phase_template_id)
    assert progetto.current_phase_id == fasi[0].id


def test_il_modello_di_fasi_resta_congelato_nel_progetto(db_session):
    """Il modello scelto alla nascita e' quello che il progetto seguira'.

    I modelli sono immutabili per costruzione: una correzione diventa una
    versione nuova del modello. Il progetto tiene l'identificatore di quello
    di allora, quindi una versione nuova del modello non lo tocca (D-041).
    """
    creatore = crea_creatore(db_session, "prova.capo.congelato")
    responsabile = crea_utente(db_session, username="prova.pm.congelato")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    modello_di_allora = progetto.phase_template_id

    # Arriva un modello nuovo e quello vecchio viene tolto dai proponibili.
    progetto.phase_template.is_active = False
    db_session.flush()

    db_session.refresh(progetto)
    assert progetto.phase_template_id == modello_di_allora, (
        "il progetto gia' avviato non cambia modello"
    )


def test_le_norme_si_copiano_dentro_il_progetto(db_session):
    """Le norme applicabili sono scritte nel progetto, non lette dal modello."""
    creatore = crea_creatore(db_session, "prova.capo.norme")
    responsabile = crea_utente(db_session, username="prova.pm.norme")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    assert progetto.standards == ["EN 50155"]


def test_il_project_manager_e_anche_un_assegnato(db_session):
    """Il responsabile entra da solo nella squadra.

    Cosi' "chi vede questo progetto" ha una risposta sola - chi ha
    un'assegnazione non revocata - e il responsabile non e' un caso a parte da
    ricordarsi in ogni interrogazione.
    """
    creatore = crea_creatore(db_session, "prova.capo.squadra")
    responsabile = crea_utente(db_session, username="prova.pm.squadra")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    squadra = projects.assegnazioni_attive(db_session, progetto.id)
    ruoli = {a.user_id: a.project_role for a in squadra}

    assert ruoli[responsabile.id] is ProjectRole.PROJECT_MANAGER


def test_una_persona_ha_un_solo_ruolo_attivo_per_progetto(db_session):
    """Riassegnandola, quella di prima viene revocata e resta in tabella."""
    creatore = crea_creatore(db_session, "prova.capo.ruoli")
    responsabile = crea_utente(db_session, username="prova.pm.ruoli")
    tecnico = crea_utente(db_session, username="prova.tecnico.ruoli")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session,
        versione,
        project_manager=responsabile,
        autore=creatore,
        squadra=[tecnico],
    )

    projects.assegna(
        db_session,
        progetto=progetto,
        utente=tecnico,
        ruolo=ProjectRole.LETTORE,
        autore=creatore,
    )
    db_session.flush()

    attive = [
        a
        for a in projects.assegnazioni_attive(db_session, progetto.id)
        if a.user_id == tecnico.id
    ]
    assert len(attive) == 1
    assert attive[0].project_role is ProjectRole.LETTORE


# --- Chi vede che cosa ------------------------------------------------------


def test_chi_non_e_assegnato_non_vede_il_progetto_nel_cruscotto(db_session):
    """IL criterio di accettazione.

    Il progetto non e' nascosto dal template: non esce proprio
    dall'interrogazione.
    """
    creatore = crea_creatore(db_session, "prova.capo.visibilita")
    responsabile = crea_utente(db_session, username="prova.pm.visibilita")
    estraneo = crea_utente(db_session, username="prova.estraneo.visibilita")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    visti_dal_responsabile = projects.cruscotto(db_session, responsabile)
    assert progetto.id in [p.id for p in visti_dal_responsabile]

    visti_dall_estraneo = projects.cruscotto(db_session, estraneo)
    assert progetto.id not in [p.id for p in visti_dall_estraneo]


def test_il_creatore_vede_tutti_i_progetti(db_session):
    """E' lui che li apre e che assegna le persone."""
    creatore = crea_creatore(db_session, "prova.capo.tuttovede")
    responsabile = crea_utente(db_session, username="prova.pm.tuttovede")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    assert progetto.id in [p.id for p in projects.cruscotto(db_session, creatore)]


def test_chi_e_nella_squadra_vede_il_progetto(db_session):
    """Anche senza essere il responsabile."""
    creatore = crea_creatore(db_session, "prova.capo.squadravede")
    responsabile = crea_utente(db_session, username="prova.pm.squadravede")
    tecnico = crea_utente(db_session, username="prova.tecnico.squadravede")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session,
        versione,
        project_manager=responsabile,
        autore=creatore,
        squadra=[tecnico],
    )

    assert progetto.id in [p.id for p in projects.cruscotto(db_session, tecnico)]


def test_chi_e_stato_revocato_non_vede_piu(db_session):
    """L'assegnazione revocata resta in tabella ma non da' piu' accesso."""
    creatore = crea_creatore(db_session, "prova.capo.revoca")
    responsabile = crea_utente(db_session, username="prova.pm.revoca")
    tecnico = crea_utente(db_session, username="prova.tecnico.revoca")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    progetto = crea_progetto(
        db_session,
        versione,
        project_manager=responsabile,
        autore=creatore,
        squadra=[tecnico],
    )

    sua = [
        a
        for a in projects.assegnazioni_attive(db_session, progetto.id)
        if a.user_id == tecnico.id
    ][0]
    projects.revoca(db_session, assegnazione=sua, autore=creatore)
    db_session.flush()

    assert progetto.id not in [p.id for p in projects.cruscotto(db_session, tecnico)]
    assert not permissions.puo(
        db_session, tecnico, permissions.Azione.VEDERE, progetto
    )


# --- I filtri del cruscotto -------------------------------------------------


def test_il_cruscotto_si_filtra_per_stato(db_session):
    creatore = crea_creatore(db_session, "prova.capo.filtrostato")
    responsabile = crea_utente(db_session, username="prova.pm.filtrostato")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    in_sviluppo = projects.cruscotto(db_session, responsabile, stato="in_sviluppo")
    assert progetto.id in [p.id for p in in_sviluppo]

    rilasciati = projects.cruscotto(db_session, responsabile, stato="rilasciato")
    assert progetto.id not in [p.id for p in rilasciati]


def test_il_cruscotto_si_filtra_per_fase(db_session):
    creatore = crea_creatore(db_session, "prova.capo.filtrofase")
    responsabile = crea_utente(db_session, username="prova.pm.filtrofase")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    nome_fase = progetto.current_phase.name

    giusta = projects.cruscotto(db_session, responsabile, fase=nome_fase)
    assert progetto.id in [p.id for p in giusta]

    sbagliata = projects.cruscotto(
        db_session, responsabile, fase="Una fase che non esiste"
    )
    assert progetto.id not in [p.id for p in sbagliata]


def test_le_fasi_proposte_sono_solo_quelle_in_uso(db_session):
    """Una tendina che porta a un elenco vuoto non andava proposta."""
    creatore = crea_creatore(db_session, "prova.capo.tendinafasi")
    responsabile = crea_utente(db_session, username="prova.pm.tendinafasi")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )

    proposte = projects.fasi_in_uso(db_session, responsabile)

    assert progetto.current_phase.name in proposte


# --- Le pagine --------------------------------------------------------------


def test_il_cruscotto_mostra_le_colonne_chieste(client, db_session):
    """Codice prodotto, versione, cliente, fase, ciclo di vita, responsabile."""
    creatore = crea_utente(
        db_session, username="prova.capo.cruscotto2", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db_session, username="prova.pm.cruscotto")
    prodotto, versione = crea_prodotto(db_session, autore=creatore)
    crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    db_session.flush()

    entra(client, "prova.pm.cruscotto", PASSWORD_DI_PROVA)
    pagina = client.get("/")
    testo = contenuto_leggibile(pagina)

    assert pagina.status_code == 200
    assert prodotto.code in testo
    assert prodotto.customer.name in testo
    assert responsabile.full_name in testo
    assert "in sviluppo" in testo
    assert "Fase corrente" in testo


def test_un_estraneo_non_trova_il_progetto_nel_cruscotto(client, db_session):
    """Il criterio di accettazione, guardato dal browser."""
    creatore = crea_utente(
        db_session, username="prova.capo.estraneo", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db_session, username="prova.pm.estraneo")
    crea_utente(db_session, username="prova.fuori.estraneo")
    prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    db_session.flush()

    entra(client, "prova.fuori.estraneo", PASSWORD_DI_PROVA)

    cruscotto = client.get("/")
    assert prodotto.code not in cruscotto.text
    assert str(progetto.id) not in cruscotto.text

    elenco = client.get("/progetti")
    assert prodotto.code not in elenco.text


def test_un_estraneo_non_apre_il_progetto_nemmeno_scrivendo_l_indirizzo(
    client, db_session
):
    """L'elenco e' una porta chiusa, non una tenda.

    E la porta chiusa non ha nemmeno il campanello: 404 e non 403, con lo
    stesso messaggio di un progetto che non esiste. Chi provasse gli
    identificativi uno per uno non riuscirebbe a distinguere i progetti veri
    da quelli inventati (D-051).
    """
    creatore = crea_utente(
        db_session, username="prova.capo.porta", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db_session, username="prova.pm.porta")
    crea_utente(db_session, username="prova.fuori.porta")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    progetto = crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    db_session.flush()

    entra(client, "prova.fuori.porta", PASSWORD_DI_PROVA)

    risposta = client.get(f"/progetti/{progetto.id}")

    assert risposta.status_code == 404
    assert "Il progetto richiesto non esiste" in contenuto_leggibile(risposta)

    # E la risposta e' indistinguibile da quella di un progetto inventato.
    inventato = client.get(f"/progetti/{uuid.uuid4()}")
    assert inventato.status_code == 404
    assert contenuto_leggibile(inventato) == contenuto_leggibile(risposta)


def test_si_apre_un_progetto_dall_interfaccia(client, db_session):
    """Il giro completo dal modulo, senza JavaScript."""
    crea_utente(
        db_session, username="prova.capo.apertura", ruolo=GlobalRole.CREATORE
    )
    creatore = crea_utente(
        db_session, username="prova.capo.apertura2", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db_session, username="prova.pm.apertura")
    tecnico = crea_utente(db_session, username="prova.tecnico.apertura")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.apertura", PASSWORD_DI_PROVA)

    modulo = client.get(f"/progetti/nuovo?versione={versione.id}")
    assert modulo.status_code == 200

    modelli = phases.modelli_di_fasi(db_session)
    assert modelli, "serve almeno un modello di fasi attivo"

    risposta = client.post(
        "/progetti/nuovo",
        data={
            "versione": str(versione.id),
            "project_manager": str(responsabile.id),
            "modello": str(modelli[0].id),
            "norme": "EN 50155\nEN 45545-2",
            "ingegneri": [str(tecnico.id)],
            "csrf": gettone_csrf(client, f"/progetti/nuovo?versione={versione.id}"),
        },
        follow_redirects=True,
    )

    assert risposta.status_code == 200
    testo = contenuto_leggibile(risposta)
    assert responsabile.full_name in testo
    assert "EN 45545-2" in testo

    db_session.refresh(versione)
    assert versione.project is not None
    squadra = projects.assegnazioni_attive(db_session, versione.project.id)
    assert {a.user_id for a in squadra} == {responsabile.id, tecnico.id}


def test_su_una_versione_si_apre_un_progetto_solo(client, db_session):
    """Il legame e' uno a uno, e il rifiuto e' una frase italiana."""
    crea_utente(
        db_session, username="prova.capo.unoauno", ruolo=GlobalRole.CREATORE
    )
    creatore = crea_utente(
        db_session, username="prova.capo.unoauno2", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db_session, username="prova.pm.unoauno")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    crea_progetto(
        db_session, versione, project_manager=responsabile, autore=creatore
    )
    db_session.flush()

    entra(client, "prova.capo.unoauno", PASSWORD_DI_PROVA)

    risposta = client.get(f"/progetti/nuovo?versione={versione.id}")

    assert risposta.status_code == 400
    assert "gia' un progetto" in contenuto_leggibile(risposta)


def test_solo_il_creatore_apre_un_progetto(client, db_session):
    crea_utente(db_session, username="prova.mario.progetti")
    creatore = crea_utente(
        db_session, username="prova.capo.negatoprog", ruolo=GlobalRole.CREATORE
    )
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.mario.progetti", PASSWORD_DI_PROVA)

    assert client.get(f"/progetti/nuovo?versione={versione.id}").status_code == 403
