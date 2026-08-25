"""Gestione degli utenti: creazione, password riassegnate, disattivazione.

Riservato al ruolo "creatore" - il controllo lo fa la dipendenza
richiedi_creatore in app/dependencies.py - ma le funzioni qui dentro non sanno
niente di HTTP e si possono richiamare da uno script o da un test.

**Un utente non si cancella.** Non c'e' nessuna funzione per farlo, e non va
aggiunta: le firme sui documenti e le righe di audit di una persona devono
restare leggibili dieci anni dopo che ha lasciato l'azienda. Al suo posto c'e'
disattiva(), che mette is_active a falso e chiude tutte le sue sessioni.

**Le password non si mostrano e non si recuperano.** Le due funzioni che ne
producono una - crea_utente() e reimposta_password() - restituiscono la
password in chiaro **una volta sola**, al chiamante, che la mostra e la
dimentica. Nel database entra soltanto l'impronta argon2. Se quella password
va persa prima di essere usata, non si recupera: se ne assegna un'altra.
"""

import logging
import re
import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GlobalRole, User
from app.services import audit, auth, passwords

logger = logging.getLogger("aurora.users")

# Larghezza della colonna users.username.
USERNAME_MAX_LENGTH = 50

# Quanti caratteri si lasciano al nome vero e proprio, per avere sempre posto
# per il numero progressivo dei casi di omonimia. Cinque cifre bastano: se un
# giorno l'azienda avesse novantanovemila persone che si chiamano tutte Mario
# Rossi, il problema non sarebbe questo.
SUFFIX_ROOM = 5

# Da quale numero parte la numerazione degli omonimi. Il primo Mario Rossi e'
# "mario.rossi", il secondo "mario.rossi2": partire da 1 farebbe sembrare che
# ci sia anche un "mario.rossi1" da qualche parte.
FIRST_HOMONYM_NUMBER = 2


def _ripulisci(parte: str) -> str:
    """Riduce un pezzo di nome alla forma che puo' stare in un nome utente.

    Toglie gli accenti, porta in minuscolo e butta via tutto quello che non e'
    una lettera o una cifra: spazi, apostrofi, trattini. Cosi' "D'Angelo"
    diventa "dangelo" e "De Luca" diventa "deluca".

    Se dopo la ripulitura non resta niente - succede con un nome scritto in un
    alfabeto che non e' il nostro - restituisce una stringa vuota, e chi
    chiama decide che farne.
    """
    senza_accenti = passwords.strip_accents(parte)
    return re.sub(r"[^a-z0-9]", "", senza_accenti.lower())


def proponi_username(db: Session, first_name: str, last_name: str) -> str:
    """Propone il nome utente per una persona: nome.cognome, tutto minuscolo.

    "Mario Rossi" diventa "mario.rossi"; "Nicolò D'Angelo" diventa
    "nicolo.dangelo". Se quel nome e' gia' preso si aggiunge un numero
    progressivo: "mario.rossi2", "mario.rossi3", e cosi' via fino a trovarne
    uno libero.

    Il confronto con i nomi gia' esistenti considera **anche gli utenti
    disattivati**. Un nome utente riusato sarebbe una trappola: le vecchie
    righe di audit continuerebbero a dire "mario.rossi" riferendosi a una
    persona, e le nuove a un'altra.
    """
    nome = _ripulisci(first_name)
    cognome = _ripulisci(last_name)

    # Se uno dei due pezzi si e' svuotato si usa solo l'altro, senza lasciare
    # il punto appeso. Se si sono svuotati tutti e due si ripiega su "utente":
    # meglio "utente2" che un nome utente vuoto, che il database rifiuterebbe.
    parti = [p for p in (nome, cognome) if p]
    base = ".".join(parti) if parti else "utente"
    base = base[: USERNAME_MAX_LENGTH - SUFFIX_ROOM]

    if not _username_occupato(db, base):
        return base

    numero = FIRST_HOMONYM_NUMBER
    while _username_occupato(db, f"{base}{numero}"):
        numero += 1

    return f"{base}{numero}"


def _username_occupato(db: Session, username: str) -> bool:
    """Dice se quel nome utente e' gia' di qualcuno, attivo o disattivato."""
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.username == username)
        )
        or 0
    ) > 0


def email_gia_usata(db: Session, email: str) -> bool:
    """Dice se quell'indirizzo di posta e' gia' di un altro utente.

    La colonna e' unica nel database, quindi il vincolo c'e' comunque; questa
    funzione serve a dirlo in italiano nel modulo invece di lasciare che sia
    il database a fermare l'inserimento con un errore tecnico.
    """
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.email) == email.strip().lower())
        )
        or 0
    ) > 0


def crea_utente(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    email: str,
    username: str,
    ruolo: GlobalRole,
    creato_da: User,
    request: Request | None = None,
) -> tuple[User, str]:
    """Crea un utente e restituisce lui e la sua password in chiaro.

    La password e' generata (quattro parole italiane) e va mostrata **una
    volta sola** a chi ha creato l'utente, che la consegnera' all'interessato.
    Da qui in avanti non e' piu' recuperabile da nessuno.

    L'utente nasce con must_change_password a vero: al primo accesso non potra'
    fare nient'altro che cambiarla. E' la ragione per cui non e' un problema
    che la password sia passata a voce o su un foglietto: vale un accesso solo.
    """
    password = passwords.generate_password()

    utente = User(
        username=username,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email.strip(),
        password_hash=passwords.hash_password(password),
        must_change_password=True,
        is_active=True,
        global_role=ruolo,
    )
    db.add(utente)
    # Serve l'id per la riga di audit qui sotto: flush lo fa assegnare senza
    # chiudere la transazione.
    db.flush()

    audit.record(
        db,
        action=audit.ACTION_USER_CREATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=creato_da.id,
        request=request,
        # Nel registro finisce chi e' stato creato, mai la sua password:
        # nemmeno l'impronta.
        new_value={
            "username": utente.username,
            "email": utente.email,
            "global_role": utente.global_role.value,
        },
    )
    logger.info("Utente '%s' creato da '%s'", utente.username, creato_da.username)

    return utente, password


def reimposta_password(
    db: Session,
    utente: User,
    reimpostata_da: User,
    request: Request | None = None,
) -> str:
    """Assegna una password nuova a un utente e lo butta fuori da ovunque.

    Restituisce la password in chiaro, da mostrare una volta sola.

    Fa tre cose, e le fa tutte e tre insieme perche' separarle lascerebbe una
    finestra aperta:

      1. imposta la password nuova;
      2. rimette must_change_password a vero, cosi' la password temporanea
         vale un accesso solo;
      3. revoca **tutte** le sessioni dell'utente, comprese quelle aperte.

    Il punto 3 e' quello che conta davvero. Se la password viene riassegnata
    perche' si sospetta che qualcuno l'avesse scoperta, lasciargli aperte le
    sessioni che aveva gia' avviato renderebbe l'operazione inutile.
    """
    password = passwords.generate_password()

    utente.password_hash = passwords.hash_password(password)
    utente.must_change_password = True

    revocate = auth.revoca_sessioni_utente(db, utente.id)

    audit.record(
        db,
        action=audit.ACTION_PASSWORD_RESET,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=reimpostata_da.id,
        request=request,
        new_value={"sessioni_revocate": revocate},
    )
    logger.info(
        "Password di '%s' riassegnata da '%s': revocate %s sessioni",
        utente.username,
        reimpostata_da.username,
        revocate,
    )

    return password


def disattiva(
    db: Session,
    utente: User,
    disattivato_da: User,
    request: Request | None = None,
) -> int:
    """Disattiva un utente e chiude tutte le sue sessioni.

    Restituisce quante sessioni ha chiuso.

    E' quello che in altri programmi si chiamerebbe "cancellare l'utente", ed
    e' l'unica forma di cancellazione che Aurora conosce: la riga resta dov'e'
    con tutto quello che ci punta.

    La revoca delle sessioni non sarebbe strettamente necessaria, perche'
    auth.trova_sessione() controlla is_active a ogni richiesta e le sessioni di
    un disattivato smetterebbero comunque di funzionare. Si fa lo stesso, per
    due ragioni: la tabella delle sessioni resta pulita e leggibile, e la
    sicurezza di una persona non deve dipendere dal fatto che un solo
    controllo, da qualche parte, sia scritto giusto.
    """
    utente.is_active = False
    revocate = auth.revoca_sessioni_utente(db, utente.id)

    audit.record(
        db,
        action=audit.ACTION_USER_DEACTIVATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=disattivato_da.id,
        request=request,
        old_value={"is_active": True},
        new_value={"is_active": False, "sessioni_revocate": revocate},
    )
    logger.info(
        "Utente '%s' disattivato da '%s'", utente.username, disattivato_da.username
    )

    return revocate


def riattiva(
    db: Session,
    utente: User,
    riattivato_da: User,
    request: Request | None = None,
) -> None:
    """Rimette in servizio un utente disattivato.

    Non gli restituisce le sessioni che aveva: quelle sono state chiuse e
    restano chiuse. Dovra' rientrare, ed e' giusto cosi'.
    """
    utente.is_active = True

    audit.record(
        db,
        action=audit.ACTION_USER_REACTIVATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=riattivato_da.id,
        request=request,
        old_value={"is_active": False},
        new_value={"is_active": True},
    )
    logger.info(
        "Utente '%s' riattivato da '%s'", utente.username, riattivato_da.username
    )


def elenco_utenti(db: Session, solo_attivi: bool = False) -> list[User]:
    """Tutti gli utenti, attivi e no, in ordine di cognome e nome.

    Qui i disattivati **si mostrano**, a differenza di quasi tutte le altre
    interrogazioni del programma: e' proprio la pagina in cui si va per
    riattivarne uno, e nasconderli lo renderebbe impossibile. Nell'elenco
    compare la colonna "stato" che li distingue.

    Con solo_attivi=True i disattivati restano fuori. Lo chiedono le pagine
    che non elencano le persone ma le fanno **scegliere** - la squadra di un
    progetto, per esempio: proporre di assegnare un lavoro a chi non puo' piu'
    entrare non ha senso.
    """
    interrogazione = select(User)
    if solo_attivi:
        interrogazione = interrogazione.where(User.is_active.is_(True))

    return list(
        db.scalars(
            interrogazione.order_by(User.last_name, User.first_name)
        ).all()
    )


def trova_utente(db: Session, user_id: uuid.UUID) -> User | None:
    """Cerca un utente per identificatore. None se non esiste."""
    return db.get(User, user_id)
