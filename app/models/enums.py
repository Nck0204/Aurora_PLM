"""Elenchi di valori ammessi (gli "stati") usati dalle tabelle di Aurora.

Ogni elenco qui sotto diventa un vero tipo enumerato di PostgreSQL. Il
vantaggio rispetto a una colonna di testo libero e' che il database stesso
rifiuta un valore sbagliato: uno stato scritto male non entra, invece di
comparire sei mesi dopo in un elenco filtrato che non torna.

Due convenzioni, spiegate una volta per tutte:

  - il **nome della classe** e' in inglese, come tutti gli identificatori del
    progetto (vedi CLAUDE.md, regola 4);
  - il **valore** e' in italiano, perche' non e' un identificatore ma un dato
    che finisce scritto nel database e mostrato all'utente. E' il vocabolario
    che in azienda si usa gia' a voce: "bozza", "in verifica", "rilasciato".

Il nome del membro (a sinistra dell'uguale) e' scritto in maiuscolo come si fa
con le costanti, e ricalca il valore per non doverli tenere a mente in due
lingue diverse.
"""

import enum


class GlobalRole(str, enum.Enum):
    """Ruolo di un utente nell'intero programma, non nel singolo progetto.

    "creatore" e' l'amministratore: crea gli utenti, i clienti, i modelli di
    fasi. "utente" e' chiunque altro: quello che puo' fare dipende dai ruoli
    che gli sono stati assegnati nei singoli progetti.
    """

    CREATORE = "creatore"
    UTENTE = "utente"


class SessionKind(str, enum.Enum):
    """Durata di una sessione di accesso.

    "sessione" dura finche' il browser resta aperto; "ricordami" e' la
    sessione lunga che sopravvive alla chiusura del browser.
    """

    SESSIONE = "sessione"
    RICORDAMI = "ricordami"


class LifecycleState(str, enum.Enum):
    """Ciclo di vita di una versione di prodotto.

    L'ordine di dichiarazione e' anche l'ordine naturale di avanzamento, ma il
    database non lo impone: le regole di passaggio da uno stato all'altro
    saranno scritte nella logica applicativa, non qui.
    """

    IN_SVILUPPO = "in_sviluppo"
    RILASCIATO = "rilasciato"
    IN_PRODUZIONE = "in_produzione"
    SUPERATO = "superato"
    OBSOLETO = "obsoleto"


class ProjectRole(str, enum.Enum):
    """Ruolo di un utente dentro un singolo progetto.

    Un utente puo' essere ingegnere su un progetto e semplice lettore su un
    altro: il ruolo non e' una proprieta' della persona ma del legame fra la
    persona e il progetto.
    """

    PROJECT_MANAGER = "project_manager"
    INGEGNERE = "ingegnere"
    LETTORE = "lettore"


class DocumentState(str, enum.Enum):
    """Stato di avanzamento di un documento.

    "superato" e' lo stato di un documento rimpiazzato da uno piu' recente:
    resta consultabile ma non e' piu' quello valido.
    """

    BOZZA = "bozza"
    IN_VERIFICA = "in_verifica"
    RILASCIATO = "rilasciato"
    SUPERATO = "superato"


class EmailAssignmentState(str, enum.Enum):
    """Come un messaggio di posta e' stato collegato a una versione di prodotto.

    "automatica" quando il collegamento l'ha dedotto il programma dall'oggetto
    o dalla catena di risposte; "manuale" quando l'ha stabilito una persona;
    "quarantena" quando il programma non ha capito a cosa appartiene e il
    messaggio aspetta che qualcuno lo smisti a mano.
    """

    AUTOMATICA = "automatica"
    MANUALE = "manuale"
    QUARANTENA = "quarantena"


class PhaseTransitionState(str, enum.Enum):
    """A che punto e' un passaggio di fase scritto in "phase_transitions".

    Un passaggio non e' sempre un fatto avvenuto: puo' essere una domanda
    ancora senza risposta. Chi ha il permesso di muovere il progetto scrive
    direttamente una riga "approvata"; chi puo' solo chiedere ne scrive una
    "richiesta", che resta li' finche' il project manager non la guarda.

    "respinta" e' una riga che non ha cambiato niente, e si tiene lo stesso:
    fra un anno "perche' a marzo il progetto e' rimasto fermo" e' una domanda
    a cui si deve poter rispondere, e la risposta e' una richiesta respinta
    con la sua motivazione.
    """

    RICHIESTA = "richiesta"
    APPROVATA = "approvata"
    RESPINTA = "respinta"
