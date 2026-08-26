"""I motivi ammessi nell'oggetto di un messaggio, amministrati dall'interfaccia.

La convenzione aziendale vuole che l'oggetto della posta cominci con tre
parentesi quadre:

    [RMS1100-24-110SW][V2][SPECS] Chiarimento sulla tensione di ingresso
     |                 |   |
     |                 |   il motivo: perche' si scrive
     |                 la versione del prodotto
     il codice del prodotto

Questo modulo si occupa della terza parentesi soltanto. L'elenco dei motivi
ammessi sta in una **tabella** (`email_reasons`) e non in un file di
configurazione ne' in una costante: la sessione 10 chiede che si possa
cambiare dall'interfaccia, e la pagina che lo fa e' `/posta/motivi`.

**Perche' una tabella e non un file in `config/`.** I due file di `config/` -
la scomposizione dei codici e i tipi di documento - si cambiano sul server con
un editore di testo, e chi li cambia e' chi amministra la macchina (regola 8 di
CLAUDE.md). Questo elenco invece lo cambia chi usa Aurora, dal browser, e ogni
cambiamento deve lasciare una riga nel registro delle operazioni: sono
esattamente le due cose che un file di testo non sa fare (D-071).

**Il motivo non decide niente.** Un oggetto con un motivo che non e' in elenco
non manda il messaggio in quarantena: il codice prodotto c'e' e basta quello ad
attribuirlo. Il motivo sconosciuto resta scritto in `subject_parsed`, cosi' chi
amministra puo' accorgersi che ne serve uno nuovo. Rifiutare l'attribuzione per
via di una sigla fuori elenco vorrebbe dire mettere in quarantena della posta
che sappiamo benissimo a chi appartiene.
"""

import logging
import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmailReason, User
from app.services import audit

logger = logging.getLogger("aurora.posta.motivi")


# --- Le azioni registrate nel registro delle operazioni ---------------------

ACTION_REASON_CREATED = "email_reason.created"
ACTION_REASON_UPDATED = "email_reason.updated"
ACTION_REASON_DEACTIVATED = "email_reason.deactivated"
ACTION_REASON_REACTIVATED = "email_reason.reactivated"

ENTITY_EMAIL_REASONS = "email_reasons"

# Quanto puo' essere lungo un codice, per non far arrivare l'errore dal
# database in inglese. E' la stessa misura della colonna.
LUNGHEZZA_CODICE = 30


class CodiceNonValido(Exception):
    """Il codice scritto nel modulo non si puo' usare come motivo.

    Il messaggio e' gia' in italiano e va bene per essere mostrato in pagina.
    """


def normalizza(codice: str) -> str:
    """Il codice come finisce nel database: senza spazi e in maiuscolo.

    Nell'oggetto di un messaggio il motivo si scrive in maiuscolo per
    convenzione, ma chi lo scrive e' una persona: `[specs]` e `[ Specs ]`
    vogliono dire la stessa cosa. Normalizzando qui, il confronto fra quello
    che arriva nell'oggetto e quello che c'e' in tabella torna a essere una
    uguaglianza invece che un indovinello.
    """
    return " ".join((codice or "").split()).upper()


def verifica_codice(codice: str) -> str:
    """Controlla il codice scritto nel modulo e lo restituisce normalizzato.

    Tre regole, e ciascuna evita un motivo che poi non si riconoscerebbe mai:

      - non vuoto, perche' una parentesi vuota nell'oggetto non e' un motivo;
      - senza parentesi quadre dentro, che chiuderebbero la parentesi prima
        del previsto e romperebbero la lettura dell'oggetto;
      - non piu' lungo della colonna, cosi' l'errore lo dice questa funzione
        in italiano invece di PostgreSQL in inglese.
    """
    pulito = normalizza(codice)

    if not pulito:
        raise CodiceNonValido("Scrivi il codice del motivo, per esempio SPECS.")

    if "[" in pulito or "]" in pulito:
        raise CodiceNonValido(
            "Il codice di un motivo non puo' contenere parentesi quadre: sono "
            "quelle che lo delimitano dentro l'oggetto del messaggio."
        )

    if len(pulito) > LUNGHEZZA_CODICE:
        raise CodiceNonValido(
            f"Il codice di un motivo non puo' superare {LUNGHEZZA_CODICE} "
            "caratteri."
        )

    return pulito


# ---------------------------------------------------------------------------
#  Lettura
# ---------------------------------------------------------------------------


def elenco(db: Session, solo_attivi: bool = True) -> list[EmailReason]:
    """I motivi, nell'ordine in cui vanno mostrati."""
    interrogazione = select(EmailReason)
    if solo_attivi:
        interrogazione = interrogazione.where(EmailReason.is_active.is_(True))

    return list(
        db.scalars(
            interrogazione.order_by(EmailReason.sort_order, EmailReason.code)
        ).all()
    )


def trova(db: Session, reason_id: uuid.UUID) -> EmailReason | None:
    """Un motivo dal suo identificatore."""
    return db.get(EmailReason, reason_id)


def trova_per_codice(db: Session, codice: str) -> EmailReason | None:
    """Il motivo con quel codice, attivo o no.

    Anche quelli disattivati si trovano, ed e' voluto: un messaggio arrivato
    l'anno scorso con un motivo che nel frattempo e' stato messo da parte deve
    continuare a mostrarlo per quello che e'.
    """
    pulito = normalizza(codice)
    if not pulito:
        return None

    return db.scalars(
        select(EmailReason).where(EmailReason.code == pulito)
    ).first()


def codici_ammessi(db: Session) -> set[str]:
    """I codici dei motivi attivi, per il riconoscimento dell'oggetto.

    E' un insieme e non un elenco perche' la domanda che gli si fa e' sempre
    la stessa: "questa sigla e' un motivo?".
    """
    return {motivo.code for motivo in elenco(db, solo_attivi=True)}


def codice_gia_usato(
    db: Session, codice: str, escludi: uuid.UUID | None = None
) -> bool:
    """Dice se quel codice appartiene gia' a un motivo, attivo o no."""
    interrogazione = select(EmailReason.id).where(
        func.upper(EmailReason.code) == normalizza(codice)
    )
    if escludi is not None:
        interrogazione = interrogazione.where(EmailReason.id != escludi)

    return db.scalars(interrogazione).first() is not None


def opzioni(db: Session) -> list[tuple[str, str]]:
    """I motivi attivi come coppie (codice, "CODICE - descrizione").

    Si compongono qui e non nel template, come tutti gli elenchi di scelte
    (docs/GUIDA_STILE.md, sezione 5).
    """
    voci: list[tuple[str, str]] = []
    for motivo in elenco(db, solo_attivi=True):
        etichetta = (
            f"{motivo.code} - {motivo.description}"
            if motivo.description
            else motivo.code
        )
        voci.append((motivo.code, etichetta))
    return voci


# ---------------------------------------------------------------------------
#  Scrittura
# ---------------------------------------------------------------------------


def crea(
    db: Session,
    *,
    codice: str,
    descrizione: str,
    autore: User,
    request: Request | None = None,
) -> EmailReason:
    """Aggiunge un motivo in fondo all'elenco.

    Chi chiama ha gia' verificato con codice_gia_usato() che non ci sia: il
    vincolo di unicita' del database e' la rete di sicurezza, non il modo in
    cui si dice a una persona che quel codice esiste gia'.
    """
    pulito = verifica_codice(codice)
    ultimo = db.scalar(select(func.max(EmailReason.sort_order))) or 0

    motivo = EmailReason(
        code=pulito,
        description=descrizione.strip() or None,
        sort_order=ultimo + 1,
        is_active=True,
    )
    db.add(motivo)
    db.flush()

    audit.record(
        db,
        action=ACTION_REASON_CREATED,
        entity_type=ENTITY_EMAIL_REASONS,
        entity_id=motivo.id,
        user_id=autore.id,
        request=request,
        etichetta=motivo.code,
        new_value={"codice": motivo.code, "descrizione": motivo.description},
    )

    logger.info("'%s' ha aggiunto il motivo '%s'", autore.username, motivo.code)
    return motivo


def modifica(
    db: Session,
    motivo: EmailReason,
    *,
    codice: str,
    descrizione: str,
    autore: User,
    request: Request | None = None,
) -> None:
    """Corregge codice e descrizione di un motivo.

    **Il codice si puo' cambiare**, a differenza del nome utente. La ragione e'
    che qui non c'e' niente che ci punti: i messaggi gia' archiviati portano
    il motivo scritto dentro `subject_parsed`, che e' una copia del giorno in
    cui il messaggio e' arrivato e non un collegamento a questa riga. Cambiare
    il codice cambia quello che si riconoscera' da domani, non quello che e'
    stato riconosciuto ieri.
    """
    pulito = verifica_codice(codice)
    nuova_descrizione = descrizione.strip() or None

    prima = {"codice": motivo.code, "descrizione": motivo.description}
    if prima["codice"] == pulito and prima["descrizione"] == nuova_descrizione:
        return

    motivo.code = pulito
    motivo.description = nuova_descrizione
    db.flush()

    audit.record(
        db,
        action=ACTION_REASON_UPDATED,
        entity_type=ENTITY_EMAIL_REASONS,
        entity_id=motivo.id,
        user_id=autore.id,
        request=request,
        etichetta=motivo.code,
        old_value=prima,
        new_value={"codice": motivo.code, "descrizione": motivo.description},
    )


def disattiva(
    db: Session,
    motivo: EmailReason,
    *,
    autore: User,
    request: Request | None = None,
) -> None:
    """Toglie un motivo dall'elenco di quelli riconosciuti. Non cancella.

    Da quel momento un oggetto che lo contiene viene attribuito lo stesso -
    conta il codice prodotto - ma il motivo non risulta piu' fra quelli
    ammessi. I messaggi che ce l'hanno addosso continuano a mostrarlo.
    """
    if not motivo.is_active:
        return

    motivo.is_active = False
    db.flush()

    audit.record(
        db,
        action=ACTION_REASON_DEACTIVATED,
        entity_type=ENTITY_EMAIL_REASONS,
        entity_id=motivo.id,
        user_id=autore.id,
        request=request,
        etichetta=motivo.code,
        old_value={"attivo": True},
        new_value={"attivo": False},
    )


def riattiva(
    db: Session,
    motivo: EmailReason,
    *,
    autore: User,
    request: Request | None = None,
) -> None:
    """Rimette un motivo fra quelli riconosciuti, com'era."""
    if motivo.is_active:
        return

    motivo.is_active = True
    db.flush()

    audit.record(
        db,
        action=ACTION_REASON_REACTIVATED,
        entity_type=ENTITY_EMAIL_REASONS,
        entity_id=motivo.id,
        user_id=autore.id,
        request=request,
        etichetta=motivo.code,
        old_value={"attivo": False},
        new_value={"attivo": True},
    )
