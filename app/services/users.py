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
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GlobalRole, User
from app.services import audit, auth, etichette, passwords

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


def email_gia_usata(
    db: Session, email: str, tranne_id: uuid.UUID | None = None
) -> bool:
    """Dice se quell'indirizzo di posta e' gia' di un altro utente.

    La colonna e' unica nel database, quindi il vincolo c'e' comunque; questa
    funzione serve a dirlo in italiano nel modulo invece di lasciare che sia
    il database a fermare l'inserimento con un errore tecnico.

    "tranne_id" serve alla modifica: salvando la scheda di una persona senza
    averle cambiato l'indirizzo, l'indirizzo risulterebbe altrimenti "gia'
    usato" - da lei stessa.
    """
    condizioni = [func.lower(User.email) == email.strip().lower()]
    if tranne_id is not None:
        condizioni.append(User.id != tranne_id)

    return (
        db.scalar(select(func.count()).select_from(User).where(*condizioni)) or 0
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
        etichetta=etichette.nome_utente(utente),
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


def modifica(
    db: Session,
    utente: User,
    *,
    first_name: str,
    last_name: str,
    email: str,
    modificato_da: User,
    request: Request | None = None,
) -> list[str]:
    """Corregge nome, cognome e indirizzo di posta di una persona.

    Restituisce l'elenco dei campi che sono cambiati davvero: vuoto se non e'
    cambiato niente, e in quel caso **non** viene scritta nessuna riga nel
    registro. Un registro che segna "modificato" ogni volta che qualcuno apre
    una scheda e preme Salva senza toccare niente e' un registro che nessuno
    legge piu'.

    **Tre cose che questa funzione non tocca, e sono tre decisioni.**

    Il **nome utente** resta quello scelto alla creazione. Compare nelle righe
    del registro di anni, nelle assegnazioni ai progetti e in cima a ogni
    pagina che quella persona ha aperto: cambiarlo vorrebbe dire rendere
    illeggibile la storia. Chi si sposa non diventa un altro dipendente.

    La **password** ha la sua funzione, reimposta_password(), che oltre a
    cambiarla revoca tutte le sessioni. Metterla qui vorrebbe dire poter
    cambiare una password per sbaglio salvando una scheda.

    Il **ruolo globale** e' rimasto in sospeso dalla sessione 3 e in sospeso
    resta: chi puo' amministrare Aurora e' la decisione piu' pesante del
    programma, e va fatta con la sua pagina, la sua conferma e le sue
    precauzioni - a cominciare dall'ultimo creatore, che non deve poter
    togliere il ruolo a se' stesso. Vedi docs/STATO.md.
    """
    prima = {
        "first_name": utente.first_name,
        "last_name": utente.last_name,
        "email": utente.email,
    }
    dopo = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "email": email.strip(),
    }

    cambiati = [campo for campo in prima if prima[campo] != dopo[campo]]
    if not cambiati:
        return []

    for campo in cambiati:
        setattr(utente, campo, dopo[campo])

    audit.record(
        db,
        action=audit.ACTION_USER_UPDATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=modificato_da.id,
        request=request,
        etichetta=etichette.nome_utente(utente),
        old_value={campo: prima[campo] for campo in cambiati},
        new_value={campo: dopo[campo] for campo in cambiati},
    )
    logger.info(
        "Utente '%s' modificato da '%s': %s",
        utente.username,
        modificato_da.username,
        ", ".join(cambiati),
    )

    return cambiati


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
        etichetta=etichette.nome_utente(utente),
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
        etichetta=etichette.nome_utente(utente),
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
        etichetta=etichette.nome_utente(utente),
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


# --- Il ruolo, come si mostra -----------------------------------------------


@dataclass(frozen=True)
class RuoloMostrato:
    """Il ruolo globale di una persona, gia' pronto da disegnare.

    Sono due stringhe: il testo dell'etichetta e la variante di tinta con cui
    disegnarla. Il calcolo si fa qui e non dentro il template per la regola di
    CLAUDE.md sui menu a tendina - "un template che trasforma un valore in
    un'etichetta contiene una regola" - e per una seconda ragione, che riguarda
    questa sessione: dentro un template un `{% if utente.is_creatore %}` non si
    distingue a colpo d'occhio da una verifica di permesso, e la regola della
    sessione 7 e' che di verifiche di permesso nei template non ce ne siano
    (D-051). Togliendole tutte, quello che resta si legge.

    **Questo non e' un permesso**: e' il nome del ruolo e il colore con cui
    scriverlo. Chi puo' fare che cosa lo dice permissions.puo().
    """

    testo: str
    variante: str


def ruolo_mostrato(utente: User) -> RuoloMostrato:
    """L'etichetta del ruolo globale di una persona.

    Il creatore si distingue con la tinta d'accento perche' in un elenco di
    trenta righe uguali dev'essere possibile trovare in un colpo d'occhio chi
    amministra il programma.
    """
    return RuoloMostrato(
        testo=utente.global_role.value,
        variante="accento" if utente.global_role is GlobalRole.CREATORE else "neutra",
    )


# --- Il primo creatore, quello che non lo ha creato nessuno -----------------
#
# Le due funzioni qui sotto servono soltanto alla configurazione guidata del
# primo avvio (sessione 12) e stanno **in questo file** per una ragione
# precisa: qui e' lecito guardare `global_role`, e in app/services/setup.py no.
# C'e' un test che legge i sorgenti e diventa rosso se il ruolo globale ricompare
# in un file che non e' fra i cinque autorizzati (tests/test_permessi.py).


def esiste_un_creatore(db: Session) -> bool:
    """Dice se nel database c'e' almeno una persona attiva che amministra.

    E' la domanda a cui risponde il primo avvio: finche' la risposta e' no, il
    sistema non e' configurato e la procedura guidata si apre a chiunque -
    perche' non c'e' nessuno a cui chiedere il permesso. Appena la risposta
    diventa si', quella stessa procedura pretende di parlare con quella
    persona.

    **Non e' una verifica di permesso**, ed e' il motivo per cui non passa da
    permissions.puo(): quella funzione risponde a "questa persona puo' fare
    questa cosa?"; questa risponde a "esiste qualcuno?", che e' una domanda
    sull'installazione, non su una persona.

    Si guardano solo gli utenti **attivi**: un creatore disattivato non puo'
    entrare, e un sistema in cui l'unico amministratore e' stato disattivato e'
    un sistema in cui nessuno puo' piu' fare niente. Riaprire li' la procedura
    guidata sarebbe pero' pericoloso quanto comodo - chiunque arrivi al server
    potrebbe crearsi un amministratore - e per questo la procedura, oltre a
    questa risposta, pretende che il database sia vuoto anche di documenti
    (vedi app/services/setup.py, `sistema_da_configurare`).
    """
    quanti = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.global_role == GlobalRole.CREATORE, User.is_active.is_(True))
        )
        or 0
    )
    return quanti > 0


def crea_primo_creatore(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    email: str,
    username: str,
    password: str,
    request: Request | None = None,
) -> User:
    """Crea la prima persona che amministra Aurora, in un sistema vuoto.

    E' diversa da crea_utente() in tre punti, e tutti e tre hanno la stessa
    causa: **non c'e' nessuno che la stia creando.**

      - non c'e' un `creato_da`: la voce del registro non ha una persona, come
        quelle scritte all'avvio dal controllo della configurazione. Inventarne
        una sarebbe la peggiore delle bugie da mettere in un audit trail;
      - la password **la sceglie l'interessato** invece di essere generata:
        chi sta facendo il primo avvio e' seduto davanti al server, non c'e'
        nessuno che gliela debba dettare al telefono;
      - per la stessa ragione `must_change_password` resta falso: non c'e'
        nessun passaggio di consegne da cui difendersi.

    **Chi la chiama ha gia' verificato che il sistema sia da configurare.**
    Questa funzione non lo verifica: e' un servizio, e i servizi di Aurora non
    decidono chi puo' chiamarli. La verifica sta in
    `app/services/setup.py`, che e' l'unico posto da cui questa funzione viene
    richiamata, e la rotta la ripete prima di scrivere.
    """
    utente = User(
        username=username,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email.strip(),
        password_hash=passwords.hash_password(password),
        must_change_password=False,
        is_active=True,
        global_role=GlobalRole.CREATORE,
    )
    db.add(utente)
    db.flush()

    audit.record(
        db,
        action=audit.ACTION_USER_CREATED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        # Nessun autore: al primo avvio non c'e' ancora nessuno.
        user_id=None,
        request=request,
        etichetta=etichette.nome_utente(utente),
        description=(
            f"Primo accesso amministrativo creato dalla configurazione "
            f"guidata: {etichette.nome_utente(utente)}."
        ),
        new_value={
            "username": utente.username,
            "email": utente.email,
            "global_role": utente.global_role.value,
        },
    )
    logger.info(
        "Primo creatore '%s' creato dalla configurazione guidata", utente.username
    )

    return utente
