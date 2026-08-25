"""Test del ciclo di vita delle versioni di prodotto.

Sono i due criteri di accettazione che l'azienda ha messo per primi:

    "Creo la V2 per derivazione, la porto a rilasciato, e la V1 diventa
     superato da sola."

    "Un tentativo di transizione non ammessa produce un messaggio chiaro, non
     un errore tecnico."

Il primo blocco verifica il **grafo** delle transizioni, il secondo il
**superamento automatico**, il terzo chi puo' muovere gli stati, il quarto le
pagine.

    pytest tests/test_versioni.py -v
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, GlobalRole, LifecycleState
from app.services import lifecycle, products
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_leggibile,
    crea_cliente,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
)


def crea_creatore(db, username: str = "prova.capo.versioni"):
    """Un utente con il ruolo di creatore."""
    return crea_utente(db, username=username, ruolo=GlobalRole.CREATORE)


# --- Il grafo delle transizioni ---------------------------------------------


def test_il_grafo_copre_tutti_gli_stati():
    """Ogni stato del ciclo di vita ha la sua riga nel grafo.

    Uno stato che manca dal grafo non e' una transizione vietata: e' una riga
    dimenticata, e si comporterebbe come uno stato terminale senza che nessuno
    lo abbia deciso. Aggiungendo un valore a LifecycleState questo test
    diventa rosso, ed e' esattamente quello che deve succedere.
    """
    assert set(lifecycle.TRANSIZIONI_AMMESSE) == set(LifecycleState)


def test_le_destinazioni_del_grafo_sono_stati_veri():
    """Nessuna freccia punta a uno stato che non esiste."""
    for partenze in lifecycle.TRANSIZIONI_AMMESSE.values():
        for arrivo in partenze:
            assert isinstance(arrivo, LifecycleState)


@pytest.mark.parametrize(
    "da, a",
    [
        (LifecycleState.IN_SVILUPPO, LifecycleState.RILASCIATO),
        (LifecycleState.IN_SVILUPPO, LifecycleState.OBSOLETO),
        (LifecycleState.RILASCIATO, LifecycleState.IN_PRODUZIONE),
        (LifecycleState.RILASCIATO, LifecycleState.SUPERATO),
        (LifecycleState.IN_PRODUZIONE, LifecycleState.SUPERATO),
        (LifecycleState.SUPERATO, LifecycleState.OBSOLETO),
    ],
)
def test_le_transizioni_previste_passano(da, a):
    """Le frecce che ci sono si percorrono."""
    assert lifecycle.transizione_ammessa(da, a)
    lifecycle.verifica_transizione(da, a)  # non deve sollevare


@pytest.mark.parametrize(
    "da, a",
    [
        # Non si torna indietro.
        (LifecycleState.RILASCIATO, LifecycleState.IN_SVILUPPO),
        (LifecycleState.IN_PRODUZIONE, LifecycleState.RILASCIATO),
        (LifecycleState.SUPERATO, LifecycleState.RILASCIATO),
        # Non si salta il rilascio.
        (LifecycleState.IN_SVILUPPO, LifecycleState.IN_PRODUZIONE),
        (LifecycleState.IN_SVILUPPO, LifecycleState.SUPERATO),
        # Da obsoleto non si esce.
        (LifecycleState.OBSOLETO, LifecycleState.RILASCIATO),
        (LifecycleState.OBSOLETO, LifecycleState.IN_SVILUPPO),
    ],
)
def test_le_transizioni_non_previste_vengono_rifiutate(da, a):
    """Le frecce che non ci sono non si percorrono."""
    assert not lifecycle.transizione_ammessa(da, a)
    with pytest.raises(lifecycle.TransizioneNonAmmessa):
        lifecycle.verifica_transizione(da, a)


def test_il_rifiuto_e_una_frase_italiana_che_dice_come_si_fa():
    """**Non un errore tecnico**: e' il criterio di accettazione.

    Il messaggio dice tre cose: da dove si parte, dove non si puo' andare, e
    quali sono le strade che restano.
    """
    with pytest.raises(lifecycle.TransizioneNonAmmessa) as rifiuto:
        lifecycle.verifica_transizione(
            LifecycleState.RILASCIATO, LifecycleState.IN_SVILUPPO
        )

    messaggio = str(rifiuto.value)
    assert "rilasciato" in messaggio
    assert "in sviluppo" in messaggio
    assert "in produzione" in messaggio, "deve dire dove si puo' andare"
    assert "Traceback" not in messaggio
    assert "Error" not in messaggio


def test_lo_stato_terminale_lo_dice_a_parole():
    with pytest.raises(lifecycle.TransizioneNonAmmessa) as rifiuto:
        lifecycle.verifica_transizione(
            LifecycleState.OBSOLETO, LifecycleState.RILASCIATO
        )

    assert "ultimo passo del ciclo di vita" in str(rifiuto.value)


def test_restare_nello_stesso_stato_lo_dice_a_parole():
    with pytest.raises(lifecycle.TransizioneNonAmmessa) as rifiuto:
        lifecycle.verifica_transizione(
            LifecycleState.RILASCIATO, LifecycleState.RILASCIATO
        )

    assert "gia' nello stato" in str(rifiuto.value)


def test_gli_stati_proponibili_sono_quelli_del_grafo():
    """I pulsanti delle pagine si costruiscono da qui."""
    assert lifecycle.stati_raggiungibili(LifecycleState.OBSOLETO) == ()
    assert LifecycleState.RILASCIATO in lifecycle.stati_raggiungibili(
        LifecycleState.IN_SVILUPPO
    )


# --- Il superamento automatico ----------------------------------------------


def test_la_v2_rilasciata_supera_la_v1_da_sola(db_session):
    """IL criterio di accettazione della sessione.

    Creo un prodotto (nasce la V1), derivo la V2, rilascio prima la V1 e poi
    la V2: la V1 diventa "superato" senza che nessuno glielo abbia chiesto.
    """
    creatore = crea_creatore(db_session, "prova.capo.superamento")
    prodotto, prima = crea_prodotto(db_session, autore=creatore)

    seconda = products.deriva_versione(
        db_session,
        origine=prima,
        motivazione="Richiesta di variante del cliente.",
        autore=creatore,
    )
    db_session.flush()

    assert seconda.version_number == 2
    assert seconda.lifecycle_state is LifecycleState.IN_SVILUPPO
    assert seconda.derived_from_id == prima.id

    # La V1 va in campo.
    lifecycle.cambia_stato(
        db_session, prima, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()
    assert prima.lifecycle_state is LifecycleState.RILASCIATO

    # E adesso la V2. Questo e' il momento della regola.
    superata = lifecycle.cambia_stato(
        db_session, seconda, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()

    assert seconda.lifecycle_state is LifecycleState.RILASCIATO
    assert prima.lifecycle_state is LifecycleState.SUPERATO, (
        "la versione precedente doveva passare a superato da sola"
    )
    assert superata is not None and superata.id == prima.id, (
        "cambia_stato deve dire quale versione ha superato"
    )


def test_il_superamento_automatico_e_registrato_come_azione_di_sistema(db_session):
    """Nel registro la riga del superamento non ha autore.

    Non l'ha chiesta nessuno: l'ha decisa il programma applicando una regola.
    Scriverci dentro chi ha premuto il pulsante direbbe una cosa falsa.
    """
    creatore = crea_creatore(db_session, "prova.capo.registro")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Evoluzione.", autore=creatore
    )
    db_session.flush()

    lifecycle.cambia_stato(
        db_session, prima, LifecycleState.RILASCIATO, autore=creatore
    )
    lifecycle.cambia_stato(
        db_session, seconda, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()

    righe = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == lifecycle.ACTION_SUPERSEDED,
            AuditLog.entity_id == prima.id,
        )
    ).all()

    assert len(righe) == 1, "il superamento deve lasciare una riga sola"
    riga = righe[0]
    assert riga.user_id is None, "e' un'azione di sistema, non di una persona"
    assert riga.old_value["lifecycle_state"] == "rilasciato"
    assert riga.new_value["lifecycle_state"] == "superato"
    assert riga.new_value["superata_da_versione"] == 2, (
        "deve dire da quale versione e' stata superata"
    )


def test_la_prima_versione_rilasciata_non_supera_niente(db_session):
    """Senza una versione precedente non c'e' niente da superare."""
    creatore = crea_creatore(db_session, "prova.capo.primo")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)

    superata = lifecycle.cambia_stato(
        db_session, prima, LifecycleState.RILASCIATO, autore=creatore
    )

    assert superata is None


def test_una_precedente_obsoleta_resta_obsoleta(db_session):
    """Il grafo vale anche per le operazioni che fa il programma da solo.

    Da "obsoleto" non si esce: il superamento automatico salta la versione
    invece di forzarla, e questo e' il test che impedisce di scrivere un
    giorno un `precedente.lifecycle_state = SUPERATO` senza passare dal grafo.
    """
    creatore = crea_creatore(db_session, "prova.capo.obsoleta")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Rifacimento.", autore=creatore
    )
    db_session.flush()

    lifecycle.cambia_stato(
        db_session,
        prima,
        LifecycleState.OBSOLETO,
        autore=creatore,
        motivazione="Progetto abbandonato.",
    )
    db_session.flush()

    superata = lifecycle.cambia_stato(
        db_session, seconda, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()

    assert superata is None
    assert prima.lifecycle_state is LifecycleState.OBSOLETO


def test_la_versione_da_superare_si_puo_sapere_prima(db_session):
    """La pagina di conferma dice quale versione verra' superata.

    Usa la stessa funzione che poi esegue: se ne usasse una sua, prima o poi
    direbbe una cosa e il programma ne farebbe un'altra.
    """
    creatore = crea_creatore(db_session, "prova.capo.anteprima.stato")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Variante.", autore=creatore
    )
    db_session.flush()
    lifecycle.cambia_stato(
        db_session, prima, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()

    prevista = lifecycle.versione_da_superare(db_session, seconda)

    assert prevista is not None and prevista.id == prima.id

    # E quello che era previsto e' quello che succede.
    davvero = lifecycle.cambia_stato(
        db_session, seconda, LifecycleState.RILASCIATO, autore=creatore
    )
    assert davvero.id == prevista.id


def test_la_precedente_e_quella_col_numero_piu_alto_sotto(db_session):
    """Con la 1, la 2 e la 3, la precedente della 3 e' la 2."""
    creatore = crea_creatore(db_session, "prova.capo.numeri")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Due.", autore=creatore
    )
    terza = products.deriva_versione(
        db_session, origine=prima, motivazione="Tre, derivata dalla uno.",
        autore=creatore,
    )
    db_session.flush()

    assert terza.version_number == 3
    assert terza.derived_from_id == prima.id, "derivata dalla 1, non dalla 2"
    # Ma la precedente resta la 2: e' quella che era in campo fino a un
    # momento fa, indipendentemente dalla catena delle derivazioni.
    precedente = lifecycle.versione_precedente(db_session, terza)
    assert precedente.id == seconda.id


def test_la_data_di_rilascio_si_scrive_al_rilascio(db_session):
    creatore = crea_creatore(db_session, "prova.capo.data")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)

    assert prima.released_at is None

    lifecycle.cambia_stato(
        db_session, prima, LifecycleState.RILASCIATO, autore=creatore
    )

    assert prima.released_at is not None


def test_una_transizione_rifiutata_non_scrive_niente(db_session):
    """Il controllo viene prima di qualunque scrittura."""
    creatore = crea_creatore(db_session, "prova.capo.rifiuto")
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)

    with pytest.raises(lifecycle.TransizioneNonAmmessa):
        lifecycle.cambia_stato(
            db_session, prima, LifecycleState.SUPERATO, autore=creatore
        )

    assert prima.lifecycle_state is LifecycleState.IN_SVILUPPO
    assert prima.released_at is None


# --- Chi puo' muovere gli stati ---------------------------------------------


def test_il_creatore_puo_sempre(db_session):
    creatore = crea_creatore(db_session, "prova.capo.permessi")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    assert lifecycle.puo_cambiare_stato(versione, creatore)


def test_un_utente_qualunque_non_puo(db_session):
    creatore = crea_creatore(db_session, "prova.capo.permessi2")
    passante = crea_utente(db_session, username="prova.passante.uno")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    assert not lifecycle.puo_cambiare_stato(versione, passante)


def test_il_project_manager_del_progetto_puo(db_session):
    """E' la seconda meta' della regola: creatore **e** project manager."""
    creatore = crea_creatore(db_session, "prova.capo.permessi3")
    responsabile = crea_utente(db_session, username="prova.responsabile.uno")
    ingegnere = crea_utente(db_session, username="prova.ingegnere.uno")
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)

    crea_progetto(
        db_session,
        versione,
        project_manager=responsabile,
        autore=creatore,
        squadra=[ingegnere],
    )
    db_session.refresh(versione)

    assert lifecycle.puo_cambiare_stato(versione, responsabile)
    assert not lifecycle.puo_cambiare_stato(versione, ingegnere), (
        "essere nella squadra non basta: serve essere il responsabile"
    )


# --- Le pagine --------------------------------------------------------------


def test_il_giro_completo_dall_interfaccia(client, db_session):
    """V2 derivata, rilasciata, e la V1 superata: tutto dal browser.

    E' il criterio di accettazione percorso come lo percorre una persona, con
    il finto browser che non esegue JavaScript.
    """
    crea_creatore(db_session, "prova.capo.giro")
    creatore = crea_utente(
        db_session, username="prova.capo.giro2", ruolo=GlobalRole.CREATORE
    )
    prodotto, prima = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.giro", PASSWORD_DI_PROVA)

    # 1. La V1 va in campo.
    client.post(
        f"/versioni/{prima.id}/stato",
        data={
            "nuovo": "rilasciato",
            "csrf": gettone_csrf(client, f"/versioni/{prima.id}"),
        },
        follow_redirects=True,
    )
    db_session.refresh(prima)
    assert prima.lifecycle_state is LifecycleState.RILASCIATO

    # 2. Si deriva la V2.
    derivata = client.post(
        f"/versioni/{prima.id}/deriva",
        data={
            "origine": str(prima.id),
            "motivazione": "Il cliente ha chiesto un connettore diverso.",
            "csrf": gettone_csrf(client, f"/versioni/{prima.id}/deriva"),
        },
        follow_redirects=True,
    )
    assert derivata.status_code == 200

    versioni = products.versioni_di(db_session, prodotto.id)
    assert len(versioni) == 2
    seconda = versioni[1]
    assert seconda.lifecycle_state is LifecycleState.IN_SVILUPPO

    # 3. La conferma dice quale versione verra' superata, prima di procedere.
    conferma = client.get(f"/versioni/{seconda.id}/stato?nuovo=rilasciato")
    testo = contenuto_leggibile(conferma)
    assert conferma.status_code == 200
    assert "versione 1" in testo.lower()
    assert "superato" in testo

    # 4. Si conferma.
    client.post(
        f"/versioni/{seconda.id}/stato",
        data={
            "nuovo": "rilasciato",
            "csrf": gettone_csrf(client, f"/versioni/{seconda.id}"),
        },
        follow_redirects=True,
    )

    db_session.refresh(prima)
    db_session.refresh(seconda)
    assert seconda.lifecycle_state is LifecycleState.RILASCIATO
    assert prima.lifecycle_state is LifecycleState.SUPERATO


def test_una_transizione_non_ammessa_dall_interfaccia_e_leggibile(client, db_session):
    """Il criterio: messaggio chiaro, non errore tecnico.

    Si prova a riportare in sviluppo una versione gia' rilasciata costruendo
    la richiesta a mano, che e' l'unico modo di provarci: le pagine i pulsanti
    impossibili non li mostrano nemmeno.
    """
    crea_creatore(db_session, "prova.capo.rifiuto2")
    creatore = crea_utente(
        db_session, username="prova.capo.rifiuto3", ruolo=GlobalRole.CREATORE
    )
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    lifecycle.cambia_stato(
        db_session, versione, LifecycleState.RILASCIATO, autore=creatore
    )
    db_session.flush()

    entra(client, "prova.capo.rifiuto2", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/versioni/{versione.id}/stato",
        data={
            "nuovo": "in_sviluppo",
            "csrf": gettone_csrf(client, f"/versioni/{versione.id}"),
        },
    )

    assert risposta.status_code == 400
    testo = contenuto_leggibile(risposta)
    assert "non puo' passare a" in testo
    assert "in produzione, superato e obsoleto" in testo
    assert "Traceback" not in testo
    assert "Internal Server Error" not in testo

    db_session.refresh(versione)
    assert versione.lifecycle_state is LifecycleState.RILASCIATO


def test_uno_stato_inventato_non_produce_un_errore_tecnico(client, db_session):
    crea_creatore(db_session, "prova.capo.inventato")
    creatore = crea_utente(
        db_session, username="prova.capo.inventato2", ruolo=GlobalRole.CREATORE
    )
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.inventato", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/versioni/{versione.id}/stato",
        data={
            "nuovo": "stato-che-non-esiste",
            "csrf": gettone_csrf(client, f"/versioni/{versione.id}"),
        },
    )

    assert risposta.status_code == 400
    assert "non esiste" in contenuto_leggibile(risposta)


def test_obsoleto_richiede_una_motivazione(client, db_session):
    """Dichiarare obsoleta una versione e' una decisione: va spiegata."""
    crea_creatore(db_session, "prova.capo.motivazione")
    creatore = crea_utente(
        db_session, username="prova.capo.motivazione2", ruolo=GlobalRole.CREATORE
    )
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.motivazione", PASSWORD_DI_PROVA)

    # Senza motivazione: rifiutato, e la versione non si muove.
    senza = client.post(
        f"/versioni/{versione.id}/stato",
        data={
            "nuovo": "obsoleto",
            "motivazione": "   ",
            "csrf": gettone_csrf(client, f"/versioni/{versione.id}"),
        },
    )
    assert senza.status_code == 400
    assert "bisogna scrivere" in contenuto_leggibile(senza)
    db_session.refresh(versione)
    assert versione.lifecycle_state is LifecycleState.IN_SVILUPPO

    # Con la motivazione: passa, e la motivazione finisce nel registro.
    client.post(
        f"/versioni/{versione.id}/stato",
        data={
            "nuovo": "obsoleto",
            "motivazione": "La linea di prodotto e' stata abbandonata.",
            "csrf": gettone_csrf(client, f"/versioni/{versione.id}"),
        },
        follow_redirects=True,
    )
    db_session.refresh(versione)
    assert versione.lifecycle_state is LifecycleState.OBSOLETO

    riga = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == lifecycle.ACTION_STATE_CHANGED,
            AuditLog.entity_id == versione.id,
        )
    ).first()
    assert "abbandonata" in riga.new_value["motivazione"]


def test_chi_non_e_responsabile_non_cambia_lo_stato(client, db_session):
    crea_utente(db_session, username="prova.passante.due")
    creatore = crea_utente(
        db_session, username="prova.capo.negato", ruolo=GlobalRole.CREATORE
    )
    _prodotto, versione = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.passante.due", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/versioni/{versione.id}/stato",
        data={
            "nuovo": "rilasciato",
            "csrf": gettone_csrf(client, f"/versioni/{versione.id}"),
        },
    )

    assert risposta.status_code == 403
    assert "project manager" in contenuto_leggibile(risposta)


def test_la_scheda_avvisa_che_esiste_una_versione_piu_recente(client, db_session):
    """L'avviso in cima alla versione vecchia, con il collegamento."""
    crea_creatore(db_session, "prova.capo.avviso")
    creatore = crea_utente(
        db_session, username="prova.capo.avviso2", ruolo=GlobalRole.CREATORE
    )
    _prodotto, prima = crea_prodotto(db_session, autore=creatore)
    seconda = products.deriva_versione(
        db_session, origine=prima, motivazione="Evoluzione.", autore=creatore
    )
    db_session.flush()

    entra(client, "prova.capo.avviso", PASSWORD_DI_PROVA)

    vecchia = client.get(f"/versioni/{prima.id}")
    testo = contenuto_leggibile(vecchia)
    assert "non e' la versione corrente" in testo
    assert f"/versioni/{seconda.id}" in vecchia.text, "manca il collegamento"

    # Sulla piu' recente l'avviso non c'e'.
    recente = contenuto_leggibile(client.get(f"/versioni/{seconda.id}"))
    assert "non e' la versione corrente" not in recente


def test_la_derivazione_vuole_una_motivazione(client, db_session):
    crea_creatore(db_session, "prova.capo.derivazione")
    creatore = crea_utente(
        db_session, username="prova.capo.derivazione2", ruolo=GlobalRole.CREATORE
    )
    prodotto, prima = crea_prodotto(db_session, autore=creatore)
    db_session.flush()

    entra(client, "prova.capo.derivazione", PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/versioni/{prima.id}/deriva",
        data={
            "origine": str(prima.id),
            "motivazione": "",
            "csrf": gettone_csrf(client, f"/versioni/{prima.id}/deriva"),
        },
    )

    assert risposta.status_code == 400
    assert "Scrivi perche'" in contenuto_leggibile(risposta)
    assert len(products.versioni_di(db_session, prodotto.id)) == 1
