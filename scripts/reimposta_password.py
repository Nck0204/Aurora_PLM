"""Riassegna la password di un utente dalla riga di comando.

Serve in un caso solo, ma e' un caso che prima o poi capita: **nessuno riesce
piu' a entrare come creatore**. La password di "admin" e' andata persa, oppure
l'unico creatore e' stato disattivato per sbaglio, e dall'interfaccia non c'e'
niente da fare perche' per gestire gli utenti bisogna essere gia' entrati.

Le password non si recuperano: nel database c'e' solo l'impronta argon2, che
non si inverte (vedi app/services/passwords.py). Questo script non recupera
niente, ne assegna una nuova.

Come si esegue, dalla radice del progetto e con l'ambiente virtuale attivo:

    python scripts/reimposta_password.py                 (l'utente "admin")
    python scripts/reimposta_password.py mario.rossi     (un altro utente)

Fa esattamente le stesse cose che farebbe il pulsante "Nuova password"
nell'interfaccia, perche' chiama la stessa funzione:

  - assegna una password nuova, generata, e la stampa una volta sola;
  - segna l'utente come "deve cambiare la password";
  - revoca tutte le sue sessioni aperte;
  - scrive la riga nel registro delle operazioni.

In piu' fa una cosa che dall'interfaccia non si puo' fare: se l'utente e'
disattivato, chiede se riattivarlo. E' l'unica strada quando ci si e' chiusi
fuori disattivando l'ultimo creatore.

**Chi puo' eseguirlo.** Chiunque abbia accesso al server e al file .env, cioe'
chi amministra la macchina. E' inevitabile - e' la procedura di soccorso - ed
e' la ragione per cui il file .env e l'accesso al server vanno protetti quanto
le password stesse.
"""

import sys
from pathlib import Path

# Questo script viene lanciato dalla riga di comando, quindi la radice del
# progetto non e' automaticamente fra le cartelle in cui Python cerca i moduli.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import GlobalRole, User  # noqa: E402
from app.services import users  # noqa: E402

# L'utente su cui si interviene se non se ne indica un altro.
DEFAULT_USERNAME = "admin"


def print_password_box(username: str, password: str) -> None:
    """Stampa la password nuova in un riquadro ben visibile.

    Compare una volta sola: da qui in avanti nel database c'e' solo l'impronta.
    """
    larghezza = 58

    print()
    print("  +" + "-" * larghezza + "+")
    print("  |" + "  PASSWORD NUOVA - ANNOTARE ORA".ljust(larghezza) + "|")
    print("  +" + "-" * larghezza + "+")
    print("  |" + f"  utente:    {username}".ljust(larghezza) + "|")
    print("  |" + f"  password:  {password}".ljust(larghezza) + "|")
    print("  +" + "-" * larghezza + "+")
    print()
    print("  Questa password compare una volta sola e non e' recuperabile.")
    print("  Va cambiata al primo accesso: l'utente e' gia' segnato come")
    print("  'deve cambiare password'.")
    print()
    print("  Tutte le sessioni aperte di questo utente sono state chiuse.")
    print()


def main(argomenti: list[str]) -> int:
    """Riassegna la password dell'utente indicato. Restituisce il codice di uscita."""
    # Su Windows lo standard output usa la codifica locale e le lettere
    # accentate si romperebbero quando l'uscita viene rediretta su un file.
    sys.stdout.reconfigure(encoding="utf-8")

    username = argomenti[0].strip().lower() if argomenti else DEFAULT_USERNAME

    print()
    print("Aurora - riassegnazione della password")
    print("=" * 46)
    print()

    with SessionLocal() as db:
        utente = db.scalar(select(User).where(User.username == username))

        if utente is None:
            print(f"  L'utente '{username}' non esiste.")
            print()
            print("  Gli utenti presenti sono:")
            for esistente in db.scalars(select(User).order_by(User.username)):
                stato = "attivo" if esistente.is_active else "disattivato"
                ruolo = esistente.global_role.value
                print(f"    - {esistente.username} ({ruolo}, {stato})")
            print()
            return 1

        if not utente.is_active:
            print(f"  Attenzione: l'utente '{username}' e' disattivato.")
            print("  Con la password nuova non riuscirebbe comunque a entrare.")
            risposta = input("  Riattivarlo? [s/N] ").strip().lower()

            if risposta not in ("s", "si", "sì"):
                print()
                print("  Non e' stato fatto niente.")
                print()
                return 1

            utente.is_active = True
            print("  Utente riattivato.")

        # Chi esegue lo script non e' un utente di Aurora: nel registro delle
        # operazioni si indica l'utente stesso come autore. E' la scelta meno
        # sbagliata fra le due possibili - l'alternativa sarebbe lasciare il
        # campo vuoto, che nel registro vuol dire "l'ha fatto il programma da
        # solo di notte", e non e' quello che e' successo. Il fatto che si sia
        # passati di qui resta comunque visibile: e' l'unica riga di
        # riassegnazione in cui autore e destinatario coincidono.
        password = users.reimposta_password(db, utente, reimpostata_da=utente)

        db.commit()

    print_password_box(username, password)

    if utente.global_role is not GlobalRole.CREATORE:
        print(f"  Nota: '{username}' non ha il ruolo di creatore, quindi non")
        print("  potra' gestire gli altri utenti.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
