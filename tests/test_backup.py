"""Test della copia di sicurezza e del ripristino.

    pytest tests/test_backup.py -v

**Che cosa si prova qui e che cosa no.** Si prova tutto quello che si puo'
provare senza un secondo database: la copia incrementale dell'archivio, la
rotazione, il riconoscimento di una copia interrotta, la lettura della stringa
di collegamento, il ripristino dei file e la verifica di coerenza.

Il giro completo `pg_dump` → `pg_restore` su un database vuoto **non si prova
qui**, e la ragione e' che creare un database richiede i diritti di
superutente, che l'utente con cui gira Aurora giustamente non ha (vedi
`scripts/setup_postgres.md`). Quella prova la fa una persona, una volta, su una
macchina diversa dal server, e la procedura passo per passo e' in
`docs/BACKUP_E_RIPRISTINO.md`, sezione 7. **E' la prova piu' importante di
tutte**, ed e' anche l'unica che un test automatico non puo' sostituire: una
copia di sicurezza che non e' mai stata ripristinata su un'altra macchina non
e' una copia di sicurezza, e' una speranza.

Quello che pero' si prova, e che vale piu' di quanto sembri, e' che `pg_dump`
**esista e funzioni davvero** su questa macchina: il test lo esegue e rilegge
il file che ne esce con `pg_restore --list`. Se `pg_dump` non c'e', il test
viene saltato invece che fallito - manca un pezzo di ambiente, non e' il codice
a essere sbagliato.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Backup
from scripts import backup as copia
from scripts import ripristino


@pytest.fixture
def senza_tracce_di_copia():
    """Toglie dal database le righe di `backups` scritte durante il test.

    **E' l'unica pulizia esplicita dei test di Aurora**, e serve perche' lo
    script della copia apre una sessione sua e fa commit: la transazione
    annullata di `db_session` non lo copre, e senza questa fixture ogni giro di
    pytest lascerebbe una copia finta nel database di sviluppo - che la pagina
    di diagnostica mostrerebbe come se fosse vera.

    Il DELETE qui non contraddice la regola 5 di CLAUDE.md: `backups` non
    contiene dati dell'azienda, contiene il verbale di una manutenzione, e
    quella manutenzione non e' mai avvenuta.
    """
    with SessionLocal() as fuori:
        prima = fuori.scalar(select(func.max(Backup.started_at)))

    yield

    with SessionLocal() as fuori:
        condizione = (
            Backup.started_at > prima if prima is not None else Backup.id.is_not(None)
        )
        for riga in fuori.scalars(select(Backup).where(condizione)).all():
            fuori.delete(riga)
        fuori.commit()


# ===========================================================================
#  1. LA STRINGA DI COLLEGAMENTO
# ===========================================================================


def test_la_stringa_di_collegamento_si_scompone_nei_pezzi_di_pg_dump():
    """pg_dump vuole host, porta, utente e database separati, non un indirizzo."""
    pezzi = copia.Collegamento(
        "postgresql+psycopg://aurora_app:segreta@srv-aurora:5433/aurora"
    )

    assert pezzi.host == "srv-aurora"
    assert pezzi.porta == "5433"
    assert pezzi.utente == "aurora_app"
    assert pezzi.password == "segreta"
    assert pezzi.database == "aurora"


def test_i_caratteri_speciali_della_password_si_decodificano():
    """Nel .env i caratteri speciali sono codificati in percentuale.

    "p@ss" si scrive "p%40ss", e passandolo a pg_dump cosi' com'e' la
    password sarebbe sbagliata. E' il genere di guasto che si manifesta solo
    in produzione, dove le password non sono "aurora_dev".
    """
    pezzi = copia.Collegamento(
        "postgresql+psycopg://aurora_app:p%40ss%3Aword@localhost:5432/aurora"
    )
    assert pezzi.password == "p@ss:word"


def test_la_password_non_finisce_nella_riga_di_comando():
    """Gli argomenti di un processo si leggono da Gestione attivita'."""
    pezzi = copia.Collegamento(
        "postgresql+psycopg://aurora_app:segretissima@localhost:5432/aurora"
    )

    assert pezzi.ambiente()["PGPASSWORD"] == "segretissima"
    assert "segretissima" not in pezzi.descrizione()


# ===========================================================================
#  2. LA COPIA INCREMENTALE DELL'ARCHIVIO
# ===========================================================================


def archivio_finto(radice: Path, quanti: int = 3) -> Path:
    """Un finto archivio con la stessa forma di quello vero.

    Due livelli di cartelle da due caratteri, come `storage/objects`, piu' le
    cartelle che non vanno copiate: cosi' il test verifica anche le esclusioni.
    """
    sorgente = radice / "storage"

    for numero in range(quanti):
        impronta = f"{numero:02x}" + uuid.uuid4().hex[:62]
        percorso = sorgente / "objects" / impronta[:2] / impronta[2:4] / impronta
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(f"contenuto {numero}".encode("utf-8"))

    (sorgente / "tmp").mkdir(parents=True, exist_ok=True)
    (sorgente / "tmp" / "a-meta.parziale").write_bytes(b"caricamento interrotto")

    (sorgente / "posta" / "elaborate").mkdir(parents=True, exist_ok=True)
    (sorgente / "posta" / "elaborate" / "uno.eml").write_bytes(b"From: x")

    (sorgente / "posta_graph.json").write_text("{}", encoding="utf-8")

    return sorgente


def test_la_prima_copia_prende_tutto(tmp_path):
    """Su una destinazione vuota si copia ogni file."""
    sorgente = archivio_finto(tmp_path, quanti=5)
    destinazione = tmp_path / "copie" / "archivio"

    copiati, saltati, byte = copia.copia_archivio(
        sorgente, destinazione, dire=lambda _riga: None
    )

    assert copiati == 5
    assert saltati == 0
    assert byte > 0


def test_la_seconda_copia_non_riscrive_niente(tmp_path):
    """E' la copia incrementale, ed e' il punto di tutta la procedura."""
    sorgente = archivio_finto(tmp_path, quanti=5)
    destinazione = tmp_path / "copie" / "archivio"

    copia.copia_archivio(sorgente, destinazione, dire=lambda _r: None)
    copiati, saltati, _byte = copia.copia_archivio(
        sorgente, destinazione, dire=lambda _r: None
    )

    assert copiati == 0, "un file gia' copiato non va riscritto"
    assert saltati == 5


def test_un_file_nuovo_si_aggiunge_agli_altri(tmp_path):
    """Il caso di tutte le notti: tre file nuovi su decine di migliaia."""
    sorgente = archivio_finto(tmp_path, quanti=3)
    destinazione = tmp_path / "copie" / "archivio"
    copia.copia_archivio(sorgente, destinazione, dire=lambda _r: None)

    impronta = "ff" + uuid.uuid4().hex[:62]
    nuovo = sorgente / "objects" / impronta[:2] / impronta[2:4] / impronta
    nuovo.parent.mkdir(parents=True, exist_ok=True)
    nuovo.write_bytes(b"caricato stamattina")

    copiati, saltati, _byte = copia.copia_archivio(
        sorgente, destinazione, dire=lambda _r: None
    )

    assert copiati == 1
    assert saltati == 3


def test_un_file_copiato_a_meta_viene_riscritto(tmp_path):
    """Il confronto e' anche sulla dimensione, non solo sul nome.

    Il nome di un file dell'archivio **e'** l'impronta del suo contenuto,
    quindi lo stesso nome vuol dire lo stesso contenuto. Resta il caso di una
    copia interrotta a meta' file: nome giusto, contenuto sbagliato. Quella si
    riscrive.
    """
    sorgente = archivio_finto(tmp_path, quanti=1)
    destinazione = tmp_path / "copie" / "archivio"
    copia.copia_archivio(sorgente, destinazione, dire=lambda _r: None)

    troncato = next(percorso for percorso in destinazione.rglob("*") if percorso.is_file())
    troncato.write_bytes(b"tron")

    copiati, _saltati, _byte = copia.copia_archivio(
        sorgente, destinazione, dire=lambda _r: None
    )
    assert copiati == 1


def test_le_cartelle_di_transito_non_si_copiano(tmp_path):
    """tmp, posta e il segnalibro restano fuori: sono file di passaggio."""
    sorgente = archivio_finto(tmp_path, quanti=2)
    destinazione = tmp_path / "copie" / "archivio"

    copia.copia_archivio(sorgente, destinazione, dire=lambda _r: None)

    assert not (destinazione / "tmp").exists(), "i caricamenti interrotti non si copiano"
    assert not (destinazione / "posta").exists(), "i messaggi in transito non si copiano"
    assert not (destinazione / "posta_graph.json").exists()
    assert (destinazione / "objects").is_dir(), "l'archivio vero invece si copia"


def test_una_cartella_nuova_dentro_storage_si_copia_da_sola(tmp_path):
    """L'elenco e' di esclusioni, non di inclusioni: e' voluto.

    Una cartella che una sessione futura aggiungera' dentro `storage/` finira'
    nelle copie senza che nessuno debba ricordarsene. Per una copia di
    sicurezza, sbagliare per eccesso e' l'unico modo sensato di sbagliare.
    """
    sorgente = archivio_finto(tmp_path, quanti=1)
    (sorgente / "qualcosa-di-nuovo").mkdir()
    (sorgente / "qualcosa-di-nuovo" / "dato.bin").write_bytes(b"importante")

    destinazione = tmp_path / "copie" / "archivio"
    copia.copia_archivio(sorgente, destinazione, dire=lambda _r: None)

    assert (destinazione / "qualcosa-di-nuovo" / "dato.bin").is_file()


def test_un_archivio_che_non_esiste_e_un_guasto_con_una_frase(tmp_path):
    """Non un'eccezione tecnica: una frase che dice che cosa controllare."""
    with pytest.raises(copia.Guasto) as errore:
        copia.copia_archivio(
            tmp_path / "non-esiste", tmp_path / "copie", dire=lambda _r: None
        )

    assert "STORAGE_PATH" in str(errore.value)


# ===========================================================================
#  3. LA ROTAZIONE
# ===========================================================================


def crea_copia_finta(cartella: Path, nome: str, *, completa: bool = True) -> Path:
    """Una cartella con la forma di una copia. Con o senza il file finale."""
    copia_finta = cartella / nome
    copia_finta.mkdir(parents=True, exist_ok=True)
    (copia_finta / copia.FILE_DUMP).write_bytes(b"finto salvataggio")
    if completa:
        (copia_finta / copia.FILE_INFO).write_text("{}", encoding="utf-8")
    return copia_finta


def test_la_rotazione_tiene_le_ultime_e_butta_le_piu_vecchie(tmp_path):
    """Il nome contiene la data con l'anno davanti: si ordina da solo."""
    for giorno in range(20, 30):
        crea_copia_finta(tmp_path, f"aurora-2026-08-{giorno}_0300")

    tolte = copia.ruota(tmp_path, tieni=3, dire=lambda _r: None)

    assert len(tolte) == 7
    restano = sorted(
        percorso.name for percorso in tmp_path.iterdir() if percorso.is_dir()
    )
    assert restano == [
        "aurora-2026-08-27_0300",
        "aurora-2026-08-28_0300",
        "aurora-2026-08-29_0300",
    ]


def test_la_rotazione_non_tocca_l_archivio_dei_file(tmp_path):
    """L'archivio non invecchia: un salvataggio del database si', lui no.

    Cancellare da li' vorrebbe dire perdere il contenuto di un documento, che
    e' esattamente la cosa che questa procedura esiste per impedire.
    """
    archivio = tmp_path / copia.CARTELLA_ARCHIVIO
    archivio.mkdir()
    (archivio / "un-file").write_bytes(b"contenuto")

    for giorno in range(20, 30):
        crea_copia_finta(tmp_path, f"aurora-2026-08-{giorno}_0300")

    copia.ruota(tmp_path, tieni=1, dire=lambda _r: None)

    assert (archivio / "un-file").is_file(), (
        "la rotazione ha toccato l'archivio dei file: non deve mai farlo"
    )


def test_una_copia_interrotta_non_conta_come_copia(tmp_path):
    """Senza informazioni.json e' una copia a meta', e non va tenuta al posto
    di una buona."""
    for giorno in (20, 21, 22):
        crea_copia_finta(tmp_path, f"aurora-2026-08-{giorno}_0300")
    crea_copia_finta(tmp_path, "aurora-2026-08-23_0300", completa=False)
    crea_copia_finta(tmp_path, "aurora-2026-08-24_0300", completa=False)

    copia.ruota(tmp_path, tieni=3, dire=lambda _r: None)

    restano = {percorso.name for percorso in tmp_path.iterdir() if percorso.is_dir()}
    assert "aurora-2026-08-23_0300" not in restano, (
        "le copie interrotte si tolgono per prime"
    )
    assert {"aurora-2026-08-20_0300", "aurora-2026-08-21_0300",
            "aurora-2026-08-22_0300"} <= restano


# ===========================================================================
#  4. IL RIPRISTINO
# ===========================================================================


def test_il_ripristino_vede_solo_le_copie_complete(tmp_path):
    """Proporre una copia a meta' e' il modo piu' diretto di far perdere dati."""
    crea_copia_finta(tmp_path, "aurora-2026-08-25_0300")
    crea_copia_finta(tmp_path, "aurora-2026-08-26_0300", completa=False)
    crea_copia_finta(tmp_path, "aurora-2026-08-27_0300")

    trovate = [percorso.name for percorso in ripristino.copie_disponibili(tmp_path)]

    assert trovate == ["aurora-2026-08-27_0300", "aurora-2026-08-25_0300"], (
        "vanno elencate solo le copie complete, dalla piu' recente"
    )


def test_il_ripristino_rimette_i_file_che_mancano(tmp_path):
    """E non tocca quelli che ci sono gia'."""
    dalla_copia = tmp_path / "copia" / "archivio"
    dalla_copia.mkdir(parents=True)
    (dalla_copia / "3f").mkdir()
    (dalla_copia / "3f" / "uno").write_bytes(b"dalla copia")
    (dalla_copia / "3f" / "due").write_bytes(b"anche questo")

    archivio = tmp_path / "storage"
    (archivio / "3f").mkdir(parents=True)
    (archivio / "3f" / "uno").write_bytes(b"gia' presente, diverso")

    rimessi = ripristino.ripristina_archivio(
        dalla_copia, archivio, dire=lambda _r: None
    )

    assert rimessi == 1
    assert (archivio / "3f" / "due").read_bytes() == b"anche questo"
    assert (archivio / "3f" / "uno").read_bytes() == b"gia' presente, diverso", (
        "un file gia' presente non si sovrascrive: il nome e' l'impronta del "
        "contenuto, quindi quello che c'e' e' gia' quello giusto"
    )


def test_una_copia_senza_archivio_non_ferma_il_ripristino(tmp_path):
    """Il database si ripristina lo stesso, e lo script lo dice."""
    detto: list[str] = []
    rimessi = ripristino.ripristina_archivio(
        tmp_path / "non-esiste", tmp_path / "storage", dire=detto.append
    )

    assert rimessi == 0
    assert any("non c'e' nessun archivio" in riga for riga in detto)


# ===========================================================================
#  5. pg_dump ESISTE E FUNZIONA DAVVERO
# ===========================================================================


def test_pg_dump_si_trova_e_produce_un_file_leggibile(tmp_path):
    """Il giro vero: si salva il database e si rilegge l'indice del file.

    E' l'unica cosa della copia che non si puo' simulare senza perdere il
    senso: un file troncato esiste e non e' vuoto, e la sola prova che valga
    e' rileggerlo con lo stesso strumento che dovra' ripristinarlo.

    Se pg_dump non c'e', si salta: manca un pezzo di ambiente, non e' il
    codice a essere sbagliato. La riga che lo dice e' la stessa che comparira'
    a chi installa Aurora e si dimentica POSTGRES_BIN_PATH.
    """
    if copia.trova_programma("pg_dump") is None:
        pytest.skip(
            "pg_dump non trovato: scrivere POSTGRES_BIN_PATH nel file .env. "
            "Vedi docs/BACKUP_E_RIPRISTINO.md, sezione 3."
        )

    destinazione = tmp_path / "database.dump"
    byte = copia.salva_database(destinazione, dire=lambda _r: None)

    assert destinazione.is_file()
    assert byte > 0
    assert byte == destinazione.stat().st_size

    # verifica_dump solleva se il file non si riesce a rileggere.
    copia.verifica_dump(destinazione, dire=lambda _r: None)


def test_il_giro_completo_scrive_una_copia_completa(tmp_path, senza_tracce_di_copia):
    """Copia vera, con destinazione dentro la cartella temporanea del test.

    Non tocca la cartella delle copie della macchina: `--destinazione` esiste
    apposta, e un test che scrivesse nella destinazione vera farebbe ruotare
    via una copia buona di qualcun altro.
    """
    if copia.trova_programma("pg_dump") is None:
        pytest.skip("pg_dump non trovato")

    destinazione = tmp_path / "copie"
    uscita = copia.esegui(
        destinazione=destinazione,
        tieni=3,
        con_database=True,
        con_archivio=True,
        dire=lambda _r: None,
    )

    assert uscita == 0, "la copia doveva riuscire"

    copie = ripristino.copie_disponibili(destinazione)
    assert len(copie) == 1

    informazioni = json.loads(
        (copie[0] / copia.FILE_INFO).read_text(encoding="utf-8")
    )
    assert informazioni["programma"] == "Aurora"
    assert informazioni["migrazione"], "manca il numero della migrazione"
    assert informazioni["righe"], "mancano i conteggi che servono al ripristino"
    assert (copie[0] / copia.FILE_DUMP).is_file()
    assert (destinazione / copia.CARTELLA_ARCHIVIO).is_dir()


def test_la_copia_lascia_la_sua_riga_nella_tabella(
    tmp_path, db_session, senza_tracce_di_copia
):
    """La diagnostica legge quella riga: senza, non saprebbe niente."""
    if copia.trova_programma("pg_dump") is None:
        pytest.skip("pg_dump non trovato")

    prima = db_session.scalar(select(func.count()).select_from(Backup)) or 0

    copia.esegui(
        destinazione=tmp_path / "copie",
        tieni=3,
        con_database=True,
        con_archivio=False,
        dire=lambda _r: None,
    )

    # Lo script apre una sessione sua e fa commit: la riga c'e' davvero nel
    # database, fuori dalla transazione del test. Si rilegge da li'; a
    # toglierla ci pensa la fixture.
    with SessionLocal() as fuori:
        dopo = fuori.scalar(select(func.count()).select_from(Backup)) or 0
        assert dopo == prima + 1, "la copia deve lasciare la sua riga"

        ultima = fuori.scalars(
            select(Backup).order_by(Backup.started_at.desc()).limit(1)
        ).first()
        assert ultima.riuscito
        assert ultima.database_bytes > 0
        assert ultima.finished_at is not None
        assert ultima.hostname


def test_la_riga_si_apre_prima_di_cominciare(
    tmp_path, monkeypatch, senza_tracce_di_copia
):
    """Una copia interrotta lascia comunque traccia, con esito "in_corso".

    Scrivendo solo alla fine, una copia interrotta sarebbe indistinguibile da
    una copia che nessuno ha mai programmato: sono due guasti diversi con due
    rimedi diversi.
    """
    from app.models.backup import ESITO_IN_CORSO

    def si_rompe_subito(*_argomenti, **_parole):
        raise copia.Guasto("guasto inventato dal test")

    monkeypatch.setattr(copia, "salva_database", si_rompe_subito)

    with SessionLocal() as fuori:
        prima = fuori.scalar(select(func.count()).select_from(Backup)) or 0

    uscita = copia.esegui(
        destinazione=tmp_path / "copie",
        tieni=3,
        con_database=True,
        con_archivio=False,
        dire=lambda _r: None,
    )
    assert uscita == 1

    with SessionLocal() as fuori:
        dopo = fuori.scalar(select(func.count()).select_from(Backup)) or 0
        assert dopo == prima + 1

        ultima = fuori.scalars(
            select(Backup).order_by(Backup.started_at.desc()).limit(1)
        ).first()
        assert not ultima.riuscito
        assert ultima.outcome != ESITO_IN_CORSO, (
            "la riga va chiusa anche quando la copia fallisce"
        )
        assert "guasto inventato" in (ultima.message or "")


# ===========================================================================
#  6. LA VERIFICA DI COERENZA
# ===========================================================================


def test_la_verifica_di_coerenza_usa_la_stessa_funzione_della_diagnostica():
    """Quello che dice il ripristino e' quello che dira' la pagina domani.

    E' un test che legge i sorgenti: se un giorno il ripristino si scrivesse
    un proprio confronto fra database e archivio, i due comincerebbero a dire
    cose diverse e nessuno saprebbe a quale credere.
    """
    testo = Path(ripristino.__file__).read_text(encoding="utf-8")

    assert "diagnostics.verifica_archivio" in testo, (
        "il ripristino deve verificare con la stessa funzione della "
        "diagnostica, non con un confronto suo"
    )


def test_la_data_nel_nome_si_ordina_da_sola():
    """Con "27-08-2026" la rotazione butterebbe via la copia sbagliata."""
    momento = datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)
    nome = momento.strftime(copia.FORMATO_DATA)

    assert nome == "2026-08-27_0300"
    assert "2026-08-26_0300" < nome < "2026-08-28_0300"
