"""Il ripristino di Aurora da una copia di sicurezza.

QUANDO SI USA QUESTO SCRIPT
---------------------------

In tre situazioni, e sono diverse fra loro:

  1. **il disco del server e' morto** e Aurora va rimessa in piedi su una
     macchina nuova;
  2. **qualcuno ha rovinato i dati** - una migrazione andata male, una
     cancellazione fatta con psql - e si vuole tornare a ieri sera;
  3. **si sta provando il ripristino**, su una macchina diversa, per sapere in
     anticipo che funziona. Questo e' l'uso piu' importante dei tre, ed e' il
     solo che si puo' fare con calma. **Una copia di sicurezza che non e' mai
     stata ripristinata non e' una copia di sicurezza: e' una speranza.**

CHE COSA FA, IN ORDINE
----------------------

    1. legge la copia e dice che cosa contiene, senza toccare niente
    2. chiede conferma, per esteso
    3. rimette il database con pg_restore
    4. rimette i file dell'archivio che mancano
    5. **verifica la coerenza**: per ogni impronta che il database nomina,
       controlla che il file ci sia davvero

Il passo 5 e' quello che distingue un ripristino da una speranza di
ripristino. Senza, si scopre che manca meta' dell'archivio il giorno in cui
qualcuno prova a scaricare un documento.

LE DUE CONFERME, E PERCHE' SONO DUE
------------------------------------

Questo script **sovrascrive un database**. Non c'e' modo di renderlo
innocuo, e quindi si e' scelto di renderlo difficile da eseguire per sbaglio:

  - la prima conferma chiede di scrivere per esteso il nome del database che
    si sta per sovrascrivere. Non "si", non "y": il nome. Chi lo scrive lo ha
    letto, e chi lo ha letto non sta ripristinando sul server sbagliato;
  - la seconda compare solo se il database di destinazione **non e' vuoto**, e
    dice quante righe si stanno per buttare via.

Con `--senza-conferme` si saltano tutte e due. Esiste per le prove
automatiche e per chi ripristina su una macchina appena installata; non va
scritto in nessuna procedura che qualcuno esegue a mano.

COME SI ESEGUE
--------------

Dalla radice del progetto, con l'ambiente virtuale attivo:

    python scripts/ripristino.py                        l'ultima copia
    python scripts/ripristino.py --copia aurora-2026-08-27_0300
    python scripts/ripristino.py --elenca               non ripristina niente
    python scripts/ripristino.py --solo-verifica        controlla e basta

Opzioni:

    --da PERCORSO        la cartella delle copie (di partenza: BACKUP_PATH)
    --copia NOME         quale copia usare (di partenza: la piu' recente)
    --elenca             mostra le copie disponibili e si ferma
    --solo-verifica      salta il ripristino e fa solo il controllo di
                         coerenza fra database e archivio
    --senza-conferme     non chiede niente. Vedi sopra.

CODICE DI USCITA
----------------

    0   ripristino riuscito e coerente
    1   ripristino non riuscito, o riuscito ma incoerente
    2   non e' potuto partire (copia non trovata, pg_restore assente)
    3   annullato da chi lo stava eseguendo

LA PROCEDURA COMPLETA, PASSO PER PASSO, E' IN docs/BACKUP_E_RIPRISTINO.md.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from scripts.backup import (  # noqa: E402
    CARTELLA_ARCHIVIO,
    FILE_DUMP,
    FILE_INFO,
    PREFISSO_COPIA,
    Collegamento,
    Guasto,
    misura,
    trova_programma,
)

# Quanto si aspetta pg_restore. Come per pg_dump: due ore, perche' un
# ripristino interrotto a meta' e' peggio di un ripristino lento.
TIMEOUT_SECONDI = 7200


# ---------------------------------------------------------------------------
#  1. TROVARE E LEGGERE LE COPIE
# ---------------------------------------------------------------------------


def copie_disponibili(cartella: Path) -> list[Path]:
    """Le copie complete che ci sono, dalla piu' recente.

    **Complete**: quelle che hanno dentro `informazioni.json`, che lo script di
    copia scrive per ultimo. Una cartella senza quel file e' una copia
    interrotta a meta', e proporla per un ripristino sarebbe il modo piu'
    diretto di far perdere dei dati a qualcuno.
    """
    if not cartella.is_dir():
        return []

    return sorted(
        (
            copia
            for copia in cartella.iterdir()
            if copia.is_dir()
            and copia.name.startswith(PREFISSO_COPIA)
            and (copia / FILE_INFO).is_file()
        ),
        key=lambda copia: copia.name,
        reverse=True,
    )


def leggi_informazioni(copia: Path) -> dict:
    """Il contenuto di `informazioni.json`. Dizionario vuoto se illeggibile."""
    try:
        return json.loads((copia / FILE_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def descrivi(copia: Path) -> None:
    """Stampa che cosa c'e' dentro una copia, prima di toccare niente."""
    informazioni = leggi_informazioni(copia)
    righe = informazioni.get("righe") or {}

    print(f"  Copia:        {copia.name}")
    print(f"  Eseguita il:  {informazioni.get('eseguita_il', 'non indicato')}")
    print(f"  Sulla macchina: {informazioni.get('macchina', 'non indicata')}")
    print(f"  Versione di Aurora: {informazioni.get('versione', 'non indicata')}")
    print(f"  Migrazione:   {informazioni.get('migrazione', 'non indicata')}")
    print(f"  Database:     {misura(informazioni.get('database_byte', 0))}")
    print(f"  Archivio:     {misura(informazioni.get('archivio_byte', 0))}")

    if righe:
        print("  Dentro c'erano:")
        for nome, quante in righe.items():
            print(f"    {nome:.<28} {quante}")


# ---------------------------------------------------------------------------
#  2. LE CONFERME
# ---------------------------------------------------------------------------


def conta_righe_attuali() -> dict[str, int]:
    """Quante righe ci sono adesso nel database di destinazione.

    Dizionario vuoto se il database non risponde o e' vuoto: e' il caso della
    macchina appena installata, e li' non c'e' niente da confermare.
    """
    try:
        from sqlalchemy import func, select

        from app.db import SessionLocal
        from app.models import AuditLog, Document, EmailMessage, Project, User

        with SessionLocal() as db:
            return {
                "utenti": db.scalar(select(func.count()).select_from(User)) or 0,
                "progetti": db.scalar(select(func.count()).select_from(Project)) or 0,
                "documenti": db.scalar(select(func.count()).select_from(Document)) or 0,
                "email": db.scalar(select(func.count()).select_from(EmailMessage)) or 0,
                "registro": db.scalar(select(func.count()).select_from(AuditLog)) or 0,
            }
    except Exception:
        return {}


def chiedi_conferme(collegamento: Collegamento) -> bool:
    """Le due domande. Restituisce False se chi risponde vuole fermarsi."""
    print("")
    print("  ATTENZIONE")
    print("  Il ripristino SOVRASCRIVE il database indicato qui sotto.")
    print(f"    server:   {collegamento.host}:{collegamento.porta}")
    print(f"    database: {collegamento.database}")
    print(f"    utente:   {collegamento.utente}")
    print("")

    attuali = conta_righe_attuali()
    se_ne_perdono = sum(attuali.values())

    if se_ne_perdono:
        print("  In questo database ci sono gia' dei dati, e andranno persi:")
        for nome, quante in attuali.items():
            print(f"    {nome:.<28} {quante}")
        print("")
        print("  Se non sei sicuro, fermati adesso e fai prima una copia di")
        print("  quello che c'e': python scripts/backup.py")
        print("")

    risposta = input(
        f"  Per continuare, scrivi il nome del database ({collegamento.database}): "
    ).strip()

    if risposta != collegamento.database:
        print("  Il nome non corrisponde: non e' stato ripristinato niente.")
        return False

    if se_ne_perdono:
        seconda = input(
            f"  Confermi di voler buttare via quelle {se_ne_perdono} righe? "
            "Scrivi SI: "
        ).strip()
        if seconda.upper() not in ("SI", "SÌ"):
            print("  Annullato: non e' stato ripristinato niente.")
            return False

    return True


# ---------------------------------------------------------------------------
#  3. IL RIPRISTINO DEL DATABASE
# ---------------------------------------------------------------------------


def ripristina_database(dump: Path, *, dire) -> None:
    """Rimette il database con pg_restore.

    **`--clean --if-exists` prima di ricreare.** Senza, un ripristino dentro un
    database che ha gia' le tabelle fallirebbe a meta' con centinaia di righe
    "l'oggetto esiste gia'", lasciando un database mezzo vecchio e mezzo nuovo,
    che e' il peggior risultato possibile: sembra funzionare.

    **Le righe di errore di pg_restore non fermano tutto.** Ce ne sono sempre
    alcune innocue - il tentativo di togliere un oggetto che non c'era, i
    permessi di un ruolo che su questa macchina non esiste - e trattarle come
    guasti vorrebbe dire che nessun ripristino su una macchina nuova riesce
    mai. Si guarda invece il codice di uscita, e quello che pg_restore ha
    scritto viene mostrato per intero: chi ripristina deve poterlo leggere.
    """
    pg_restore = trova_programma("pg_restore")
    if pg_restore is None:
        raise Guasto(
            "pg_restore non e' stato trovato. E' il programma con cui "
            "PostgreSQL rimette a posto un database salvato, e sta nella "
            "cartella «bin» dell'installazione di PostgreSQL. Scrivi quella "
            "cartella nel parametro POSTGRES_BIN_PATH del file .env."
        )

    collegamento = Collegamento(settings.DATABASE_URL)
    dire(f"  Ripristino di {collegamento.descrizione()} ...")

    comando = [
        pg_restore,
        "--host", collegamento.host,
        "--port", collegamento.porta,
        "--username", collegamento.utente,
        "--dbname", collegamento.database,
        # Toglie gli oggetti prima di ricrearli, senza lamentarsi di quelli
        # che non c'erano.
        "--clean",
        "--if-exists",
        # Va avanti anche se una singola istruzione fallisce: vedi sopra.
        "--no-owner",
        "--no-privileges",
        "--no-password",
        str(dump),
    ]

    try:
        esito = subprocess.run(
            comando,
            env=collegamento.ambiente(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDI,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as errore:
        raise Guasto(f"pg_restore non e' riuscito a partire: {errore}") from errore

    avvisi = [riga for riga in (esito.stderr or "").splitlines() if riga.strip()]

    if esito.returncode != 0 and not avvisi:
        raise Guasto(
            "pg_restore si e' fermato con un errore e non ha detto perche'. "
            "Controlla che il database esista gia' (va creato vuoto prima del "
            "ripristino) e che le credenziali di DATABASE_URL siano giuste."
        )

    if avvisi:
        dire("")
        dire(f"  pg_restore ha scritto {len(avvisi)} righe di segnalazione.")
        dire("  Le prime dieci:")
        for riga in avvisi[:10]:
            dire(f"    {riga}")
        dire("")
        dire(
            "  Le segnalazioni su oggetti che «non esistono» e sui permessi di "
            "ruoli assenti sono normali su una macchina nuova."
        )

    if esito.returncode != 0:
        dire("")
        dire(
            "  Attenzione: pg_restore si e' fermato con un codice di errore. "
            "La verifica di coerenza qui sotto dira' se il ripristino e' "
            "utilizzabile lo stesso."
        )


# ---------------------------------------------------------------------------
#  4. IL RIPRISTINO DEI FILE
# ---------------------------------------------------------------------------


def ripristina_archivio(sorgente: Path, destinazione: Path, *, dire) -> int:
    """Rimette nell'archivio i file che non ci sono. Restituisce quanti.

    **Non sovrascrive quello che c'e' gia'** e non cancella niente. Un file
    dell'archivio ha per nome l'impronta del proprio contenuto: se c'e' gia' un
    file con quel nome, il suo contenuto e' quello giusto per costruzione, e
    riscriverlo sarebbe lavoro sprecato su decine di gigabyte.
    """
    if not sorgente.is_dir():
        dire(
            f"  Attenzione: nella copia non c'e' nessun archivio dei file "
            f"({sorgente}). Il database verra' ripristinato lo stesso, ma i "
            "documenti non si scaricheranno."
        )
        return 0

    destinazione.mkdir(parents=True, exist_ok=True)
    rimessi = 0

    for file_sorgente in sorgente.rglob("*"):
        if not file_sorgente.is_file():
            continue

        relativa = file_sorgente.relative_to(sorgente)
        file_destinazione = destinazione / relativa

        if file_destinazione.is_file():
            continue

        file_destinazione.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(file_sorgente, file_destinazione)
            rimessi += 1
        except OSError as errore:
            raise Guasto(
                f"Non si e' riuscito a rimettere {relativa}: {errore}"
            ) from errore

    dire(f"  Archivio: {rimessi} file rimessi al loro posto.")
    return rimessi


# ---------------------------------------------------------------------------
#  5. LA VERIFICA DI COERENZA
# ---------------------------------------------------------------------------


def verifica_coerenza(*, dire) -> bool:
    """Controlla che ogni file nominato dal database esista sul disco.

    **E' il passo che distingue un ripristino da una speranza di ripristino.**
    Un database rimesso a posto e un archivio a meta' danno un programma che
    si apre, mostra gli elenchi, e non scarica niente: il genere di guasto che
    si scopre tre settimane dopo, quando la copia da cui si e' ripristinato
    non c'e' piu'.

    Usa la stessa funzione della pagina di diagnostica
    (`diagnostics.verifica_archivio`): quello che dice qui e' esattamente
    quello che dira' la riga «Integrita' dell'archivio» quando qualcuno aprira'
    la diagnostica domani mattina.
    """
    try:
        from app.db import SessionLocal
        from app.services import diagnostics
    except Exception as errore:  # noqa: BLE001
        dire(f"  Non si e' riuscito a verificare: {errore}")
        return False

    try:
        with SessionLocal() as db:
            esito = diagnostics.verifica_archivio(db, esempi=10)
            righe = diagnostics.stato_del_sistema(db)
    except Exception as errore:  # noqa: BLE001
        dire("")
        dire(f"  Il database non risponde: {errore}")
        return False

    dire("")
    dire("  VERIFICA DI COERENZA FRA DATABASE E ARCHIVIO")
    dire(f"    file attesi dal database ......... {esito.impronte_nel_database}")
    dire(f"    file trovati sul disco ........... {esito.oggetti_su_disco}")
    dire(f"    attesi e NON trovati ............. {esito.mancanti_su_disco}")
    dire(f"    trovati e non riferiti da nessuno  {esito.orfani_su_disco}")

    contenuto = righe.voce("contenuto")
    if contenuto is not None:
        dire("")
        dire("  QUANTO C'E' DENTRO ADESSO")
        for etichetta, valore in contenuto.dettagli:
            dire(f"    {etichetta:.<34} {valore}")

    if esito.mancanti_su_disco:
        dire("")
        dire("  IL RIPRISTINO NON E' COMPLETO.")
        dire(
            f"  Ci sono {esito.mancanti_su_disco} file che il database nomina e "
            "che sul disco non ci sono: quei documenti compariranno negli "
            "elenchi e non si scaricheranno."
        )
        dire("  Prime impronte mancanti:")
        for impronta in esito.esempi_mancanti:
            dire(f"    {impronta}")
        dire("")
        dire(
            "  Che fare: controlla che STORAGE_PATH nel file .env punti alla "
            "cartella giusta, e che nella copia di sicurezza ci fosse "
            "l'archivio (la cartella «archivio/» accanto alle copie del "
            "database)."
        )
        return False

    dire("")
    dire("  Il ripristino e' coerente: ogni file nominato dal database c'e'.")
    return True


# ---------------------------------------------------------------------------
#  6. IL GIRO COMPLETO
# ---------------------------------------------------------------------------


def main() -> int:
    """Legge le opzioni, chiede le conferme, ripristina, verifica."""
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    argomenti = argparse.ArgumentParser(
        description="Ripristino di Aurora da una copia di sicurezza.",
    )
    argomenti.add_argument("--da", default=None, help="la cartella delle copie")
    argomenti.add_argument("--copia", default=None, help="quale copia usare")
    argomenti.add_argument(
        "--elenca", action="store_true", help="mostra le copie e si ferma"
    )
    argomenti.add_argument(
        "--solo-verifica",
        action="store_true",
        help="non ripristina: controlla soltanto la coerenza",
    )
    argomenti.add_argument(
        "--senza-conferme",
        action="store_true",
        help="non chiede niente (per le prove automatiche)",
    )
    scelte = argomenti.parse_args()

    def dire(riga: str) -> None:
        print(riga)

    print("")
    print("Ripristino di Aurora")
    print("=" * 62)

    if scelte.solo_verifica:
        return 0 if verifica_coerenza(dire=dire) else 1

    cartella = Path(scelte.da).expanduser() if scelte.da else settings.backup_dir
    copie = copie_disponibili(cartella)

    if not copie:
        print("")
        print(f"  In {cartella} non c'e' nessuna copia completa.")
        print("")
        print("  Una copia e' completa quando ha dentro il file")
        print("  informazioni.json, che viene scritto per ultimo: una cartella")
        print("  senza quel file e' una copia interrotta a meta'.")
        print("")
        return 2

    if scelte.elenca:
        print("")
        print(f"  Copie disponibili in {cartella}:")
        print("")
        for copia in copie:
            informazioni = leggi_informazioni(copia)
            print(
                f"    {copia.name}   "
                f"{informazioni.get('eseguita_il', '')}   "
                f"database {misura(informazioni.get('database_byte', 0))}"
            )
        print("")
        return 0

    if scelte.copia:
        scelta = cartella / scelte.copia
        if scelta not in copie:
            print("")
            print(f"  La copia «{scelte.copia}» non esiste o non e' completa.")
            print("  Le copie disponibili si vedono con --elenca.")
            print("")
            return 2
    else:
        scelta = copie[0]

    print("")
    descrivi(scelta)

    dump = scelta / FILE_DUMP
    if not dump.is_file():
        print("")
        print(f"  In questa copia non c'e' il salvataggio del database ({FILE_DUMP}).")
        print("")
        return 2

    collegamento = Collegamento(settings.DATABASE_URL)

    if not scelte.senza_conferme and not chiedi_conferme(collegamento):
        return 3

    print("")
    try:
        ripristina_database(dump, dire=dire)
        ripristina_archivio(
            cartella / CARTELLA_ARCHIVIO, settings.storage_dir, dire=dire
        )
    except Guasto as guasto:
        print("", file=sys.stderr)
        print("  IL RIPRISTINO NON E' RIUSCITO", file=sys.stderr)
        print(f"  {guasto}", file=sys.stderr)
        print("", file=sys.stderr)
        return 1

    coerente = verifica_coerenza(dire=dire)

    print("")
    if coerente:
        print("  FATTO. Aurora si puo' riavviare.")
        print("")
        print("  Due cose da controllare subito dopo:")
        print("    1. il file .env di questa macchina punta al database giusto")
        print("       e ha la cartella dell'archivio giusta;")
        print("    2. l'irrobustimento del registro va rifatto sul database")
        print("       ripristinato:  psql -U postgres -d aurora")
        print("                           -f scripts/hardening_db.sql")
        print("")
    return 0 if coerente else 1


if __name__ == "__main__":
    raise SystemExit(main())
