"""Verifica la catena di impronte del registro delle operazioni.

A CHE COSA SERVE
----------------

Ogni voce di `audit_logs` porta l'impronta SHA-256 della voce precedente. Chi
cambia una riga scavalcando il programma - con `psql`, con le credenziali di
chi amministra il database - non riesce a rendere di nuovo giusta la catena
senza rifare **tutte** le impronte successive una per una.

Questo script ricalcola tutta la catena e dice se torna. Non impedisce niente:
rende visibile.

Non e' un compito che si fa una volta. Va eseguito:

  - **dopo l'installazione**, come collaudo (vedi scripts/hardening_db.md);
  - **prima di una verifica aziendale**, per poter dire che il registro non e'
    stato toccato e mostrarlo;
  - **dopo qualunque intervento sul database** fatto a mano;
  - **ogni tanto**, per abitudine. Un controllo che si fa solo quando si
    sospetta qualcosa non serve a scoprire quello che non si sospetta.

Dalla sessione 11 si potra' agganciarlo ai lavori notturni di APScheduler.

COME SI ESEGUE
--------------

Dalla radice del progetto, con l'ambiente virtuale attivo:

    python scripts/verifica_audit.py

Opzioni:

    --dal N     riprende dalla voce numero N invece che dalla prima. Utile su
                un registro di milioni di righe, quando si vuole controllare
                solo l'ultimo periodo. **Attenzione**: partendo da N, l'aggancio
                della voce N alla N-1 non si puo' verificare, perche' la N-1
                non viene letta. Lo script lo dice.
    --silenzioso  stampa solo in caso di anomalie. E' la forma da usare in un
                lavoro pianificato: un controllo che scrive qualcosa ogni notte
                e' un controllo che dopo un mese nessuno legge piu'.

CODICE DI USCITA
----------------

    0   la catena e' integra
    1   sono state trovate anomalie
    2   la verifica non e' potuta partire (database irraggiungibile)

E' quello che serve a un lavoro pianificato per decidere se mandare un
messaggio a qualcuno.

CHE COSA SIGNIFICA UN'ANOMALIA
-------------------------------

Non significa per forza che qualcuno abbia manomesso il registro. Puo' anche
voler dire che il ripristino di una copia di sicurezza e' stato fatto a meta',
o che qualcuno ha spostato righe fra due database. Significa pero' sempre la
stessa cosa: **da quel punto in avanti il registro non dimostra piu' niente**,
e chi lo usa per rispondere a una verifica deve saperlo.
"""

import argparse
import sys
from pathlib import Path

# Lo script sta in scripts/ e importa il programma, che sta in app/: senza
# questa riga "python scripts/verifica_audit.py" non troverebbe il pacchetto.
# E' la stessa riga che hanno gli altri script della cartella.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.services import registro  # noqa: E402

# Quante anomalie si scrivono per esteso prima di fermarsi al conteggio. Se il
# registro e' stato riscritto da capo ce ne sono decine di migliaia, e
# stamparle tutte non aiuta nessuno: la prima e' quella che dice dove si e'
# rotto.
MASSIMO_ANOMALIE_STAMPATE = 20


def leggi_argomenti() -> argparse.Namespace:
    """Gli argomenti della riga di comando."""
    analizzatore = argparse.ArgumentParser(
        description=(
            "Ricalcola la catena di impronte del registro delle operazioni "
            "di Aurora e segnala le anomalie."
        )
    )
    analizzatore.add_argument(
        "--dal",
        type=int,
        default=1,
        metavar="N",
        help=(
            "riprende dalla voce numero N invece che dalla prima. L'aggancio "
            "della voce N a quella precedente non viene verificato."
        ),
    )
    analizzatore.add_argument(
        "--silenzioso",
        action="store_true",
        help="stampa soltanto in caso di anomalie (per i lavori pianificati)",
    )
    return analizzatore.parse_args()


def main() -> int:
    """Esegue la verifica e restituisce il codice di uscita."""
    argomenti = leggi_argomenti()

    def dire(messaggio: str = "") -> None:
        """Stampa, a meno che non sia stato chiesto il silenzio."""
        if not argomenti.silenzioso:
            print(messaggio)

    db = SessionLocal()
    try:
        try:
            esito = registro.verifica_catena(db, dal_numero=argomenti.dal)
        except SQLAlchemyError as errore:
            # Si stampa anche in modalita' silenziosa: un controllo che non e'
            # riuscito a partire e' una notizia, non un silenzio.
            print(
                "Il database non risponde, quindi la verifica non e' stata "
                f"fatta. Dettaglio tecnico: {errore}",
                file=sys.stderr,
            )
            return 2
    finally:
        db.close()

    dire()
    dire("=== Verifica del registro delle operazioni di Aurora ===")
    dire()
    dire(f"Voci esaminate: {esito.voci_esaminate}")
    if argomenti.dal > 1:
        dire(
            f"Verifica ripresa dalla voce {argomenti.dal}: l'aggancio di "
            "quella voce alla precedente non e' stato controllato, perche' la "
            "precedente non e' stata letta."
        )
    dire()

    if esito.integro:
        dire("La catena e' INTEGRA.")
        dire()
        dire(
            "Ogni voce corrisponde alla propria impronta e si aggancia a "
            "quella prima. Nessuna riga e' stata modificata o tolta dopo la "
            "scrittura."
        )
        dire()
        return 0

    # Le anomalie si stampano sempre, anche in modalita' silenziosa: e' l'unica
    # cosa per cui questo script esiste.
    print()
    print("=== ANOMALIE NEL REGISTRO DELLE OPERAZIONI DI AURORA ===")
    print()
    print(f"Voci esaminate: {esito.voci_esaminate}")
    print(f"Anomalie trovate: {len(esito.anomalie)}")
    print()

    for anomalia in esito.anomalie[:MASSIMO_ANOMALIE_STAMPATE]:
        print(f"  voce {anomalia.seq} [{anomalia.genere}]")
        print(f"    {anomalia.spiegazione}")
        print()

    restanti = len(esito.anomalie) - MASSIMO_ANOMALIE_STAMPATE
    if restanti > 0:
        print(f"  ...e altre {restanti} anomalie non elencate.")
        print()

    print("Che cosa vuol dire.")
    print()
    print(
        "  Qualcuno ha modificato o tolto delle righe di audit_logs\n"
        "  scavalcando Aurora: il programma non ci riesce, perche' l'utente\n"
        "  con cui si collega non ha il permesso di modificare quella\n"
        "  tabella (scripts/hardening_db.sql). E' stato fatto con le\n"
        "  credenziali di chi amministra il database."
    )
    print()
    print(
        "  Puo' anche essere il segno di un ripristino incompleto di una\n"
        "  copia di sicurezza, o di righe spostate fra due database. In\n"
        "  tutti i casi il significato pratico e' lo stesso: da quel punto\n"
        "  in avanti il registro non dimostra piu' niente."
    )
    print()
    print("Che cosa fare.")
    print()
    print(
        "  1. non toccare niente: il database in questo stato e' la prova;\n"
        "  2. avvisare chi risponde del sistema informativo;\n"
        "  3. controllare i registri di PostgreSQL e di Windows per capire\n"
        "     chi si e' collegato al database e quando;\n"
        "  4. confrontare con l'ultima esportazione CSV del registro, se ce\n"
        "     n'e' una: le impronte ci sono anche li', e dicono com'era.\n"
        "     Le esportazioni sono a loro volta registrate (audit.exported)."
    )
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
