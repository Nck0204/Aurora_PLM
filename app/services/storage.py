"""L'archivio fisico dei file: deposito per impronta, senza nomi originali.

E' la meta' del programma che tocca il disco. Il database sa che cosa e' un
file (titolo, autore, data, versione); questo modulo sa soltanto **dove sta**
il contenuto, e lo trova a partire dalla sua impronta SHA-256.

    STORAGE_PATH/objects/3f/9a/3f9a2c11...e4  (l'impronta per intero)

Quattro regole, e sono tutte e quattro il motivo per cui questo modulo esiste
invece di qualche riga di codice sparsa nelle rotte (D-004).

**Nessun nome originale sul filesystem.** Il nome che l'utente ha dato al file
sta nel database, in document_versions.original_filename. Sul disco c'e' solo
l'impronta, che e' esadecimale minuscola: niente caratteri che Windows
rifiuta, niente percorsi che sfondano il limite dei 260 caratteri, niente due
"schema.pdf" che si sovrascrivono a vicenda.

**Due file uguali occupano un file solo.** L'impronta e' calcolata sul
contenuto: caricando due volte lo stesso datasheet, la seconda volta il file
c'e' gia' e non viene riscritto. Nella documentazione tecnica succede di
continuo.

**La scrittura e' atomica.** Il file arriva prima in un temporaneo dentro
l'archivio, e solo quando e' scritto per intero viene spostato al suo posto
definitivo con os.replace(), che a livello di sistema operativo e' atomico. Se
il server si spegne a meta' caricamento, nell'archivio non resta un file
troncato che sembra buono: resta un temporaneo che non e' riferito da nessuno.
Il temporaneo sta **dentro** STORAGE_PATH e non nella cartella temporanea di
sistema perche' os.replace() e' atomico solo dentro lo stesso volume.

**Il limite di dimensione si verifica mentre il file arriva**, non dopo. Un
file da otto gigabyte va fermato prima di aver riempito il disco, non dopo
averlo riempito.

Le due cartelle (objects e tmp) vengono create quando servono: chi installa
Aurora deve creare STORAGE_PATH e basta.
"""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.config import settings

logger = logging.getLogger("aurora.archivio")

# Le due cartelle dentro STORAGE_PATH.
CARTELLA_OGGETTI = "objects"
CARTELLA_TEMPORANEI = "tmp"

# Il file temporaneo si riconosce da questa coda: chi guarda la cartella deve
# capire subito che quello non e' un file dell'archivio.
CODA_TEMPORANEO = ".parziale"

# Quanti caratteri dell'impronta diventano cartella a ogni livello, e quanti
# livelli. Due livelli da due caratteri fanno 256 x 256 cartelle: con qualche
# centinaio di migliaia di file nessuna cartella arriva a contenerne piu' di
# qualche decina, ed Esplora risorse le apre ancora.
CARATTERI_PER_LIVELLO = 2
LIVELLI = 2

# Quanto si legge per volta. 1 MB: abbastanza grande da non fare un milione di
# giri su un file da 2 GB, abbastanza piccolo da non tenere in memoria niente
# di importante.
BLOCCO = 1024 * 1024

# Lunghezza dell'impronta SHA-256 scritta in esadecimale.
LUNGHEZZA_IMPRONTA = 64

# Le sole lettere ammesse in un'impronta. Serve al controllo di percorso_di().
CIFRE_ESADECIMALI = frozenset("0123456789abcdef")


class FileTroppoGrande(Exception):
    """Il file supera il limite configurato in MAX_UPLOAD_MB.

    Il messaggio e' gia' scritto in italiano e va bene per essere mostrato a
    chi sta caricando: chi la cattura non deve ricomporre nessuna frase.
    """


class OggettoNonTrovato(Exception):
    """Nel database c'e' la riga, nell'archivio non c'e' il file.

    E' un guasto vero, non una situazione normale: vuol dire che qualcuno ha
    tolto un file da STORAGE_PATH a mano, oppure che l'archivio collegato non
    e' quello giusto. Va segnalato, non nascosto.
    """


@dataclass(frozen=True)
class Deposito:
    """L'esito di un deposito nell'archivio.

    impronta      lo SHA-256 del contenuto, esadecimale minuscolo. E' anche il
                  nome del file sul disco e il valore che finisce in
                  document_versions.storage_hash.
    dimensione    quanti byte sono stati letti davvero.
    gia_presente  vero quando quel contenuto era gia' nell'archivio e non e'
                  stato riscritto. E' la deduplicazione, e serve saperlo per
                  poterla verificare con un test.
    """

    impronta: str
    dimensione: int
    gia_presente: bool


def cartella_oggetti() -> Path:
    """La cartella che contiene l'archivio vero e proprio."""
    return settings.storage_dir / CARTELLA_OGGETTI


def cartella_temporanei() -> Path:
    """La cartella dei file a meta' scrittura, dentro lo stesso volume."""
    return settings.storage_dir / CARTELLA_TEMPORANEI


def percorso_di(impronta: str) -> Path:
    """Dove sta (o dove andra') il file con quell'impronta.

    Non tocca il disco: e' un calcolo. "3f9a2c11..." diventa
    objects/3f/9a/3f9a2c11...

    L'impronta viene normalizzata a minuscolo perche' su Windows i percorsi non
    distinguono maiuscole e minuscole ma il valore scritto nel database si':
    normalizzando qui, una sola forma raggiunge il disco.

    Il controllo sulla forma non e' pignoleria. Questo valore diventa un
    percorso: un valore che non e' un'impronta potrebbe contenere due punti e
    portare la lettura o la scrittura fuori dall'archivio.
    """
    pulita = impronta.strip().lower()

    if len(pulita) != LUNGHEZZA_IMPRONTA or not set(pulita) <= CIFRE_ESADECIMALI:
        raise ValueError(f"'{impronta}' non e' un'impronta SHA-256 valida.")

    cartelle = [
        pulita[
            livello * CARATTERI_PER_LIVELLO : (livello + 1) * CARATTERI_PER_LIVELLO
        ]
        for livello in range(LIVELLI)
    ]
    return cartella_oggetti().joinpath(*cartelle, pulita)


def esiste(impronta: str) -> bool:
    """Dice se quel contenuto e' gia' nell'archivio."""
    return percorso_di(impronta).is_file()


def dimensione_di(impronta: str) -> int:
    """Quanti byte occupa il file con quell'impronta."""
    percorso = percorso_di(impronta)
    if not percorso.is_file():
        raise OggettoNonTrovato(
            f"Nell'archivio manca il file con impronta {impronta}."
        )
    return percorso.stat().st_size


def apri(impronta: str) -> BinaryIO:
    """Apre in lettura il file con quell'impronta. Chi lo apre lo chiude.

    Serve a mandare il file al browser un pezzo per volta, senza tenerne in
    memoria due gigabyte.
    """
    percorso = percorso_di(impronta)
    try:
        return percorso.open("rb")
    except OSError as errore:
        logger.error("Oggetto mancante nell'archivio: %s (%s)", percorso, errore)
        raise OggettoNonTrovato(
            f"Nell'archivio manca il file con impronta {impronta}."
        ) from errore


def leggi(impronta: str) -> bytes:
    """Il contenuto per intero, in memoria.

    Si usa **solo** quando il contenuto va trasformato tutto insieme: la
    filigrana di un PDF, per esempio. Per mandare un file al browser si usa
    apri(), che non lo carica in memoria.
    """
    with apri(impronta) as sorgente:
        return sorgente.read()


def impronta_di(dati: bytes) -> str:
    """L'impronta SHA-256 di un contenuto gia' in memoria.

    Serve ai test, che devono poter dire "il file riscaricato e' identico a
    quello caricato" senza passare dall'archivio.
    """
    return hashlib.sha256(dati).hexdigest()


def _messaggio_limite(limite_byte: int) -> str:
    """La frase che legge chi ha provato a caricare un file troppo grande.

    Sotto il megabyte il limite si scrive in byte: "0 MB" non e' un limite,
    e' un errore di battitura agli occhi di chi lo legge. Succede solo nei
    test, che usano limiti piccolissimi, ma la frase e' la stessa.
    """
    megabyte = limite_byte / (1024 * 1024)
    misura = f"{megabyte:.0f} MB" if megabyte >= 1 else f"{limite_byte} byte"
    return f"Il file supera la dimensione massima consentita di {misura}."


def deposita(sorgente: BinaryIO, *, limite_byte: int | None = None) -> Deposito:
    """Deposita nell'archivio quello che si legge da "sorgente".

    Il giro e' questo, e l'ordine conta:

      1. si legge un blocco per volta, calcolando l'impronta mentre si scrive
         su un file temporaneo. Il contenuto passa una volta sola: calcolare
         l'impronta prima vorrebbe dire leggere due volte un file da 2 GB;
      2. se durante la lettura si supera il limite ci si ferma subito e il
         temporaneo viene buttato: il disco non si riempie;
      3. a scrittura finita si sa l'impronta, quindi si sa dove va il file. Se
         quel contenuto c'e' gia', il temporaneo viene buttato e non si
         riscrive niente: e' la deduplicazione;
      4. altrimenti il temporaneo viene spostato al suo posto con os.replace(),
         che e' atomico. Da quel momento il file c'e' per intero o non c'e'
         affatto: non esiste un istante in cui esista a meta'.

    Il fsync prima dello spostamento serve a essere sicuri che il contenuto sia
    davvero sul disco e non solo nella memoria del sistema operativo: senza,
    un'interruzione di corrente subito dopo potrebbe lasciare al posto giusto
    un file pieno di zeri, che e' il caso peggiore di tutti - un file che
    sembra buono e non lo e'.

    Il "finally" che toglie il temporaneo copre tutte le uscite anticipate:
    limite superato, disco pieno, connessione interrotta a meta' caricamento.
    """
    cartella_temporanei().mkdir(parents=True, exist_ok=True)
    temporaneo = cartella_temporanei() / f"{uuid.uuid4().hex}{CODA_TEMPORANEO}"

    digest = hashlib.sha256()
    scritti = 0

    try:
        with temporaneo.open("wb") as uscita:
            while True:
                pezzo = sorgente.read(BLOCCO)
                if not pezzo:
                    break

                scritti += len(pezzo)
                if limite_byte is not None and scritti > limite_byte:
                    raise FileTroppoGrande(_messaggio_limite(limite_byte))

                digest.update(pezzo)
                uscita.write(pezzo)

            uscita.flush()
            os.fsync(uscita.fileno())

        impronta = digest.hexdigest()
        destinazione = percorso_di(impronta)

        if destinazione.is_file():
            logger.info(
                "Contenuto gia' presente nell'archivio (%s): non riscritto",
                impronta,
            )
            return Deposito(
                impronta=impronta, dimensione=scritti, gia_presente=True
            )

        destinazione.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporaneo, destinazione)

        logger.info("Depositato nell'archivio %s (%s byte)", impronta, scritti)
        return Deposito(impronta=impronta, dimensione=scritti, gia_presente=False)

    finally:
        # Dopo os.replace() il temporaneo non c'e' piu' e questa riga non fa
        # niente. In tutti gli altri casi - errore, limite superato,
        # deduplicazione - e' quello che impedisce alla cartella tmp di
        # riempirsi di scarti.
        temporaneo.unlink(missing_ok=True)


def temporanei_rimasti() -> list[Path]:
    """I temporanei ancora presenti: in condizioni normali sono sempre zero.

    Serve ai test e, un giorno, alla pagina di diagnostica della sessione 11:
    un temporaneo rimasto li' vuol dire che un caricamento si e' interrotto, e
    siccome non e' riferito da nessuna riga del database si puo' togliere
    senza perdere niente.
    """
    cartella = cartella_temporanei()
    if not cartella.is_dir():
        return []
    return sorted(cartella.glob(f"*{CODA_TEMPORANEO}"))
