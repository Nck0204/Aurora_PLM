"""Dati iniziali di Aurora.

Riempie un database appena migrato con il minimo indispensabile perche' il
programma sia utilizzabile:

  - un utente creatore, "admin", con una password casuale stampata una volta
    sola e da cambiare al primo accesso;
  - le classificazioni dei documenti;
  - la griglia dei permessi di partenza, tutte le sue caselle;
  - il modello di fasi di partenza, versione 1, con le sue fasi e le due
    proprieta' che le governano.

**Che cosa sono quelle classificazioni e quelle fasi non e' scritto qui.** Si
legge da `config/dati_iniziali.toml`, che e' lo stesso file che legge la
configurazione guidata del primo avvio (/primo-avvio): le due strade
d'installazione devono dare lo stesso sistema, e fino alla sessione 12 erano
due elenchi scritti in due posti. Le fasi, in piu', non potrebbero stare dentro
`app/`: sono dati e non codice (D-055).

**Dalla sessione 12 questo script non e' piu' la strada normale.** Chi installa
Aurora apre il programma e segue la procedura guidata, che fa le stesse cose
con una spiegazione accanto a ciascuna. Questo resta per chi preferisce la riga
di comando e per le installazioni non presidiate.

Come si esegue, dalla radice del progetto e con l'ambiente virtuale attivo:

    python scripts/seed.py

**E' idempotente**: eseguirlo due volte non duplica niente. Ogni pezzo viene
cercato prima di essere creato, usando il nome che lo identifica davvero (il
nome utente, il nome della classificazione, la coppia ruolo/classificazione,
la coppia nome/versione del modello di fasi). Al secondo giro non scrive nulla
e lo dice.

Nota sulla password. Dalla sessione 3 la password viene generata e cifrata
dalle funzioni di app/services/passwords.py, le stesse che usa la gestione
utenti: quattro parole italiane unite da trattini, impronta argon2id. Cosi' la
password dei dati iniziali si detta al telefono come tutte le altre, e non
esiste un secondo modo di trattare le password sparso per il programma.
"""

import sys
from pathlib import Path

# Questo script viene lanciato dalla riga di comando, quindi la radice del
# progetto non e' automaticamente fra le cartelle in cui Python cerca i moduli.
# Gliela aggiungiamo, altrimenti "import app..." qui sotto fallirebbe.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Classification,
    GlobalRole,
    PermissionRule,
    Phase,
    PhaseTemplate,
    ProjectRole,
    User,
)
from app.services import initial_data, passwords  # noqa: E402

# --- Costanti dei dati iniziali ---------------------------------------------

ADMIN_USERNAME = "admin"
ADMIN_FIRST_NAME = "Amministratore"
ADMIN_LAST_NAME = "Aurora"

# Indirizzo di comodo: va corretto con quello vero al primo accesso, altrimenti
# le notifiche destinate all'amministratore non arriveranno a nessuno.
ADMIN_EMAIL = "admin@aurora.local"

# --- I dati iniziali, che non stanno qui -----------------------------------
#
# Le classificazioni, la griglia dei permessi e il percorso delle fasi si
# leggono da **config/dati_iniziali.toml**, lo stesso file che legge la
# configurazione guidata del primo avvio (/primo-avvio). Fino alla sessione 12
# erano scritti qui dentro e anche li', e bastava correggerne uno perche' due
# installazioni dessero due sistemi diversi.
#
# Le fasi, in particolare, non possono stare dentro app/: sono dati e non
# codice (D-055), e c'e' un test che diventa rosso se un nome di fase ricompare
# li' dentro. Averli in un file di configurazione risolve tutte e due le cose.


# La versione con cui nasce il modello di fasi. E' sempre 1: i modelli sono
# immutabili, e una correzione diventa una versione nuova creata
# dall'interfaccia, non una modifica di questa.
PHASE_TEMPLATE_VERSION = 1


def dati_iniziali():
    """Legge config/dati_iniziali.toml. Si ferma se non si riesce a leggerlo.

    A differenza del programma - che deve partire comunque e lo dice nella
    configurazione guidata - **questo script si ferma**: e' stato lanciato
    apposta per creare quei dati, e riempire il database a meta' sarebbe
    peggio che non riempirlo affatto.
    """
    letti = initial_data.dati()
    if not letti.leggibili:
        raise SystemExit(
            f"\n  Errore: {letti.problema}\n"
            f"  Il file atteso e': {settings.initial_data_config}\n"
        )
    return letti


# --- Creazione dei singoli pezzi --------------------------------------------


def ensure_admin_user(db: Session) -> str | None:
    """Crea l'utente creatore "admin" se non c'e' gia'.

    Restituisce la password in chiaro se l'utente e' stato creato adesso, None
    se esisteva gia'. La password in chiaro vive solo il tempo di stamparla:
    nel database entra soltanto l'impronta argon2.
    """
    existing = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
    if existing is not None:
        return None

    password = passwords.generate_password()

    admin = User(
        username=ADMIN_USERNAME,
        first_name=ADMIN_FIRST_NAME,
        last_name=ADMIN_LAST_NAME,
        email=ADMIN_EMAIL,
        password_hash=passwords.hash_password(password),
        must_change_password=True,
        is_active=True,
        global_role=GlobalRole.CREATORE,
    )
    db.add(admin)
    db.flush()

    return password


def ensure_classifications(db: Session, dati) -> int:
    """Crea le classificazioni mancanti. Restituisce quante ne ha create."""
    created = 0

    for position, classe in enumerate(dati.classificazioni, start=1):
        existing = db.scalar(
            select(Classification).where(Classification.name == classe.nome)
        )
        if existing is not None:
            continue

        db.add(
            Classification(
                name=classe.nome,
                description=classe.descrizione,
                sort_order=position,
            )
        )
        created += 1

    db.flush()
    return created


def ensure_permission_rules(db: Session, dati) -> int:
    """Crea le caselle mancanti della matrice dei permessi.

    Restituisce quante ne ha create. Le caselle gia' presenti non vengono
    toccate: se qualcuno ha corretto i permessi dall'interfaccia, rieseguire
    questo script non glieli riporta indietro. E' voluto, lo script mette i
    dati di partenza, non li impone.
    """
    classifications = {
        classification.name: classification
        for classification in db.scalars(select(Classification)).all()
    }

    created = 0

    for role in ProjectRole:
        per_classification = (dati.permessi or {}).get(role.value, {})
        for classification_name, permessi in per_classification.items():
            can_view, can_upload, can_edit = permessi
            classification = classifications.get(classification_name)
            if classification is None:
                # Una casella che nomina una classificazione che non c'e': il
                # file di configurazione e' incoerente. Si salta invece di
                # fermarsi, e la casella mancante varra' "no" - che e' la
                # scelta prudente.
                continue

            existing = db.scalar(
                select(PermissionRule).where(
                    PermissionRule.project_role == role,
                    PermissionRule.classification_id == classification.id,
                )
            )
            if existing is not None:
                continue

            db.add(
                PermissionRule(
                    project_role=role,
                    classification_id=classification.id,
                    can_view=can_view,
                    can_upload=can_upload,
                    can_edit=can_edit,
                )
            )
            created += 1

    db.flush()
    return created


def ensure_phase_template(db: Session, dati) -> int:
    """Crea il modello di fasi di partenza, versione 1, con le sue fasi.

    Restituisce quante fasi ha creato, zero se il modello c'era gia'. Il
    modello si cerca per la coppia (nome, versione) perche' e' quella che lo
    identifica: i modelli sono immutabili e le correzioni diventano una
    versione nuova, non una modifica di questa.
    """
    existing = db.scalar(
        select(PhaseTemplate).where(
            PhaseTemplate.name == dati.modello_fasi,
            PhaseTemplate.version == PHASE_TEMPLATE_VERSION,
        )
    )
    if existing is not None:
        return 0

    template = PhaseTemplate(
        name=dati.modello_fasi,
        description=dati.descrizione_modello,
        standards=[],
        is_active=True,
        version=PHASE_TEMPLATE_VERSION,
    )
    db.add(template)
    db.flush()

    for position, fase in enumerate(dati.fasi, start=1):
        db.add(
            Phase(
                phase_template_id=template.id,
                name=fase.nome,
                sort_order=position,
                description=fase.descrizione,
                blocks_return=fase.blocca_ritorno,
                closes_project=fase.chiude_progetto,
            )
        )

    db.flush()
    return len(dati.fasi)


# --- Stampa a video ---------------------------------------------------------


def print_password_box(password: str) -> None:
    """Stampa la password del primo accesso in un riquadro ben visibile.

    Compare una volta sola. Nel database c'e' soltanto l'impronta argon2: se la
    password va persa non si recupera, si assegna la successiva a mano.
    """
    larghezza = 58

    print()
    print("  +" + "-" * larghezza + "+")
    print("  |" + "  PRIMO ACCESSO - ANNOTARE ORA".ljust(larghezza) + "|")
    print("  +" + "-" * larghezza + "+")
    print("  |" + f"  utente:    {ADMIN_USERNAME}".ljust(larghezza) + "|")
    print("  |" + f"  password:  {password}".ljust(larghezza) + "|")
    print("  +" + "-" * larghezza + "+")
    print()
    print("  Questa password compare una volta sola e non e' recuperabile.")
    print("  Va cambiata al primo accesso: l'utente e' gia' segnato come")
    print("  'deve cambiare password'.")
    print()


def print_outcome(etichetta: str, esito: str) -> None:
    """Stampa una riga del riepilogo, con i puntini di guida."""
    print(f"  {etichetta:.<44} {esito}")


def main() -> int:
    """Esegue tutte le creazioni in un'unica transazione.

    Se una qualunque parte fallisce non viene scritto niente: meglio un
    database vuoto che un database riempito a meta', in cui non si sa piu' che
    cosa c'e' e che cosa manca.
    """
    # Su Windows lo standard output usa la codifica locale, e le lettere
    # accentate dei nomi delle classificazioni si romperebbero quando l'uscita
    # viene rediretta su un file. Una riga per togliersi il pensiero.
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print("Aurora - dati iniziali")
    print("=" * 46)
    print()

    # Prima di aprire il database: se il file dei dati iniziali non si legge,
    # non c'e' niente da scrivere e ci si ferma qui.
    letti = dati_iniziali()
    print(f"  Letti da {settings.initial_data_config}")
    print()

    with SessionLocal() as db:
        try:
            admin_password = ensure_admin_user(db)
            classifications_created = ensure_classifications(db, letti)
            rules_created = ensure_permission_rules(db, letti)
            phases_created = ensure_phase_template(db, letti)
            db.commit()
        except Exception:
            db.rollback()
            print("  Errore: non e' stato scritto niente. Dettaglio qui sotto.")
            print()
            raise

    print_outcome(
        f"Utente creatore '{ADMIN_USERNAME}'",
        "creato" if admin_password else "gia' presente",
    )
    print_outcome(
        "Classificazioni",
        f"{classifications_created} create"
        if classifications_created
        else "gia' presenti",
    )
    print_outcome(
        "Matrice dei permessi",
        f"{rules_created} regole create" if rules_created else "gia' presente",
    )
    print_outcome(
        f"Modello di fasi '{letti.modello_fasi}' v{PHASE_TEMPLATE_VERSION}",
        f"creato con {phases_created} fasi" if phases_created else "gia' presente",
    )

    if admin_password is not None:
        print_password_box(admin_password)
    else:
        print()
        print("  Niente da fare: i dati iniziali c'erano gia' tutti.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
