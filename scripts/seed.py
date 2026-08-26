"""Dati iniziali di Aurora.

Riempie un database appena migrato con il minimo indispensabile perche' il
programma sia utilizzabile:

  - un utente creatore, "admin", con una password casuale stampata una volta
    sola e da cambiare al primo accesso;
  - le cinque classificazioni (quattro dei documenti piu' la corrispondenza);
  - la matrice dei permessi di partenza, tutte e dodici le caselle;
  - il modello di fasi "Standard", versione 1, con le sue sei fasi e le
    due proprieta' che le governano (da Development non si torna
    indietro, "Chiuso" chiude il progetto).

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
from app.services import passwords  # noqa: E402

# --- Costanti dei dati iniziali ---------------------------------------------

ADMIN_USERNAME = "admin"
ADMIN_FIRST_NAME = "Amministratore"
ADMIN_LAST_NAME = "Aurora"

# Indirizzo di comodo: va corretto con quello vero al primo accesso, altrimenti
# le notifiche destinate all'amministratore non arriveranno a nessuno.
ADMIN_EMAIL = "admin@aurora.local"

# Le cinque classificazioni, nell'ordine in cui devono comparire.
#
# "Corrispondenza" e' arrivata con la sessione 10 ed e' diversa dalle altre
# quattro: non se la sceglie chi carica un documento, ce l'hanno addosso tutti
# i messaggi di posta archiviati, ed e' con lei che si decide chi li puo'
# vedere (D-069). Sui database gia' in uso la crea la migrazione
# d4b8607e15a2; qui c'e' per le installazioni nuove.
CLASSIFICATIONS = [
    ("Tecnico", "Schemi, disegni, distinte, relazioni di prova, firmware."),
    ("Commerciale", "Offerte, listini, ordini, corrispondenza commerciale."),
    ("Qualità", "Piani della qualità, non conformità, rapporti di audit."),
    ("Amministrativo", "Contratti, accordi di riservatezza, documenti di spesa."),
    ("Corrispondenza", "I messaggi di posta archiviati e i loro allegati."),
]

# La matrice dei permessi di partenza, una riga per ruolo.
# Le tre lettere sono: V = vedere, C = caricare, M = modificare.
#
#                      Tecnico   Commerciale   Qualità   Amministrativo   Corrispondenza
#   project_manager    V C M     V C M         V C M     V C M            V C M
#   ingegnere          V C M     - - -         V C M     V - -            V - M
#   lettore            V - -     - - -         - - -     - - -            V - -
#
# La colonna della corrispondenza e' della sessione 10 e va letta cosi': i
# messaggi non si "caricano" - arrivano dalla casella - quindi la casella C
# non serve a nessuno tranne al responsabile; la M e' il permesso di
# **correggere l'attribuzione** di un messaggio finito sulla versione
# sbagliata, e l'ingegnere ce l'ha perche' e' lui che se ne accorge.
#
# Le regole che la sessione chiede espressamente sono tre: l'ingegnere non vede
# il Commerciale, il project manager vede tutto del proprio progetto, il lettore
# vede solo il Tecnico e in sola lettura. Il resto della matrice e' la scelta
# ragionevole che ne discende, e si corregge dall'interfaccia.
#
# Ci sono tutte e dodici le caselle, comprese quelle con tutti i permessi a
# falso: una casella che dice "no" e' una decisione, una casella che manca e'
# una dimenticanza, e a distanza di mesi non si distinguono piu'.
PERMISSION_MATRIX = {
    ProjectRole.PROJECT_MANAGER: {
        "Tecnico": (True, True, True),
        "Commerciale": (True, True, True),
        "Qualità": (True, True, True),
        "Amministrativo": (True, True, True),
        "Corrispondenza": (True, True, True),
    },
    ProjectRole.INGEGNERE: {
        "Tecnico": (True, True, True),
        "Commerciale": (False, False, False),
        "Qualità": (True, True, True),
        "Amministrativo": (True, False, False),
        "Corrispondenza": (True, False, True),
    },
    ProjectRole.LETTORE: {
        "Tecnico": (True, False, False),
        "Commerciale": (False, False, False),
        "Qualità": (False, False, False),
        "Amministrativo": (False, False, False),
        "Corrispondenza": (True, False, False),
    },
}

PHASE_TEMPLATE_NAME = "Standard"
PHASE_TEMPLATE_VERSION = 1
PHASE_TEMPLATE_DESCRIPTION = (
    "Percorso di sviluppo prodotto usato in azienda: dalla selezione "
    "dell'idea alla chiusura del progetto."
)

# Le fasi, nell'ordine di attraversamento. Le due colonne dopo la descrizione
# sono le proprieta' che governano il comportamento del percorso:
#
#   blocks_return    da questa fase non si torna a una precedente;
#   closes_project   entrando in questa fase il progetto si chiude.
#
# Sono dati e non codice, ed e' il punto (D-055). Il programma non sa che la
# fase da cui non si torna indietro si chiami "Development": sa che una fase
# con blocks_return blocca il ritorno. Cambiarle nome, riordinarle o scrivere
# un percorso completamente diverso non costa una riga di programma.
PHASES = [
    ("Idea screening", "Vaglio iniziale dell'idea: vale la pena di studiarla?",
     False, False),
    ("Concept", "Definizione di che cosa deve fare il prodotto.",
     False, False),
    ("Feasibility", "Verifica tecnica ed economica di fattibilità.",
     False, False),
    ("Quoted", "Offerta presentata al cliente, in attesa di risposta.",
     False, False),
    ("Development", "Progettazione, prototipi, prove, industrializzazione.",
     True, False),
    ("Chiuso", "Progetto concluso, per rilascio o per rinuncia.",
     False, True),
]


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


def ensure_classifications(db: Session) -> int:
    """Crea le classificazioni mancanti. Restituisce quante ne ha create."""
    created = 0

    for position, (name, description) in enumerate(CLASSIFICATIONS, start=1):
        existing = db.scalar(select(Classification).where(Classification.name == name))
        if existing is not None:
            continue

        db.add(
            Classification(name=name, description=description, sort_order=position)
        )
        created += 1

    db.flush()
    return created


def ensure_permission_rules(db: Session) -> int:
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

    for role, per_classification in PERMISSION_MATRIX.items():
        for classification_name, permessi in per_classification.items():
            can_view, can_upload, can_edit = permessi
            classification = classifications[classification_name]

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


def ensure_phase_template(db: Session) -> int:
    """Crea il modello di fasi "Standard" versione 1 con le sue fasi.

    Restituisce quante fasi ha creato, zero se il modello c'era gia'. Il
    modello si cerca per la coppia (nome, versione) perche' e' quella che lo
    identifica: i modelli sono immutabili e le correzioni diventano una
    versione nuova, non una modifica di questa.
    """
    existing = db.scalar(
        select(PhaseTemplate).where(
            PhaseTemplate.name == PHASE_TEMPLATE_NAME,
            PhaseTemplate.version == PHASE_TEMPLATE_VERSION,
        )
    )
    if existing is not None:
        return 0

    template = PhaseTemplate(
        name=PHASE_TEMPLATE_NAME,
        description=PHASE_TEMPLATE_DESCRIPTION,
        standards=[],
        is_active=True,
        version=PHASE_TEMPLATE_VERSION,
    )
    db.add(template)
    db.flush()

    for position, (name, description, blocks, closes) in enumerate(PHASES, start=1):
        db.add(
            Phase(
                phase_template_id=template.id,
                name=name,
                sort_order=position,
                description=description,
                blocks_return=blocks,
                closes_project=closes,
            )
        )

    db.flush()
    return len(PHASES)


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

    with SessionLocal() as db:
        try:
            admin_password = ensure_admin_user(db)
            classifications_created = ensure_classifications(db)
            rules_created = ensure_permission_rules(db)
            phases_created = ensure_phase_template(db)
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
        f"Modello di fasi '{PHASE_TEMPLATE_NAME}' v{PHASE_TEMPLATE_VERSION}",
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
