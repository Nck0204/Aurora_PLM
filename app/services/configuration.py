"""Le modifiche alla configurazione finiscono nel registro.

**Il problema.** Regola 8 di CLAUDE.md: la configurazione di Aurora sta nel
file `.env` e nei file di `config/`, e si cambia sul server aziendale con un
editore di testo. Non c'e' nessuna pagina che la modifichi, quindi non c'e'
nessuna operazione dell'utente da registrare - e "le modifiche alla
configurazione" resterebbero l'unica cosa importante che succede ad Aurora e
di cui il registro non sa niente. Chi verifica il programma fra un anno,
davanti a un documento scaricato da un indirizzo che non si aspettava, deve
poter sapere se quel giorno la configurazione era quella di oggi.

**Quello che si puo' fare, e che si fa qui.** Non si registra chi ha
modificato il file - il programma non lo sa, e inventarselo sarebbe peggio che
tacere: quello lo dicono i permessi del filesystem e il registro di Windows.
Si registra il **fatto** che la configurazione con cui il programma sta
girando sia diversa da quella dell'avvio precedente, con il valore di prima e
quello di dopo. All'avvio si confronta la configurazione effettiva con l'ultima
scritta nel registro:

  - la prima volta in assoluto si scrive una voce `config.loaded`, che e' la
    fotografia di partenza;
  - se qualcosa e' cambiato si scrive `config.changed`, con i valori di
    prima dei soli parametri cambiati e la fotografia completa di adesso;
  - se non e' cambiato niente non si scrive niente. Un registro con dentro una
    riga a ogni riavvio del server e' un registro in cui non si trova piu'
    nulla.

L'utente della voce e' **nullo**, cioe' "sistema": non c'e' nessuna persona
collegata quando il server parte, e scriverne una finta sarebbe la peggiore
delle bugie da mettere in un audit trail.

**I segreti non entrano nel registro.** Della stringa di connessione si
registra tutto tranne la password, e la chiave di firma dei cookie non si
registra affatto: se ne registra l'impronta, che dice se e' cambiata senza
dire qual e'. Vedi PARAMETRI_RISERVATI qui sotto.

Dei file di `config/` non si registra il contenuto - sono tabelle intere - ma
il percorso e l'impronta SHA-256: cambiare la regola di scomposizione dei
codici prodotto cambia l'impronta, e la voce nel registro lo dice.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog
from app.services import audit

logger = logging.getLogger("aurora.configurazione")

# I parametri di cui si registra l'impronta e non il valore. Sono i segreti:
# quello che serve sapere e' se sono cambiati, non che cosa sono diventati.
PARAMETRI_RISERVATI = ("SECRET_KEY",)

# Quello che si scrive al posto di un file di configurazione che non c'e'.
# Non e' un errore da fermare qui - il programma continua a funzionare anche
# senza quei file (D-038, D-039) - ma e' un fatto da registrare.
FILE_MANCANTE = "(assente)"


def _impronta_del_testo(valore: str) -> str:
    """Le prime dodici cifre dell'impronta di un segreto.

    Dodici e non sessantaquattro: bastano a distinguere due valori diversi, e
    un'impronta intera scritta nel registro invita qualcuno a provare a
    indovinare che cosa ci sia dietro.
    """
    return hashlib.sha256(valore.encode("utf-8")).hexdigest()[:12]


def _impronta_del_file(percorso: Path) -> str:
    """L'impronta di un file di configurazione, o "(assente)" se non c'e'.

    Non si legge il contenuto dentro il registro: un file di corrispondenze
    puo' essere lungo, e quello che serve sapere e' se e' cambiato.
    """
    try:
        contenuto = percorso.read_bytes()
    except OSError as errore:
        # Non si rilancia: la mancanza di un file di configurazione e' un caso
        # previsto e il programma va avanti lo stesso (D-039). Ma va detto nel
        # registro su file, perche' e' quasi sempre un errore di installazione.
        logger.warning(
            "Il file di configurazione %s non si legge (%s): nel registro "
            "delle operazioni risultera' assente",
            percorso,
            errore,
        )
        return FILE_MANCANTE

    return hashlib.sha256(contenuto).hexdigest()[:12]


def _database_senza_password(url: str) -> str:
    """La stringa di connessione con la password sostituita da tre asterischi.

    Indirizzo, porta, nome del database e utente **restano leggibili**, e
    devono: "questo scarico e' avvenuto quando Aurora era collegata al
    database di collaudo" e' esattamente il genere di cosa che un audit deve
    poter dire.
    """
    pezzi = urlsplit(url)
    if pezzi.password is None:
        return url

    utente = pezzi.username or ""
    porta = f":{pezzi.port}" if pezzi.port else ""
    autorita = f"{utente}:***@{pezzi.hostname or ''}{porta}"
    return urlunsplit(
        (pezzi.scheme, autorita, pezzi.path, pezzi.query, pezzi.fragment)
    )


def configurazione_effettiva() -> dict[str, Any]:
    """La configurazione con cui il programma sta girando adesso.

    E' un dizionario piatto di sole stringhe e numeri, perche' finisce dentro
    una colonna jsonb e perche' due configurazioni si confrontano campo per
    campo. I nomi delle chiavi sono quelli del file .env, cosi' chi legge la
    voce nel registro sa subito quale riga andare a guardare.
    """
    valori: dict[str, Any] = {
        "DATABASE_URL": _database_senza_password(settings.DATABASE_URL),
        "STORAGE_PATH": str(settings.storage_dir),
        "APP_NAME": settings.APP_NAME,
        "LOG_LEVEL": settings.LOG_LEVEL,
        "COOKIE_SECURE": settings.COOKIE_SECURE,
        "SESSION_HOURS": settings.SESSION_HOURS,
        "REMEMBER_ME_DAYS": settings.REMEMBER_ME_DAYS,
        "LOGIN_MAX_ATTEMPTS": settings.LOGIN_MAX_ATTEMPTS,
        "LOGIN_WINDOW_MINUTES": settings.LOGIN_WINDOW_MINUTES,
        "PAGE_SIZE": settings.PAGE_SIZE,
        "MAX_UPLOAD_MB": settings.MAX_UPLOAD_MB,
        "MAIL_PROVIDER": settings.MAIL_PROVIDER,
        "MAIL_LOCAL_PATH": str(settings.mail_local_dir),
        "PRODUCT_CODE_CONFIG": str(settings.product_code_config),
        "DOCUMENT_TYPES_CONFIG": str(settings.document_types_config),
    }

    for nome in PARAMETRI_RISERVATI:
        valori[f"{nome} (impronta)"] = _impronta_del_testo(getattr(settings, nome))

    valori["codice_prodotto.toml (impronta)"] = _impronta_del_file(
        settings.product_code_config
    )
    valori["tipi_documento.toml (impronta)"] = _impronta_del_file(
        settings.document_types_config
    )

    return valori


def ultima_configurazione_registrata(db: Session) -> dict[str, Any] | None:
    """La configurazione dell'ultima voce di sistema scritta nel registro.

    None quando non ce n'e' ancora nessuna: e' il primo avvio dopo
    l'installazione di questa versione del programma.
    """
    riga = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action.in_(
                (audit.ACTION_CONFIG_LOADED, audit.ACTION_CONFIG_CHANGED)
            )
        )
        .order_by(AuditLog.seq.desc())
        .limit(1)
    ).first()

    return riga.new_value if riga is not None else None


def _descrizione_del_cambiamento(
    prima: dict[str, Any], adesso: dict[str, Any], cambiati: list[str]
) -> str:
    """La frase in italiano di una voce config.changed.

    Si scrive a mano invece di lasciarla comporre a
    audit.descrizione_predefinita() perche' qui new_value e' la
    configurazione intera: la composizione automatica elencherebbe tutti e
    diciassette i parametri invece dei due che sono cambiati davvero.
    """
    assente_prima = "(non c'era)"
    assente_dopo = "(tolto)"
    pezzi = [
        f"{nome}: {prima.get(nome, assente_prima)} -> "
        f"{adesso.get(nome, assente_dopo)}"
        for nome in cambiati
    ]
    quanti = len(cambiati)
    return (
        f"Configurazione cambiata rispetto all'avvio precedente: "
        f"{quanti} parametro{'' if quanti == 1 else 'i'} divers"
        f"{'o' if quanti == 1 else 'i'} ({'; '.join(pezzi)})"
    )


def registra_configurazione(db: Session) -> str | None:
    """Confronta la configurazione con quella dell'avvio precedente e registra.

    Restituisce il nome dell'azione scritta, oppure None se non e' cambiato
    niente e quindi non c'e' stato niente da scrivere.

    **Non fa commit.** Lo fa chi la chiama, come tutto il resto del programma:
    cosi' la stessa funzione va bene per l'avvio del server e per un test che
    lavora dentro una transazione annullata.
    """
    adesso = configurazione_effettiva()
    prima = ultima_configurazione_registrata(db)

    if prima is None:
        audit.record(
            db,
            action=audit.ACTION_CONFIG_LOADED,
            entity_type=audit.ENTITY_SISTEMA,
            user_id=None,
            new_value=adesso,
            description=(
                "Configurazione letta all'avvio: e' la prima volta che viene "
                f"registrata, e fa da riferimento per i confronti successivi "
                f"({len(adesso)} parametri)"
            ),
        )
        logger.info("Configurazione registrata per la prima volta")
        return audit.ACTION_CONFIG_LOADED

    # I parametri che sono cambiati, piu' quelli comparsi e quelli spariti: un
    # parametro nuovo aggiunto al programma e' una modifica come le altre.
    nomi = sorted(set(prima) | set(adesso))
    cambiati = [nome for nome in nomi if prima.get(nome) != adesso.get(nome)]

    if not cambiati:
        return None

    # **new_value e' la configurazione intera, non i soli campi cambiati**, ed
    # e' l'unica eccezione alla regola scritta in audit.record(). Il motivo e'
    # che questa voce serve anche da fotografia per il confronto del prossimo
    # avvio: se ci finissero dentro solo i campi cambiati, il riavvio
    # successivo confronterebbe la configurazione completa con tre righe e
    # direbbe che e' cambiato tutto.
    #
    # old_value invece contiene i soli valori di prima dei campi cambiati, che
    # e' quello che serve leggere: "PAGE_SIZE era 25 ed e' diventato 50".
    audit.record(
        db,
        action=audit.ACTION_CONFIG_CHANGED,
        entity_type=audit.ENTITY_SISTEMA,
        user_id=None,
        old_value={nome: prima.get(nome) for nome in cambiati},
        new_value=adesso,
        description=_descrizione_del_cambiamento(prima, adesso, cambiati),
    )
    logger.warning(
        "La configurazione e' cambiata dall'avvio precedente: %s",
        ", ".join(cambiati),
    )
    return audit.ACTION_CONFIG_CHANGED
