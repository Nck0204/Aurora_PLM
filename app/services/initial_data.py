"""I dati iniziali di Aurora, letti da un file di configurazione.

Le classificazioni, la griglia dei permessi di partenza e il percorso delle
fasi che un'installazione nuova si porta appresso. Stanno in
`config/dati_iniziali.toml` e non dentro il programma, per due ragioni.

**La prima e' la regola 8 di CLAUDE.md.** E' roba che l'azienda potrebbe voler
cambiare - un'altra azienda avrebbe altre fasi e altre classificazioni - e
cambiarla non deve costare una modifica al programma (D-038).

**La seconda e' piu' stringente e riguarda le fasi.** In Aurora le fasi sono
**dati e non codice** (D-055): il programma non sa e non deve sapere come si
chiamano, quello che guarda sono `blocks_return` e `closes_project`. C'e' un
test che legge i sorgenti e diventa rosso se un nome di fase ricompare dentro
`app/`. Scrivendo i dati iniziali dentro un servizio, quel test diventerebbe
rosso - e avrebbe ragione.

**Lo leggono in due, e devono leggere la stessa cosa:** la configurazione
guidata del primo avvio e `scripts/seed.py`. Prima della sessione 12 quegli
elenchi erano scritti dentro tutti e due, e bastava correggerne uno perche' due
installazioni dessero due sistemi diversi.

**Non c'e' nessun elenco di ripiego, e non va aggiunto.** Gli altri due file di
`config/` ne hanno uno (`doc_types.py`, `product_codes.py`) perche' senza di
loro il programma non funzionerebbe. Qui no: se questo file manca, l'unica cosa
che non si puo' fare e' **creare i dati iniziali con un pulsante**, e le stesse
cose si creano a mano dalle pagine «Permessi» e «Fasi». Un elenco di ripiego,
qui, vorrebbe dire riportare i nomi delle fasi dentro `app/`, cioe' rimettere
esattamente il problema che questo file esiste per togliere.
"""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger("aurora.dati_iniziali")

# I tre permessi di una casella della griglia, con il nome che hanno nel file
# di configurazione e quello che hanno nella colonna del database. La
# corrispondenza si scrive qui e in nessun altro posto.
PERMESSI = (
    ("vedere", "can_view"),
    ("caricare", "can_upload"),
    ("modificare", "can_edit"),
)


@dataclass(frozen=True)
class Classificazione:
    """Una classificazione di partenza."""

    nome: str
    descrizione: str


@dataclass(frozen=True)
class Fase:
    """Una fase del percorso di partenza.

    Le due proprieta' sono le sole cose che il programma sappia di una fase:
    tutto il resto - il nome, la descrizione - e' testo che si legge e basta.
    """

    nome: str
    descrizione: str
    blocca_ritorno: bool = False
    chiude_progetto: bool = False


@dataclass(frozen=True)
class DatiIniziali:
    """Tutto quello che serve a riempire un'installazione nuova.

    `problema` e' la frase in italiano da mostrare quando il file non si e'
    potuto leggere: quando c'e', gli elenchi sono vuoti e i due passi della
    configurazione guidata che li usano lo dicono invece di fare finta di
    niente.
    """

    classificazioni: tuple[Classificazione, ...] = ()
    permessi: dict[str, dict[str, tuple[bool, bool, bool]]] | None = None
    modello_fasi: str = ""
    descrizione_modello: str = ""
    fasi: tuple[Fase, ...] = ()
    problema: str | None = None

    @property
    def leggibili(self) -> bool:
        """Vero quando il file c'era ed era scritto bene."""
        return self.problema is None

    def caselle(self) -> dict[tuple[str, str], tuple[bool, bool, bool]]:
        """La griglia come dizionario (ruolo, classificazione) -> tre spunte."""
        griglia: dict[tuple[str, str], tuple[bool, bool, bool]] = {}
        for ruolo, per_classe in (self.permessi or {}).items():
            for classe, spunte in per_classe.items():
                griglia[(ruolo, classe)] = spunte
        return griglia


# Letti una volta sola, come gli altri file di config/: sono parametri di
# funzionamento, non dati, e si rileggono riavviando il server. ricarica()
# esiste per i test.
_letti: DatiIniziali | None = None


def _guasto(frase: str) -> DatiIniziali:
    """Dati vuoti, con scritto perche'."""
    return DatiIniziali(problema=frase)


def _leggi(percorso: Path) -> DatiIniziali:
    """Legge il file. Non solleva mai: un guasto diventa una frase."""
    try:
        contenuto = percorso.read_bytes()
    except OSError as errore:
        logger.error("I dati iniziali non si leggono (%s): %s", percorso, errore)
        return _guasto(
            f"Il file di configurazione {percorso.name} non e' stato trovato o "
            "non si riesce a leggerlo."
        )

    try:
        dati = tomllib.loads(contenuto.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as errore:
        logger.error("Il file %s non e' un TOML valido: %s", percorso, errore)
        return _guasto(
            f"Il file di configurazione {percorso.name} contiene un errore di "
            "scrittura e non e' stato compreso."
        )

    classificazioni = _classificazioni(dati, percorso)
    if classificazioni is None:
        return _guasto(
            f"Nel file {percorso.name} manca l'elenco delle classificazioni, "
            "oppure e' scritto in un modo che non si riesce a leggere."
        )

    fasi, modello, descrizione = _fasi(dati, percorso)
    if fasi is None:
        return _guasto(
            f"Nel file {percorso.name} manca il percorso delle fasi, oppure e' "
            "scritto in un modo che non si riesce a leggere."
        )

    logger.info(
        "Dati iniziali: %s classificazioni e %s fasi lette da %s",
        len(classificazioni),
        len(fasi),
        percorso,
    )
    return DatiIniziali(
        classificazioni=classificazioni,
        permessi=_permessi(dati),
        modello_fasi=modello,
        descrizione_modello=descrizione,
        fasi=fasi,
    )


def _classificazioni(
    dati: dict, percorso: Path
) -> tuple[Classificazione, ...] | None:
    """Le classificazioni. None se la voce manca o e' inutilizzabile."""
    grezze = dati.get("classificazioni")
    if not isinstance(grezze, list) or not grezze:
        logger.error("In %s manca la voce 'classificazioni'", percorso)
        return None

    lette: list[Classificazione] = []
    for voce in grezze:
        if not isinstance(voce, dict):
            continue
        nome = str(voce.get("nome") or "").strip()
        if not nome or any(gia.nome == nome for gia in lette):
            continue
        lette.append(
            Classificazione(
                nome=nome,
                descrizione=str(voce.get("descrizione") or "").strip(),
            )
        )

    return tuple(lette) if lette else None


def _permessi(dati: dict) -> dict[str, dict[str, tuple[bool, bool, bool]]]:
    """La griglia dei permessi. Vuota se manca: si sceglie il "no".

    Una casella che non c'e' vale "niente permessi", che e' la scelta prudente
    e la stessa che fa `permissions.crea_classificazione()`. Un file senza
    griglia produce quindi classificazioni con tutti i permessi chiusi, che si
    aprono dalla pagina «Permessi»: nessuno resta chiuso fuori per sbaglio, e
    nessuno riceve un permesso che nessuno gli ha dato.
    """
    grezzi = dati.get("permessi")
    if not isinstance(grezzi, dict):
        return {}

    griglia: dict[str, dict[str, tuple[bool, bool, bool]]] = {}
    for ruolo, per_classe in grezzi.items():
        if not isinstance(per_classe, dict):
            continue
        caselle: dict[str, tuple[bool, bool, bool]] = {}
        for classe, spunte in per_classe.items():
            if not isinstance(spunte, dict):
                continue
            caselle[classe] = tuple(
                bool(spunte.get(nel_file, False)) for nel_file, _colonna in PERMESSI
            )
        if caselle:
            griglia[str(ruolo)] = caselle

    return griglia


def _fasi(
    dati: dict, percorso: Path
) -> tuple[tuple[Fase, ...] | None, str, str]:
    """Il percorso: le fasi in ordine, il nome del modello, la descrizione."""
    blocco = dati.get("fasi")
    if not isinstance(blocco, dict):
        logger.error("In %s manca la voce 'fasi'", percorso)
        return None, "", ""

    modello = str(blocco.get("modello") or "").strip()
    descrizione = str(blocco.get("descrizione") or "").strip()

    grezze = blocco.get("elenco")
    if not modello or not isinstance(grezze, list) or not grezze:
        logger.error("In %s il percorso delle fasi e' incompleto", percorso)
        return None, "", ""

    lette: list[Fase] = []
    for voce in grezze:
        if not isinstance(voce, dict):
            continue
        nome = str(voce.get("nome") or "").strip()
        if not nome:
            continue
        lette.append(
            Fase(
                nome=nome,
                descrizione=str(voce.get("descrizione") or "").strip(),
                blocca_ritorno=bool(voce.get("blocca_ritorno", False)),
                chiude_progetto=bool(voce.get("chiude_progetto", False)),
            )
        )

    if not lette:
        return None, "", ""

    return tuple(lette), modello, descrizione


def dati() -> DatiIniziali:
    """I dati iniziali, letti dal file la prima volta che servono."""
    global _letti
    if _letti is None:
        _letti = _leggi(settings.initial_data_config)
    return _letti


def ricarica(percorso: Path | None = None) -> DatiIniziali:
    """Rilegge il file. Serve ai test e a chi lo corregge senza riavviare."""
    global _letti
    _letti = _leggi(percorso or settings.initial_data_config)
    return _letti
