"""L'elenco dei tipi di documento, letto da un file di configurazione.

Quando si carica un documento bisogna dire che genere di documento e':
"Schema elettrico", "PCB", "Firmware". L'elenco delle scelte **non sta qui
dentro**: sta in un file TOML indicato da DOCUMENT_TYPES_CONFIG nel file .env,
che di partenza e' config/tipi_documento.toml.

E' la stessa scelta gia' presa per la scomposizione dei codici prodotto
(D-038): un elenco che l'azienda cambiera' non deve stare nel programma,
altrimenti aggiungere "Manuale d'uso" vuol dire una modifica al codice e un
rilascio.

**Il programma non si ferma mai per colpa di questo file.** Se manca, se non
si legge o se e' scritto male, si usa l'elenco di ripiego qui sotto e il
guasto viene scritto nel registro e mostrato nella pagina di caricamento. Un
errore di battitura in un file di configurazione non deve poter impedire a
tutta l'azienda di caricare i documenti (D-039).

**Il tipo resta testo libero nel database.** documents.doc_type e' una colonna
di testo, non una chiave esterna: togliendo una voce da questo elenco i
documenti che l'avevano continuano a mostrare il loro tipo, semplicemente non
lo si puo' piu' scegliere per un documento nuovo (docs/MODELLO_DATI.md, 6.3).
"""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger("aurora.tipi_documento")

# Il nome della voce attesa nel file di configurazione.
CHIAVE_TIPI = "tipi"

# L'elenco usato quando il file non e' leggibile. E' quello che l'azienda ha
# indicato all'inizio della sessione 6: se il file di configurazione sparisce,
# il programma continua a proporre esattamente queste voci.
TIPI_DI_RIPIEGO: tuple[str, ...] = (
    "Schema elettrico",
    "PCB",
    "Meccanica",
    "Firmware",
    "Specifica",
    "Rapporto di prova",
    "Certificato",
    "Corrispondenza",
    "Altro",
)


@dataclass(frozen=True)
class Elenco:
    """I tipi di documento, cosi' come sono stati letti dal file.

    tipi        le voci, nell'ordine in cui vanno mostrate.
    problema    la spiegazione in italiano di che cosa non va nel file, da
                mostrare nelle pagine. None quando e' tutto a posto.
    """

    tipi: tuple[str, ...]
    problema: str | None = None

    @property
    def dal_file(self) -> bool:
        """Vero quando l'elenco arriva davvero dal file di configurazione."""
        return self.problema is None


# L'elenco letto una volta sola. Come per la regola dei codici prodotto, il
# file si rilegge riavviando il server: e' un parametro di funzionamento, non
# un dato, e rileggerlo a ogni richiesta vorrebbe dire un accesso al disco per
# ogni menu a tendina disegnato. ricarica() esiste per i test.
_elenco_in_uso: Elenco | None = None


def _ripiego(problema: str) -> Elenco:
    """L'elenco di ripiego, con scritto perche' si e' finiti a usarlo."""
    return Elenco(tipi=TIPI_DI_RIPIEGO, problema=problema)


def _leggi(percorso: Path) -> Elenco:
    """Legge il file di configurazione. Non solleva mai."""
    try:
        contenuto = percorso.read_bytes()
    except OSError as errore:
        logger.error(
            "Il file dei tipi di documento non si legge (%s): %s", percorso, errore
        )
        return _ripiego(
            f"Il file di configurazione {percorso.name} non e' stato trovato "
            "o non si riesce a leggerlo."
        )

    try:
        dati = tomllib.loads(contenuto.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as errore:
        logger.error("Il file %s non e' un TOML valido: %s", percorso, errore)
        return _ripiego(
            f"Il file di configurazione {percorso.name} contiene un errore di "
            "scrittura e non e' stato compreso."
        )

    grezzi = dati.get(CHIAVE_TIPI)
    if not isinstance(grezzi, list):
        logger.error("In %s manca la voce '%s'", percorso, CHIAVE_TIPI)
        return _ripiego(
            f"Nel file di configurazione {percorso.name} manca l'elenco "
            f"'{CHIAVE_TIPI}'."
        )

    # Si tengono le sole voci che sono testo e non sono vuote, e si tolgono i
    # doppioni conservando l'ordine: due voci identiche in un menu a tendina
    # sono un errore che chi sceglie non puo' risolvere.
    tipi: list[str] = []
    for voce in grezzi:
        if isinstance(voce, str) and voce.strip() and voce.strip() not in tipi:
            tipi.append(voce.strip())

    if not tipi:
        logger.error("L'elenco '%s' in %s e' vuoto", CHIAVE_TIPI, percorso)
        return _ripiego(
            f"L'elenco '{CHIAVE_TIPI}' nel file {percorso.name} e' vuoto: "
            "senza tipi non si potrebbe caricare nessun documento."
        )

    logger.info("Tipi di documento: %s voci lette da %s", len(tipi), percorso)
    return Elenco(tipi=tuple(tipi))


def elenco() -> Elenco:
    """L'elenco in uso, letto dal file la prima volta che serve."""
    global _elenco_in_uso
    if _elenco_in_uso is None:
        _elenco_in_uso = _leggi(settings.document_types_config)
    return _elenco_in_uso


def ricarica(percorso: Path | None = None) -> Elenco:
    """Rilegge l'elenco dal file. Serve ai test e a una futura pagina di servizio."""
    global _elenco_in_uso
    _elenco_in_uso = _leggi(percorso or settings.document_types_config)
    return _elenco_in_uso


def tipi() -> tuple[str, ...]:
    """Le voci proponibili, nell'ordine del file."""
    return elenco().tipi


def opzioni(includi: str | None = None) -> list[tuple[str, str]]:
    """I tipi come coppie (valore, etichetta), pronti per il menu a tendina.

    Le coppie si compongono qui e non nei template (docs/GUIDA_STILE.md,
    sezione 5). Valore ed etichetta coincidono perche' il tipo e' gia' testo
    in italiano: la coppia serve perche' il componente della tendina vuole
    quella forma, non perche' ci sia una traduzione da fare.

    In "includi" si passa il tipo che un documento ha gia': se nel frattempo
    e' stato tolto dal file di configurazione va proposto lo stesso, altrimenti
    riaprendo quel documento il menu mostrerebbe un tipo diverso dal suo.
    """
    voci = list(tipi())
    if includi and includi not in voci:
        voci.append(includi)
    return [(voce, voce) for voce in voci]
