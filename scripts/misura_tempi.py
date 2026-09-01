"""Misura quanto ci mette Aurora a comporre le pagine principali.

E' la seconda meta' di `scripts/dati_prova.py`: quello riempie il database,
questo dice se le pagine reggono il volume. Il limite che l'azienda ha chiesto
per la sessione 13 e' **due secondi**, e le righe che lo superano compaiono in
rosso.

    python scripts/dati_prova.py
    python scripts/misura_tempi.py

Opzioni utili:

    --utente prova.mario.rossi   misura come la vede quella persona, invece
                                 che come la vede un creatore
    --giri 5                     quante volte si apre ciascuna pagina
    --limite 1.5                 il tetto oltre il quale la riga e' rossa


COME MISURA, E PERCHE' COSI'
----------------------------

Non con un cronometro alla mano su un browser, e non con un programma di
carico: con il **finto browser** di Starlette, lo stesso che usano i test.
Parla con l'applicazione vera - rotte, dipendenze, permessi, template - senza
la rete di mezzo.

Quello che si misura e' quindi il tempo che Aurora ci mette a **comporre** la
pagina: interrogazioni, permessi, disegno dell'HTML. Non c'e' dentro il tempo
di rete, che su una rete locale e' trascurabile, ne' quello che il browser
impiega a disegnare, che non dipende da noi. E' la parte su cui si puo'
intervenire, ed e' quella che cresce quando il database cresce.

**Il primo giro non conta.** La prima apertura di una pagina paga la
compilazione del template Jinja e il riempimento delle cache di SQLAlchemy, e
misurarla direbbe di un rallentamento che nessun utente vedra' mai due volte.
Si scalda una volta, poi si misura.

**Si riporta il tempo peggiore, non la media.** Una pagina che di solito
risponde in 300 millisecondi e ogni tanto ne impiega tremila e' una pagina
lenta: la media la nasconde, il massimo no.


PERCHE' SERVE UNA PERSONA VERA
-------------------------------

I permessi cambiano l'interrogazione. Un creatore non ha nessun filtro sui
documenti (`filtro_documenti()` restituisce None); una persona normale porta
con se' due EXISTS correlati su `assignments` e `permission_rules`. Sono due
interrogazioni diverse e possono avere due tempi molto diversi, quindi si
misurano tutte e due: **il creatore e un utente normale**, uno dopo l'altro.

Lo script si costruisce da solo la sessione di quelle persone, scrivendola
nella tabella `user_sessions` come farebbe l'accesso vero: la password non si
puo' rileggere da nessuna parte (e' un'impronta argon2id, D-025), quindi
entrare dal modulo non e' possibile senza conoscerla. La sessione dura un'ora
e viene revocata alla fine.
"""

import argparse
import statistics
import sys
import time

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Document,
    EmailMessage,
    GlobalRole,
    Product,
    Project,
    SessionKind,
    User,
)
from app.services import auth  # noqa: E402
from app.services.cookies import COOKIE_SESSIONE  # noqa: E402

# Il tetto chiesto dall'azienda per la sessione 13.
LIMITE_SECONDI = 2.0

# Quante volte si apre ciascuna pagina, oltre al giro di riscaldamento.
GIRI = 3

# Larghezza della colonna del nome nella tabella dei risultati.
COLONNA_NOME = 46


class Pagina:
    """Una pagina da misurare.

    nome        come si chiama in italiano, per la tabella dei risultati
    percorso    l'indirizzo da aprire. Puo' contenere `{...}`, che viene
                riempito con un identificativo vero preso dal database
    solo_creatore
                vera per le pagine riservate: misurarle come utente normale
                misurerebbe il tempo di comporre un errore 403
    """

    def __init__(
        self, nome: str, percorso: str, solo_creatore: bool = False
    ) -> None:
        self.nome = nome
        self.percorso = percorso
        self.solo_creatore = solo_creatore


# Le pagine principali, cioe' quelle che una persona apre tutti i giorni piu'
# quelle che crescono con il database. Le pagine di modulo (creazione di un
# prodotto, caricamento di un documento) non ci sono: non leggono elenchi e il
# loro tempo non dipende dal volume.
PAGINE = (
    Pagina("Cruscotto (pagina iniziale)", "/"),
    Pagina("Cruscotto con i filtri", "/?stato=rilasciato"),
    Pagina("Elenco prodotti", "/prodotti"),
    Pagina("Elenco prodotti con ricerca", "/prodotti?q=PRV"),
    Pagina("Elenco progetti", "/progetti"),
    Pagina("Elenco documenti", "/documenti"),
    Pagina("Elenco documenti con ricerca", "/documenti?q=Schema"),
    Pagina("Elenco documenti, seconda pagina", "/documenti?pagina=2"),
    Pagina("Elenco posta", "/posta"),
    Pagina("Elenco posta con ricerca nel contenuto", "/posta?q=collaudo"),
    Pagina("Scheda di un prodotto", "/prodotti/{prodotto}"),
    Pagina("Scheda di un progetto", "/progetti/{progetto}"),
    Pagina("Scheda di un documento", "/documenti/{documento}"),
    Pagina("Scheda di un messaggio", "/posta/{messaggio}"),
    Pagina("Storico di un progetto", "/progetti/{progetto}/storico"),
    Pagina("Storico di un documento", "/documenti/{documento}/storico"),
    Pagina("Registro delle operazioni", "/registro", solo_creatore=True),
    Pagina("Registro filtrato per gruppo", "/registro?gruppo=documenti",
           solo_creatore=True),
    Pagina("Quarantena della posta", "/posta/quarantena", solo_creatore=True),
    Pagina("Diagnostica", "/diagnostica", solo_creatore=True),
    Pagina("Elenco utenti", "/utenti", solo_creatore=True),
    Pagina("Matrice dei permessi", "/permessi", solo_creatore=True),
    Pagina("Salute (JSON)", "/salute"),
)


def identificativi(db: Session) -> dict[str, str]:
    """Un identificativo vero per ciascun tipo di scheda da misurare.

    Si prendono le righe piu' recenti: sono quelle scritte dall'ultimo lotto
    di `dati_prova.py`, quindi quelle che stanno dentro il volume che si
    vuole misurare. Una scheda mancante si segnala e la sua riga si salta.
    """
    trovati: dict[str, str] = {}

    prodotto = db.scalars(
        select(Product).order_by(Product.created_at.desc())
    ).first()
    if prodotto is not None:
        trovati["prodotto"] = str(prodotto.id)

    progetto = db.scalars(
        select(Project).order_by(Project.opened_at.desc())
    ).first()
    if progetto is not None:
        trovati["progetto"] = str(progetto.id)

    documento = db.scalars(
        select(Document)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    ).first()
    if documento is not None:
        trovati["documento"] = str(documento.id)

    messaggio = db.scalars(
        select(EmailMessage).order_by(EmailMessage.created_at.desc())
    ).first()
    if messaggio is not None:
        trovati["messaggio"] = str(messaggio.id)

    return trovati


def volume(db: Session) -> str:
    """Una riga che dice quanto c'e' dentro il database che si sta misurando.

    Senza, il risultato non vale niente: «l'elenco documenti risponde in 200
    millisecondi» e' un'informazione solo se si sa su quanti documenti.
    """
    quanti = {
        "prodotti": Product,
        "progetti": Project,
        "documenti": Document,
        "messaggi": EmailMessage,
    }
    pezzi = [
        f"{db.scalar(select(func.count()).select_from(classe)) or 0} {nome}"
        for nome, classe in quanti.items()
    ]
    return ", ".join(pezzi)


def persona(db: Session, username: str | None, creatore: bool) -> User | None:
    """La persona con cui misurare.

    Con `--utente` si cerca quella; senza, si prende la prima attiva del ruolo
    richiesto. Una persona che non c'e' non e' un guasto: si salta quella meta'
    della misura e lo si scrive.
    """
    if username:
        return db.scalars(
            select(User).where(User.username == username, User.is_active.is_(True))
        ).first()

    ruolo = GlobalRole.CREATORE if creatore else GlobalRole.UTENTE
    return db.scalars(
        select(User)
        .where(User.global_role == ruolo, User.is_active.is_(True))
        .order_by(User.created_at)
    ).first()


def apri_sessione(db: Session, utente: User) -> str:
    """Scrive nel database una sessione per quella persona e ne da' il gettone.

    Passa da `auth.crea_sessione()`, cioe' dalla stessa funzione che chiama
    l'accesso vero: la sessione che si misura e' una sessione come le altre,
    con la sua impronta nel database e la sua scadenza. Il gettone in chiaro
    esiste solo dentro questo processo e viene revocato alla fine.
    """
    gettone = auth.crea_sessione(db, utente, SessionKind.SESSIONE, None)
    db.commit()
    return gettone


def chiudi_sessione(db: Session, gettone: str) -> None:
    """Revoca la sessione aperta per la misura.

    Si ritrova dal gettone, come la ritroverebbe una richiesta vera: nel
    database c'e' solo l'impronta, e cercarla per impronta e' l'unica strada
    (D-025). Se non si trova - perche' e' gia' scaduta, o perche' qualcuno l'ha
    revocata nel frattempo - non c'e' niente da fare e non e' un guasto.
    """
    trovata = auth.trova_sessione(db, gettone, SessionKind.SESSIONE)
    if trovata is not None:
        auth.revoca_sessione(db, trovata[0])
        db.commit()


def misura_una(
    client: TestClient, percorso: str, giri: int
) -> tuple[float, float, int] | None:
    """Apre la pagina `giri` volte e restituisce (peggiore, mediana, codice).

    Il giro di riscaldamento non e' contato: la prima apertura paga la
    compilazione del template e il riempimento delle cache, e non e' il tempo
    che vedra' chi usa il programma.
    """
    risposta = client.get(percorso, headers={"accept": "text/html"})
    if risposta.status_code >= 400:
        return None

    tempi = []
    for _ in range(giri):
        inizio = time.perf_counter()
        risposta = client.get(percorso, headers={"accept": "text/html"})
        tempi.append(time.perf_counter() - inizio)

    return max(tempi), statistics.median(tempi), risposta.status_code


def misura_tutte(
    db: Session,
    utente: User,
    riferimenti: dict[str, str],
    giri: int,
    limite: float,
) -> list[tuple[str, float, float, int]]:
    """Misura tutte le pagine che questa persona puo' aprire.

    Restituisce una riga per pagina: nome, tempo peggiore, tempo mediano,
    codice di stato. Le pagine che rispondono con un errore vengono saltate e
    segnalate: misurare il tempo di comporre un 403 non serve a niente.
    """
    creatore = utente.global_role is GlobalRole.CREATORE
    gettone = apri_sessione(db, utente)
    righe: list[tuple[str, float, float, int]] = []

    try:
        with TestClient(app) as client:
            client.cookies.set(COOKIE_SESSIONE, gettone)

            for pagina in PAGINE:
                if pagina.solo_creatore and not creatore:
                    continue

                percorso = pagina.percorso
                mancante = False
                for chiave, valore in riferimenti.items():
                    percorso = percorso.replace("{" + chiave + "}", valore)
                if "{" in percorso:
                    mancante = True

                if mancante:
                    print(f"    {pagina.nome:<{COLONNA_NOME}} saltata (manca il dato)")
                    continue

                esito = misura_una(client, percorso, giri)
                if esito is None:
                    print(f"    {pagina.nome:<{COLONNA_NOME}} saltata (non si apre)")
                    continue

                peggiore, mediano, codice = esito
                righe.append((pagina.nome, peggiore, mediano, codice))
                segno = "  <-- OLTRE IL LIMITE" if peggiore > limite else ""
                print(
                    f"    {pagina.nome:<{COLONNA_NOME}}"
                    f"{mediano * 1000:7.0f} ms"
                    f"{peggiore * 1000:9.0f} ms{segno}"
                )
    finally:
        # La sessione si revoca sempre, anche se la misura si e' interrotta:
        # una sessione aperta da uno script che non c'e' piu' e' una riga che
        # nessuno sa spiegare.
        chiudi_sessione(db, gettone)

    return righe


def argomenti() -> argparse.Namespace:
    """Legge le opzioni della riga di comando."""
    analizzatore = argparse.ArgumentParser(
        description=(
            "Misura il tempo che Aurora impiega a comporre le pagine "
            "principali, con il volume di dati che c'e' adesso nel database."
        )
    )
    analizzatore.add_argument(
        "--utente",
        default=None,
        help="il nome utente con cui misurare. Senza, si misura due volte: "
        "come creatore e come utente normale.",
    )
    analizzatore.add_argument("--giri", type=int, default=GIRI)
    analizzatore.add_argument("--limite", type=float, default=LIMITE_SECONDI)
    return analizzatore.parse_args()


def main() -> int:
    """Misura e stampa. Restituisce 0 se nessuna pagina supera il limite."""
    opzioni = argomenti()

    db = SessionLocal()
    try:
        print()
        print("Misura dei tempi di risposta")
        print(f"  volume nel database: {volume(db)}")
        print(f"  giri per pagina:     {opzioni.giri} (piu' uno di riscaldamento)")
        print(f"  limite:              {opzioni.limite:.1f} s")
        print()

        riferimenti = identificativi(db)
        tutte: list[tuple[str, float, float, int]] = []

        if opzioni.utente:
            persone = [(opzioni.utente, persona(db, opzioni.utente, True))]
        else:
            persone = [
                ("creatore", persona(db, None, creatore=True)),
                ("utente normale", persona(db, None, creatore=False)),
            ]

        for etichetta, chi in persone:
            if chi is None:
                print(f"  {etichetta}: non trovato, misura saltata")
                print()
                continue

            print(f"  Come {etichetta} ({chi.username})")
            print(
                f"    {'pagina':<{COLONNA_NOME}}"
                f"{'mediana':>10}{'peggiore':>12}"
            )
            tutte.extend(
                misura_tutte(db, chi, riferimenti, opzioni.giri, opzioni.limite)
            )
            print()

    finally:
        db.close()

    lente = [riga for riga in tutte if riga[1] > opzioni.limite]

    print("  " + "-" * 70)
    if not tutte:
        print("  Nessuna pagina misurata.")
        return 1

    peggiore = max(tutte, key=lambda riga: riga[1])
    print(f"  Pagine misurate:  {len(tutte)}")
    print(
        f"  La piu' lenta:    {peggiore[0]} "
        f"({peggiore[1] * 1000:.0f} ms nel giro peggiore)"
    )

    if lente:
        print(f"  OLTRE {opzioni.limite:.1f} s: {len(lente)}")
        for nome, peggiore_tempo, _mediano, _codice in lente:
            print(f"    - {nome}: {peggiore_tempo * 1000:.0f} ms")
        return 1

    print(f"  Nessuna pagina supera {opzioni.limite:.1f} secondi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
