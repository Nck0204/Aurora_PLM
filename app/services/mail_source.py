"""Da dove arrivano i messaggi: l'interfaccia della fonte, e le due fonti.

Il motore che archivia la posta (`app/services/emails.py`) non sa niente di
Outlook, di IMAP e di cartelle su disco. Sa fare quattro domande, e le fa a un
oggetto che rispetta l'interfaccia `FonteEmail`:

    elenca_nuovi_messaggi()          quali messaggi ci sono da prendere
    scarica_messaggio_grezzo(id)     dammi il messaggio per intero, in byte
    marca_elaborato(id)              questo l'ho archiviato, non ridarmelo
    sposta_in_quarantena(id)         questo non ho saputo dove metterlo

Le fonti realizzate sono **due**:

    FonteLocale   una cartella di file `.eml` (sessione 10)
    FonteGraph    la casella aziendale di Microsoft 365 (sessione 11)

**Perche' l'interfaccia e' nata prima della seconda implementazione.** La
sessione 10 ha realizzato solo `FonteLocale`. Scrivere il motore contro
un'interfaccia invece che contro la cartella e' quello che ha permesso di
collaudarlo **prima** di avere accesso alla casella aziendale: i venti casi
difficili - l'oggetto con `R:` davanti, il messaggio senza codice, il file
rotto - si scrivono come file e si rileggono all'infinito. Con Outlook di
mezzo, ciascuno di quei casi sarebbe stato una mail da farsi mandare da
qualcuno.

Il conto e' tornato: `FonteGraph` e' entrata **senza toccare una riga** del
motore di `app/services/emails.py`, e i ventiquattro file di prova della
sessione 10 continuano a valere come prima.

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

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote, urlencode

from app.config import settings
from app.services.graph_api import (
    ClienteGraph,
    Credenziali,
    ErroreGraph,
    LimiteDiFrequenza,
)

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
    scrivera' l'adattatore di IMAP.

    "runtime_checkable" serve a due test soli, quelli che verificano che
    FonteLocale e FonteGraph rispettino davvero l'interfaccia: senza,
    isinstance() su un Protocol non si puo' chiamare.
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


# ===========================================================================
#  LA CASELLA AZIENDALE: MICROSOFT GRAPH
# ===========================================================================
#
# La seconda fonte, quella della sessione 11. Fa le stesse quattro cose di
# FonteLocale su una casella di Microsoft 365 invece che su una cartella:
#
#     la cartella "Posta in arrivo"  <->  MAIL_LOCAL_PATH
#     la cartella "Elaborate"        <->  MAIL_LOCAL_PATH/elaborate/
#     la cartella "Quarantena"       <->  MAIL_LOCAL_PATH/quarantena/
#
# Le due cartelle di arrivo le crea Aurora la prima volta che le serve. **Non
# si cancella mai niente dalla casella** (regola 5 di CLAUDE.md): un messaggio
# archiviato viene spostato, e chi apre Outlook lo ritrova dov'e' andato a
# finire.

# I nomi delle due cartelle nella casella. Sono in italiano perche' li legge
# chi usa la casella, non il programma.
CARTELLA_ELABORATE_CASELLA = "Elaborate"
CARTELLA_QUARANTENA_CASELLA = "Quarantena"

# La cartella da cui si leggono i messaggi. "inbox" e' il nome che Graph
# riconosce in qualunque lingua sia configurata la casella: scrivere "Posta in
# arrivo" funzionerebbe solo sulle caselle italiane.
CARTELLA_ARRIVO = "inbox"

# Quanti messaggi si chiedono per pagina nella lettura con il filtro sulla
# data. Cinquanta e' il compromesso solito: poche chiamate, risposte che
# arrivano in fretta.
PER_PAGINA = 50


def credenziali_configurate() -> Credenziali:
    """I quattro parametri della casella, letti dalla configurazione."""
    return Credenziali(
        tenant_id=settings.MAIL_TENANT_ID.strip(),
        client_id=settings.MAIL_CLIENT_ID.strip(),
        client_secret=settings.MAIL_CLIENT_SECRET.strip(),
        mailbox=settings.MAIL_MAILBOX_ADDRESS.strip(),
    )


class SegnalibroGraph:
    """Dove Aurora era arrivata a leggere, fra un controllo e l'altro.

    Dentro ci sono due cose: il **gettone delta**, che Microsoft restituisce a
    fine lettura e che alla lettura successiva vuol dire "dammi solo quello che
    e' cambiato da allora", e l'**ultimo istante elaborato**, che serve alla
    strada di riserva quando le delta query non si possono usare.

    **E' un file, non una tabella** (D-082). Non e' un dato dell'azienda: e' un
    segnalibro, si ricostruisce da solo e perderlo non costa niente. Se sparisce,
    al giro successivo Aurora rilegge la cartella "Posta in arrivo" da capo - che
    contiene solo messaggi non ancora elaborati, perche' quelli elaborati li ha
    spostati lei - e il `Message-ID` impedisce comunque i doppioni (D-074).

    **Un file illeggibile non ferma niente.** Se il JSON e' rotto o il disco non
    risponde, si riparte da zero con una riga nel registro: e' la stessa regola
    dei file di `config/` (D-039).
    """

    def __init__(self, percorso: Path | None = None) -> None:
        self.percorso = (
            Path(percorso) if percorso is not None else settings.mail_graph_state_file
        )

    def leggi(self) -> dict[str, Any]:
        """Il segnalibro salvato, oppure un segnalibro vuoto."""
        try:
            testo = self.percorso.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as errore:
            logger.warning(
                "Il segnalibro della casella (%s) non si legge: %s. Si "
                "ricomincia dall'inizio della cartella.",
                self.percorso,
                errore,
            )
            return {}

        try:
            contenuto = json.loads(testo)
        except ValueError as errore:
            logger.warning(
                "Il segnalibro della casella (%s) e' scritto male: %s. Si "
                "ricomincia dall'inizio della cartella.",
                self.percorso,
                errore,
            )
            return {}

        return contenuto if isinstance(contenuto, dict) else {}

    def scrivi(self, **campi: Any) -> None:
        """Aggiorna solo i campi passati, lasciando gli altri come stanno.

        La scrittura e' atomica - prima un file accanto, poi la sostituzione -
        per la stessa ragione per cui lo e' quella dell'archivio (D-047): un
        server che si spegne a meta' scrittura lascerebbe altrimenti un
        segnalibro troncato, e un segnalibro troncato e' peggio di nessun
        segnalibro.
        """
        contenuto = self.leggi()
        contenuto.update(campi)

        provvisorio = self.percorso.with_name(self.percorso.name + ".tmp")
        try:
            self.percorso.parent.mkdir(parents=True, exist_ok=True)
            provvisorio.write_text(
                json.dumps(contenuto, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            provvisorio.replace(self.percorso)
        except OSError as errore:
            # Non si rilancia: il segnalibro e' una comodita', e perderlo
            # costa una rilettura, non un messaggio.
            logger.error(
                "Il segnalibro della casella (%s) non si e' potuto salvare: "
                "%s. Il prossimo controllo rileggera' la cartella da capo.",
                self.percorso,
                errore,
            )


class FonteGraph:
    """Legge i messaggi dalla casella aziendale con Microsoft Graph.

    Rispetta la stessa interfaccia `FonteEmail` di `FonteLocale`, e questo e'
    il punto: il motore di `app/services/emails.py` non e' stato toccato di una
    riga per farla funzionare (D-076). L'identificativo di un messaggio, qui,
    e' quello che gli da' Microsoft, e finisce in `email_messages.source_reference`
    come per la fonte locale ci finisce il nome del file.

    **Quali messaggi.** Quelli non letti della cartella "Posta in arrivo". Si
    prova prima con le **delta query**, che sono il modo con cui Microsoft
    risponde alla domanda "che cosa e' cambiato da quando ho guardato l'ultima
    volta"; se la casella non le sopporta si passa al **filtro sulla data di
    ricezione**, ricordando l'ultimo istante letto. Le due strade danno lo
    stesso risultato: la seconda fa piu' lavoro.

    **Il segnalibro si salva solo a giro finito.** Finche' c'e' anche un solo
    messaggio elencato e non ancora spostato, il segno non avanza: al controllo
    successivo Microsoft riproporra' la stessa finestra, i messaggi gia'
    archiviati verranno riconosciuti dal loro `Message-ID` e spostati allora, e
    quello rimasto indietro verra' riprovato. E' la stessa proprieta' della
    fonte locale, dove il file resta nella cartella finche' non e' andato a
    posto.
    """

    def __init__(
        self,
        cliente: ClienteGraph | None = None,
        *,
        segnalibro: SegnalibroGraph | None = None,
    ) -> None:
        self.cliente = cliente or ClienteGraph(credenziali_configurate())
        self.segnalibro = (
            segnalibro if segnalibro is not None else SegnalibroGraph()
        )

        # Gli identificativi delle due cartelle di arrivo, chiesti a Microsoft
        # la prima volta che servono e poi tenuti da parte: sono fissi per
        # tutta la vita della casella, e chiederli a ogni messaggio vorrebbe
        # dire raddoppiare le chiamate.
        self._cartelle: dict[str, str] = {}

        # Il giro in corso: che cosa e' stato elencato e non ancora spostato,
        # e che segno si salverebbe quando la coda sara' vuota.
        self._in_sospeso: set[str] = set()
        self._delta_da_salvare: str | None = None
        self._istante_da_salvare: str | None = None
        self._segno_bloccato = False

    # --- Gli indirizzi -----------------------------------------------------

    @property
    def _radice(self) -> str:
        """La parte comune di ogni indirizzo: la casella di cui si parla."""
        casella = quote(self.cliente.credenziali.mailbox, safe="@.")
        return f"/users/{casella}"

    def _messaggio(self, identificativo: str) -> str:
        """L'indirizzo di un messaggio, con l'identificativo reso sicuro.

        L'identificativo arriva da Microsoft, ma passa dal database e da un
        modulo prima di tornare qui: si codifica come si codifica qualunque
        cosa venga da fuori. `quote` lascia stare le lettere, le cifre e i
        segni che negli identificativi di Graph ci sono per davvero.
        """
        pulito = quote(identificativo or "", safe="-_.~=")
        return f"{self._radice}/messages/{pulito}"

    # --- Le quattro operazioni dell'interfaccia ----------------------------

    def elenca_nuovi_messaggi(self) -> list[str]:
        """Gli identificativi dei messaggi non letti della "Posta in arrivo".

        Le due strade - delta query e filtro sulla data - non si scelgono da
        configurazione: si prova la prima e, se la casella la rifiuta per un
        motivo che non riguarda i permessi, si passa alla seconda scrivendolo
        nel registro. Un parametro in piu' da decidere sarebbe un parametro che
        qualcuno metterebbe storto.
        """
        self._in_sospeso = set()
        self._delta_da_salvare = None
        self._istante_da_salvare = None
        self._segno_bloccato = False

        stato = self.segnalibro.leggi()

        try:
            trovati = self._elenca_con_delta(stato.get("delta_link"))
        except LimiteDiFrequenza as errore:
            raise FonteNonDisponibile(errore.messaggio) from errore
        except ErroreGraph as errore:
            if errore.da_riferire_a_una_persona:
                logger.error("Lettura della casella rifiutata: %s", errore.tecnico)
                raise FonteNonDisponibile(errore.messaggio) from errore

            logger.warning(
                "Le delta query non funzionano su questa casella (%s): si "
                "passa al filtro sulla data di ricezione",
                errore.tecnico,
            )
            try:
                trovati = self._elenca_per_data(stato.get("ultimo_istante"))
            except ErroreGraph as secondo:
                logger.error("Lettura della casella fallita: %s", secondo.tecnico)
                raise FonteNonDisponibile(secondo.messaggio) from secondo

        self._in_sospeso = set(trovati)
        logger.info(
            "Nella casella %s ci sono %s messaggi da leggere",
            self.cliente.credenziali.mailbox,
            len(trovati),
        )

        # Un giro senza niente da fare e' un giro finito: il segno si salva
        # subito. Senza questa riga, una casella vuota non registrerebbe mai il
        # proprio segno - lo salva solo lo spostamento dell'ultimo messaggio -
        # e ogni controllo ripartirebbe dall'inizio della cartella.
        self._salva_il_segno_se_e_finita()

        return trovati

    def scarica_messaggio_grezzo(self, identificativo: str) -> bytes:
        """Il messaggio per intero, come lo ha ricevuto la casella.

        Si chiede `/$value`, che restituisce il **MIME integrale**: le
        intestazioni originali, il corpo in tutte le sue forme e gli allegati
        dentro, esattamente come sono arrivati. E' la sola forma che permette di
        conservare il messaggio come fatto avvenuto invece che come lo
        ricomporrebbe Aurora, ed e' anche quella che il motore sa gia' leggere,
        perche' e' identica al contenuto di un file `.eml`.
        """
        try:
            dati = self.cliente.byte(f"{self._messaggio(identificativo)}/$value")
        except ErroreGraph as errore:
            if errore.codice_http == 404:
                # Qualcuno ha spostato il messaggio dalla casella mentre Aurora
                # stava lavorando: si salta e si prosegue con gli altri, come
                # fa la fonte locale con un file sparito.
                self._in_sospeso.discard(identificativo)
                raise MessaggioNonTrovato(
                    "Il messaggio non e' piu' nella casella: probabilmente e' "
                    "stato spostato a mano mentre Aurora stava leggendo."
                ) from errore

            logger.error("Messaggio non scaricato: %s", errore.tecnico)
            raise FonteNonDisponibile(errore.messaggio) from errore

        if not dati:
            self._in_sospeso.discard(identificativo)
            raise MessaggioNonTrovato(
                "Microsoft ha restituito un messaggio vuoto: verra' riprovato "
                "al controllo successivo."
            )

        return dati

    def marca_elaborato(self, identificativo: str) -> None:
        """Sposta il messaggio nella cartella "Elaborate" della casella."""
        self._sposta(identificativo, CARTELLA_ELABORATE_CASELLA)

    def sposta_in_quarantena(self, identificativo: str) -> None:
        """Sposta il messaggio nella cartella "Quarantena" della casella."""
        self._sposta(identificativo, CARTELLA_QUARANTENA_CASELLA)

    # --- La lettura, nelle due strade --------------------------------------

    def _elenca_con_delta(self, gettone_delta: str | None) -> list[str]:
        """La strada normale: "che cosa e' cambiato da quando ho guardato?".

        Alla prima lettura in assoluto non c'e' nessun gettone e Microsoft
        elenca tutto quello che c'e' nella cartella; da li' in poi restituisce
        solo le differenze, e in fondo all'ultima pagina consegna il gettone
        per la volta dopo.

        Un gettone scaduto - capita dopo settimane di server spento - si
        riconosce dal codice 410: si butta e si rilegge da capo.
        """
        indirizzo = gettone_delta or (
            f"{self._radice}/mailFolders/{CARTELLA_ARRIVO}/messages/delta"
            "?$select=id,isRead,receivedDateTime"
        )

        trovati: list[str] = []
        while indirizzo:
            try:
                corpo = self.cliente.json("GET", indirizzo)
            except ErroreGraph as errore:
                if errore.codice_http == 410 and gettone_delta:
                    logger.info(
                        "Il segno di lettura della casella e' scaduto: si "
                        "rilegge la cartella da capo"
                    )
                    self.segnalibro.scrivi(delta_link=None)
                    return self._elenca_con_delta(None)
                raise

            for voce in corpo.get("value") or []:
                if "@removed" in voce:
                    # Il messaggio e' uscito dalla cartella - di solito perche'
                    # lo ha spostato Aurora stessa al giro precedente.
                    continue
                if voce.get("isRead"):
                    continue
                identificativo = voce.get("id")
                if not identificativo:
                    continue
                trovati.append(str(identificativo))
                self._ricorda_istante(voce.get("receivedDateTime"))

            if len(trovati) >= MESSAGGI_PER_GIRO:
                return self._taglia(trovati)

            indirizzo = corpo.get("@odata.nextLink")
            if not indirizzo:
                # Ultima pagina: qui c'e' il gettone per la volta prossima. Non
                # si salva adesso, si salva quando tutti questi messaggi
                # saranno andati a posto.
                self._delta_da_salvare = corpo.get("@odata.deltaLink")

        return trovati

    def _elenca_per_data(self, ultimo_istante: str | None) -> list[str]:
        """La strada di riserva: i non letti da un certo istante in poi.

        Il confronto e' "maggiore **o uguale**" e non "maggiore": due messaggi
        arrivati nello stesso secondo esistono, e perderne uno per una
        disuguaglianza stretta sarebbe un messaggio che l'azienda ha ricevuto e
        Aurora non ha. Rileggerne uno gia' archiviato non costa niente: il
        `Message-ID` lo riconosce e lo salta (D-074).
        """
        filtro = "isRead eq false"
        if ultimo_istante:
            filtro += f" and receivedDateTime ge {ultimo_istante}"

        parametri = urlencode(
            {
                "$select": "id,receivedDateTime",
                "$orderby": "receivedDateTime asc",
                "$top": str(PER_PAGINA),
                "$filter": filtro,
            }
        )
        indirizzo = (
            f"{self._radice}/mailFolders/{CARTELLA_ARRIVO}/messages?{parametri}"
        )

        trovati: list[str] = []
        while indirizzo:
            corpo = self.cliente.json("GET", indirizzo)

            for voce in corpo.get("value") or []:
                identificativo = voce.get("id")
                if not identificativo:
                    continue
                trovati.append(str(identificativo))
                self._ricorda_istante(voce.get("receivedDateTime"))

            if len(trovati) >= MESSAGGI_PER_GIRO:
                return self._taglia(trovati)

            indirizzo = corpo.get("@odata.nextLink")

        return trovati

    def _taglia(self, trovati: list[str]) -> list[str]:
        """Ferma la lettura a MESSAGGI_PER_GIRO e lo scrive nel registro.

        Il segno non si salva: quello che non si e' letto va letto al giro
        successivo, e un segno che avanzasse comunque lo lascerebbe indietro
        per sempre.
        """
        logger.info(
            "Nella casella ci sono almeno %s messaggi: se ne prendono %s, gli "
            "altri al controllo successivo",
            len(trovati),
            MESSAGGI_PER_GIRO,
        )
        self._delta_da_salvare = None
        self._segno_bloccato = True
        return trovati[:MESSAGGI_PER_GIRO]

    def _ricorda_istante(self, valore: Any) -> None:
        """Tiene da parte l'istante di ricezione piu' recente incontrato.

        Il confronto e' fra stringhe e va bene cosi': Graph scrive le date
        sempre nella stessa forma (`2026-08-27T09:12:33Z`), e in quella forma
        l'ordine alfabetico e l'ordine cronologico coincidono.
        """
        if not valore:
            return
        testo = str(valore)
        if self._istante_da_salvare is None or testo > self._istante_da_salvare:
            self._istante_da_salvare = testo

    # --- Lo spostamento ----------------------------------------------------

    def _sposta(self, identificativo: str, nome_cartella: str) -> None:
        """Sposta il messaggio in una cartella della casella, creandola se manca.

        **Non solleva mai**, come non solleva `FonteLocale._sposta()`: quando si
        arriva qui il messaggio e' gia' scritto nel database, e un errore di
        spostamento non deve fermare i messaggi che vengono dopo. Il messaggio
        resta nella "Posta in arrivo" e al controllo successivo viene
        riconosciuto come gia' archiviato e spostato allora.
        """
        try:
            destinazione = self._cartella(nome_cartella)
            self.cliente.json(
                "POST",
                f"{self._messaggio(identificativo)}/move",
                json={"destinationId": destinazione},
            )
        except ErroreGraph as errore:
            # Il permesso di spostare e' una cosa a parte da quello di leggere:
            # con `Mail.Read` e basta, Microsoft risponde 403 a ogni
            # spostamento, e risponderebbe 403 anche fra un'ora e domani. In
            # quel caso il segno **avanza lo stesso**: il messaggio e' gia'
            # archiviato, e tenerlo indietro vorrebbe dire riscaricare tutta la
            # posta in arrivo a ogni controllo per riprovare una cosa che non
            # riuscira' mai. Su tutti gli altri errori - la rete, un guasto
            # momentaneo di Microsoft - il segno resta fermo e al controllo
            # successivo si riprova.
            manca_il_permesso = errore.codice_http == 403
            if manca_il_permesso:
                logger.error(
                    "Il messaggio %s resta nella posta in arrivo: "
                    "all'applicazione manca il permesso di spostare i "
                    "messaggi. Serve «Mail.ReadWrite» invece di «Mail.Read»: "
                    "vedi docs/RICHIESTA_IT.md. Dettaglio: %s",
                    identificativo,
                    errore.tecnico,
                )
            else:
                logger.error(
                    "Il messaggio %s non si e' potuto spostare in «%s»: %s",
                    identificativo,
                    nome_cartella,
                    errore.tecnico,
                )
                self._segno_bloccato = True

            self._in_sospeso.discard(identificativo)
            if manca_il_permesso:
                self._salva_il_segno_se_e_finita()
            return

        logger.info(
            "Messaggio %s spostato in «%s»", identificativo, nome_cartella
        )
        self._in_sospeso.discard(identificativo)
        self._salva_il_segno_se_e_finita()

    def _cartella(self, nome: str) -> str:
        """L'identificativo di una cartella della casella; la crea se non c'e'.

        Il confronto sul nome si fa anche dopo la ricerca perche' il filtro di
        Graph non distingue maiuscole e minuscole allo stesso modo su tutte le
        caselle: se qualcuno ha gia' una cartella "elaborate", si usa quella
        invece di crearne una seconda quasi uguale.
        """
        if nome in self._cartelle:
            return self._cartelle[nome]

        trovata = self._cerca_cartella(nome)
        if trovata is not None:
            self._cartelle[nome] = trovata
            return trovata

        logger.info("La cartella «%s» non c'e' nella casella: viene creata", nome)
        try:
            creata = self.cliente.json(
                "POST", f"{self._radice}/mailFolders", json={"displayName": nome}
            )
        except ErroreGraph as errore:
            # Due controlli partiti insieme possono averla creata tutti e due:
            # in quel caso Microsoft risponde "esiste gia'" e la si ricerca.
            if errore.codice_http == 409:
                trovata = self._cerca_cartella(nome)
                if trovata is not None:
                    self._cartelle[nome] = trovata
                    return trovata
            raise

        identificativo = str(creata.get("id") or "")
        if not identificativo:
            raise ErroreGraph(
                f"La cartella «{nome}» non e' stata creata nella casella e "
                "Microsoft non ha detto perche'.",
                tecnico=f"POST mailFolders senza id: {creata}",
            )

        self._cartelle[nome] = identificativo
        return identificativo

    def _cerca_cartella(self, nome: str) -> str | None:
        """Cerca una cartella di primo livello per nome. None se non c'e'."""
        parametri = urlencode(
            {"$filter": f"displayName eq '{nome}'", "$select": "id,displayName"}
        )
        corpo = self.cliente.json("GET", f"{self._radice}/mailFolders?{parametri}")

        for voce in corpo.get("value") or []:
            if str(voce.get("displayName") or "").casefold() == nome.casefold():
                return str(voce.get("id") or "") or None

        return None

    def _salva_il_segno_se_e_finita(self) -> None:
        """Salva il segnalibro solo quando il giro e' andato a posto tutto.

        E' la riga che rende il giro ripetibile senza perdere niente: se anche
        un solo messaggio e' rimasto indietro, il segno non avanza e al
        controllo successivo la stessa finestra viene riletta.
        """
        if self._in_sospeso or self._segno_bloccato:
            return

        campi: dict[str, Any] = {}
        if self._delta_da_salvare:
            campi["delta_link"] = self._delta_da_salvare
        if self._istante_da_salvare:
            campi["ultimo_istante"] = self._istante_da_salvare

        if campi:
            self.segnalibro.scrivi(**campi)
            self._delta_da_salvare = None

    # --- La prova del collegamento -----------------------------------------

    def verifica(self) -> str:
        """Prova il giro intero e racconta com'e' andata, in una frase.

        E' quello che chiama il pulsante VERIFICA della pagina di
        configurazione: chiede il gettone, legge la scheda della casella e
        conta i messaggi non letti. Se qualcosa non va solleva un `ErroreGraph`
        che dice gia' quale parametro guardare.
        """
        scheda = self.cliente.json(
            "GET", f"{self._radice}?$select=displayName,mail,userPrincipalName"
        )
        nome = scheda.get("displayName") or self.cliente.credenziali.mailbox

        conteggio = self.cliente.json(
            "GET",
            f"{self._radice}/mailFolders/{CARTELLA_ARRIVO}"
            "?$select=displayName,unreadItemCount,totalItemCount",
        )
        non_letti = conteggio.get("unreadItemCount")

        if non_letti is None:
            return f"Collegamento riuscito alla casella di {nome}."

        if non_letti == 0:
            return (
                f"Collegamento riuscito alla casella di {nome}: nella posta in "
                "arrivo non ci sono messaggi da leggere."
            )

        return (
            f"Collegamento riuscito alla casella di {nome}: nella posta in "
            f"arrivo ci sono {non_letti} messagg"
            f"{'io' if non_letti == 1 else 'i'} da leggere."
        )


def fonte_configurata() -> FonteEmail:
    """La fonte che dice il parametro MAIL_PROVIDER.

    E' l'unico posto del programma in cui si guarda quel parametro: chi vuole
    i messaggi chiama questa funzione e riceve un oggetto che risponde alle
    quattro domande, senza sapere da dove arrivino.

    Con `graph` mancano i parametri, ci si ferma **prima** di chiamare
    Microsoft e si dice quali: una fonte che restituisse un elenco vuoto
    lascerebbe credere che la casella sia vuota, che e' il modo peggiore di non
    funzionare.
    """
    if settings.MAIL_PROVIDER == "locale":
        return FonteLocale()

    credenziali = credenziali_configurate()
    mancanti = credenziali.mancanti()
    if mancanti:
        raise FonteNonDisponibile(
            "La casella di posta aziendale non e' ancora configurata: "
            f"manca{'no' if len(mancanti) > 1 else ''} "
            + ", ".join(mancanti)
            + ". Si scrive nella pagina «Configurazione posta»."
        )

    return FonteGraph(ClienteGraph(credenziali))
