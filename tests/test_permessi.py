"""Test delle regole di accesso: la funzione centrale, gli elenchi, le pagine.

I criteri di accettazione della sessione 7 sono quattro, e sono tutti e quattro
qui dentro:

  1. **ogni combinazione ruolo x classificazione x azione**, verificata sia sul
     diniego all'accesso diretto sia sull'assenza dagli elenchi. E' la sezione
     2, che genera i casi invece di scriverli a mano: con tre ruoli, quattro
     classificazioni e tre azioni sono trentasei caselle, e trentasei test
     scritti a mano sono trentasei occasioni di sbagliarne uno;
  2. **un ingegnere non vede i documenti Commerciali**: ne' in elenco, ne' in
     ricerca, ne' tramite indirizzo diretto (sezione 3);
  3. **la matrice corretta mentre qualcuno e' collegato ha effetto subito**,
     senza che debba riconnettersi (sezione 6);
  4. **le verifiche di permesso esistono solo tramite la funzione centrale**:
     la sezione 8 legge i sorgenti e lo verifica.

    pytest tests/test_permessi.py -v

**I dati dei test sono irripetibili**, come dappertutto in Aurora: i test
girano sul database di sviluppo, che contiene dati veri lasciati dalle
verifiche a mano, e nomi utente o codici prodotto inventati collidono con
quelli. Vedi conftest.py.
"""

import io
import pathlib
import uuid

import pytest

from app.models import (
    Classification,
    Document,
    GlobalRole,
    PermissionRule,
    ProjectRole,
)
from app.services import documents, permissions, projects
from tests.conftest import (
    PASSWORD_DI_PROVA,
    contenuto_irripetibile,
    contenuto_leggibile,
    crea_documento,
    crea_progetto,
    crea_prodotto,
    crea_utente,
    entra,
    gettone_csrf,
)

VEDERE = permissions.Azione.VEDERE
CARICARE = permissions.Azione.CARICARE
MODIFICARE = permissions.Azione.MODIFICARE
AMMINISTRARE = permissions.Azione.AMMINISTRARE

# I tre ruoli di progetto per esteso: servono a generare i casi della sezione 2.
RUOLI = list(ProjectRole)

# Le tre azioni che la matrice governa. AMMINISTRARE non e' della matrice: e'
# del creatore, e ha i suoi test nella sezione 7.
AZIONI_DELLA_MATRICE = [VEDERE, CARICARE, MODIFICARE]

# ===========================================================================
#  Attrezzi
# ===========================================================================


def nome_irripetibile(prefisso: str = "PROVA") -> str:
    """Un nome di classificazione che nel database non puo' gia' esserci.

    classifications.name ha un vincolo di unicita', e sul database di sviluppo
    ci sono le quattro classificazioni vere. E' la stessa medicina di
    modello_irripetibile() applicata ai nomi delle classi.
    """
    return f"{prefisso} {uuid.uuid4().hex[:8]}"


def crea_classificazione(db, permessi_per_ruolo=None) -> Classification:
    """Una classificazione nuova con le sue tre caselle della matrice.

    "permessi_per_ruolo" va da ProjectRole a una terna (vedere, caricare,
    modificare). Quello che non si nomina nasce chiuso, come nella pagina
    vera.
    """
    classe = Classification(
        name=nome_irripetibile(),
        description="Creata da un test.",
        sort_order=99,
        is_active=True,
    )
    db.add(classe)
    db.flush()

    permessi_per_ruolo = permessi_per_ruolo or {}
    for ruolo in ProjectRole:
        vedere, caricare, modificare = permessi_per_ruolo.get(
            ruolo, (False, False, False)
        )
        db.add(
            PermissionRule(
                project_role=ruolo,
                classification_id=classe.id,
                can_view=vedere,
                can_upload=caricare,
                can_edit=modificare,
            )
        )
    db.flush()
    return classe


def prepara_squadra(db):
    """Un progetto con dentro un responsabile, un ingegnere e un lettore.

    Restituisce (progetto, creatore, responsabile, ingegnere, lettore,
    estraneo). E' il palcoscenico di quasi tutti i test di questo file: le
    regole di accesso non si provano su una persona sola.

    Il **responsabile** e' il project manager del progetto, cioe' quello
    scritto in projects.project_manager_id: per lui la matrice non conta, puo'
    tutto sui documenti del suo progetto. L'**ingegnere** e il **lettore**
    sono assegnati con il loro ruolo, e per loro decide la matrice.
    L'**estraneo** e' entrato in Aurora e non e' assegnato a niente.
    """
    coda = uuid.uuid4().hex[:8]

    creatore = crea_utente(
        db, username=f"prova.capo.perm.{coda}", ruolo=GlobalRole.CREATORE
    )
    responsabile = crea_utente(db, username=f"prova.pm.perm.{coda}")
    ingegnere = crea_utente(db, username=f"prova.ing.perm.{coda}")
    lettore = crea_utente(db, username=f"prova.let.perm.{coda}")
    estraneo = crea_utente(db, username=f"prova.est.perm.{coda}")

    _prodotto, versione = crea_prodotto(db, autore=creatore)
    progetto = crea_progetto(
        db, versione, project_manager=responsabile, autore=creatore
    )

    projects.assegna(
        db,
        progetto=progetto,
        utente=ingegnere,
        ruolo=ProjectRole.INGEGNERE,
        autore=creatore,
    )
    projects.assegna(
        db,
        progetto=progetto,
        utente=lettore,
        ruolo=ProjectRole.LETTORE,
        autore=creatore,
    )
    db.flush()

    return progetto, creatore, responsabile, ingegnere, lettore, estraneo


def persona_con_ruolo(db, progetto, ruolo: ProjectRole, creatore):
    """Una persona nuova, assegnata al progetto con quel ruolo.

    Non riusa quelle di prepara_squadra() perche' i casi generati della
    sezione 2 hanno bisogno di una persona per ruolo che non sia anche il
    responsabile del progetto: il responsabile e' l'eccezione, e mescolarlo
    con la regola vorrebbe dire non provare ne' l'una ne' l'altra.
    """
    persona = crea_utente(
        db, username=f"prova.{ruolo.value[:4]}.{uuid.uuid4().hex[:8]}"
    )
    projects.assegna(
        db, progetto=progetto, utente=persona, ruolo=ruolo, autore=creatore
    )
    db.flush()
    return persona


# ===========================================================================
#  1. LA FUNZIONE CENTRALE
# ===========================================================================


def test_il_creatore_puo_tutto_su_tutto(db_session):
    """Il primo dei tre casi del modello: il creatore non ha limiti."""
    progetto, creatore, responsabile, *_ = prepara_squadra(db_session)
    documento, _ = crea_documento(db_session, progetto, responsabile)

    for azione in permissions.Azione:
        assert permissions.puo(db_session, creatore, azione, documento)
        assert permissions.puo(db_session, creatore, azione, progetto)
    assert permissions.puo(
        db_session, creatore, AMMINISTRARE, permissions.AMMINISTRAZIONE
    )


def test_il_project_manager_puo_tutto_sui_documenti_del_suo_progetto(db_session):
    """Il secondo caso: il responsabile passa sopra la matrice.

    La classificazione qui e' chiusa a tutti e tre i ruoli, compreso
    project_manager. Il responsabile ci accede lo stesso, perche' e' il
    responsabile di quel progetto e non perche' abbia quel ruolo: chi risponde
    di un progetto risponde anche delle offerte che ci stanno dentro.
    """
    progetto, _creatore, responsabile, *_ = prepara_squadra(db_session)
    chiusa = crea_classificazione(db_session)

    documento, _ = crea_documento(
        db_session, progetto, responsabile, classificazione=chiusa
    )

    for azione in AZIONI_DELLA_MATRICE:
        assert permissions.puo(db_session, responsabile, azione, documento), (
            f"il responsabile del progetto deve poter {azione.value} "
            "anche su una classificazione chiusa a tutti"
        )


def test_il_ruolo_project_manager_di_qualcun_altro_segue_la_matrice(db_session):
    """L'eccezione e' del **responsabile**, non di chiunque abbia quel ruolo.

    E' la distinzione che tiene in piedi la matrice: se bastasse avere il
    ruolo "project manager" in un progetto per passare sopra le caselle, la
    riga project_manager della griglia non deciderebbe piu' niente e chi la
    corregge lo farebbe a vuoto.
    """
    progetto, creatore, *_ = prepara_squadra(db_session)
    chiusa = crea_classificazione(db_session)
    altro_pm = persona_con_ruolo(
        db_session, progetto, ProjectRole.PROJECT_MANAGER, creatore
    )

    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=chiusa
    )

    assert not permissions.puo(db_session, altro_pm, VEDERE, documento)


def test_chi_non_e_assegnato_non_puo_niente(db_session):
    """Fuori dai tre casi del modello non c'e' accesso."""
    progetto, _creatore, responsabile, _ing, _let, estraneo = prepara_squadra(
        db_session
    )
    documento, _ = crea_documento(db_session, progetto, responsabile)

    for azione in permissions.Azione:
        assert not permissions.puo(db_session, estraneo, azione, documento)
        assert not permissions.puo(db_session, estraneo, azione, progetto)


def test_una_casella_che_manca_vale_no(db_session):
    """Il modo prudente di sbagliare: senza riga, niente permesso.

    Puo' succedere solo se qualcuno aggiunge una classificazione senza passare
    dalla pagina - la pagina le caselle le scrive tutte - ma quel qualcuno
    potrebbe essere una migrazione, o una riga scritta a mano nel database.
    """
    progetto, creatore, _responsabile, ingegnere, *_ = prepara_squadra(db_session)

    orfana = Classification(
        name=nome_irripetibile("ORFANA"), sort_order=99, is_active=True
    )
    db_session.add(orfana)
    db_session.flush()

    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=orfana
    )

    assert not permissions.puo(db_session, ingegnere, VEDERE, documento)


def test_su_un_oggetto_sconosciuto_puo_risponde_no(db_session):
    """Chi aggiunge un oggetto nuovo se ne accorge, invece di aprirlo a tutti."""
    _progetto, _creatore, _resp, ingegnere, *_ = prepara_squadra(db_session)

    assert not permissions.puo(db_session, ingegnere, VEDERE, "una stringa")


# ===========================================================================
#  2. OGNI COMBINAZIONE RUOLO x CLASSIFICAZIONE x AZIONE
# ===========================================================================
#
# Il criterio di accettazione principale della sessione. I casi si generano
# invece di scriverli: con tre ruoli, tre azioni e le due risposte possibili
# per casella sono decine di combinazioni, e scriverle a mano vorrebbe dire
# scriverne trentacinque giuste e una sbagliata.
#
# Ogni caso verifica **due cose insieme**, ed e' il punto: che puo() risponda
# come dice la casella, e che l'elenco - cioe' la condizione SQL - sia
# d'accordo. Le due strade devono dare la stessa risposta sempre, non quasi
# sempre.


@pytest.mark.parametrize("ruolo", RUOLI, ids=[r.value for r in RUOLI])
@pytest.mark.parametrize(
    "azione", AZIONI_DELLA_MATRICE, ids=[a.value for a in AZIONI_DELLA_MATRICE]
)
@pytest.mark.parametrize("consentito", [True, False], ids=["si", "no"])
def test_la_casella_della_matrice_decide(db_session, ruolo, azione, consentito):
    """La risposta di puo() e' esattamente quello che dice la casella.

    Si costruisce una classificazione con la casella (ruolo, azione) messa a
    "consentito" e tutto il resto chiuso, e si verifica che la risposta sia
    quella. Vale per tutte e nove le coppie ruolo/azione, in tutte e due le
    direzioni.
    """
    progetto, creatore, *_ = prepara_squadra(db_session)

    terna = tuple(
        consentito if altra is azione else False for altra in AZIONI_DELLA_MATRICE
    )
    classe = crea_classificazione(db_session, {ruolo: terna})

    persona = persona_con_ruolo(db_session, progetto, ruolo, creatore)
    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=classe
    )

    assert permissions.puo(db_session, persona, azione, documento) is consentito


@pytest.mark.parametrize("ruolo", RUOLI, ids=[r.value for r in RUOLI])
@pytest.mark.parametrize("consentito", [True, False], ids=["si", "no"])
def test_l_elenco_dice_la_stessa_cosa_della_scheda(db_session, ruolo, consentito):
    """La condizione SQL degli elenchi concorda con puo(), sempre.

    Sono le due strade di D-051: se divergessero, un elenco mostrerebbe righe
    che poi la scheda rifiuta di aprire, oppure - molto peggio - le
    nasconderebbe pur lasciandole aprire a chi ne scrive l'indirizzo.

    **Il conteggio conta insieme all'elenco.** Un documento invisibile che
    comparisse nel totale direbbe il numero esatto delle cose che non si
    dovrebbero sapere.
    """
    progetto, creatore, *_ = prepara_squadra(db_session)
    classe = crea_classificazione(
        db_session, {ruolo: (consentito, False, False)}
    )
    persona = persona_con_ruolo(db_session, progetto, ruolo, creatore)

    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=classe
    )

    trovati, totale = documents.cerca_documenti(
        db_session, persona, project_id=progetto.id
    )
    nell_elenco = documento.id in {trovato.id for trovato in trovati}

    assert nell_elenco is consentito
    assert nell_elenco is permissions.puo(db_session, persona, VEDERE, documento)
    assert totale == len(trovati), (
        "il totale dell'impaginazione conta righe che l'elenco non mostra"
    )
    assert documents.conta_documenti(db_session, persona, progetto.id) == totale


@pytest.mark.parametrize("ruolo", RUOLI, ids=[r.value for r in RUOLI])
def test_l_accesso_diretto_a_un_documento_non_visibile_risponde_404(
    client, db_session, ruolo
):
    """Il diniego non dice che l'oggetto esiste: 404, non 403.

    E la risposta e' **la stessa parola per parola** di quella che si riceve
    per un identificativo inventato: se differissero anche solo per una
    virgola, quella virgola direbbe a chi la nota che il documento c'e'.
    """
    progetto, creatore, *_ = prepara_squadra(db_session)
    chiusa = crea_classificazione(db_session)
    persona = persona_con_ruolo(db_session, progetto, ruolo, creatore)

    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=chiusa
    )
    db_session.flush()

    entra(client, persona.username, PASSWORD_DI_PROVA)

    negato = client.get(f"/documenti/{documento.id}")
    inventato = client.get(f"/documenti/{uuid.uuid4()}")

    assert negato.status_code == 404
    assert inventato.status_code == 404
    assert contenuto_leggibile(negato) == contenuto_leggibile(inventato)


@pytest.mark.parametrize(
    "azione", [CARICARE, MODIFICARE], ids=["caricare", "modificare"]
)
def test_chi_vede_ma_non_puo_riceve_403_con_la_spiegazione(
    client, db_session, azione
):
    """Il 403 resta per le operazioni: li' non c'e' piu' niente da nascondere.

    Chi il documento lo vede gia' sa che esiste. Rispondergli 404 lo
    manderebbe a cercare un guasto che non c'e' invece che a chiedere il
    permesso.
    """
    progetto, creatore, *_ = prepara_squadra(db_session)
    sola_lettura = crea_classificazione(
        db_session, {ProjectRole.LETTORE: (True, False, False)}
    )
    persona = persona_con_ruolo(
        db_session, progetto, ProjectRole.LETTORE, creatore
    )
    documento, _ = crea_documento(
        db_session, progetto, creatore, classificazione=sola_lettura
    )
    db_session.flush()

    entra(client, persona.username, PASSWORD_DI_PROVA)

    # La scheda si apre: il documento lo vede.
    assert client.get(f"/documenti/{documento.id}").status_code == 200

    indirizzo = (
        f"/documenti/{documento.id}/versione"
        if azione is CARICARE
        else f"/documenti/{documento.id}/stato?nuovo=in_verifica"
    )
    risposta = client.get(indirizzo)

    assert risposta.status_code == 403
    assert "ruolo" in contenuto_leggibile(risposta).lower()


# ===========================================================================
#  3. L'INGEGNERE E I DOCUMENTI COMMERCIALI
# ===========================================================================
#
# Il criterio scritto per esteso nella sessione: "un ingegnere non vede i
# documenti Commerciali: ne' in elenco, ne' in ricerca, ne' tramite URL
# diretto". Tre strade, tre verifiche, un test solo: se passassero due strade
# su tre il programma sarebbe rotto lo stesso.


def test_un_ingegnere_non_vede_i_documenti_commerciali(client, db_session):
    """Le tre strade insieme: elenco, ricerca, indirizzo diretto."""
    progetto, creatore, responsabile, ingegnere, *_ = prepara_squadra(db_session)

    # La classificazione "Commerciale" come la scrive scripts/seed.py:
    # l'ingegnere non ci puo' fare niente, il lettore nemmeno.
    commerciale = crea_classificazione(
        db_session,
        {
            ProjectRole.PROJECT_MANAGER: (True, True, True),
            ProjectRole.INGEGNERE: (False, False, False),
            ProjectRole.LETTORE: (False, False, False),
        },
    )
    tecnico = crea_classificazione(
        db_session,
        {
            ProjectRole.PROJECT_MANAGER: (True, True, True),
            ProjectRole.INGEGNERE: (True, True, True),
            ProjectRole.LETTORE: (True, False, False),
        },
    )

    titolo = f"Offerta al cliente {uuid.uuid4().hex[:8]}"
    offerta, _ = crea_documento(
        db_session,
        progetto,
        responsabile,
        titolo=titolo,
        classificazione=commerciale,
    )
    schema, _ = crea_documento(
        db_session,
        progetto,
        responsabile,
        titolo=f"Schema elettrico {uuid.uuid4().hex[:8]}",
        classificazione=tecnico,
    )
    db_session.flush()

    entra(client, ingegnere.username, PASSWORD_DI_PROVA)

    # 1. L'elenco: c'e' lo schema, non c'e' l'offerta. Si cerca il
    #    collegamento e non il titolo, perche' il titolo comparirebbe nella
    #    pagina anche solo perche' e' stato scritto nella casella di ricerca.
    elenco = client.get(f"/documenti?progetto={progetto.id}")
    assert elenco.status_code == 200
    testo = contenuto_leggibile(elenco)
    assert f"/documenti/{schema.id}" in testo
    assert f"/documenti/{offerta.id}" not in testo

    # 2. La ricerca per titolo: non trova niente, e il totale e' zero.
    ricerca = client.get(f"/documenti?q={titolo}")
    assert ricerca.status_code == 200
    assert f"/documenti/{offerta.id}" not in contenuto_leggibile(ricerca)

    trovati, totale = documents.cerca_documenti(db_session, ingegnere, testo=titolo)
    assert trovati == []
    assert totale == 0, (
        "il conteggio della ricerca conta un documento che l'ingegnere non vede"
    )

    # 3. L'indirizzo diretto: 404, non 403.
    diretto = client.get(f"/documenti/{offerta.id}")
    assert diretto.status_code == 404

    # 4. E nemmeno lo scarica.
    versione = documents.versioni_di(db_session, offerta.id)[0]
    scarico = client.get(
        f"/documenti/{offerta.id}/versioni/{versione.id}/scarica"
    )
    assert scarico.status_code == 404


def test_il_conteggio_del_progetto_non_conta_l_invisibile(db_session):
    """Un documento invisibile non compare nemmeno nei conteggi.

    E' la seconda meta' del requisito sugli elenchi: nascondere una riga e
    contarla lo stesso vuol dire pubblicare il numero esatto delle cose
    riservate.
    """
    progetto, creatore, responsabile, ingegnere, *_ = prepara_squadra(db_session)
    chiusa = crea_classificazione(db_session)
    aperta = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, False, False)}
    )

    crea_documento(db_session, progetto, responsabile, classificazione=chiusa)
    crea_documento(db_session, progetto, responsabile, classificazione=aperta)
    db_session.flush()

    assert documents.conta_documenti(db_session, ingegnere, progetto.id) == 1
    assert documents.conta_documenti(db_session, responsabile, progetto.id) == 2


# ===========================================================================
#  4. LE CLASSIFICAZIONI
# ===========================================================================


def test_una_classificazione_nuova_nasce_con_tutte_le_sue_caselle(db_session):
    """Creare una classe scrive anche le sue tre righe della matrice.

    E le scrive **chiuse**. Creare la classe e poi i permessi vorrebbe dire
    che fra i due momenti - due richieste diverse, con una persona in mezzo
    che potrebbe andare a pranzo - la classe esiste senza regole.
    """
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.classi.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )

    classe = permissions.crea_classificazione(
        db_session,
        nome=nome_irripetibile("NUOVA"),
        descrizione="Creata da un test.",
        autore=creatore,
    )
    db_session.flush()

    caselle = [
        casella
        for casella in permissions.matrice(db_session)
        if casella.classificazione.id == classe.id
    ]

    assert len(caselle) == len(ProjectRole)
    assert all(
        not (c.can_view or c.can_upload or c.can_edit) for c in caselle
    ), "una classificazione nuova non deve aprire niente a nessuno"


def test_una_classificazione_in_uso_non_si_disattiva(client, db_session):
    """Togliere la classe a un documento vuol dire lasciarlo senza regola."""
    progetto, creatore, responsabile, *_ = prepara_squadra(db_session)
    classe = crea_classificazione(db_session)
    crea_documento(db_session, progetto, responsabile, classificazione=classe)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.post(
        f"/permessi/classificazioni/{classe.id}/disattiva",
        data={"csrf": gettone_csrf(client, "/permessi/classificazioni")},
    )

    assert risposta.status_code == 400
    assert "non si puo' togliere" in contenuto_leggibile(risposta)

    db_session.refresh(classe)
    assert classe.is_active is True


def test_una_classificazione_libera_si_disattiva_e_si_riattiva(client, db_session):
    """Senza documenti addosso si toglie dai menu. Non si cancella niente."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.dis.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    classe = crea_classificazione(db_session)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    client.post(
        f"/permessi/classificazioni/{classe.id}/disattiva",
        data={"csrf": gettone_csrf(client, "/permessi/classificazioni")},
    )
    db_session.refresh(classe)
    assert classe.is_active is False

    # La riga c'e' ancora, con le sue caselle: non e' stato cancellato niente.
    assert permissions.trova_classificazione(db_session, classe.id) is not None
    assert classe not in permissions.elenco_classificazioni(db_session)
    assert classe in permissions.elenco_classificazioni(
        db_session, comprese_disattivate=True
    )

    client.post(
        f"/permessi/classificazioni/{classe.id}/riattiva",
        data={"csrf": gettone_csrf(client, "/permessi/classificazioni")},
    )
    db_session.refresh(classe)
    assert classe.is_active is True


def test_rinominare_una_classificazione_non_tocca_i_documenti(db_session):
    """I documenti puntano all'identificativo, non al nome."""
    progetto, creatore, responsabile, *_ = prepara_squadra(db_session)
    classe = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, False, False)}
    )
    documento, _ = crea_documento(
        db_session, progetto, responsabile, classificazione=classe
    )

    permissions.rinomina_classificazione(
        db_session,
        classe,
        nome=nome_irripetibile("RINOMINATA"),
        descrizione="Cambiata da un test.",
        autore=creatore,
    )
    db_session.flush()

    assert documento.classification_id == classe.id


def test_l_ordinamento_si_sposta_di_un_posto(db_session):
    """Su e giu' scambiano due vicine, non rinumerano tutte."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.ord.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    # Si creano dal servizio vero: e' lui che assegna l'ordinamento in fondo
    # all'elenco, e sono quindi due vicine per costruzione. Costruirle a mano
    # con lo stesso sort_order le lascerebbe ordinate per nome, e i nomi qui
    # sono casuali.
    prima = permissions.crea_classificazione(
        db_session, nome=nome_irripetibile("ORD-A"), descrizione="", autore=creatore
    )
    seconda = permissions.crea_classificazione(
        db_session, nome=nome_irripetibile("ORD-B"), descrizione="", autore=creatore
    )
    db_session.flush()

    elenco = permissions.elenco_classificazioni(db_session)
    posizione_prima = elenco.index(prima)
    posizione_seconda = elenco.index(seconda)
    assert posizione_seconda == posizione_prima + 1

    permissions.sposta_classificazione(
        db_session, seconda, verso="su", autore=creatore
    )
    db_session.flush()

    dopo = permissions.elenco_classificazioni(db_session)
    assert dopo.index(seconda) == posizione_prima
    assert dopo.index(prima) == posizione_seconda


def test_la_prima_non_sale_e_l_ultima_non_scende(db_session):
    """Ai bordi non succede niente, e non e' un errore."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.bordi.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    elenco = permissions.elenco_classificazioni(db_session, comprese_disattivate=True)
    if not elenco:
        pytest.skip("nessuna classificazione nel database")

    assert not permissions.sposta_classificazione(
        db_session, elenco[0], verso="su", autore=creatore
    )
    assert not permissions.sposta_classificazione(
        db_session, elenco[-1], verso="giu", autore=creatore
    )


def test_una_classificazione_disattivata_sparisce_dai_menu(db_session):
    """Chi carica non se la vede piu' proporre."""
    progetto, creatore, responsabile, ingegnere, *_ = prepara_squadra(db_session)
    classe = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, True, True)}
    )
    db_session.flush()

    caricabili = permissions.classificazioni_caricabili(
        db_session, progetto, ingegnere
    )
    assert classe in caricabili

    permissions.disattiva_classificazione(db_session, classe, autore=creatore)
    db_session.flush()

    assert classe not in permissions.classificazioni_caricabili(
        db_session, progetto, ingegnere
    )


def test_su_una_classificazione_disattivata_non_si_carica_piu(db_session):
    """Il menu non la propone, e la richiesta scritta a mano viene rifiutata.

    E' l'invariante che tiene in piedi tutto il resto: una classe si disattiva
    solo se non e' addosso a nessun documento, e da quel momento non ne accetta
    di nuovi. "Disattivata" vuol dire quindi "vuota per sempre", ed e' per
    questo che la griglia dei permessi puo' smettere di mostrarla.
    """
    progetto, creatore, _responsabile, ingegnere, *_ = prepara_squadra(db_session)
    classe = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, True, True)}
    )
    bersaglio = permissions.BersaglioCaricamento(
        progetto=progetto, classification_id=classe.id
    )

    assert permissions.puo(db_session, ingegnere, CARICARE, bersaglio)

    permissions.disattiva_classificazione(db_session, classe, autore=creatore)
    db_session.flush()

    assert not permissions.puo(db_session, ingegnere, CARICARE, bersaglio)


def test_la_griglia_non_mostra_le_classificazioni_disattivate(db_session):
    """Le loro caselle non governano piu' niente: mostrarle e' rumore."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.grig.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    classe = crea_classificazione(db_session)
    db_session.flush()

    assert any(
        casella.classificazione.id == classe.id
        for casella in permissions.matrice(db_session)
    )

    permissions.disattiva_classificazione(db_session, classe, autore=creatore)
    db_session.flush()

    assert not any(
        casella.classificazione.id == classe.id
        for casella in permissions.matrice(db_session)
    )


# ===========================================================================
#  5. LA PAGINA DELLA MATRICE
# ===========================================================================


def test_la_pagina_dei_permessi_e_riservata_al_creatore(client, db_session):
    """Il lucchetto e' la dipendenza sul router, non la voce di menu nascosta."""
    utente = crea_utente(
        db_session, username=f"prova.norm.perm.{uuid.uuid4().hex[:8]}"
    )
    db_session.flush()

    entra(client, utente.username, PASSWORD_DI_PROVA)

    for indirizzo in ("/permessi", "/permessi/classificazioni"):
        risposta = client.get(indirizzo)
        assert risposta.status_code == 403, indirizzo


def test_la_griglia_mostra_tutte_le_caselle(client, db_session):
    """Tutte, comprese quelle a permessi chiusi: una casella che manca e' una
    dimenticanza, e a distanza di mesi non si distingue da una decisione."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.griglia.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get("/permessi")

    assert risposta.status_code == 200

    classificazioni = permissions.elenco_classificazioni(db_session)
    attese = len(classificazioni) * len(ProjectRole) * len(
        permissions.PERMESSI_DELLA_MATRICE
    )
    assert risposta.text.count('type="checkbox"') == attese


def test_il_salvataggio_passa_da_una_conferma_e_registra_prima_e_dopo(
    client, db_session
):
    """Due passi: il primo mostra e non scrive, il secondo scrive e registra.

    Il registro conserva il valore precedente e quello successivo, come chiede
    il requisito 4 della sessione: "che cosa poteva vedere un ingegnere il 3
    marzo" e' una domanda a cui si deve poter rispondere.
    """
    from app.models import AuditLog
    from sqlalchemy import select

    creatore = crea_utente(
        db_session,
        username=f"prova.capo.salva.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    classe = crea_classificazione(db_session)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    campo = f"{ProjectRole.INGEGNERE.value}:{classe.id}:can_view"
    gettone = gettone_csrf(client, "/permessi")

    # Primo passo: la conferma. Non deve aver scritto niente.
    conferma = client.post(
        "/permessi",
        data={"csrf": gettone, f"{campo}.c": "1", campo: "si"},
    )
    assert conferma.status_code == 200
    assert "Conferma la correzione" in contenuto_leggibile(conferma)

    regola = db_session.scalars(
        select(PermissionRule).where(
            PermissionRule.project_role == ProjectRole.INGEGNERE,
            PermissionRule.classification_id == classe.id,
        )
    ).first()
    assert regola.can_view is False, "la conferma non deve scrivere niente"

    # Secondo passo: si applica quello che la conferma ha mostrato.
    applicata = client.post(
        "/permessi/applica",
        data={
            "csrf": gettone_csrf(client, "/permessi"),
            "cambiamento": [
                f"{campo}=si",
                f"{ProjectRole.INGEGNERE.value}:{classe.id}:can_upload=no",
                f"{ProjectRole.INGEGNERE.value}:{classe.id}:can_edit=no",
            ],
        },
        follow_redirects=False,
    )
    assert applicata.status_code == 303

    db_session.refresh(regola)
    assert regola.can_view is True

    riga = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == permissions.ACTION_MATRIX_CHANGED,
            AuditLog.entity_id == regola.id,
        )
    ).first()
    assert riga is not None
    assert riga.old_value["can_view"] is False
    assert riga.new_value["can_view"] is True
    assert riga.new_value["classificazione"] == classe.name


def test_salvare_senza_aver_cambiato_niente_non_chiede_conferma(client, db_session):
    """Chi preme Salva senza aver toccato nulla non deve confermare il nulla."""
    creatore = crea_utente(
        db_session,
        username=f"prova.capo.nulla.{uuid.uuid4().hex[:8]}",
        ruolo=GlobalRole.CREATORE,
    )
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)

    risposta = client.post(
        "/permessi",
        data={"csrf": gettone_csrf(client, "/permessi")},
        follow_redirects=False,
    )
    assert risposta.status_code == 303


# ===========================================================================
#  6. L'EFFETTO IMMEDIATO SULLE SESSIONI APERTE
# ===========================================================================


def test_la_matrice_corretta_ha_effetto_senza_riconnettersi(
    client, secondo_browser, db_session
):
    """Il criterio di accettazione, percorso da due browser insieme.

    Il primo browser e' l'ingegnere, che sta lavorando e non esce mai. Il
    secondo e' il creatore, che corregge la matrice. Alla pagina successiva
    l'ingegnere vede la differenza: i permessi si rileggono a ogni richiesta,
    non si tengono in memoria e non stanno nel cookie.
    """
    from sqlalchemy import select

    progetto, creatore, responsabile, ingegnere, *_ = prepara_squadra(db_session)
    chiusa = crea_classificazione(db_session)
    documento, _ = crea_documento(
        db_session, progetto, responsabile, classificazione=chiusa
    )
    db_session.flush()

    # L'ingegnere entra e non lo vede.
    entra(client, ingegnere.username, PASSWORD_DI_PROVA)
    assert client.get(f"/documenti/{documento.id}").status_code == 404

    # Il creatore, da un altro browser, apre quella casella.
    entra(secondo_browser, creatore.username, PASSWORD_DI_PROVA)
    campo = f"{ProjectRole.INGEGNERE.value}:{chiusa.id}:can_view"
    secondo_browser.post(
        "/permessi/applica",
        data={
            "csrf": gettone_csrf(secondo_browser, "/permessi"),
            "cambiamento": [f"{campo}=si"],
        },
        follow_redirects=False,
    )

    regola = db_session.scalars(
        select(PermissionRule).where(
            PermissionRule.project_role == ProjectRole.INGEGNERE,
            PermissionRule.classification_id == chiusa.id,
        )
    ).first()
    assert regola.can_view is True

    # L'ingegnere non ha fatto niente: nessuna uscita, nessun rientro, stesso
    # cookie di sessione. Alla pagina dopo il documento c'e'.
    assert client.get(f"/documenti/{documento.id}").status_code == 200

    # E funziona anche nell'altro verso: richiudendo la casella sparisce.
    secondo_browser.post(
        "/permessi/applica",
        data={
            "csrf": gettone_csrf(secondo_browser, "/permessi"),
            "cambiamento": [f"{campo}=no"],
        },
        follow_redirects=False,
    )
    assert client.get(f"/documenti/{documento.id}").status_code == 404


# ===========================================================================
#  7. LA VERIFICA DEGLI ACCESSI
# ===========================================================================


def test_la_verifica_accessi_e_riservata_al_creatore(client, db_session):
    utente = crea_utente(
        db_session, username=f"prova.norm.acc.{uuid.uuid4().hex[:8]}"
    )
    db_session.flush()

    entra(client, utente.username, PASSWORD_DI_PROVA)
    assert client.get(f"/utenti/{utente.id}/accessi").status_code == 403


def test_la_verifica_accessi_dice_quello_che_direbbe_la_pagina_vera(
    client, db_session
):
    """La pagina non ricalcola niente: chiede a puo(), come tutti.

    E' la ragione per cui questo test confronta la pagina con la funzione
    invece di confrontarla con una tabella scritta a mano: una pagina che
    serve a verificare le regole non puo' essere l'unica a usarne una diversa.
    """
    progetto, creatore, _responsabile, ingegnere, *_ = prepara_squadra(db_session)
    visibile = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, True, False)}
    )
    chiusa = crea_classificazione(db_session)
    db_session.flush()

    accessi = permissions.verifica_accessi(db_session, ingegnere)
    assert [a.progetto.id for a in accessi] == [progetto.id]

    per_classe = {
        riga.classificazione.id: riga for riga in accessi[0].righe
    }
    assert per_classe[visibile.id].vedere is True
    assert per_classe[visibile.id].caricare is True
    assert per_classe[visibile.id].modificare is False
    assert per_classe[chiusa.id].nessuno is True

    assert accessi[0].ruolo is ProjectRole.INGEGNERE
    assert accessi[0].e_responsabile is False

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    pagina = client.get(f"/utenti/{ingegnere.id}/accessi")

    assert pagina.status_code == 200
    testo = contenuto_leggibile(pagina)
    assert ingegnere.full_name in testo
    assert visibile.name in testo
    assert chiusa.name in testo


def test_la_verifica_accessi_dice_che_il_creatore_vede_tutto(client, db_session):
    """Per il creatore l'elenco dei progetti non e' il limite di quello che vede."""
    _progetto, creatore, *_ = prepara_squadra(db_session)
    db_session.flush()

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(f"/utenti/{creatore.id}/accessi")

    assert risposta.status_code == 200
    assert "ruolo di creatore" in contenuto_leggibile(risposta)


def test_la_verifica_accessi_di_chi_non_ha_niente(client, db_session):
    """Chi non e' assegnato a niente lo si vede scritto, non lo si deduce."""
    _progetto, creatore, _resp, _ing, _let, estraneo = prepara_squadra(db_session)
    db_session.flush()

    assert permissions.verifica_accessi(db_session, estraneo) == []

    entra(client, creatore.username, PASSWORD_DI_PROVA)
    risposta = client.get(f"/utenti/{estraneo.id}/accessi")

    assert risposta.status_code == 200
    assert "Nessun accesso" in contenuto_leggibile(risposta)


# ===========================================================================
#  8. LE VERIFICHE DI PERMESSO ESISTONO SOLO NELLA FUNZIONE CENTRALE
# ===========================================================================
#
# Questi tre test non guardano il comportamento: guardano i sorgenti. Servono
# a proteggere la regola piu' importante della sessione 7, che e' una regola
# di forma e non di funzionamento - "i permessi si decidono in un posto solo" -
# e le regole di forma, senza un test, durano fino alla prossima fretta.
#
# Diventano rossi se qualcuno, in buona fede, scrive un `if utente.is_creatore`
# dentro una rotta o un `{% if %}` sui permessi dentro un template. Il
# messaggio dice che cosa fare al posto suo.

RADICE = pathlib.Path(__file__).resolve().parent.parent / "app"

# Il file che ha il diritto di decidere, e quello che traduce la sua risposta
# in un codice HTTP.
DECIDE = RADICE / "services" / "permissions.py"
TRADUCE = RADICE / "dependencies.py"


def sorgenti_python() -> list[pathlib.Path]:
    """Tutti i .py di app/, tranne quello che i permessi li decide."""
    return [
        percorso
        for percorso in RADICE.rglob("*.py")
        if percorso != DECIDE and "__pycache__" not in percorso.parts
    ]


def test_nessun_file_legge_la_matrice_fuori_da_permissions(db_session):
    """permission_rules la interroga un file solo.

    Se la leggesse anche qualcun altro ci sarebbero due regole, e la seconda
    volta che si corregge la prima la seconda resta indietro. E' D-048,
    verificato invece che raccomandato.
    """
    # I due file che la **dichiarano** non la interrogano: uno e' la classe
    # della tabella, l'altro l'elenco dei modelli che Alembic deve vedere.
    dichiarano = {
        RADICE / "models" / "permission_rule.py",
        RADICE / "models" / "__init__.py",
    }

    colpevoli = []

    for percorso in sorgenti_python():
        if percorso in dichiarano:
            continue
        testo = percorso.read_text(encoding="utf-8")
        if "PermissionRule" in testo:
            colpevoli.append(percorso.relative_to(RADICE.parent))

    assert colpevoli == [], (
        "questi file leggono la matrice dei permessi per conto loro: "
        f"{colpevoli}. La matrice la legge app/services/permissions.py, e "
        "chi ha bisogno di una risposta chiama permissions.puo()"
    )


def test_il_ruolo_globale_si_guarda_solo_dove_si_decide(db_session):
    """`is_creatore` e `global_role` non compaiono in una rotta.

    Sono le due scritture con cui una verifica di permesso si intrufola dentro
    un file che parla d'altro. I posti in cui e' lecito guardarli sono tre: la
    funzione che decide, il modello che li dichiara, e users.ruolo_mostrato(),
    che non decide niente - sceglie il colore con cui scrivere il nome del
    ruolo.
    """
    permessi = {
        RADICE / "models" / "user.py",
        RADICE / "models" / "enums.py",
        RADICE / "models" / "__init__.py",
        RADICE / "services" / "users.py",
        RADICE / "routers" / "users.py",
    }

    colpevoli = []
    for percorso in sorgenti_python():
        if percorso in permessi:
            continue
        testo = percorso.read_text(encoding="utf-8")
        # Si guardano le righe di codice, non i commenti: la regola si spiega
        # nei commenti di mezzo programma, ed e' giusto cosi'.
        righe = [
            riga
            for riga in testo.splitlines()
            if not riga.lstrip().startswith("#")
            and ("is_creatore" in riga or "global_role" in riga)
        ]
        if righe:
            colpevoli.append((percorso.relative_to(RADICE.parent), righe[0].strip()))

    assert colpevoli == [], (
        "questi file guardano il ruolo globale di una persona per decidere "
        f"qualcosa: {colpevoli}. La domanda si fa con permissions.puo(), "
        "oppure con la dipendenza richiedi_creatore"
    )


def test_nessun_template_contiene_una_verifica_di_permesso(db_session):
    """Nei template non si decide niente: si disegna.

    Un `{% if utente.is_creatore %}` dentro una pagina e' la peggiore delle
    verifiche di permesso, perche' non protegge niente - la rotta si apre lo
    stesso scrivendone l'indirizzo - e sembra che protegga. Le pagine ricevono
    la risposta gia' pronta ("puo_amministrare", "permessi.caricare") e la
    usano per sapere se disegnare un pulsante.
    """
    vietate = ("is_creatore", "global_role", "PermissionRule", "permission_rules")

    colpevoli = []
    for percorso in (RADICE / "templates").rglob("*.html"):
        testo = percorso.read_text(encoding="utf-8")
        for parola in vietate:
            if parola in testo:
                colpevoli.append((percorso.relative_to(RADICE.parent), parola))

    assert colpevoli == [], (
        f"questi template guardano un ruolo o la matrice: {colpevoli}. "
        "La risposta la calcola la rotta con permissions.puo() e la passa al "
        "template come una variabile normale"
    )


def test_le_rotte_chiedono_i_permessi_alla_funzione_centrale(db_session):
    """Ogni rotta che tocca i permessi passa da permissions.

    Non e' un test di stile: e' la verifica che il file che decide sia davvero
    sulla strada obbligata. Un router che tocca documenti o progetti senza mai
    nominare permissions o richiedi_creatore sta decidendo per conto suo.
    """
    da_controllare = (
        "documents.py",
        "projects.py",
        "versions.py",
        "permissions.py",
        "phases.py",
        # La posta e' arrivata con la sessione 10: un messaggio si vede con la
        # stessa regola di un documento, trattato come classificazione
        # "Corrispondenza" (D-069).
        "emails.py",
    )

    for nome in da_controllare:
        testo = (RADICE / "routers" / nome).read_text(encoding="utf-8")
        assert (
            "permissions." in testo or "richiedi_creatore" in testo
        ), f"app/routers/{nome} non chiede mai niente a permissions.py"


# ===========================================================================
#  9. GLI ALTRI OGGETTI: PROGETTI E VERSIONI
# ===========================================================================


def test_il_filtro_dei_progetti_dice_la_stessa_cosa_di_puo(db_session):
    """Le due strade valgono anche per i progetti, non solo per i documenti."""
    progetto, _creatore, responsabile, ingegnere, _lettore, estraneo = (
        prepara_squadra(db_session)
    )

    for persona, atteso in (
        (responsabile, True),
        (ingegnere, True),
        (estraneo, False),
    ):
        nel_cruscotto = progetto.id in {
            p.id for p in projects.cruscotto(db_session, persona)
        }
        assert nel_cruscotto is atteso
        assert (
            permissions.puo(db_session, persona, VEDERE, progetto) is atteso
        ), f"{persona.username}: l'elenco e la scheda non sono d'accordo"


def test_solo_il_responsabile_modifica_la_versione(db_session):
    """La regola che stava in lifecycle.puo_cambiare_stato() e' rimasta uguale."""
    progetto, creatore, responsabile, ingegnere, *_ = prepara_squadra(db_session)
    versione = progetto.product_version

    assert permissions.puo(db_session, creatore, MODIFICARE, versione)
    assert permissions.puo(db_session, responsabile, MODIFICARE, versione)
    assert not permissions.puo(db_session, ingegnere, MODIFICARE, versione)

    # Ma la versione la vedono tutti: il catalogo dei prodotti e' il
    # vocabolario comune dell'azienda.
    assert permissions.puo(db_session, ingegnere, VEDERE, versione)


def test_un_documento_ritirato_lo_vede_solo_il_creatore(db_session):
    """Il ritiro e' logico, ma per chi non e' creatore e' come se non ci fosse."""
    progetto, creatore, responsabile, *_ = prepara_squadra(db_session)
    aperta = crea_classificazione(
        db_session,
        {
            ProjectRole.PROJECT_MANAGER: (True, True, True),
            ProjectRole.INGEGNERE: (True, True, True),
            ProjectRole.LETTORE: (True, True, True),
        },
    )
    documento, _ = crea_documento(
        db_session, progetto, responsabile, classificazione=aperta
    )
    ingegnere = persona_con_ruolo(
        db_session, progetto, ProjectRole.INGEGNERE, creatore
    )

    assert permissions.puo(db_session, ingegnere, VEDERE, documento)

    documents.elimina(db_session, documento=documento, autore=creatore)
    db_session.flush()

    assert not permissions.puo(db_session, ingegnere, VEDERE, documento)
    assert permissions.puo(db_session, creatore, VEDERE, documento)


def test_il_caricamento_verifica_la_classificazione_scelta_davvero(
    client, db_session
):
    """Il menu propone solo le classi consentite, ma non ci si fida del menu.

    La richiesta puo' arrivare scritta a mano: il permesso si chiede sulla
    coppia (progetto, classificazione) che e' arrivata davvero.
    """
    progetto, creatore, _responsabile, ingegnere, *_ = prepara_squadra(db_session)
    vietata = crea_classificazione(db_session)
    permessa = crea_classificazione(
        db_session, {ProjectRole.INGEGNERE: (True, True, True)}
    )
    db_session.flush()

    entra(client, ingegnere.username, PASSWORD_DI_PROVA)

    modulo = client.get(f"/documenti/nuovo?progetto={progetto.id}")
    assert modulo.status_code == 200
    assert permessa.name in contenuto_leggibile(modulo)
    assert vietata.name not in contenuto_leggibile(modulo)

    risposta = client.post(
        "/documenti/nuovo",
        data={
            "csrf": gettone_csrf(client, f"/documenti/nuovo?progetto={progetto.id}"),
            "progetto": str(progetto.id),
            "titolo": "Tentativo",
            "tipo": "Schema elettrico",
            "classificazione": str(vietata.id),
        },
        files={
            "file": (
                "prova.txt",
                io.BytesIO(contenuto_irripetibile()),
                "text/plain",
            )
        },
    )

    assert risposta.status_code == 403
    assert (
        db_session.query(Document)
        .filter(Document.title == "Tentativo")
        .count()
        == 0
    )
