"""Archivia su file compresso le voci piu' vecchie del registro.

LA POLITICA DI CONSERVAZIONE DI AURORA, IN UNA RIGA
----------------------------------------------------

**Le voci del registro non si cancellano mai.** Nemmeno le piu' vecchie,
nemmeno quelle archiviate da questo script, nemmeno quando il database diventa
grosso. E' la regola 5 di CLAUDE.md applicata alla tabella a cui si applica
peggio: un registro con dentro un buco, in sede di verifica, non vale come un
registro con dentro tutto - vale come un registro assente, perche' nessuno puo'
dimostrare che il buco fosse innocente.

Questo script quindi **copia**, non sposta. Scrive un file `.csv.gz` con le
voci piu' vecchie di N anni e lascia il database esattamente com'era. Il file
serve a due cose: a poterlo consegnare a chi verifica senza dargli accesso al
programma, e a tenere una copia fuori dal database, dove un ripristino
sbagliato non la puo' toccare.

Se un giorno il database dovesse davvero diventare ingestibile - non e' il caso
di un'azienda con qualche decina di persone e qualche migliaio di righe l'anno
- la risposta sara' una tabella storica, non un DELETE. E la decisione andra'
presa da chi risponde dei dati, non da uno script.

NON SI ESEGUE DA SOLO
---------------------

Questo file non e' agganciato a nessun lavoro pianificato, e non va agganciato
senza pensarci. E' scritto per essere lanciato a mano, da una persona che sa
perche' lo sta facendo e dove va a finire il file che ne esce. Vedi
docs/DECISIONI.md, D-065.

L'archiviazione **e' registrata**: scrivere un archivio significa far uscire
una copia del registro da Aurora, e come l'esportazione in CSV lascia una riga
nel registro stesso (`audit.archived`). E' l'unica scrittura che fa.

COME SI ESEGUE
--------------

Dalla radice del progetto, con l'ambiente virtuale attivo:

    python scripts/archivia_audit.py --anni 5

Opzioni:

    --anni N       archivia le voci piu' vecchie di N anni. Senza, sono 5.
    --cartella P   dove scrivere il file. Senza, e' "storage/archivio-audit".
    --prova        dice che cosa farebbe e non scrive niente.

CODICE DI USCITA
----------------

    0   fatto (anche quando non c'era niente da archiviare)
    1   qualcosa e' andato storto
"""

import argparse
import csv
import gzip
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Lo script sta in scripts/ e importa il programma, che sta in app/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import AuditLog  # noqa: E402
from app.services import audit, registro  # noqa: E402

# Quanti anni si tengono nel database prima di considerare una voce "vecchia".
# Cinque perche' e' il periodo che l'azienda tiene la documentazione di un
# progetto chiuso; si cambia dalla riga di comando, non modificando questa
# riga.
ANNI_PREDEFINITI = 5

# Dove finiscono i file, se non si dice altro. Sotto storage/ perche' e' la
# cartella che va nei backup del server (vedi scripts/setup_postgres.md).
CARTELLA_PREDEFINITA = Path("storage") / "archivio-audit"

# Quante righe si leggono per volta. Un registro di cinque anni non entra in
# memoria, e uno strumento che va in difficolta' proprio sugli archivi grossi
# non serve a niente.
BLOCCO = 1000


def leggi_argomenti() -> argparse.Namespace:
    """Gli argomenti della riga di comando."""
    analizzatore = argparse.ArgumentParser(
        description=(
            "Copia su file compresso le voci del registro piu' vecchie di N "
            "anni. Non cancella niente dal database."
        )
    )
    analizzatore.add_argument(
        "--anni",
        type=int,
        default=ANNI_PREDEFINITI,
        metavar="N",
        help=f"archivia le voci piu' vecchie di N anni (predefinito: "
        f"{ANNI_PREDEFINITI})",
    )
    analizzatore.add_argument(
        "--cartella",
        type=Path,
        default=CARTELLA_PREDEFINITA,
        metavar="P",
        help=f"cartella in cui scrivere (predefinito: {CARTELLA_PREDEFINITA})",
    )
    analizzatore.add_argument(
        "--prova",
        action="store_true",
        help="dice che cosa farebbe, senza scrivere niente",
    )
    return analizzatore.parse_args()


def main() -> int:
    """Scrive l'archivio e restituisce il codice di uscita."""
    argomenti = leggi_argomenti()

    if argomenti.anni < 1:
        print(
            "L'intervallo dev'essere di almeno un anno: archiviare quello di "
            "ieri non ha senso, e il file sarebbe indistinguibile da "
            "un'esportazione fatta dalla pagina /registro.",
            file=sys.stderr,
        )
        return 1

    # Un anno e' 365 giorni e non si fa piu' preciso di cosi': la soglia di
    # un'archiviazione non e' una data di scadenza, e nessuno la porta in
    # tribunale per un giorno.
    limite = datetime.now(timezone.utc) - timedelta(days=365 * argomenti.anni)

    db = SessionLocal()
    try:
        try:
            return _archivia(db, argomenti, limite)
        except SQLAlchemyError as errore:
            db.rollback()
            print(
                "Il database non risponde, quindi non e' stato archiviato "
                f"niente. Dettaglio tecnico: {errore}",
                file=sys.stderr,
            )
            return 1
        except OSError as errore:
            db.rollback()
            print(
                "Il file dell'archivio non si e' potuto scrivere, quindi non "
                f"e' stato archiviato niente. Dettaglio tecnico: {errore}",
                file=sys.stderr,
            )
            return 1
    finally:
        db.close()


def _archivia(db, argomenti, limite: datetime) -> int:
    """Il lavoro vero, con il database gia' aperto.

    **Le voci non si leggono tutte insieme.** Prima si chiede al database
    quante sono e da quale numero a quale - tre valori, una interrogazione
    sola - e poi si scorrono a blocchi, scrivendole via via sul file. Un
    registro di cinque anni non entra in memoria, e uno strumento che va in
    difficolta' proprio sugli archivi grossi non serve a niente.
    """
    quante, dalla, alla = db.execute(
        select(
            func.count(AuditLog.seq),
            func.min(AuditLog.seq),
            func.max(AuditLog.seq),
        ).where(AuditLog.occurred_at < limite)
    ).one()

    print()
    print("=== Archiviazione del registro delle operazioni di Aurora ===")
    print()
    print(f"Soglia: voci precedenti al {limite.astimezone():%d/%m/%Y}")
    print(f"Voci da archiviare: {quante}")

    if not quante:
        print()
        print(
            "Non c'e' niente da archiviare: nel registro non ci sono voci "
            f"piu' vecchie di {argomenti.anni} anni."
        )
        print()
        return 0

    print(f"Dalla voce {dalla} alla voce {alla}")

    nome = (
        f"registro-aurora-fino-al-{limite.astimezone():%Y%m%d}"
        f"-voci-{dalla}-{alla}.csv.gz"
    )
    destinazione = argomenti.cartella / nome
    print(f"File: {destinazione}")
    print()

    if argomenti.prova:
        print("Modalita' prova: non e' stato scritto niente.")
        print()
        return 0

    argomenti.cartella.mkdir(parents=True, exist_ok=True)

    voci = db.scalars(
        select(AuditLog)
        .where(AuditLog.occurred_at < limite)
        .order_by(AuditLog.seq)
        .execution_options(yield_per=BLOCCO)
    )

    # newline="" come vuole il modulo csv, e il BOM in cima come per
    # l'esportazione dalla pagina: il file lo apre una persona con Excel, e
    # senza BOM le lettere accentate diventano geroglifici (D-066).
    with gzip.open(destinazione, "wt", encoding="utf-8", newline="") as archivio:
        archivio.write("﻿")
        scrittore = csv.writer(archivio, delimiter=";", lineterminator="\r\n")
        scrittore.writerow(list(registro.COLONNE_CSV))
        for blocco in voci.partitions():
            scrittore.writerows(registro.righe_csv(blocco, intestazione=False))

    dimensione = destinazione.stat().st_size

    # L'archiviazione e' un'operazione come le altre e lascia la sua traccia.
    # E' anche l'unica riga che questo script scrive nel database.
    audit.record(
        db,
        action=audit.ACTION_AUDIT_ARCHIVED,
        entity_type=audit.ENTITY_SISTEMA,
        user_id=None,
        new_value={
            "file": str(destinazione),
            "voci": quante,
            "dalla_voce": dalla,
            "alla_voce": alla,
            "soglia": limite.isoformat(),
            "byte": dimensione,
        },
        description=(
            f"Registro archiviato su file compresso: {quante} voci "
            f"(dalla {dalla} alla {alla}), precedenti al "
            f"{limite.astimezone():%d/%m/%Y}, nel file {destinazione.name}. "
            "Nessuna voce e' stata cancellata dal database."
        ),
    )
    db.commit()

    print(f"Scritto: {dimensione} byte.")
    print()
    print(
        "**Nel database non e' stato cancellato niente.** Le voci archiviate\n"
        "ci sono ancora tutte, e la catena delle impronte resta intera: e' la\n"
        "politica di conservazione di Aurora, spiegata in cima a questo file\n"
        "e in docs/DECISIONI.md, D-065."
    )
    print()
    print(
        "Il file va messo dove va messo il resto: nei backup del server, e in\n"
        "una copia fuori dal server. Contiene le impronte di ogni voce,\n"
        "quindi si puo' verificare anche a distanza di anni."
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
