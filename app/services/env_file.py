"""Scrivere un parametro nel file `.env` senza rovinare il resto.

**Perche' esiste.** La regola 8 di CLAUDE.md dice che la configurazione sta nel
file `.env`, e fino alla sessione 10 quel file lo scriveva soltanto una persona
con un editore di testo. La sessione 11 aggiunge la pagina «Configurazione
posta», che l'azienda ha chiesto esplicitamente di poter compilare **senza
toccare file di testo**: i quattro parametri della casella arrivano dall'ufficio
informatico su un foglio, e chi li riceve non ha accesso al server.

La regola non cambia: il `.env` resta l'unico posto in cui la configurazione
vive. Cambia chi lo scrive - adesso puo' scriverlo anche il programma - e questo
file e' l'unico che lo fa (D-081).

**Che cosa garantisce.**

  - *I commenti restano.* Il `.env` di Aurora e' commentato riga per riga, ed e'
    la sola documentazione che chi amministra il server abbia sottomano. Si
    riscrive **solo la riga del parametro cambiato**, al posto in cui gia'
    stava; i parametri nuovi si aggiungono in fondo con il loro commento.
  - *La scrittura e' atomica.* Prima un file accanto, poi la sostituzione: un
    server che si spegne a meta' scrittura lascerebbe altrimenti un `.env`
    troncato, e un `.env` troncato e' un programma che non riparte piu'. E' la
    stessa precauzione dell'archivio dei file (D-047).
  - *Il file di prima resta.* La copia precedente viene tenuta accanto come
    `.env.precedente`: e' l'unico modo di tornare indietro se qualcuno salva
    un valore sbagliato e il server viene riavviato prima che se ne accorga.
"""

import logging
from pathlib import Path

from app.config import ENV_FILE

logger = logging.getLogger("aurora.configurazione.env")

# I caratteri che obbligano a mettere il valore fra virgolette. Uno spazio in
# fondo verrebbe altrimenti mangiato dalla lettura, e un cancelletto in mezzo
# trasformerebbe meta' valore in un commento.
CARATTERI_DA_PROTEGGERE = ('"', "'", "#", " ", "\t")


def riga_di(chiave: str, valore: str) -> str:
    """La riga da scrivere nel file per una coppia chiave-valore.

    Il valore va fra virgolette solo quando serve: un `.env` in cui tutto e'
    virgolettato si legge peggio, e la meta' delle righe di Aurora sono numeri
    o parole singole.
    """
    testo = valore or ""
    if any(carattere in testo for carattere in CARATTERI_DA_PROTEGGERE):
        testo = '"' + testo.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{chiave}={testo}"


def _e_la_riga_di(riga: str, chiave: str) -> bool:
    """Dice se questa riga del file assegna proprio quella chiave.

    Si guarda la riga senza spazi davanti e si pretende l'uguale subito dopo il
    nome: senza quest'ultima condizione, "MAIL_POLL_MINUTES" verrebbe
    riconosciuto anche dentro un ipotetico "MAIL_POLL_MINUTES_MAX".
    """
    pulita = riga.lstrip()
    if pulita.startswith("#"):
        return False
    return pulita.startswith(chiave) and pulita[len(chiave) :].lstrip().startswith("=")


def scrivi_parametri(
    valori: dict[str, str],
    *,
    percorso: Path | None = None,
    commenti: dict[str, str] | None = None,
) -> Path:
    """Scrive nel `.env` i parametri indicati, lasciando stare tutto il resto.

    `commenti` e' il commento da mettere sopra un parametro che nel file non
    c'era ancora: quando si aggiunge una riga nuova, la si aggiunge spiegata.

    Restituisce il percorso del file scritto, cosi' chi lo chiama puo' dirlo
    nel registro.
    """
    file_env = Path(percorso) if percorso is not None else ENV_FILE

    try:
        righe = file_env.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        righe = [
            "# Configurazione di Aurora. Questo file NON entra in git.",
            "# Il modello commentato di tutti i parametri e' in .env.example.",
            "",
        ]
    except OSError as errore:
        logger.error("Il file %s non si legge: %s", file_env, errore)
        raise

    da_scrivere = dict(valori)

    for indice, riga in enumerate(righe):
        for chiave in list(da_scrivere):
            if _e_la_riga_di(riga, chiave):
                righe[indice] = riga_di(chiave, da_scrivere.pop(chiave))
                break

    # Quello che non c'era si aggiunge in fondo, con il suo commento.
    if da_scrivere:
        if righe and righe[-1].strip():
            righe.append("")
        righe.append("# --- Aggiunto dalla pagina di configurazione di Aurora ---")
        for chiave, valore in da_scrivere.items():
            commento = (commenti or {}).get(chiave)
            if commento:
                for pezzo in commento.splitlines():
                    righe.append(f"# {pezzo}".rstrip())
            righe.append(riga_di(chiave, valore))

    contenuto = "\n".join(righe) + "\n"

    provvisorio = file_env.with_name(file_env.name + ".tmp")
    precedente = file_env.with_name(file_env.name + ".precedente")

    try:
        provvisorio.write_text(contenuto, encoding="utf-8")
        if file_env.exists():
            # La copia di sicurezza si fa **prima** della sostituzione: dopo,
            # il file da copiare sarebbe gia' quello nuovo.
            precedente.write_text(
                file_env.read_text(encoding="utf-8"), encoding="utf-8"
            )
        provvisorio.replace(file_env)
    except OSError as errore:
        logger.error("Il file %s non si e' potuto scrivere: %s", file_env, errore)
        raise

    logger.info(
        "Configurazione scritta in %s: %s", file_env, ", ".join(sorted(valori))
    )
    return file_env
