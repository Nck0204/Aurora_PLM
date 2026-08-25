"""Le voci della barra laterale, in un posto solo.

Il menu di Aurora e' scritto qui e non dentro il template per due ragioni.

La prima e' che le voci vanno filtrate per ruolo, e un filtro fatto con dei
`{% if %}` dentro l'HTML diventa illeggibile alla terza condizione. La seconda
e' che parecchie voci puntano a sezioni che ancora non esistono: quali sono e
in quale sessione arriveranno e' un fatto del programma, non della grafica, e
va scritto in un posto in cui si aggiorna cancellando una riga.

**Nascondere una voce non protegge niente.** Il controllo che conta e' la
dipendenza dichiarata sulla rotta (`richiedi_login`, `richiedi_creatore` in
app/dependencies.py), che a sua volta chiede a `permissions.puo()`: quello e'
il lucchetto. Il menu si limita a non mostrare le porte che non si aprirebbero
comunque, cosi' nessuno ci va a sbattere.

Per la stessa ragione qui dentro **non si guarda il ruolo di nessuno**: la
risposta arriva gia' fatta da chi l'ha chiesta a `permissions.puo()`, e questo
file la usa e basta (D-051).

Quando una sezione viene realizzata si toglie `attiva=False` dalla sua voce e
si mette il percorso giusto. E' l'unica modifica necessaria: la barra laterale
si aggiorna da sola in tutte le pagine.
"""

from dataclasses import dataclass

from app.models import User


@dataclass(frozen=True)
class VoceMenu:
    """Una voce della barra laterale.

    etichetta       il testo che si legge
    percorso        dove porta. Per le voci spente e' il percorso che avra',
                    e serve solo a ricordarselo: il template non lo usa.
    icona           il nome dell'icona in templates/components/icone.html
    attiva          falsa finche' la sezione non esiste. Le voci spente si
                    vedono ma non si possono premere.
    solo_creatore   vera per le sezioni riservate al ruolo di creatore
    nota            la scritta piccola in fondo alla voce spenta
    """

    etichetta: str
    percorso: str
    icona: str
    attiva: bool = True
    solo_creatore: bool = False
    nota: str = ""


# Il menu principale. L'ordine e' quello in cui le voci compaiono, ed e'
# l'ordine del lavoro: si parte da un prodotto, ci si apre sopra un progetto,
# dentro il progetto si mettono i documenti, intorno gira la posta.
MENU_PRINCIPALE: tuple[VoceMenu, ...] = (
    VoceMenu(
        etichetta="Prodotti",
        percorso="/prodotti",
        icona="prodotti",
        attiva=True,
    ),
    VoceMenu(
        etichetta="Progetti",
        percorso="/progetti",
        icona="progetti",
        attiva=True,
    ),
    VoceMenu(
        etichetta="Documenti",
        percorso="/documenti",
        icona="documenti",
        attiva=True,
    ),
    VoceMenu(
        etichetta="Posta",
        percorso="/posta",
        icona="posta",
        attiva=False,
        nota="sessione 10",
    ),
    VoceMenu(
        etichetta="Clienti",
        percorso="/clienti",
        icona="clienti",
        attiva=True,
        solo_creatore=True,
    ),
    VoceMenu(
        etichetta="Utenti",
        percorso="/utenti",
        icona="utenti",
        attiva=True,
        solo_creatore=True,
    ),
    VoceMenu(
        etichetta="Permessi",
        percorso="/permessi",
        icona="permessi",
        attiva=True,
        solo_creatore=True,
    ),
    VoceMenu(
        etichetta="Diagnostica",
        percorso="/diagnostica",
        icona="diagnostica",
        attiva=False,
        solo_creatore=True,
        nota="sessione 11",
    ),
)

# Le voci di servizio, in fondo alla barra e staccate dalle altre: non sono
# parte del lavoro di tutti i giorni.
MENU_SERVIZIO: tuple[VoceMenu, ...] = (
    VoceMenu(
        etichetta="Stile",
        percorso="/stile",
        icona="stile",
        attiva=True,
        solo_creatore=True,
    ),
)


def voci_visibili(
    voci: tuple[VoceMenu, ...],
    utente: User | None,
    puo_amministrare: bool = False,
) -> list[VoceMenu]:
    """Le voci che questo utente puo' vedere.

    Chi non e' entrato non vede niente: la barra laterale esiste solo dentro
    il programma, e le pagine di accesso non ce l'hanno.

    "puo_amministrare" arriva gia' calcolato da app/dependencies.py, che l'ha
    chiesto a permissions.puo(). Qui non si guarda nessun ruolo apposta: se
    questa funzione decidesse per conto suo chi e' creatore, sarebbe la
    seconda regola di accesso del programma, e la prima volta che cambia
    l'altra questa resterebbe indietro.
    """
    if utente is None:
        return []

    return [voce for voce in voci if not voce.solo_creatore or puo_amministrare]


def sezione_corrente(percorso: str) -> str | None:
    """Quale voce di menu corrisponde all'indirizzo che si sta guardando.

    Il confronto e' sul primo pezzo del percorso, non sull'uguaglianza: stando
    su `/utenti/nuovo` la voce "Utenti" deve risultare comunque quella
    corrente. Senza questo, la barra laterale si spegnerebbe tutte le volte
    che si apre una sottopagina, e chi guarda non saprebbe piu' dove si trova.
    """
    for voce in MENU_PRINCIPALE + MENU_SERVIZIO:
        if percorso == voce.percorso or percorso.startswith(voce.percorso + "/"):
            return voce.percorso

    return None
