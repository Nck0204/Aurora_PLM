"""Da dove arrivano i messaggi: l'interfaccia della fonte, e quella locale.

Il motore che archivia la posta (`app/services/emails.py`) non sa niente di
Outlook, di IMAP e di cartelle su disco. Sa fare quattro domande, e le fa a un
oggetto che rispetta l'interfaccia `FonteEmail`:

    elenca_nuovi_messaggi()          quali messaggi ci sono da prendere
    scarica_messaggio_grezzo(id)     dammi il messaggio per intero, in byte
    marca_elaborato(id)              questo l'ho archiviato, non ridarmelo
    sposta_in_quarantena(id)         questo non ho saputo dove metterlo

**Perche' l'interfaccia esiste prima della seconda implementazione.** La
sessione 10 realizza solo `FonteLocale`, che legge file `.eml` da una cartella;
il collegamento vero a Microsoft Graph arriva nella sessione 11. Scrivere il
motore contro un'interfaccia invece che contro la cartella e' quello che
permette di collaudarlo **adesso**, senza nessun accesso alla casella
aziendale: i venti casi difficili - l'oggetto con `R:` davanti, il messaggio
senza codice, il file rotto - si scrivono come file e si rileggono all'infinito.
Con Outlook di mezzo, ciascuno di quei casi sarebbe una mail da farsi mandare
da qualcuno.

E' anche la sola forma in cui il collaudo resta possibile per sempre: fra un
anno, chi tocchera' l'attribuzione potra' rieseguire gli stessi venti file e
sapere se ha rotto qualcosa.

**Le quattro operazioni sono tutto quello che serve, e non una di piu'.** Non
c'e' `cancella`, perche' in Aurora non si cancella niente (regola 5 di
CLAUDE.md): un messaggio archiviato viene **spostato**, non tolto. Non c'e'
`segna_come_letto`, perche' lo stato di lettura appartiene alla casella di chi
la usa e Aurora non e' il suo programma di posta.

**Le due operazioni finali si chiamano dopo il commit.** Se il programma si
spegne fra la scrittura nel database e lo spostamento del file, alla ripartenza
il messaggio viene riletto, riconosciuto come gia' archiviato dal suo
Message-ID e spostato allora: la cartella si svuota comunque e nel database non
compare niente due volte. L'ordine inverso - sposta e poi scrivi - perderebbe
invece il messaggio per sempre.


LA CARTELLA DI `FonteLocale`
----------------------------

    MAIL_LOCAL_PATH/               i messaggi da leggere: *.eml
    MAIL_LOCAL_PATH/elaborate/     quelli archiviati e attribuiti
    MAIL_LOCAL_PATH/quarantena/    quelli che aspettano una persona

Le tre cartelle si creano da sole quando servono. L'identificativo di un
messaggio e' il **nome del file**, non il percorso: e' quello che chi indaga
ritrova poi in `email_messages.source_reference` e nella cartella
`elaborate/`.
"""

import logging
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger("aurora.posta.fonte")

# L'estensione dei file che FonteLocale considera messaggi. Tutto il resto
# nella cartella viene ignorato in silenzio: chi ci lascia dentro un blocco
# note o un file di scarto non deve vedersi comparire un messaggio in
# quarantena.
ESTENSIONE_MESSAGGIO = ".eml"

# Le due sottocartelle in cui finiscono i messaggi dopo l'elaborazione.
CARTELLA_ELABORATE = "elaborate"
CARTELLA_QUARANTENA = "quarantena"

# Quanti messaggi al massimo si prendono in un giro. Serve a non tenere
# occupato il server per un'ora la prima volta che si punta Aurora a una
# cartella con dentro dieci anni di posta: il giro successivo prende i
# successivi, e la cartella si svuota in piu' passate.
MESSAGGI_PER_GIRO = 500


class FonteNonDisponibile(Exception):
    """La fonte configurata non si puo' usare adesso.

    La cartella non c'e', il collegamento alla casella non risponde, il
    provider configurato non e' ancora stato realizzato. Il messaggio e' gia'
    scritto in italiano e va bene per essere mostrato: chi la cattura non deve
    ricomporre nessuna frase.
    """


class MessaggioNonTrovato(Exception):
    """L'identificativo chiesto alla fonte non corrisponde a niente.

    Capita normalmente quando due giri si sovrappongono, o quando qualcuno
    sposta a mano un file mentre Aurora sta lavorando: non e' un guasto, e chi
    la cattura salta quel messaggio e prosegue con gli altri.
    """


@runtime_checkable
class FonteEmail(Protocol):
    """Che cosa Aurora si aspetta da una sorgente di posta.

    E' un Protocol e non una classe base astratta perche' non c'e' niente da
    ereditare: sono quattro firme, e chi le rispetta va bene. Una classe base
    con quattro metodi che sollevano NotImplementedError direbbe la stessa
    cosa in piu' righe e costringerebbe a ereditare da noi anche chi domani
    scrivera' l'adattatore di Graph.

    "runtime_checkable" serve a un test solo, quello che verifica che
    FonteLocale rispetti davvero l'interfaccia: senza, isinstance() su un
    Protocol non si puo' chiamare.
    """

    def elenca_nuovi_messaggi(self) -> list[str]:
        """Gli identificativi dei messaggi ancora da archiviare."""
        ...

    def scarica_messaggio_grezzo(self, identificativo: str) -> bytes:
        """Il messaggio per intero, come e' arrivato: intestazioni e corpo."""
        ...

    def marca_elaborato(self, identificativo: str) -> None:
        """Il messaggio e' archiviato: la fonte non deve piu' proporlo."""
        ...

    def sposta_in_quarantena(self, identificativo: str) -> None:
        """Il messaggio e' archiviato ma non attribuito: aspetta una persona."""
        ...


class FonteLocale:
    """Legge i messaggi da una cartella di file `.eml`.

    E' la fonte con cui si collauda tutto il motore senza toccare la casella
    aziendale, ed e' anche quella che si usera' in produzione il giorno in cui
    qualcuno esportera' un archivio di posta vecchia da caricare in blocco.

    **Non si fida del nome del file.** Un identificativo arriva dal database o
    da un modulo, quindi puo' contenere qualunque cosa: `_percorso_di()`
    verifica che sia un nome semplice e che il file stia davvero dentro la
    cartella dei messaggi. Un nome con dentro `..` porterebbe altrimenti a
    leggere - e a spostare - un file qualunque del disco.
    """

    def __init__(self, cartella: Path | None = None) -> None:
        """La cartella e' quella di MAIL_LOCAL_PATH, salvo per i test."""
        self.cartella = Path(cartella) if cartella is not None else settings.mail_local_dir

    # --- Le tre cartelle ---------------------------------------------------

    @property
    def cartella_elaborate(self) -> Path:
        """Dove finiscono i messaggi archiviati e attribuiti."""
        return self.cartella / CARTELLA_ELABORATE

    @property
    def cartella_quarantena(self) -> Path:
        """Dove finiscono i messaggi archiviati ma non attribuiti."""
        return self.cartella / CARTELLA_QUARANTENA

    def prepara(self) -> None:
        """Crea le tre cartelle se non ci sono. Si puo' chiamare sempre."""
        try:
            self.cartella.mkdir(parents=True, exist_ok=True)
            self.cartella_elaborate.mkdir(parents=True, exist_ok=True)
            self.cartella_quarantena.mkdir(parents=True, exist_ok=True)
        except OSError as errore:
            logger.error(
                "La cartella della posta non si prepara (%s): %s",
                self.cartella,
                errore,
            )
            raise FonteNonDisponibile(
                f"La cartella della posta ({self.cartella}) non esiste e non "
                "si riesce a crearla. Controlla MAIL_LOCAL_PATH nel file .env."
            ) from errore

    # --- Le quattro operazioni dell'interfaccia ----------------------------

    def elenca_nuovi_messaggi(self) -> list[str]:
        """I file `.eml` presenti nella cartella, in ordine di nome.

        L'ordine e' quello del nome e non quello della data di modifica: e'
        stabile, si vede guardando la cartella, e si puo' governare dando ai
        file un nome che comincia per data. Un ordine che dipende dal
        filesystem renderebbe irripetibile un collaudo.

        Le sottocartelle non si guardano: `elaborate/` e `quarantena/`
        contengono roba gia' passata di qui, e ripescarla vorrebbe dire
        rileggere tutto l'archivio a ogni giro.
        """
        self.prepara()

        try:
            trovati = [
                percorso.name
                for percorso in sorted(self.cartella.iterdir())
                if percorso.is_file()
                and percorso.suffix.lower() == ESTENSIONE_MESSAGGIO
            ]
        except OSError as errore:
            logger.error("La cartella %s non si legge: %s", self.cartella, errore)
            raise FonteNonDisponibile(
                f"La cartella della posta ({self.cartella}) non si riesce a "
                "leggere."
            ) from errore

        if len(trovati) > MESSAGGI_PER_GIRO:
            logger.info(
                "Nella cartella ci sono %s messaggi: se ne prendono %s, gli "
                "altri al giro successivo",
                len(trovati),
                MESSAGGI_PER_GIRO,
            )
            trovati = trovati[:MESSAGGI_PER_GIRO]

        return trovati

    def scarica_messaggio_grezzo(self, identificativo: str) -> bytes:
        """Il contenuto del file, byte per byte, senza interpretarlo.

        Non si legge come testo apposta: un messaggio di posta e' fatto di
        byte, la codifica dei caratteri e' scritta dentro le sue intestazioni,
        e decidere qui che e' UTF-8 rovinerebbe proprio i messaggi con le
        lettere accentate che si vuole conservare intatti.
        """
        percorso = self._percorso_di(identificativo)
        try:
            return percorso.read_bytes()
        except OSError as errore:
            logger.error("Il messaggio %s non si legge: %s", percorso, errore)
            raise MessaggioNonTrovato(
                f"Il messaggio '{identificativo}' non si riesce a leggere."
            ) from errore

    def marca_elaborato(self, identificativo: str) -> None:
        """Sposta il file in `elaborate/`."""
        self._sposta(identificativo, self.cartella_elaborate)

    def sposta_in_quarantena(self, identificativo: str) -> None:
        """Sposta il file in `quarantena/`."""
        self._sposta(identificativo, self.cartella_quarantena)

    # --- Il lavoro sul disco -----------------------------------------------

    def _percorso_di(self, identificativo: str) -> Path:
        """Da un identificativo al file, verificando che sia dentro casa.

        Due controlli, e servono tutti e due. Il primo e' che il nome sia un
        nome e non un percorso: `Path(nome).name` toglie qualunque cartella,
        quindi `..\\..\\.env` diventa `.env` e non esce dalla cartella. Il
        secondo e' che il file esista davvero li' dentro, perche' fra
        l'elenco e lo scarico qualcuno puo' averlo spostato a mano.
        """
        pulito = Path(identificativo or "").name
        if not pulito or not pulito.lower().endswith(ESTENSIONE_MESSAGGIO):
            raise MessaggioNonTrovato(
                f"'{identificativo}' non e' il nome di un messaggio."
            )

        percorso = self.cartella / pulito
        if not percorso.is_file():
            raise MessaggioNonTrovato(
                f"Il messaggio '{pulito}' non e' piu' nella cartella della posta."
            )

        return percorso

    def _sposta(self, identificativo: str, destinazione: Path) -> None:
        """Sposta il file nella cartella indicata, senza sovrascrivere niente.

        Se un file con lo stesso nome c'e' gia' - due esportazioni fatte in
        giorni diversi con lo stesso nome di file, per esempio - al nuovo si
        aggiunge una coda breve invece di sovrascrivere quello vecchio. Il
        contenuto e' comunque gia' nell'archivio per impronta: quello che si
        sta salvando qui e' la possibilita' di ritrovare il file di partenza.
        """
        percorso = self._percorso_di(identificativo)
        destinazione.mkdir(parents=True, exist_ok=True)

        arrivo = destinazione / percorso.name
        if arrivo.exists():
            arrivo = destinazione / (
                f"{percorso.stem}-{uuid.uuid4().hex[:8]}{percorso.suffix}"
            )

        try:
            percorso.replace(arrivo)
        except OSError as errore:
            # Non si rilancia come FonteNonDisponibile: il messaggio e' gia'
            # nel database e il giro deve proseguire con gli altri. Al giro
            # successivo il file verra' riletto, riconosciuto come gia'
            # archiviato e spostato allora.
            logger.error(
                "Il messaggio %s non si e' potuto spostare in %s: %s",
                percorso,
                destinazione,
                errore,
            )
            return

        logger.info("Messaggio %s spostato in %s", percorso.name, destinazione.name)


def fonte_configurata() -> FonteEmail:
    """La fonte che dice il parametro MAIL_PROVIDER.

    E' l'unico posto del programma in cui si guarda quel parametro: chi vuole
    i messaggi chiama questa funzione e riceve un oggetto che risponde alle
    quattro domande, senza sapere da dove arrivino.

    Con `graph` si ferma con una spiegazione invece di far finta di niente.
    Il collegamento a Microsoft Graph e' materia della sessione 11, e una
    fonte che restituisse un elenco vuoto lascerebbe credere che la casella
    sia vuota - che e' il modo peggiore di non funzionare.
    """
    if settings.MAIL_PROVIDER == "locale":
        return FonteLocale()

    raise FonteNonDisponibile(
        "Il collegamento alla casella di posta aziendale non e' ancora "
        "disponibile. Per adesso Aurora legge i messaggi da una cartella: "
        "metti MAIL_PROVIDER=locale nel file .env."
    )
