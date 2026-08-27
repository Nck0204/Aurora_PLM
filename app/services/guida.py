"""La guida in linea: legge i file di `docs/guida/`, li disegna, li cerca.

**Perche' la guida sta in file Markdown e non in template.** Perche' chi la
scrive non e' chi scrive il programma. Un file `.md` lo corregge chiunque con
il Blocco note, entra in git come tutto il resto, e si legge anche senza aprire
Aurora - il che conta il giorno in cui Aurora non si apre. Un template Jinja,
invece, e' codice: si sbaglia una graffa e la pagina non si disegna piu'.

**Perche' il Markdown lo trasforma in HTML questo file e non una libreria.**
Regola 1 di CLAUDE.md: niente dipende da internet, e ogni dipendenza in piu'
e' una libreria in piu' da installare sul server aziendale e da aggiornare per
sempre. Il Markdown che serve qui e' un sottoinsieme piccolo e **deciso da
noi**, perche' i file li scriviamo noi e stanno in git: titoli, paragrafi,
elenchi, tabelle, citazioni, grassetto, corsivo, codice, collegamenti. Non c'e'
nessun HTML da fidarsi, nessun utente che inserisce testo, nessun caso
ambiguo da risolvere come lo risolverebbe un'altra implementazione.

Il perimetro e' scritto qui sotto in `_RIGHE_RICONOSCIUTE`, e quello che non ci
sta viene mostrato come testo normale invece che sparire: una guida che perde
una riga perche' era scritta in un modo che il programma non conosce e' peggio
di una guida con dentro una riga brutta. Vedi D-085.

**Tutto quello che esce da qui e' testo scappato.** Il `<` di una riga di
esempio diventa `&lt;` prima che qualunque altra cosa succeda, e i tag li
mette questo file. Anche se i file della guida sono nostri, un giorno qualcuno
ci incollera' dentro un messaggio di errore vero, e quel giorno non deve
succedere niente.

**I file si rileggono quando cambiano.** Si tiene in memoria quello che si e'
gia' letto, con la data di modifica del file: correggere una frase e ricaricare
la pagina basta, non serve riavviare il server. Su un server che gira per mesi
e' la differenza fra una guida che si corregge e una guida che resta sbagliata.
"""

import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import PROJECT_ROOT

logger = logging.getLogger("aurora.guida")

# Dove stanno i file. Non e' un parametro del `.env` e non deve diventarlo: la
# guida e' parte del programma, entra in git con lui e cambia quando cambia lui.
CARTELLA_GUIDA = PROJECT_ROOT / "docs" / "guida"

# I file si chiamano "NN-nome-della-pagina.md". Il numero serve solo a metterli
# in ordine e non compare da nessuna parte: l'indirizzo della pagina e' il nome
# senza numero, cosi' riordinare la guida non rompe i collegamenti gia' scritti.
NOME_FILE = re.compile(r"^(?P<ordine>\d+)-(?P<nome>[a-z0-9-]+)\.md$")

# Quante lettere di contesto si mostrano intorno a una parola trovata.
CONTESTO_RICERCA = 90

# Quanti risultati si mostrano. Con sette pagine in tutto e' un limite teorico,
# e c'e' perche' la guida crescera'.
MASSIMO_RISULTATI = 20


# ---------------------------------------------------------------------------
#  1. UNA PAGINA DELLA GUIDA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sezione:
    """Un titolo di secondo livello dentro una pagina, con la sua ancora.

    Serve a due cose: l'indice in cima alla pagina, e le icone «?» sparse
    nell'interfaccia, che puntano a una sezione precisa invece che alla pagina
    intera. Chi preme il punto interrogativo accanto a un campo vuole leggere
    tre righe, non aprire un capitolo.
    """

    ancora: str
    titolo: str


@dataclass(frozen=True)
class Pagina:
    """Una pagina della guida, gia' letta e gia' trasformata in HTML.

    nome      quello che finisce nell'indirizzo: /aiuto/primi-passi
    titolo    il primo titolo del file, che e' anche il nome nell'indice
    sommario  il primo paragrafo: si legge nell'indice, sotto il titolo
    html      il corpo, gia' pronto da mettere in pagina
    testo     lo stesso contenuto senza formattazione, per la ricerca
    sezioni   i titoli di secondo livello, per l'indice e per le icone «?»
    """

    nome: str
    ordine: int
    titolo: str
    sommario: str
    html: str
    testo: str
    sezioni: tuple[Sezione, ...] = ()


@dataclass
class _InMemoria:
    """Quello che si e' gia' letto, con la data di modifica del file."""

    pagina: Pagina
    modificato: float = 0.0


_lette: dict[str, _InMemoria] = {}


# ---------------------------------------------------------------------------
#  2. LEGGERE
# ---------------------------------------------------------------------------


def pagine() -> list[Pagina]:
    """Tutte le pagine della guida, nell'ordine dei numeri dei file."""
    trovate = []
    for percorso in _file_della_guida():
        pagina = _leggi(percorso)
        if pagina is not None:
            trovate.append(pagina)

    return sorted(trovate, key=lambda pagina: (pagina.ordine, pagina.nome))


def pagina(nome: str) -> Pagina | None:
    """Una pagina per nome. None se non esiste.

    Il nome arriva dall'indirizzo, quindi da fuori: si accettano solo lettere
    minuscole, cifre e trattini. Senza questo controllo, un nome con dentro due
    punti trasformerebbe questa funzione in un modo di leggere qualunque file
    del server.
    """
    pulito = (nome or "").strip().lower()
    if not pulito or not re.fullmatch(r"[a-z0-9-]+", pulito):
        return None

    for percorso in _file_della_guida():
        trovato = NOME_FILE.match(percorso.name)
        if trovato is not None and trovato.group("nome") == pulito:
            return _leggi(percorso)

    return None


def _file_della_guida() -> list[Path]:
    """I file `.md` della cartella della guida, in ordine di nome.

    Se la cartella non c'e' si risponde con un elenco vuoto e lo si scrive nel
    registro: la guida che manca e' un difetto dell'installazione, non un
    motivo per far cadere la pagina di chi la stava aprendo.
    """
    if not CARTELLA_GUIDA.is_dir():
        logger.error(
            "La cartella della guida non esiste: %s. La sezione «Aiuto» "
            "risultera' vuota.",
            CARTELLA_GUIDA,
        )
        return []

    return sorted(
        percorso
        for percorso in CARTELLA_GUIDA.glob("*.md")
        if NOME_FILE.match(percorso.name)
    )


def _leggi(percorso: Path) -> Pagina | None:
    """Legge e trasforma una pagina, riusando quella gia' letta se non e' cambiata."""
    trovato = NOME_FILE.match(percorso.name)
    if trovato is None:
        return None

    nome = trovato.group("nome")

    try:
        modificato = percorso.stat().st_mtime
    except OSError as errore:
        logger.error("La pagina di guida %s non si legge: %s", percorso, errore)
        return None

    in_memoria = _lette.get(nome)
    if in_memoria is not None and in_memoria.modificato == modificato:
        return in_memoria.pagina

    try:
        sorgente = percorso.read_text(encoding="utf-8")
    except OSError as errore:
        logger.error("La pagina di guida %s non si legge: %s", percorso, errore)
        return None

    composta = _componi(
        nome=nome, ordine=int(trovato.group("ordine")), sorgente=sorgente
    )
    _lette[nome] = _InMemoria(pagina=composta, modificato=modificato)
    return composta


def _componi(*, nome: str, ordine: int, sorgente: str) -> Pagina:
    """Trasforma il testo di un file nella pagina pronta da mostrare."""
    righe = sorgente.replace("\r\n", "\n").split("\n")

    titolo = nome.replace("-", " ").capitalize()
    for riga in righe:
        if riga.startswith("# "):
            titolo = riga[2:].strip()
            break

    corpo, sezioni = _in_html(righe)

    return Pagina(
        nome=nome,
        ordine=ordine,
        titolo=titolo,
        sommario=_primo_paragrafo(righe),
        html=corpo,
        testo=_senza_formattazione(sorgente),
        sezioni=tuple(sezioni),
    )


def _primo_paragrafo(righe: list[str]) -> str:
    """Il primo paragrafo di prosa, per l'indice e per il sottotitolo.

    **Il paragrafo intero, non la prima riga.** Nei file Markdown le frasi
    vanno a capo a settanta caratteri, quindi la prima riga finisce quasi
    sempre a meta' di una frase: un sottotitolo che si interrompe con "e la
    parola «stato»" sembra un difetto del programma, e in un certo senso lo e'.

    Si salta il titolo e tutto quello che non e' prosa: l'indice deve dire di
    che cosa parla la pagina, e "## Come si carica" non lo dice.
    """
    raccolte: list[str] = []

    for riga in righe:
        pulita = riga.strip()

        if not pulita or pulita.startswith(("#", ">", "-", "*", "|", "```")):
            # La riga vuota chiude il paragrafo; le altre non l'hanno mai
            # aperto. In tutti e due i casi, se qualcosa era gia' stato
            # raccolto, e' finito.
            if raccolte:
                break
            continue

        if re.match(r"^\d+[.)]\s", pulita):
            if raccolte:
                break
            continue

        raccolte.append(pulita)

    return _senza_formattazione(" ".join(raccolte))


# ---------------------------------------------------------------------------
#  3. DAL MARKDOWN ALL'HTML
# ---------------------------------------------------------------------------
#
# Il perimetro, per esteso. Quello che non e' qui dentro viene mostrato come
# testo normale, senza formattazione e senza sparire.
_RIGHE_RICONOSCIUTE = """
    # Titolo             -> <h1>, uno solo per pagina, in cima
    ## Sezione           -> <h2>, con la sua ancora per le icone «?»
    ### Sottosezione     -> <h3>
    testo normale        -> <p>, con le righe contigue unite
    - elemento           -> <ul><li>
    1. elemento          -> <ol><li>
    > citazione          -> <blockquote>
    | a | b |            -> <table>, con la prima riga come intestazione
    ```                  -> <pre><code>, senza nessuna formattazione dentro
    ---                  -> <hr>
"""

# Il formato dentro una riga. L'ordine conta: il codice si riconosce per primo,
# cosi' un asterisco dentro `codice` non diventa un corsivo.
_CODICE = re.compile(r"`([^`]+)`")
_GRASSETTO = re.compile(r"\*\*([^*]+)\*\*")
_CORSIVO = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_COLLEGAMENTO = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

# Un titolo di sezione e la riga di una tabella.
_TITOLO = re.compile(r"^(?P<livelli>#{1,4})\s+(?P<testo>.+)$")
_ELENCO_PUNTATO = re.compile(r"^[-*]\s+(?P<testo>.*)$")
_ELENCO_NUMERATO = re.compile(r"^\d+[.)]\s+(?P<testo>.*)$")
_SEPARATORE_TABELLA = re.compile(r"^\|[\s:|-]+\|$")


def _ancora(testo: str) -> str:
    """L'ancora di un titolo: il titolo ridotto a lettere, cifre e trattini.

    Deve essere **stabile**: e' quella che scrivono le icone «?» sparse
    nell'interfaccia, e cambiarla vorrebbe dire rompere quei collegamenti senza
    che nessuno se ne accorga finche' qualcuno non ci preme sopra.
    """
    pulito = _senza_formattazione(testo).lower()
    pulito = pulito.replace("à", "a").replace("è", "e").replace("é", "e")
    pulito = pulito.replace("ì", "i").replace("ò", "o").replace("ù", "u")
    pulito = re.sub(r"[^a-z0-9]+", "-", pulito).strip("-")
    return pulito or "sezione"


def _in_linea(testo: str) -> str:
    """Trasforma la formattazione dentro una riga, dopo aver reso innocuo l'HTML.

    **Lo scappamento viene per primo, sempre.** Se venisse dopo, i tag appena
    aggiunti da questa stessa funzione verrebbero scappati anche loro e si
    leggerebbe `&lt;strong&gt;` in mezzo alla frase.

    I collegamenti si accettano soltanto **dentro Aurora** (`/qualcosa`) o
    verso un altro file della guida. Un collegamento a un indirizzo esterno in
    una guida che deve funzionare su una macchina senza internet e' una
    promessa che non si puo' mantenere (regola 1 di CLAUDE.md), e infatti
    rimane scritto come testo.
    """
    pulito = html.escape(testo, quote=False)

    # Il codice per primo: quello che sta fra apici inversi non viene toccato
    # da nient'altro. Si mette da parte e si rimette alla fine.
    frammenti: list[str] = []

    def metti_da_parte(trovato: re.Match) -> str:
        frammenti.append(f"<code>{trovato.group(1)}</code>")
        return f"\x00{len(frammenti) - 1}\x00"

    pulito = _CODICE.sub(metti_da_parte, pulito)

    pulito = _GRASSETTO.sub(r"<strong>\1</strong>", pulito)
    pulito = _CORSIVO.sub(r"<em>\1</em>", pulito)
    pulito = _COLLEGAMENTO.sub(_collegamento, pulito)

    for numero, frammento in enumerate(frammenti):
        pulito = pulito.replace(f"\x00{numero}\x00", frammento)

    return pulito


def _collegamento(trovato: re.Match) -> str:
    """Un collegamento, se punta dentro Aurora. Altrimenti solo il suo testo."""
    etichetta, indirizzo = trovato.group(1), trovato.group(2)

    if indirizzo.startswith("/") and not indirizzo.startswith("//"):
        return f'<a href="{html.escape(indirizzo, quote=True)}">{etichetta}</a>'
    if indirizzo.startswith("#"):
        return f'<a href="{html.escape(indirizzo, quote=True)}">{etichetta}</a>'

    return etichetta


def _in_html(righe: list[str]) -> tuple[str, list[Sezione]]:
    """Il corpo della pagina in HTML, e l'elenco delle sue sezioni.

    E' scritto come una macchina a stati che scorre le righe una volta sola:
    ogni riga o comincia qualcosa, o continua quello che c'era, o lo chiude. E'
    la forma piu' lunga da leggere e la piu' facile da seguire con il dito, che
    e' quello che serve a chi la dovra' correggere fra due anni (regola 7 di
    CLAUDE.md).
    """
    fuori: list[str] = []
    sezioni: list[Sezione] = []

    paragrafo: list[str] = []
    elenco: list[str] = []
    tipo_elenco = ""
    citazione: list[str] = []
    tabella: list[list[str]] = []
    dentro_codice = False
    codice: list[str] = []

    def chiudi_paragrafo() -> None:
        if paragrafo:
            fuori.append(f"<p>{_in_linea(' '.join(paragrafo))}</p>")
            paragrafo.clear()

    def chiudi_elenco() -> None:
        nonlocal tipo_elenco
        if elenco:
            voci = "".join(f"<li>{_in_linea(voce)}</li>" for voce in elenco)
            fuori.append(f"<{tipo_elenco}>{voci}</{tipo_elenco}>")
            elenco.clear()
            tipo_elenco = ""

    def chiudi_citazione() -> None:
        if citazione:
            testo = _in_linea(" ".join(citazione))
            fuori.append(f"<blockquote><p>{testo}</p></blockquote>")
            citazione.clear()

    def chiudi_tabella() -> None:
        if tabella:
            fuori.append(_tabella_html(tabella))
            tabella.clear()

    def chiudi_tutto() -> None:
        chiudi_paragrafo()
        chiudi_elenco()
        chiudi_citazione()
        chiudi_tabella()

    for riga in righe:
        # Il blocco di codice mangia tutto quello che ci sta dentro, righe
        # vuote comprese: e' l'unico posto in cui la formattazione non conta.
        if riga.startswith("```"):
            if dentro_codice:
                testo = html.escape("\n".join(codice), quote=False)
                fuori.append(f"<pre><code>{testo}</code></pre>")
                codice.clear()
                dentro_codice = False
            else:
                chiudi_tutto()
                dentro_codice = True
            continue

        if dentro_codice:
            codice.append(riga)
            continue

        pulita = riga.rstrip()

        if not pulita.strip():
            chiudi_tutto()
            continue

        titolo = _TITOLO.match(pulita)
        if titolo is not None:
            chiudi_tutto()
            livello = len(titolo.group("livelli"))
            testo = titolo.group("testo").strip()
            ancora = _ancora(testo)

            if livello == 1:
                # Il titolo della pagina lo disegna il template, con il suo
                # posto nella testata: qui si salta, altrimenti comparirebbe
                # due volte.
                continue

            if livello == 2:
                sezioni.append(Sezione(ancora=ancora, titolo=testo))

            fuori.append(
                f'<h{livello} id="{ancora}">{_in_linea(testo)}</h{livello}>'
            )
            continue

        if pulita.strip() in ("---", "***", "___"):
            chiudi_tutto()
            fuori.append("<hr>")
            continue

        if pulita.lstrip().startswith("|"):
            chiudi_paragrafo()
            chiudi_elenco()
            chiudi_citazione()
            if not _SEPARATORE_TABELLA.match(pulita.strip()):
                tabella.append(_celle(pulita))
            continue
        chiudi_tabella()

        if pulita.lstrip().startswith(">"):
            chiudi_paragrafo()
            chiudi_elenco()
            citazione.append(pulita.lstrip().lstrip(">").strip())
            continue
        chiudi_citazione()

        puntato = _ELENCO_PUNTATO.match(pulita.strip())
        numerato = _ELENCO_NUMERATO.match(pulita.strip())

        if puntato is not None or numerato is not None:
            chiudi_paragrafo()
            voluto = "ul" if puntato is not None else "ol"
            if tipo_elenco and tipo_elenco != voluto:
                chiudi_elenco()
            tipo_elenco = voluto
            trovato = puntato if puntato is not None else numerato
            elenco.append(trovato.group("testo").strip())
            continue

        # Una riga rientrata che segue un elemento di elenco lo continua: e'
        # il modo in cui si scrive un elenco con dentro due frasi.
        if elenco and riga.startswith("  "):
            elenco[-1] = f"{elenco[-1]} {pulita.strip()}"
            continue
        chiudi_elenco()

        paragrafo.append(pulita.strip())

    if dentro_codice and codice:
        # Un blocco di codice mai chiuso: si mostra lo stesso. La riga che
        # manca e' un difetto del file della guida, non un motivo per perdere
        # quello che c'era scritto.
        testo = html.escape("\n".join(codice), quote=False)
        fuori.append(f"<pre><code>{testo}</code></pre>")

    chiudi_tutto()
    return "\n".join(fuori), sezioni


def _celle(riga: str) -> list[str]:
    """Le celle di una riga di tabella, senza le barre di apertura e chiusura."""
    pulita = riga.strip()
    if pulita.startswith("|"):
        pulita = pulita[1:]
    if pulita.endswith("|"):
        pulita = pulita[:-1]
    return [cella.strip() for cella in pulita.split("|")]


def _tabella_html(righe: list[list[str]]) -> str:
    """Una tabella, con la prima riga come intestazione.

    Esce con le classi della tabella dati di Aurora
    (`components/tabella.html`): una tabella nella guida deve somigliare alle
    tabelle del programma, altrimenti sembra un'altra applicazione.
    """
    intestazione = "".join(
        f'<th scope="col">{_in_linea(cella)}</th>' for cella in righe[0]
    )
    corpo = "".join(
        "<tr>" + "".join(f"<td>{_in_linea(cella)}</td>" for cella in riga) + "</tr>"
        for riga in righe[1:]
    )
    return (
        '<div class="tabella-contenitore"><table class="tabella">'
        f"<thead><tr>{intestazione}</tr></thead><tbody>{corpo}</tbody>"
        "</table></div>"
    )


def _senza_formattazione(testo: str) -> str:
    """Lo stesso testo senza i segni del Markdown. Serve alla ricerca.

    Cercare "stato rilasciato" deve trovare anche una riga scritta
    `**stato rilasciato**`, e chi cerca non sa - e non deve sapere - come sono
    scritti i file della guida.
    """
    pulito = re.sub(r"```.*?```", " ", testo, flags=re.DOTALL)
    pulito = _COLLEGAMENTO.sub(r"\1", pulito)
    pulito = pulito.replace("**", "").replace("`", "")
    pulito = re.sub(r"^\s*[#>|*-]+\s*", " ", pulito, flags=re.MULTILINE)
    pulito = pulito.replace("|", " ")
    return re.sub(r"\s+", " ", pulito).strip()


# ---------------------------------------------------------------------------
#  4. LA RICERCA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Risultato:
    """Una pagina trovata, con il pezzo di testo in cui compare la parola."""

    pagina: Pagina
    contesto: str
    quante_volte: int
    nel_titolo: bool = False


def cerca(domanda: str) -> list[Risultato]:
    """Le pagine che contengono quello che si e' scritto, dalla piu' pertinente.

    **La ricerca e' su tutte le parole scritte, non sulla frase intera.** Chi
    scrive "quarantena messaggio" cerca la pagina che parla di tutti e due, non
    quella che contiene quelle due parole in quell'ordine: le frasi esatte le
    cerca chi conosce gia' il testo, e chi conosce gia' il testo non sta usando
    la ricerca della guida.

    L'ordine e' semplice apposta: prima le pagine che hanno la parola nel
    titolo, poi quelle che la ripetono di piu'. Con sette pagine, un ordinamento
    piu' furbo sarebbe piu' difficile da spiegare che da scrivere, e la guida
    di Aurora non e' un motore di ricerca.
    """
    parole = [parola for parola in re.split(r"\s+", domanda.strip().lower()) if parola]
    if not parole:
        return []

    trovate: list[Risultato] = []

    for candidata in pagine():
        testo = candidata.testo.lower()
        titolo = candidata.titolo.lower()

        if not all(parola in testo or parola in titolo for parola in parole):
            continue

        quante = sum(testo.count(parola) for parola in parole)
        trovate.append(
            Risultato(
                pagina=candidata,
                contesto=_contesto(candidata.testo, parole[0]),
                quante_volte=quante,
                nel_titolo=any(parola in titolo for parola in parole),
            )
        )

    trovate.sort(key=lambda esito: (not esito.nel_titolo, -esito.quante_volte))
    return trovate[:MASSIMO_RISULTATI]


def _contesto(testo: str, parola: str) -> str:
    """Il pezzo di testo intorno alla parola trovata, con i puntini ai lati."""
    posizione = testo.lower().find(parola.lower())
    if posizione < 0:
        return testo[:CONTESTO_RICERCA] + ("..." if len(testo) > CONTESTO_RICERCA else "")

    inizio = max(0, posizione - CONTESTO_RICERCA // 2)
    fine = min(len(testo), posizione + len(parola) + CONTESTO_RICERCA // 2)

    pezzo = testo[inizio:fine].strip()
    if inizio > 0:
        pezzo = "..." + pezzo
    if fine < len(testo):
        pezzo = pezzo + "..."
    return pezzo


# ---------------------------------------------------------------------------
#  5. LE ICONE «?» SPARSE NELL'INTERFACCIA
# ---------------------------------------------------------------------------
#
# Ogni voce dice: da dove si preme, quale pagina si apre, e su quale sezione.
# **Stanno tutte qui e in nessun altro posto.** Un template che scrivesse a mano
# `/aiuto/versioni-e-stati#gli-stati-di-un-documento` sarebbe un collegamento
# che nessuno accorgerebbe di aver rotto rinominando un titolo; scritte qui,
# c'e' un test che le prova tutte e diventa rosso il giorno in cui una sezione
# cambia nome.

AIUTI: dict[str, tuple[str, str, str]] = {
    # chiave                  pagina                 ancora                              spiegazione breve
    "classificazione": (
        "chi-vede-che-cosa",
        "le-classificazioni",
        "Che cos'e' una classificazione e chi vede che cosa",
    ),
    "stato-documento": (
        "versioni-e-stati",
        "gli-stati-di-un-documento",
        "Bozza, in verifica, rilasciato, superato: che cosa cambia",
    ),
    "versione-documento": (
        "versioni-e-stati",
        "una-versione-e-un-fatto-avvenuto",
        "Perche' una versione caricata non si sostituisce",
    ),
    "nota-versione": (
        "caricare-un-documento",
        "la-nota-e-obbligatoria-e-non-e-una-formalita",
        "A che cosa serve la nota che si scrive caricando",
    ),
    "ciclo-di-vita": (
        "versioni-e-stati",
        "il-ciclo-di-vita-di-una-versione-di-prodotto",
        "In sviluppo, rilasciato, in produzione, superato, obsoleto",
    ),
    "fase-progetto": (
        "far-avanzare-un-progetto",
        "le-fasi-sono-dati-non-regole-del-programma",
        "Come funzionano le fasi di un progetto",
    ),
    "richiesta-fase": (
        "far-avanzare-un-progetto",
        "chi-lavora-chiede-chi-governa-decide",
        "Chi puo' far avanzare un progetto e chi lo approva",
    ),
    "oggetto-email": (
        "oggetto-delle-email",
        "come-si-scrive-un-oggetto-che-aurora-capisce",
        "Come scrivere l'oggetto perche' il messaggio si archivi da solo",
    ),
    "quarantena": (
        "messaggi-in-quarantena",
        "che-cos-e-la-quarantena",
        "Perche' un messaggio finisce in quarantena e che cosa farne",
    ),
    "codice-prodotto": (
        "glossario",
        "codice-prodotto",
        "Come e' fatto un codice prodotto e come lo legge Aurora",
    ),
}


@dataclass(frozen=True)
class Aiuto:
    """Un punto interrogativo dell'interfaccia, gia' pronto da disegnare."""

    indirizzo: str
    spiegazione: str
    esiste: bool = True
    voci: tuple[str, ...] = field(default_factory=tuple)


def aiuto(chiave: str) -> Aiuto:
    """Dove porta il punto interrogativo con quella chiave.

    Una chiave sconosciuta non fa cadere la pagina: si risponde con un
    collegamento all'indice della guida e `esiste=False`, cosi' il componente
    puo' scegliere di non disegnare niente. Un'icona che non porta da nessuna
    parte e' peggio di un'icona che non c'e'.
    """
    voce = AIUTI.get(chiave)
    if voce is None:
        logger.warning("Richiesto un aiuto che non esiste: «%s»", chiave)
        return Aiuto(indirizzo="/aiuto", spiegazione="Apri la guida", esiste=False)

    nome, ancora, spiegazione = voce
    return Aiuto(indirizzo=f"/aiuto/{nome}#{ancora}", spiegazione=spiegazione)
