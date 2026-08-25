"""Scomposizione del codice parlante di un prodotto.

Un codice come "RMS1100-24-110SW" racconta il prodotto a chi lo sa leggere.
Questo modulo lo legge per conto del programma e ne ricava un dizionario -
{"modello": "RMS", "potenza": "1100", ...} - che finisce in
products.code_parts e diventa un campo su cui si puo' cercare.

**La regola di lettura non sta qui dentro.** Sta in un file di
configurazione, indicato da PRODUCT_CODE_CONFIG nel file .env, che di
partenza e' config/codice_prodotto.toml. Il motivo e' che al momento in cui
questo modulo e' stato scritto la regola vera non era ancora stata confermata
dall'azienda: metterla nel codice avrebbe voluto dire una modifica al
programma e un rilascio il giorno in cui arriva la conferma. Cosi' invece si
cambia una riga di un file di testo e si riavvia il server (D-038).

**Il programma non rifiuta mai un codice.** Se un codice non corrisponde alla
regola, scomponi() restituisce un dizionario vuoto e il prodotto si crea lo
stesso: quello che manca e' la comodita' di cercarlo per elementi, non il
prodotto. Chi lo inserisce vede un avviso che glielo dice, e chi corregge la
regola piu' avanti puo' ricalcolare la scomposizione, perche' code_parts e'
un dato ricavato e non la fonte della verita' (docs/MODELLO_DATI.md, 4.3).

Vale anche per il file di configurazione: se manca, se non si legge o se
contiene un'espressione regolare sbagliata, Aurora **parte lo stesso** e si
comporta come se nessun codice fosse riconoscibile. Il guasto viene scritto
nel registro e mostrato nelle pagine dei prodotti, ma non ferma il programma:
un errore di battitura in un file di configurazione non deve poter chiudere
fuori tutta l'azienda (D-039).
"""

import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger("aurora.codici")

# I nomi delle due voci attese nel file di configurazione.
CHIAVE_ESPRESSIONE = "espressione"
CHIAVE_ETICHETTE = "etichette"


@dataclass(frozen=True)
class Elemento:
    """Un elemento riconosciuto dentro il codice.

    chiave      il nome del gruppo nell'espressione regolare, che e' anche la
                chiave dentro products.code_parts. E' un identificatore:
                resta in forma "tensione_ingresso".
    etichetta   come si chiama in italiano nell'interfaccia: "Tensione di
                ingresso".
    """

    chiave: str
    etichetta: str


@dataclass(frozen=True)
class Regola:
    """La regola di scomposizione, cosi' come e' stata letta dal file.

    espressione   None quando la regola non e' utilizzabile: file mancante,
                  illeggibile, o espressione regolare sbagliata.
    elementi      gli elementi nell'ordine in cui compaiono nel codice.
    problema      la spiegazione in italiano di che cosa non va, da mostrare
                  nelle pagine. None quando e' tutto a posto.
    """

    espressione: re.Pattern[str] | None
    elementi: tuple[Elemento, ...]
    problema: str | None = None

    @property
    def utilizzabile(self) -> bool:
        """Vero quando la regola puo' davvero scomporre un codice."""
        return self.espressione is not None


# La regola letta una volta sola all'avvio. Il file di configurazione si
# rilegge riavviando il server: e' un parametro di funzionamento, non un dato,
# e rileggerlo a ogni richiesta vorrebbe dire un accesso al disco per ogni
# codice mostrato. La funzione ricarica() esiste per i test.
_regola_in_uso: Regola | None = None


def _etichetta_di_ripiego(chiave: str) -> str:
    """Il nome da mostrare quando il file non ne indica uno.

    "tensione_ingresso" diventa "Tensione ingresso". Non e' l'italiano
    migliore, ma e' leggibile e compare solo quando qualcuno ha aggiunto un
    gruppo all'espressione dimenticandosi la sua etichetta.
    """
    return chiave.replace("_", " ").capitalize()


def _leggi(percorso: Path) -> Regola:
    """Legge il file di configurazione e ne ricava la regola.

    Non solleva mai: qualunque cosa vada storta diventa una Regola con
    espressione None e la spiegazione dentro "problema". Vedi la nota in cima
    al modulo sul perche'.
    """
    try:
        contenuto = percorso.read_bytes()
    except OSError as errore:
        logger.error(
            "Il file della scomposizione dei codici non si legge (%s): %s",
            percorso,
            errore,
        )
        return Regola(
            espressione=None,
            elementi=(),
            problema=(
                f"Il file di configurazione {percorso.name} non e' stato "
                "trovato o non si riesce a leggerlo."
            ),
        )

    try:
        dati = tomllib.loads(contenuto.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as errore:
        logger.error("Il file %s non e' un TOML valido: %s", percorso, errore)
        return Regola(
            espressione=None,
            elementi=(),
            problema=(
                f"Il file di configurazione {percorso.name} contiene un "
                "errore di scrittura e non e' stato compreso."
            ),
        )

    testo_espressione = dati.get(CHIAVE_ESPRESSIONE)
    if not isinstance(testo_espressione, str) or not testo_espressione:
        logger.error("In %s manca la voce '%s'", percorso, CHIAVE_ESPRESSIONE)
        return Regola(
            espressione=None,
            elementi=(),
            problema=(
                f"Nel file di configurazione {percorso.name} manca la voce "
                f"'{CHIAVE_ESPRESSIONE}'."
            ),
        )

    try:
        espressione = re.compile(testo_espressione)
    except re.error as errore:
        logger.error("L'espressione in %s e' sbagliata: %s", percorso, errore)
        return Regola(
            espressione=None,
            elementi=(),
            problema=(
                f"L'espressione scritta in {percorso.name} non e' valida: "
                f"{errore}."
            ),
        )

    etichette = dati.get(CHIAVE_ETICHETTE) or {}
    if not isinstance(etichette, dict):
        etichette = {}

    # L'ordine e' quello dei gruppi dentro l'espressione, non quello delle
    # etichette: e' l'ordine in cui gli elementi compaiono nel codice, ed e'
    # l'unico che una persona che guarda "RMS1100-24-110SW" riconosce.
    # groupindex e' {nome: numero}; si ordina per numero.
    chiavi = sorted(espressione.groupindex, key=espressione.groupindex.get)

    if not chiavi:
        logger.error(
            "L'espressione in %s non ha gruppi nominati: non scompone niente",
            percorso,
        )
        return Regola(
            espressione=None,
            elementi=(),
            problema=(
                f"L'espressione scritta in {percorso.name} non contiene "
                "nessun gruppo nominato (?P<nome>...), quindi non scompone "
                "niente."
            ),
        )

    elementi = tuple(
        Elemento(
            chiave=chiave,
            etichetta=str(etichette.get(chiave) or _etichetta_di_ripiego(chiave)),
        )
        for chiave in chiavi
    )

    logger.info(
        "Scomposizione dei codici prodotto: %s elementi (%s)",
        len(elementi),
        ", ".join(elemento.chiave for elemento in elementi),
    )
    return Regola(espressione=espressione, elementi=elementi)


def regola() -> Regola:
    """La regola in uso, letta dal file la prima volta che serve."""
    global _regola_in_uso
    if _regola_in_uso is None:
        _regola_in_uso = _leggi(settings.product_code_config)
    return _regola_in_uso


def ricarica(percorso: Path | None = None) -> Regola:
    """Rilegge la regola dal file. Serve ai test e a una futura pagina di servizio."""
    global _regola_in_uso
    _regola_in_uso = _leggi(percorso or settings.product_code_config)
    return _regola_in_uso


def elementi() -> tuple[Elemento, ...]:
    """Gli elementi previsti dalla regola, nell'ordine del codice.

    Le pagine ci costruiscono sopra i filtri di ricerca e le colonne: se un
    giorno la regola avra' sei elementi invece di cinque, i filtri diventano
    sei senza che nessuno tocchi un template.
    """
    return regola().elementi


def etichetta_di(chiave: str) -> str:
    """Il nome in italiano di un elemento, o la chiave se non e' previsto.

    La chiave puo' non essere piu' prevista: i prodotti inseriti prima di un
    cambio di regola conservano nel loro code_parts gli elementi di allora, e
    vanno mostrati lo stesso.
    """
    for elemento in elementi():
        if elemento.chiave == chiave:
            return elemento.etichetta
    return _etichetta_di_ripiego(chiave)


def scomponi(codice: str) -> dict[str, str]:
    """Scompone un codice negli elementi riconosciuti.

    Restituisce un dizionario vuoto quando il codice non corrisponde alla
    regola, quando la regola non e' utilizzabile o quando il codice e' vuoto.
    **Non solleva mai un errore**: un codice che non si scompone e' un codice
    accettato lo stesso, non un codice rifiutato.

    I gruppi facoltativi che non hanno preso niente (la variante di un codice
    che non ne ha) non entrano nel risultato: una chiave con dentro la
    stringa vuota e' peggio di una chiave che non c'e', perche' nelle ricerche
    sembrerebbe un valore.
    """
    attuale = regola()
    if attuale.espressione is None:
        return {}

    trovato = attuale.espressione.match(codice.strip())
    if trovato is None:
        return {}

    parti: dict[str, str] = {}
    for elemento in attuale.elementi:
        valore = trovato.group(elemento.chiave)
        if valore:
            parti[elemento.chiave] = valore

    return parti


def scomposizione_leggibile(parti: dict[str, str]) -> list[tuple[str, str]]:
    """Le coppie (etichetta, valore) da mostrare, nell'ordine del codice.

    Serve ai template, che non devono sapere niente ne' della regola ne'
    dell'ordine dei gruppi: ricevono un elenco gia' in fila e lo disegnano.
    Gli elementi che nel dizionario non ci sono vengono saltati; quelli che ci
    sono ma che la regola non prevede piu' finiscono in fondo, perche' un dato
    scritto nel database si mostra sempre, anche quando non lo si sa piu'
    spiegare.
    """
    if not parti:
        return []

    coppie: list[tuple[str, str]] = []
    previste = set()

    for elemento in elementi():
        previste.add(elemento.chiave)
        if elemento.chiave in parti:
            coppie.append((elemento.etichetta, parti[elemento.chiave]))

    for chiave, valore in parti.items():
        if chiave not in previste:
            coppie.append((_etichetta_di_ripiego(chiave), valore))

    return coppie
