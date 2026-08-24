"""Tutto quello che riguarda le password, e nient'altro.

Tre cose sole:

  hash_password()      trasforma una password in un'impronta argon2id.
  verify_password()    dice se una password corrisponde a un'impronta.
  generate_password()  genera una password leggibile da assegnare a qualcuno.

**Una password in chiaro non entra mai nel database e non esce mai da questo
programma.** Non esiste, e non va scritta, nessuna funzione che ne mostri una
gia' assegnata: l'impronta di argon2 non e' reversibile, ed e' esattamente la
ragione per cui la si usa. Quando una persona perde la password non la si
recupera, se ne assegna una nuova (vedi app/services/users.py).

Perche' argon2id e non un'altra funzione. Le funzioni di impronta veloci
(SHA-256 e simili) sono fatte apposta per essere rapide: un calcolatore ne
prova miliardi al secondo e una password corta cade in poche ore. argon2 e'
fatta apposta per essere lenta e affamata di memoria: ogni tentativo costa
tempo e RAM, e questo rende poco pratico provarne tante. La variante "id" e'
quella raccomandata quando non si hanno esigenze particolari, perche' resiste
sia agli attacchi con hardware dedicato sia a quelli che sfruttano i tempi di
accesso alla memoria.
"""

import random
import unicodedata
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Quante parole compongono una password generata, e con che cosa si separano.
# Quattro parole prese dall'elenco di app/services/parole.txt valgono circa 34
# bit: con il blocco dopo cinque tentativi falliti sono abbondanti per una
# password temporanea che va cambiata al primo accesso.
# Il trattino perche' e' l'unico separatore che si detta al telefono senza
# ambiguita' e che non richiede il tasto maiuscolo.
PASSWORD_WORD_COUNT = 4
PASSWORD_SEPARATOR = "-"

# L'elenco delle parole sta in un file di testo accanto a questo modulo: e'
# piu' facile da rileggere e da correggere che una lista dentro il codice.
WORDLIST_PATH = Path(__file__).parent / "parole.txt"

# Numero minimo di parole che l'elenco deve contenere. Se qualcuno un giorno
# lo sfoltisce, e' meglio che il programma si fermi subito con un errore
# chiaro piuttosto che continuare a generare password deboli in silenzio.
MINIMUM_WORDLIST_SIZE = 200

# Un solo PasswordHasher per tutto il programma: e' immutabile e non costa
# niente tenerlo. I parametri sono quelli predefiniti della libreria, che
# seguono le raccomandazioni correnti (RFC 9106). Non si toccano senza una
# ragione misurata: abbassarli indebolisce, alzarli rallenta ogni accesso.
_hasher = PasswordHasher()

# Impronta di comodo, calcolata la prima volta che serve e poi tenuta da parte.
# A che cosa serve e' spiegato in verify_dummy_password().
_dummy_hash: str | None = None


def _load_wordlist() -> tuple[str, ...]:
    """Legge l'elenco delle parole dal file, saltando commenti e righe vuote."""
    parole = []
    for riga in WORDLIST_PATH.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if riga and not riga.startswith("#"):
            parole.append(riga)

    if len(parole) < MINIMUM_WORDLIST_SIZE:
        raise RuntimeError(
            f"L'elenco {WORDLIST_PATH.name} contiene {len(parole)} parole: "
            f"ne servono almeno {MINIMUM_WORDLIST_SIZE} perche' le password "
            "generate siano abbastanza difficili da indovinare."
        )

    return tuple(parole)


# Si legge una volta sola, all'importazione del modulo: il file non cambia
# mentre il server e' acceso.
WORDLIST = _load_wordlist()


def hash_password(password: str) -> str:
    """Calcola l'impronta argon2id di una password.

    E' l'unica forma in cui una password entra nel database. Il risultato e'
    una stringa che contiene gia' dentro di se' il sale casuale e i parametri
    usati, quindi non c'e' nient'altro da conservare a parte questa.
    """
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Dice se la password corrisponde all'impronta. Non solleva eccezioni.

    Restituisce solo vero o falso: chi chiama deve poter scrivere un "if"
    normale senza avvolgere tutto in un try, perche' una password sbagliata e'
    un fatto ordinario e non un errore del programma.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy_password(password: str) -> None:
    """Spreca lo stesso tempo che si sarebbe speso a verificare una password.

    Serve quando il nome utente scritto non esiste. Senza questa chiamata la
    risposta arriverebbe subito, mentre per un utente esistente arriverebbe
    dopo il tempo di argon2: cronometrando le risposte si potrebbe scoprire
    quali nomi utente esistono, che e' esattamente quello che i messaggi di
    errore generici cercano di nascondere.

    L'impronta di comodo si calcola la prima volta che serve, non
    all'importazione del modulo, per non rallentare l'avvio del server.
    """
    global _dummy_hash

    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("password-che-non-appartiene-a-nessuno")

    verify_password(_dummy_hash, password)


def needs_rehash(password_hash: str) -> bool:
    """Dice se l'impronta e' stata calcolata con parametri ormai superati.

    Si chiama dopo un accesso riuscito, quando la password in chiaro e'
    disponibile per un istante ed e' quindi possibile ricalcolare l'impronta
    con i parametri correnti senza disturbare l'utente. Se un domani i
    parametri di argon2 verranno irrobustiti, le impronte si aggiorneranno da
    sole man mano che le persone entrano.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        # Un'impronta illeggibile non e' "da rigenerare": e' rotta. Non e'
        # compito di questa funzione accorgersene, ci pensa verify_password
        # che restituira' falso e non fara' entrare nessuno.
        return False


def generate_password() -> str:
    """Genera una password leggibile: quattro parole italiane unite da trattini.

    Il risultato ha la forma "chiave-fienile-rondine-tavolo". E' fatta per
    essere dettata al telefono e ribattuta a mano una volta sola, perche' chi
    la riceve deve cambiarla al primo accesso.

    Le parole sono estratte senza ripetizione: quattro parole diverse si
    leggono meglio di "casa-casa-luna-casa" e la differenza sul numero di
    combinazioni possibili e' trascurabile.

    random.SystemRandom() e non il generatore normale di random: il primo
    prende i numeri dal sistema operativo ed e' adatto alla crittografia, il
    secondo produce una sequenza prevedibile a chi ne conosca lo stato. Si usa
    questo e non secrets.choice() solo perche' secrets non offre l'estrazione
    senza ripetizione; la sorgente casuale e' la stessa.
    """
    parole = random.SystemRandom().sample(WORDLIST, PASSWORD_WORD_COUNT)
    return PASSWORD_SEPARATOR.join(parole)


def strip_accents(testo: str) -> str:
    """Toglie gli accenti dalle lettere, lasciando la lettera di base.

    Serve a comporre i nomi utente (vedi app/services/users.py): un nome utente
    con l'accento dentro e' un nome utente che prima o poi qualcuno scrive
    senza, e non riesce piu' a entrare.

    Come funziona: la forma NFKD di Unicode scompone la lettera accentata in
    due segni distinti, la lettera e l'accento; si buttano via i segni della
    categoria "Mn" (Mark, nonspacing), cioe' gli accenti, e resta la lettera.
    """
    scomposto = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in scomposto if unicodedata.category(c) != "Mn")
