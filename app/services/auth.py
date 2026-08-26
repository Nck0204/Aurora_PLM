"""Accesso, sessioni e blocco dei tentativi.

Questo modulo contiene la logica, non le pagine: e' fatto per essere richiamato
da una rotta, da un test o da un lavoro pianificato senza differenza. Le pagine
stanno in app/routers/auth.py, le dipendenze di FastAPI in app/dependencies.py.

Quattro cose da sapere prima di leggere il resto.

**Del gettone di sessione il database conserva solo l'impronta.** Al browser
va un numero casuale da 32 byte; nella colonna user_sessions.token_hash va il
suo SHA-256. Chi si procurasse una copia del database non troverebbe nessun
gettone utilizzabile, esattamente come non troverebbe nessuna password.

Qui l'impronta e' un SHA-256 nudo e non un argon2 come per le password, e non
e' una dimenticanza: le due cose difendono da due pericoli diversi. Una
password e' corta e scelta da una persona, quindi si puo' tentare di
indovinarla, ed e' per questo che serve una funzione lenta. Un gettone e' 32
byte estratti a caso: non lo si indovina in nessun tempo utile, e rallentare
la verifica servirebbe solo a rallentare ogni pagina di Aurora.

**Le sessioni non si cancellano, si revocano** (D-006): si scrive la data in
revoked_at e la riga resta. Serve a sapere chi era entrato, da dove e fino a
quando.

**Il blocco dei tentativi si conta sul nome utente scritto**, non sull'utente
trovato: cosi' funziona anche per i nomi che non esistono, e chi prova a
indovinare un nome utente non capisce dal comportamento del programma se ha
azzeccato quello giusto.

**Lo stato dell'utente si rilegge a ogni richiesta.** Un utente disattivato, o
a cui e' cambiato il ruolo, non deve poter continuare a lavorare con la
sessione che aveva gia' aperto. Per questo trova_sessione() controlla sempre
users.is_active e restituisce il ruolo che sta nel database adesso, non quello
che valeva quando la sessione e' nata.
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LoginAttempt, SessionKind, User, UserSession
from app.services import audit, etichette, passwords

logger = logging.getLogger("aurora.auth")

# Byte di casualita' di un gettone di sessione. Trentadue byte sono 256 bit:
# indovinarne uno a tentativi non e' una possibilita' che valga la pena di
# considerare.
TOKEN_BYTES = 32

# Lunghezza massima della colonna login_attempts.username. Il nome scritto va
# tagliato a questa misura prima di scriverlo, altrimenti chi incolla mille
# caratteri nella casella del nome utente non riceve "credenziali non valide"
# ma un errore del database, che e' un modo di far sapere qualcosa di troppo.
USERNAME_MAX_LENGTH = 50


# --- Aiuti di base ----------------------------------------------------------


def adesso() -> datetime:
    """L'ora corrente in UTC, completa di fuso orario.

    Una sola funzione per tutto il modulo: le ore "nude", senza fuso, sono
    vietate da CLAUDE.md, e averne una sola sorgente evita di ritrovarsi meta'
    delle date in ora locale e meta' in UTC.
    """
    return datetime.now(timezone.utc)


def normalizza_username(scritto: str) -> str:
    """Ripulisce il nome utente come e' stato scritto nella casella.

    Toglie gli spazi ai lati e porta tutto in minuscolo. I nomi utente di
    Aurora sono generati in minuscolo (vedi app/services/users.py), quindi
    "Mario.Rossi" e "mario.rossi " sono la stessa persona e non c'e' ragione
    di far fallire l'accesso per una maiuscola di troppo.

    Il taglio a USERNAME_MAX_LENGTH vale anche per la registrazione del
    tentativo: la colonna e' larga cinquanta caratteri.
    """
    return scritto.strip().lower()[:USERNAME_MAX_LENGTH]


def impronta_gettone(gettone: str) -> str:
    """Calcola l'impronta SHA-256 di un gettone, in esadecimale.

    E' la forma in cui il gettone entra nel database. Sessantaquattro
    caratteri, che e' esattamente la larghezza di user_sessions.token_hash.
    """
    return hashlib.sha256(gettone.encode("utf-8")).hexdigest()


def genera_gettone() -> str:
    """Estrae un gettone nuovo, da consegnare al browser dentro un cookie."""
    return secrets.token_urlsafe(TOKEN_BYTES)


# --- Tentativi di accesso e blocco -----------------------------------------


@dataclass(frozen=True)
class StatoBlocco:
    """Dice se un nome utente e' bloccato e per quanto ancora."""

    bloccato: bool
    minuti_rimanenti: int


def registra_tentativo(
    db: Session, username: str, riuscito: bool, request: Request | None
) -> None:
    """Scrive una riga in login_attempt, comunque sia andata.

    Vengono registrati **tutti** i tentativi: quelli riusciti, quelli falliti e
    anche quelli rifiutati dal blocco. Un elenco che tenesse solo i falliti non
    permetterebbe di distinguere "questa persona sbaglia a scrivere" da
    "qualcuno sta provando le password una per una".
    """
    db.add(
        LoginAttempt(
            username=normalizza_username(username),
            success=riuscito,
            ip=audit.client_ip(request),
        )
    )


def stato_blocco(db: Session, username: str) -> StatoBlocco:
    """Dice se questo nome utente e' momentaneamente bloccato.

    La regola: se negli ultimi LOGIN_WINDOW_MINUTES minuti ci sono almeno
    LOGIN_MAX_ATTEMPTS tentativi falliti su questo nome, il nome e' bloccato.
    E' una finestra che scorre: il blocco si scioglie da solo man mano che i
    tentativi vecchi escono dalla finestra, senza nessun lavoro pianificato
    che debba passare a sbloccare.

    I minuti rimanenti si calcolano sul piu' vecchio dei tentativi che stanno
    tenendo chiuso il blocco: quando quello uscira' dalla finestra, i falliti
    scenderanno sotto la soglia.

    Una conseguenza da conoscere: siccome anche i tentativi rifiutati dal
    blocco vengono registrati come falliti, chi continua a martellare tiene
    chiuso il proprio blocco da solo. Su una rete aziendale e' il
    comportamento giusto - l'insistenza non deve pagare - e chi resta chiuso
    fuori per davvero puo' farsi riassegnare la password dal creatore.
    """
    inizio_finestra = adesso() - timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)
    nome = normalizza_username(username)

    # Le date dei tentativi falliti nella finestra, dal piu' recente al piu'
    # vecchio. Se ne leggono solo quanti ne servono per decidere.
    date = db.scalars(
        select(LoginAttempt.created_at)
        .where(
            LoginAttempt.username == nome,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= inizio_finestra,
        )
        .order_by(LoginAttempt.created_at.desc())
        .limit(settings.LOGIN_MAX_ATTEMPTS)
    ).all()

    if len(date) < settings.LOGIN_MAX_ATTEMPTS:
        return StatoBlocco(bloccato=False, minuti_rimanenti=0)

    # date[-1] e' il piu' vecchio dei tentativi che pesano: il blocco dura
    # finche' quello non esce dalla finestra.
    scadenza = date[-1] + timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)
    mancanti = (scadenza - adesso()).total_seconds() / 60

    # Si arrotonda per eccesso e non si scende sotto un minuto: dire "riprova
    # fra 0 minuti" a chi e' appena stato bloccato non aiuterebbe nessuno.
    return StatoBlocco(bloccato=True, minuti_rimanenti=max(1, int(mancanti) + 1))


# --- Sessioni ---------------------------------------------------------------


def crea_sessione(
    db: Session,
    utente: User,
    tipo: SessionKind,
    request: Request | None,
) -> str:
    """Apre una sessione per l'utente e restituisce il gettone in chiaro.

    Il gettone in chiaro esce da questa funzione una volta sola, per essere
    messo nel cookie: nel database ne entra soltanto l'impronta, e da quella
    non si torna indietro. Se il cookie va perso, la sessione non si recupera:
    si rientra.

    La durata dipende dal tipo: una sessione normale vale SESSION_HOURS ore,
    una "ricordami" vale REMEMBER_ME_DAYS giorni.
    """
    if tipo is SessionKind.RICORDAMI:
        durata = timedelta(days=settings.REMEMBER_ME_DAYS)
    else:
        durata = timedelta(hours=settings.SESSION_HOURS)

    gettone = genera_gettone()

    db.add(
        UserSession(
            user_id=utente.id,
            token_hash=impronta_gettone(gettone),
            kind=tipo,
            expires_at=adesso() + durata,
            ip=audit.client_ip(request),
            # La riga User-Agent, tagliata alla larghezza della colonna: serve
            # a far riconoscere all'utente le proprie sessioni, non e' un dato
            # su cui il programma decida qualcosa.
            user_agent=(
                request.headers.get("user-agent", "")[:400] if request else None
            ),
        )
    )

    return gettone


def trova_sessione(
    db: Session, gettone: str, tipo: SessionKind
) -> tuple[UserSession, User] | None:
    """Cerca la sessione a cui appartiene il gettone, se e' ancora buona.

    Restituisce None - e non solleva nessun errore - quando il gettone non
    corrisponde a niente, quando la sessione e' stata revocata, quando e'
    scaduta, quando e' di un tipo diverso da quello atteso, oppure quando
    l'utente nel frattempo e' stato disattivato. Chi chiama non ha bisogno di
    distinguere questi casi: sono tutti "non sei entrato".

    Il controllo su users.is_active si fa **qui**, cioe' a ogni richiesta.
    E' quello che rende immediata la disattivazione di una persona: le sue
    sessioni smettono di funzionare al primo controllo successivo, senza che
    nessuno debba andare a revocarle una per una.

    Il tipo si verifica di proposito: un gettone "ricordami" non deve poter
    essere usato al posto di uno di sessione. Sono due cookie distinti proprio
    perche' hanno regole diverse, e scambiarli aggirerebbe la rotazione.
    """
    if not gettone:
        return None

    riga = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == impronta_gettone(gettone),
            UserSession.kind == tipo,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > adesso(),
            User.is_active.is_(True),
        )
    ).first()

    if riga is None:
        return None

    sessione, utente = riga
    return sessione, utente


def revoca_sessione(db: Session, sessione: UserSession) -> None:
    """Chiude una sessione. La riga resta, con la data di chiusura."""
    if sessione.revoked_at is None:
        sessione.revoked_at = adesso()


def revoca_sessioni_utente(
    db: Session, user_id: uuid.UUID, tranne: uuid.UUID | None = None
) -> int:
    """Chiude tutte le sessioni aperte di un utente. Restituisce quante.

    Con "tranne" si risparmia una sessione: e' il caso del cambio password,
    dove chi la sta cambiando deve restare dentro mentre tutti gli altri
    dispositivi vengono buttati fuori.

    E' un UPDATE, non un DELETE: le righe restano tutte (D-006).
    """
    condizioni = [
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ]
    if tranne is not None:
        condizioni.append(UserSession.id != tranne)

    risultato = db.execute(
        update(UserSession).where(*condizioni).values(revoked_at=adesso())
    )
    return risultato.rowcount or 0


def conta_sessioni_attive(db: Session, user_id: uuid.UUID) -> int:
    """Quante sessioni aperte ha in questo momento un utente."""
    return (
        db.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > adesso(),
            )
        )
        or 0
    )


# --- Accesso ----------------------------------------------------------------


@dataclass
class EsitoAccesso:
    """Com'e' andato un tentativo di entrare.

    L'utente c'e' solo quando l'accesso e' riuscito. Nei due casi di
    fallimento - credenziali sbagliate e blocco - chi chiama non riceve
    nessuna informazione su chi fosse l'utente, perche' non deve poterla
    mostrare.
    """

    utente: User | None
    bloccato: bool
    minuti_rimanenti: int = 0

    @property
    def riuscito(self) -> bool:
        return self.utente is not None


def esegui_accesso(
    db: Session,
    username: str,
    password: str,
    request: Request | None = None,
) -> EsitoAccesso:
    """Verifica le credenziali e, se vanno bene, restituisce l'utente.

    Non apre la sessione e non tocca nessun cookie: quello lo fa la rotta.
    Qui si decide soltanto se la persona ha diritto di entrare.

    L'ordine delle operazioni non e' casuale.

    1. **Prima il blocco.** Si controlla prima ancora di guardare se l'utente
       esiste, cosi' il blocco protegge anche i nomi utente inventati e non
       si spreca tempo di calcolo su una richiesta che verra' rifiutata.
    2. **Poi l'utente.** Se non esiste, si verifica lo stesso una password
       finta: la risposta deve metterci lo stesso tempo, altrimenti
       cronometrandola si scoprirebbe quali nomi utente esistono.
    3. **Poi la password.**
    4. **Un utente disattivato viene trattato come uno che ha sbagliato
       password**: stesso messaggio, stesso tempo. Che un profilo sia stato
       chiuso non e' un'informazione da dare a chi sta bussando.

    Ogni tentativo, comunque finisca, viene registrato in login_attempt e nel
    registro di audit.
    """
    nome = normalizza_username(username)

    blocco = stato_blocco(db, nome)
    if blocco.bloccato:
        registra_tentativo(db, nome, riuscito=False, request=request)
        audit.record(
            db,
            action=audit.ACTION_LOGIN_BLOCKED,
            entity_type=audit.ENTITY_USERS,
            request=request,
            etichetta=nome,
            new_value={"username": nome},
        )
        logger.warning("Accesso rifiutato per blocco: nome utente '%s'", nome)
        return EsitoAccesso(
            utente=None,
            bloccato=True,
            minuti_rimanenti=blocco.minuti_rimanenti,
        )

    utente = db.scalar(select(User).where(User.username == nome))

    if utente is None or not utente.is_active:
        # Si verifica comunque una password finta, per consumare lo stesso
        # tempo che si sarebbe consumato con un utente vero. Vedi il punto 2
        # della docstring.
        passwords.verify_dummy_password(password)
        credenziali_valide = False
    else:
        credenziali_valide = passwords.verify_password(utente.password_hash, password)

    registra_tentativo(db, nome, riuscito=credenziali_valide, request=request)

    if not credenziali_valide:
        audit.record(
            db,
            action=audit.ACTION_LOGIN_FAILED,
            entity_type=audit.ENTITY_USERS,
            entity_id=utente.id if utente is not None else None,
            request=request,
            etichetta=nome,
            new_value={"username": nome},
        )
        logger.info("Accesso fallito per il nome utente '%s'", nome)
        return EsitoAccesso(utente=None, bloccato=False)

    # Accesso riuscito. Se i parametri di argon2 sono cambiati da quando la
    # password era stata impostata, questo e' l'unico momento in cui la
    # password in chiaro e' disponibile per ricalcolare l'impronta.
    if passwords.needs_rehash(utente.password_hash):
        utente.password_hash = passwords.hash_password(password)
        logger.info("Impronta della password aggiornata per '%s'", utente.username)

    audit.record(
        db,
        action=audit.ACTION_LOGIN,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=utente.id,
        request=request,
        etichetta=etichette.nome_utente(utente),
    )
    logger.info("Accesso riuscito per '%s'", utente.username)

    return EsitoAccesso(utente=utente, bloccato=False)


def cambia_password(
    db: Session,
    utente: User,
    nuova_password: str,
    sessione_da_risparmiare: uuid.UUID | None,
    request: Request | None = None,
) -> int:
    """Imposta una password nuova e butta fuori tutti gli altri dispositivi.

    Restituisce quante sessioni sono state revocate.

    La revoca delle altre sessioni non e' un di piu': se la password veniva
    cambiata perche' qualcuno l'aveva scoperta, lasciare aperte le sessioni
    che quel qualcuno aveva gia' avviato renderebbe il cambio inutile.

    La sessione indicata in sessione_da_risparmiare resta aperta: e' quella
    del browser da cui si sta facendo il cambio, che non ha nessun motivo di
    essere buttato fuori. Passando None si revocano proprio tutte, ed e' il
    caso della password riassegnata da un amministratore.
    """
    utente.password_hash = passwords.hash_password(nuova_password)
    utente.must_change_password = False

    revocate = revoca_sessioni_utente(db, utente.id, tranne=sessione_da_risparmiare)

    audit.record(
        db,
        action=audit.ACTION_PASSWORD_CHANGED,
        entity_type=audit.ENTITY_USERS,
        entity_id=utente.id,
        user_id=utente.id,
        request=request,
        etichetta=etichette.nome_utente(utente),
        new_value={"sessioni_revocate": revocate},
    )
    logger.info(
        "Password cambiata da '%s': revocate %s sessioni", utente.username, revocate
    )

    return revocate
