"""Come si legge un messaggio di posta: intestazioni, corpo, allegati, oggetto.

Sta in un file suo e non dentro `emails.py` per una ragione sola, ma pesante:
**qui non si tocca il database.** Sono funzioni pure che prendono dei byte e
restituiscono dei dati, e questo le rende provabili una per una senza
PostgreSQL, senza un prodotto da inventare e senza una transazione da
annullare. La meta' difficile della sessione 10 - riconoscere l'oggetto con
`R:` davanti, gli spazi in mezzo alle parentesi, le lettere accentate scritte
male da un programma di posta di vent'anni fa - e' tutta qui dentro.

Quello che c'e' in `emails.py` e' invece il mestiere opposto: prendere quello
che questo file ha capito e trasformarlo in righe di tabella, permessi
compresi.


TRE PRINCIPI
------------

**Non si solleva mai su un messaggio brutto.** Un `.eml` troncato, senza
intestazioni, con una data che non e' una data o con la codifica dei caratteri
dichiarata sbagliata deve produrre un risultato povero, non un'eccezione: il
messaggio verra' archiviato lo stesso e finira' in quarantena, dove una persona
lo guardera'. La regola della sessione e' "mai scartare, mai bloccarsi", e
un'eccezione qui fermerebbe l'acquisizione di tutti gli altri.

**Il file originale resta la fonte della verita'.** Tutto quello che si estrae
qui - mittente, oggetto, corpo, allegati - e' una copia comoda per cercare. Il
`.eml` per intero va nell'archivio per impronta come tutti gli altri file
(D-004), e il giorno in cui questa lettura si scoprisse sbagliata si puo'
rifare sul file di allora.

**L'oggetto e' un indizio, non un identificatore.** La scomposizione
`[CODICE][Vn][MOTIVO]` e' una convenzione che le persone rispettano quasi
sempre: quel "quasi" e' il motivo per cui esistono la ricerca libera del
codice, l'eredita' dal filo di conversazione e infine la quarantena.
"""

import hashlib
import logging
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

logger = logging.getLogger("aurora.posta.lettura")


# ---------------------------------------------------------------------------
#  1. LE COSTANTI DELLA LETTURA
# ---------------------------------------------------------------------------

# Quello che si scrive nella colonna del mittente quando il messaggio non ne
# dichiara nessuno. La colonna e' obbligatoria e un messaggio senza mittente
# esiste davvero: e' il file rotto, ed e' uno dei casi da collaudare.
MITTENTE_SCONOSCIUTO = "(mittente sconosciuto)"

# Le sigle con cui i programmi di posta segnano una risposta o un inoltro. Sono
# scritte qui e non in un file di configurazione perche' non sono una regola
# dell'azienda: sono il modo in cui Outlook, Thunderbird e i loro cugini
# italiani e inglesi scrivono gli oggetti da trent'anni.
#
# "i" e' l'inoltro di Outlook in italiano, "r" la risposta; "re", "fw", "fwd" e
# "rif" sono le forme inglesi e quella lunga italiana. Il confronto e' senza
# distinzione di maiuscole e tollera gli spazi prima dei due punti, che
# capitano quando qualcuno riscrive l'oggetto a mano.
PREFISSI_RISPOSTA: tuple[str, ...] = ("r", "re", "rif", "i", "fw", "fwd")

# Un prefisso e' la sigla, eventuali spazi, un eventuale contatore fra
# parentesi quadre (Outlook scrive "Re[2]:") e i due punti.
_PREFISSO = re.compile(
    r"^\s*(?:" + "|".join(PREFISSI_RISPOSTA) + r")\s*(?:\[\s*\d+\s*\])?\s*:\s*",
    re.IGNORECASE,
)

# Quante volte al massimo si toglie un prefisso. Un oggetto passato di mano
# dieci volte ne accumula dieci; venti e' un limite che nessun messaggio vero
# raggiunge e che impedisce a un file costruito apposta di far girare a vuoto
# il programma.
MASSIMO_PREFISSI = 20

# La forma dell'oggetto che la convenzione aziendale chiede:
#
#     [RMS1100-24-110SW][V2][SPECS] Chiarimento sulla tensione
#
# Le tre parentesi si leggono in ordine e solo la prima e' obbligatoria: la
# versione e il motivo possono mancare. Gli spazi dentro e fuori le parentesi
# sono tollerati perche' li scrivono le persone; le maiuscole non contano
# perche' nessuno le controlla mentre digita.
_OGGETTO_FORMATTATO = re.compile(
    r"^\s*\[\s*(?P<codice>[^\[\]]+?)\s*\]"
    r"(?:\s*\[\s*[Vv]\s*(?P<versione>\d{1,4})\s*\])?"
    r"(?:\s*\[\s*(?P<motivo>[^\[\]]+?)\s*\])?",
)

# Un elemento che potrebbe essere un codice prodotto, cercato dentro un
# oggetto qualunque. I codici parlanti dell'azienda sono fatti di lettere,
# cifre e trattini ("RMS1100-24-110SW"): la punteggiatura che ci sta intorno -
# parentesi, virgole, due punti - non ne fa parte e serve a delimitarli.
_ELEMENTO_CODICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/\.]{2,59}")

# Un identificativo di messaggio come compare dentro In-Reply-To e References:
# fra parentesi angolari.
_IDENTIFICATIVO = re.compile(r"<([^<>\s]+)>")

# Il dominio con cui si costruisce l'identificativo dei messaggi che non ne
# hanno uno. Non e' un dominio vero e non deve esserlo: serve a rendere
# evidente, guardando il database, che quell'identificativo se l'e' inventato
# Aurora.
DOMINIO_IDENTIFICATIVO_COSTRUITO = "impronta.aurora.local"

# Quanto puo' essere lungo un identificativo di messaggio: e' la misura della
# colonna, che a sua volta e' il limite di una riga di intestazione.
LUNGHEZZA_IDENTIFICATIVO = 998

# Le misure delle altre colonne, per tagliare qui invece di far arrivare
# l'errore da PostgreSQL scritto in inglese.
LUNGHEZZA_MITTENTE = 320
LUNGHEZZA_OGGETTO = 500
LUNGHEZZA_NOME_ALLEGATO = 255
LUNGHEZZA_MIME = 120

# Il tipo che si scrive quando il messaggio non lo dichiara.
MIME_SCONOSCIUTO = "application/octet-stream"

# Quante righe vuote di fila restano nel corpo convertito da HTML. Una pagina
# HTML fatta di tabelle produce decine di righe vuote, e un corpo tutto bianco
# e' illeggibile quanto un corpo tutto attaccato.
MASSIME_RIGHE_VUOTE = 1

# Il carattere che PostgreSQL non accetta dentro una colonna di testo.
CARATTERE_NULLO = "\x00"


# ---------------------------------------------------------------------------
#  2. QUELLO CHE LA LETTURA PRODUCE
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Allegato:
    """Un allegato staccato dal messaggio, ancora in memoria.

    Il contenuto sta qui dentro e non nell'archivio perche' questo file non
    tocca il disco: chi lo chiama lo deposita, e lo fa passando da
    `storage.deposita()` come tutti gli altri file di Aurora.
    """

    nome_file: str
    mime_type: str
    contenuto: bytes

    @property
    def dimensione(self) -> int:
        """Quanti byte occupa."""
        return len(self.contenuto)


@dataclass(frozen=True)
class OggettoScomposto:
    """Che cosa si e' capito leggendo l'oggetto di un messaggio.

    oggetto        com'era scritto, per intero;
    pulito         senza i prefissi di risposta e di inoltro;
    prefissi       quelli tolti, nell'ordine in cui c'erano ("Re", "Fwd");
    codice         il codice prodotto scritto nella prima parentesi, se c'era;
    versione       il numero della seconda parentesi, se c'era;
    motivo         la sigla della terza parentesi, se c'era. **Non e' ancora
                   detto che sia un motivo ammesso**: chi lo sa e' il
                   database, e la verifica si fa in emails.py.
    """

    oggetto: str
    pulito: str
    prefissi: tuple[str, ...] = ()
    codice: str | None = None
    versione: int | None = None
    motivo: str | None = None

    @property
    def formattato(self) -> bool:
        """Vero se l'oggetto rispetta la convenzione delle parentesi."""
        return self.codice is not None


@dataclass(frozen=True)
class MessaggioLetto:
    """Un messaggio di posta, letto e scomposto. Nessun accesso al database.

    "identificativo_costruito" e' vero quando il messaggio non dichiarava
    nessun Message-ID e Aurora gliene ha dato uno ricavato dall'impronta del
    file. Serve a saperlo dopo: quell'identificativo e' stabile - rileggendo
    lo stesso file si ottiene lo stesso - quindi la ripetibilita' vale anche
    per i messaggi rotti, ma non e' un identificativo che qualcun altro
    riconoscerebbe.

    "difetti" e' l'elenco in italiano di quello che non tornava mentre si
    leggeva. Non ferma niente: finisce nel registro su file e nella pagina
    della quarantena, dove serve a capire perche' un messaggio e' li'.
    """

    identificativo: str
    identificativo_costruito: bool
    mittente: str
    destinatari: list[dict[str, str]]
    oggetto: str | None
    scomposizione: OggettoScomposto
    inviato_il: datetime | None
    in_risposta_a: str | None
    riferimenti: str | None
    corpo: str | None
    allegati: tuple[Allegato, ...]
    difetti: tuple[str, ...] = ()

    @property
    def identificativi_del_filo(self) -> list[str]:
        """Gli identificativi degli altri messaggi della conversazione.

        Sono quelli di In-Reply-To e di References messi insieme, senza
        doppioni e nell'ordine in cui compaiono: dal piu' lontano al piu'
        vicino, che e' l'ordine con cui li scrivono i programmi di posta.
        """
        trovati: list[str] = []
        for testo in (self.riferimenti, self.in_risposta_a):
            for identificativo in identificativi_in(testo):
                if identificativo not in trovati:
                    trovati.append(identificativo)
        return trovati


# ---------------------------------------------------------------------------
#  3. L'OGGETTO: PREFISSI E PARENTESI
# ---------------------------------------------------------------------------


def togli_prefissi(oggetto: str) -> tuple[str, tuple[str, ...]]:
    """Toglie i "Re:", "R:", "Fwd:", "I:" dall'inizio di un oggetto.

    Restituisce l'oggetto ripulito e le sigle tolte, nell'ordine in cui
    c'erano. Le sigle si restituiscono e non si buttano perche' dicono una
    cosa vera del messaggio - e' una risposta, e' un inoltro - che finisce in
    `subject_parsed` e si legge nella pagina del messaggio.

    Toglie **tutti** i prefissi accumulati, uno per volta: un oggetto passato
    di mano quattro volte comincia per "R: Re: Fwd: R:", e il codice prodotto
    sta dopo. Si ferma comunque a MASSIMO_PREFISSI, perche' un file costruito
    apposta con diecimila "Re:" non deve poter far girare a vuoto il
    programma.
    """
    testo = oggetto or ""
    tolti: list[str] = []

    for _ in range(MASSIMO_PREFISSI):
        trovato = _PREFISSO.match(testo)
        if trovato is None:
            break
        tolti.append(trovato.group(0).strip().rstrip(":").strip())
        testo = testo[trovato.end() :]

    return testo.strip(), tuple(tolti)


def scomponi_oggetto(oggetto: str | None) -> OggettoScomposto:
    """Legge l'oggetto secondo la convenzione `[CODICE][Vn][MOTIVO]`.

    Il giro e' sempre lo stesso: prima si tolgono i prefissi di risposta, poi
    si guarda se quello che resta comincia con le parentesi. Sono due passi e
    non uno perche' il secondo e' ancorato all'inizio: la convenzione dice che
    le parentesi stanno **davanti** all'oggetto, e cercarle in mezzo
    riconoscerebbe come codice anche una parentesi citata dentro una frase.

    Un oggetto che non rispetta la convenzione non e' un errore: si restituisce
    la scomposizione con il solo `pulito` valorizzato, e chi ha chiamato passa
    alla regola successiva - la ricerca libera del codice.

    La seconda parentesi si riconosce come versione **solo** se comincia per
    "v" seguita da cifre. `[RMS1100][SPECS]` ha due parentesi e la seconda e'
    il motivo, non una versione: e' il caso normale di chi non specifica la
    versione, ed e' anche il motivo per cui i due gruppi sono facoltativi
    separatamente.
    """
    testo = oggetto or ""
    pulito, prefissi = togli_prefissi(testo)

    trovato = _OGGETTO_FORMATTATO.match(pulito)
    if trovato is None:
        return OggettoScomposto(oggetto=testo, pulito=pulito, prefissi=prefissi)

    codice = (trovato.group("codice") or "").strip()
    versione_scritta = trovato.group("versione")
    motivo = (trovato.group("motivo") or "").strip() or None

    return OggettoScomposto(
        oggetto=testo,
        pulito=pulito,
        prefissi=prefissi,
        codice=codice or None,
        versione=int(versione_scritta) if versione_scritta else None,
        motivo=motivo,
    )


def elementi_candidati(oggetto: str | None) -> list[str]:
    """Le parole dell'oggetto che potrebbero essere un codice prodotto.

    Serve alla seconda regola di attribuzione: il codice scritto in mezzo alla
    frase, senza parentesi. Si estraggono gli elementi fatti di lettere, cifre
    e trattini e si lascia al database il compito di dire quali sono codici
    veri - un elenco di parole confrontato con una colonna unica e' una
    interrogazione sola.

    L'ordine e' dal piu' lungo al piu' corto. Con due prodotti chiamati
    "RMS1100" e "RMS1100-24" e un oggetto che contiene il secondo, cercare
    prima il piu' lungo evita di attribuire il messaggio al prodotto
    sbagliato: la corrispondenza piu' specifica e' quella che chi ha scritto
    l'oggetto aveva in mente.

    Le parentesi quadre non fanno parte degli elementi, quindi anche un
    oggetto formattato che la prima regola ha scartato passa di qui con il suo
    codice.
    """
    testo = oggetto or ""
    trovati: list[str] = []
    for elemento in _ELEMENTO_CODICE.findall(testo):
        # Un elemento che finisce con la punteggiatura di fine frase la
        # perde: "codice RMS1100-24-110SW." non e' un codice che finisce
        # per punto.
        pulito = elemento.strip(".")
        if pulito and pulito not in trovati:
            trovati.append(pulito)

    return sorted(trovati, key=len, reverse=True)


def identificativi_in(intestazione: str | None) -> list[str]:
    """Gli identificativi di messaggio scritti dentro un'intestazione.

    In-Reply-To e References contengono identificativi fra parentesi angolari,
    separati da spazi. Qualche programma di posta le parentesi se le dimentica:
    in quel caso si prendono gli elementi separati da spazi, che e' l'unica
    lettura possibile e non fa danni - un elemento che non e' un
    identificativo semplicemente non corrispondera' a nessun messaggio.
    """
    testo = (intestazione or "").strip()
    if not testo:
        return []

    trovati = [
        identificativo.strip()
        for identificativo in _IDENTIFICATIVO.findall(testo)
        if identificativo.strip()
    ]
    if trovati:
        return trovati

    return [pezzo.strip() for pezzo in testo.split() if pezzo.strip()]


def normalizza_identificativo(identificativo: str | None) -> str:
    """Un identificativo come si scrive nel database: senza parentesi angolari.

    Le parentesi appartengono all'intestazione, non all'identificativo. Si
    tolgono qui, in un punto solo, cosi' il confronto fra il Message-ID di un
    messaggio e il References di un altro e' un'uguaglianza fra stringhe della
    stessa forma. Chi le lasciasse dentro a meta' dei valori otterrebbe un
    filo di conversazione che si spezza senza motivo apparente.
    """
    pulito = (identificativo or "").strip()
    trovati = _IDENTIFICATIVO.findall(pulito)
    if trovati:
        pulito = trovati[0].strip()
    return pulito[:LUNGHEZZA_IDENTIFICATIVO]


def identificativo_dallimpronta(impronta: str) -> str:
    """L'identificativo dei messaggi che non ne dichiarano uno.

    Si ricava dall'impronta SHA-256 del file, quindi e' **stabile**: rileggere
    lo stesso file produce lo stesso identificativo, e il messaggio non viene
    archiviato due volte. E' quello che fa valere la ripetibilita'
    dell'acquisizione anche per i messaggi rotti, che sono proprio quelli che
    si riprova a leggere piu' spesso.

    Due file diversi con lo stesso contenuto sono lo stesso messaggio, ed e'
    giusto che lo siano: e' la stessa mail esportata due volte.
    """
    return f"aurora-{impronta}@{DOMINIO_IDENTIFICATIVO_COSTRUITO}"


def impronta_di(dati: bytes) -> str:
    """L'impronta SHA-256 dei byte del messaggio.

    E' la stessa che calcolera' l'archivio depositando il file. Si calcola
    anche qui perche' serve **prima** del deposito, per costruire
    l'identificativo dei messaggi che non ne hanno uno e poter cosi' scoprire
    che quel messaggio c'e' gia' senza scrivere niente.
    """
    return hashlib.sha256(dati).hexdigest()


# ---------------------------------------------------------------------------
#  4. DA HTML A TESTO
# ---------------------------------------------------------------------------


class _HtmlInTesto(HTMLParser):
    """Riduce una pagina HTML al testo che ci si legge dentro.

    Non e' un convertitore generale e non prova a esserlo: serve a rendere
    cercabile e leggibile il corpo di un messaggio, non a ricostruire
    l'impaginazione. Fa tre cose:

      - butta via quello che non e' testo da leggere (script, stile, testa);
      - trasforma in un a capo i marcatori che vanno a capo davvero
        (paragrafi, righe di tabella, voci di elenco, `<br>`);
      - lascia passare tutto il resto, con le entita' gia' riportate ai
        caratteri veri (`convert_charrefs`, che e' il valore predefinito).

    Il messaggio originale in HTML resta comunque dentro il `.eml`
    nell'archivio: se un giorno servira' mostrarlo com'era, il file c'e'.
    """

    # Quello che sta dentro questi marcatori non si legge: e' programma o
    # foglio di stile finito nel corpo del messaggio.
    IGNORATI = frozenset({"script", "style", "head", "title"})

    # Chiudendo uno di questi si va a capo.
    VANNO_A_CAPO = frozenset(
        {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
         "blockquote", "table", "ul", "ol", "pre"}
    )

    # Chiudendo uno di questi si mette uno spazio e non un a capo. Sono le
    # celle di una tabella: meta' delle mail aziendali sono impaginate con le
    # tabelle, e mandare a capo ogni cella farebbe di una riga di tre colonne
    # tre righe. Senza separatore, invece, le celle si attaccherebbero fra
    # loro ("15 settembre" e "30 ottobre" diventerebbero una parola sola).
    SEPARANO = frozenset({"td", "th"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pezzi: list[str] = []
        self._salta = 0

    def handle_starttag(self, tag: str, attrs: list[Any]) -> None:
        if tag in self.IGNORATI:
            self._salta += 1
        elif tag == "br":
            self._pezzi.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.IGNORATI:
            self._salta = max(0, self._salta - 1)
        elif tag in self.VANNO_A_CAPO:
            self._pezzi.append("\n")
        elif tag in self.SEPARANO:
            self._pezzi.append(" ")

    def handle_data(self, data: str) -> None:
        if self._salta == 0:
            self._pezzi.append(data)

    def testo(self) -> str:
        """Il testo raccolto, con le righe vuote di troppo tolte."""
        return _compatta_righe("".join(self._pezzi))


def scrivibile(testo: str) -> str:
    """Il testo ripulito di quello che una colonna di PostgreSQL non accetta.

    **PostgreSQL rifiuta il carattere nullo dentro una colonna di testo**, e
    non e' una curiosita' teorica: un `.eml` rovinato - un PDF rinominato, un
    file troncato a meta' di un allegato binario - ne contiene a decine, e
    finiscono dritti nel corpo del messaggio.

    Senza questa ripulitura l'INSERT fallisce, il messaggio viene contato fra
    gli errori invece che finire in quarantena, e il file resta nella cartella
    per essere riprovato al giro dopo e fallire di nuovo. Un file rotto
    continuerebbe a comparire fra gli errori per sempre, che e' esattamente il
    contrario di "mai scartare, mai bloccarsi".

    Si toglie **solo** il carattere nullo. Gli altri caratteri di controllo
    PostgreSQL li accetta, e toglierli vorrebbe dire rovinare i messaggi che
    li contengono per una ragione loro.
    """
    if CARATTERE_NULLO in testo:
        logger.warning(
            "Il messaggio conteneva %s caratteri nulli, tolti prima della "
            "scrittura",
            testo.count(CARATTERE_NULLO),
        )
        return testo.replace(CARATTERE_NULLO, "")
    return testo


def _compatta_righe(testo: str) -> str:
    """Toglie gli spazi in coda alle righe, le righe vuote di troppo e i nulli."""
    pulito = scrivibile(testo)
    righe = [riga.strip() for riga in pulito.replace("\r\n", "\n").split("\n")]

    risultato: list[str] = []
    vuote = 0
    for riga in righe:
        if riga:
            vuote = 0
            risultato.append(riga)
            continue
        vuote += 1
        if vuote <= MASSIME_RIGHE_VUOTE and risultato:
            risultato.append("")

    while risultato and not risultato[-1]:
        risultato.pop()

    return "\n".join(risultato)


def html_in_testo(html: str) -> str:
    """Il testo leggibile dentro un corpo HTML. Non solleva mai.

    Un HTML malformato - marcatori aperti e mai chiusi, virgolette sbagliate -
    non e' un caso raro: e' il caso normale della posta. HTMLParser lo
    attraversa comunque; se qualcosa andasse storto lo stesso, si restituisce
    il testo senza marcatori invece di far fallire l'archiviazione di un
    messaggio.
    """
    lettore = _HtmlInTesto()
    try:
        lettore.feed(html)
        lettore.close()
    except Exception as errore:  # pragma: no cover - HTMLParser e' molto tollerante
        logger.warning("Il corpo HTML non si e' letto per intero: %s", errore)

    return lettore.testo()


# ---------------------------------------------------------------------------
#  5. LA LETTURA VERA E PROPRIA
# ---------------------------------------------------------------------------


def _testo_intestazione(messaggio: Message, nome: str) -> str | None:
    """Un'intestazione come stringa, o None. Non solleva mai.

    Con la politica "default" della libreria standard le intestazioni tornano
    gia' decodificate: `=?utf-8?B?...?=` diventa il testo con le lettere
    accentate. Quando la decodifica fallisce - succede con le codifiche
    dichiarate male - si preferisce il valore grezzo a un'eccezione.
    """
    try:
        valore = messaggio.get(nome)
    except Exception as errore:
        logger.warning("L'intestazione %s non si legge: %s", nome, errore)
        return None

    if valore is None:
        return None

    try:
        testo = str(valore).strip()
    except Exception as errore:
        logger.warning("L'intestazione %s non si converte in testo: %s", nome, errore)
        return None

    # Le intestazioni piegate su piu' righe portano dentro degli a capo che
    # nel database non servono a niente. Il carattere nullo se ne va qui: un
    # file rovinato ne porta anche dentro le intestazioni.
    return scrivibile(" ".join(testo.split())) or None


def _indirizzi(messaggio: Message, nome: str, tipo: str) -> list[dict[str, str]]:
    """I destinatari di un'intestazione, come elenco di oggetti.

    La forma e' quella descritta in `email_messages.recipients`:
    `{"tipo": "a", "indirizzo": "mario@cliente.it", "nome": "Mario Rossi"}`.
    Un elenco e non una stringa perche' su un elenco si puo' cercare.
    """
    grezzo = _testo_intestazione(messaggio, nome)
    if not grezzo:
        return []

    try:
        coppie = getaddresses([grezzo])
    except Exception as errore:
        logger.warning("L'intestazione %s non si scompone: %s", nome, errore)
        return []

    trovati: list[dict[str, str]] = []
    for nome_persona, indirizzo in coppie:
        pulito = (indirizzo or "").strip()
        if not pulito:
            continue
        trovati.append(
            {
                "tipo": tipo,
                "indirizzo": scrivibile(pulito)[:LUNGHEZZA_MITTENTE],
                "nome": scrivibile((nome_persona or "").strip()),
            }
        )
    return trovati


def _mittente(messaggio: Message) -> str:
    """L'indirizzo di chi ha scritto, o il segnaposto se non c'e'."""
    indirizzi = _indirizzi(messaggio, "From", "da")
    if indirizzi:
        return indirizzi[0]["indirizzo"]

    # Qualche messaggio esportato male ha il From scritto senza indirizzo
    # riconoscibile. Meglio conservare quello che c'e' scritto che perderlo.
    grezzo = _testo_intestazione(messaggio, "From")
    if grezzo:
        return grezzo[:LUNGHEZZA_MITTENTE]

    return MITTENTE_SCONOSCIUTO


def _data_invio(messaggio: Message) -> tuple[datetime | None, str | None]:
    """Quando il messaggio dice di essere stato spedito.

    Restituisce anche il difetto da segnalare quando la data c'e' ma non si
    legge: e' un'informazione che serve in quarantena, dove chi guarda deve
    capire se ha davanti un messaggio vero o un file rovinato.

    **La data torna sempre con il fuso orario** (regola di CLAUDE.md, sezione
    5). Le date scritte senza fuso - capitano - si considerano UTC: e' l'unica
    scelta che non inventa un'ora diversa da quella scritta.
    """
    grezza = _testo_intestazione(messaggio, "Date")
    if not grezza:
        return None, None

    try:
        quando = parsedate_to_datetime(grezza)
    except (TypeError, ValueError) as errore:
        logger.warning("La data '%s' non si legge: %s", grezza, errore)
        return None, f"la data di invio non e' leggibile ({grezza})"

    if quando is None:
        return None, f"la data di invio non e' leggibile ({grezza})"

    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)

    return quando, None


def _corpo(messaggio: Message) -> tuple[str | None, str | None]:
    """Il corpo del messaggio in testo semplice.

    Si preferisce la parte `text/plain`, che e' gia' testo. Quando c'e' solo
    l'HTML - la maggioranza della posta di oggi - lo si converte, perche' il
    corpo serve a due cose che l'HTML non sa fare: leggersi nella pagina del
    messaggio e farsi cercare a parole.

    Restituisce anche il difetto, quando il corpo non si e' potuto leggere.
    """
    try:
        parte = messaggio.get_body(preferencelist=("plain", "html"))
    except Exception as errore:
        logger.warning("Il corpo del messaggio non si individua: %s", errore)
        return None, "il corpo del messaggio non si e' potuto leggere"

    if parte is None:
        return None, None

    try:
        contenuto = parte.get_content()
    except Exception as errore:
        logger.warning("Il corpo del messaggio non si decodifica: %s", errore)
        return None, "il corpo del messaggio non si e' potuto decodificare"

    if not isinstance(contenuto, str):
        return None, "il corpo del messaggio non e' testo"

    if parte.get_content_type() == "text/html":
        return html_in_testo(contenuto) or None, None


    return _compatta_righe(contenuto) or None, None


def _nome_allegato(parte: Message, numero: int) -> str:
    """Il nome di un allegato, inventandone uno quando manca.

    Un allegato senza nome capita con le immagini incorporate e con qualche
    programma di posta distratto. Sul disco il nome non arriva comunque -
    l'archivio deposita per impronta (D-004) - ma nella pagina del messaggio
    si deve poter scrivere qualcosa, e "allegato-1.png" si legge meglio di uno
    spazio vuoto.
    """
    try:
        nome = parte.get_filename()
    except Exception:
        nome = None

    if nome:
        # Solo il nome, mai un percorso: un allegato chiamato
        # "..\\..\\config.txt" non deve portare da nessuna parte. Sul disco
        # non ci arriva, ma finisce dentro un'intestazione di scarico.
        pulito = scrivibile(str(nome)).replace("\\", "/").split("/")[-1].strip()
        if pulito:
            return pulito[:LUNGHEZZA_NOME_ALLEGATO]

    estensione = mimetypes.guess_extension(parte.get_content_type() or "") or ".bin"
    return f"allegato-{numero}{estensione}"


def _allegati(messaggio: Message) -> tuple[tuple[Allegato, ...], tuple[str, ...]]:
    """Gli allegati staccati dal messaggio, con i difetti incontrati.

    Un allegato che non si decodifica non ferma gli altri e non ferma
    l'archiviazione: si segnala e si prosegue. Il `.eml` per intero e'
    comunque nell'archivio, quindi quel contenuto non e' perduto - e' solo
    rimasto dentro il file di partenza.
    """
    try:
        parti = list(messaggio.iter_attachments())
    except Exception as errore:
        logger.warning("Gli allegati non si elencano: %s", errore)
        return (), ("gli allegati non si sono potuti elencare",)

    trovati: list[Allegato] = []
    difetti: list[str] = []

    for numero, parte in enumerate(parti, start=1):
        nome = _nome_allegato(parte, numero)
        try:
            contenuto = parte.get_payload(decode=True)
        except Exception as errore:
            logger.warning("L'allegato '%s' non si decodifica: %s", nome, errore)
            difetti.append(f"l'allegato '{nome}' non si e' potuto decodificare")
            continue

        if not contenuto:
            difetti.append(f"l'allegato '{nome}' e' vuoto")
            continue

        tipo = (parte.get_content_type() or MIME_SCONOSCIUTO)[:LUNGHEZZA_MIME]
        trovati.append(
            Allegato(nome_file=nome, mime_type=tipo, contenuto=bytes(contenuto))
        )

    return tuple(trovati), tuple(difetti)


def leggi_messaggio(dati: bytes) -> MessaggioLetto:
    """Legge un `.eml` per intero. **Non solleva mai.**

    E' la porta d'ingresso di questo file. Qualunque cosa ci si dia dentro -
    un messaggio ben fatto, un file troncato, un PDF rinominato in `.eml`,
    zero byte - esce un `MessaggioLetto`: piu' o meno pieno, con l'elenco di
    quello che non tornava dentro `difetti`.

    E' il perno del punto 7 della sessione ("un errore su un messaggio non
    interrompe gli altri"). Se questa funzione potesse sollevare, un file
    rovinato fermerebbe l'acquisizione di tutti quelli che vengono dopo, ed e'
    esattamente il giorno in cui l'acquisizione serve di piu'.
    """
    impronta = impronta_di(dati)
    difetti: list[str] = []

    try:
        messaggio = message_from_bytes(dati, policy=policy.default)
    except Exception as errore:
        # Praticamente non capita: la libreria standard preferisce produrre un
        # messaggio vuoto con dei difetti annotati. Se capitasse, il messaggio
        # va archiviato lo stesso e messo in quarantena.
        logger.error("Il messaggio non si e' potuto leggere affatto: %s", errore)
        return MessaggioLetto(
            identificativo=identificativo_dallimpronta(impronta),
            identificativo_costruito=True,
            mittente=MITTENTE_SCONOSCIUTO,
            destinatari=[],
            oggetto=None,
            scomposizione=scomponi_oggetto(None),
            inviato_il=None,
            in_risposta_a=None,
            riferimenti=None,
            corpo=None,
            allegati=(),
            difetti=("il file non e' un messaggio di posta leggibile",),
        )

    grezzo = _testo_intestazione(messaggio, "Message-ID")
    identificativo = normalizza_identificativo(grezzo)
    costruito = not identificativo
    if costruito:
        identificativo = identificativo_dallimpronta(impronta)
        difetti.append("il messaggio non dichiara nessun Message-ID")

    oggetto = _testo_intestazione(messaggio, "Subject")
    if oggetto is None:
        difetti.append("il messaggio non ha oggetto")

    inviato_il, difetto_data = _data_invio(messaggio)
    if difetto_data:
        difetti.append(difetto_data)

    corpo, difetto_corpo = _corpo(messaggio)
    if difetto_corpo:
        difetti.append(difetto_corpo)

    allegati, difetti_allegati = _allegati(messaggio)
    difetti.extend(difetti_allegati)

    destinatari = (
        _indirizzi(messaggio, "To", "a")
        + _indirizzi(messaggio, "Cc", "cc")
        + _indirizzi(messaggio, "Bcc", "ccn")
    )

    mittente = _mittente(messaggio)
    if mittente == MITTENTE_SCONOSCIUTO:
        difetti.append("il messaggio non dichiara nessun mittente")

    return MessaggioLetto(
        identificativo=identificativo,
        identificativo_costruito=costruito,
        mittente=mittente,
        destinatari=destinatari,
        oggetto=oggetto[:LUNGHEZZA_OGGETTO] if oggetto else None,
        scomposizione=scomponi_oggetto(oggetto),
        inviato_il=inviato_il,
        in_risposta_a=_testo_intestazione(messaggio, "In-Reply-To"),
        riferimenti=_testo_intestazione(messaggio, "References"),
        corpo=corpo,
        allegati=allegati,
        difetti=tuple(difetti),
    )
