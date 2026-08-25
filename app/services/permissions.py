"""Chi puo' vedere, caricare e modificare un documento.

La domanda "questa persona puo' vedere questo documento?" non ha come risposta
una proprieta' della persona ne' una proprieta' del documento: ha come
risposta una **casella della matrice**, quella all'incrocio fra il ruolo che
la persona ha in quel progetto e la classificazione del documento. La matrice
sta nella tabella permission_rules, ha tutte e dodici le caselle e la scrive
scripts/seed.py (docs/MODELLO_DATI.md, 4.5).

Questo modulo e' l'unico posto in cui quella matrice viene consultata.

Due strade, e devono dire la stessa cosa:

  - **permessi()** risponde per un documento solo. Serve alla scheda del
    documento e a ogni operazione che lo tocca;
  - **filtro_visibilita()** e' la stessa regola scritta come condizione SQL,
    e serve agli elenchi. Un elenco che nasconde una riga che poi si apre
    scrivendone l'indirizzo non e' una protezione, e' una tenda (D-043).

**Chi non e' assegnato a un progetto non ha nessun ruolo su quel progetto**,
quindi non ha nessun permesso sui suoi documenti: non li vede nell'elenco e
non ne apre la scheda. Il creatore fa eccezione e vede tutto, come per i
progetti.

**Una casella che manca vale no.** Se in permission_rules non c'e' la riga per
una coppia (ruolo, classificazione) - perche' e' stata aggiunta una
classificazione nuova senza completare la matrice - il permesso e' negato e il
fatto finisce nel registro. E' l'unico modo prudente di sbagliare: il
contrario vorrebbe dire che aggiungendo una classificazione si aprono per
sbaglio dei documenti a chi non doveva vederli.

**La matrice non si modifica dall'interfaccia**, non ancora: questa sessione
la legge e basta. La pagina che la corregge e' rimasta in sospeso dalla
sessione 3 ed e' segnata in docs/STATO.md.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, exists, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    Classification,
    Document,
    PermissionRule,
    Project,
    ProjectRole,
    User,
)

logger = logging.getLogger("aurora.permessi")


@dataclass(frozen=True)
class Permessi:
    """Le tre caselle della matrice, per una persona su un documento.

    vedere      sapere che il documento esiste e scaricarlo;
    caricare    caricare una versione nuova, o un documento nuovo con quella
                classificazione;
    modificare  cambiare lo stato del documento ed eliminarlo.

    Sono tre booleani e non un elenco di nomi perche' sono tre, sempre gli
    stessi tre, e leggere "permessi.caricare" costa meno che ricordarsi come
    si scrive una stringa.
    """

    vedere: bool
    caricare: bool
    modificare: bool


NESSUNO = Permessi(vedere=False, caricare=False, modificare=False)
TUTTI = Permessi(vedere=True, caricare=True, modificare=True)


def ruolo_nel_progetto(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectRole | None:
    """Il ruolo attivo di una persona su un progetto, None se non e' assegnata.

    "Attivo" vuol dire con revoked_at nullo. Una persona ha al massimo un ruolo
    attivo per progetto: e' il vincolo dell'indice unico parziale su
    assignments, ed e' quello che rende questa funzione una domanda con una
    risposta sola.
    """
    return db.scalars(
        select(Assignment.project_role).where(
            Assignment.project_id == project_id,
            Assignment.user_id == user_id,
            Assignment.revoked_at.is_(None),
        )
    ).first()


def permessi(
    db: Session,
    *,
    progetto: Project,
    utente: User,
    classification_id: uuid.UUID,
) -> Permessi:
    """Che cosa questa persona puo' fare sui documenti di quella classe.

    Il creatore puo' tutto: e' lui che apre i progetti, assegna le persone e
    corregge la matrice. Per tutti gli altri la risposta e' la riga della
    matrice all'incrocio fra il loro ruolo nel progetto e la classificazione.
    """
    if utente.is_creatore:
        return TUTTI

    ruolo = ruolo_nel_progetto(db, progetto.id, utente.id)
    if ruolo is None:
        return NESSUNO

    regola = db.scalars(
        select(PermissionRule).where(
            PermissionRule.project_role == ruolo,
            PermissionRule.classification_id == classification_id,
        )
    ).first()

    if regola is None:
        logger.warning(
            "Manca la casella della matrice per (%s, classificazione %s): "
            "il permesso viene negato",
            ruolo.value,
            classification_id,
        )
        return NESSUNO

    return Permessi(
        vedere=regola.can_view,
        caricare=regola.can_upload,
        modificare=regola.can_edit,
    )


def filtro_visibilita(utente: User) -> ColumnElement[bool] | None:
    """La stessa regola di permessi(), scritta come condizione per un elenco.

    Restituisce None per il creatore, che vede tutto e per cui non serve
    nessun filtro. Per tutti gli altri restituisce la condizione

        esiste un'assegnazione non revocata di questa persona sul progetto del
        documento, il cui ruolo ha "can_view" sulla classificazione del
        documento

    scritta come EXISTS, cioe' esattamente la stessa domanda che fa permessi()
    per un documento solo. Che siano la stessa domanda e' il punto: due
    scritture diverse della stessa regola divergono alla prima modifica, e
    l'elenco comincerebbe a mostrare righe che poi la scheda rifiuta di
    aprire.

    Chi la usa la mette in un where() dell'interrogazione dei documenti; non
    serve nessuna join, perche' la condizione se le porta dentro.
    """
    if utente.is_creatore:
        return None

    return exists(
        select(PermissionRule.id)
        .join(
            Assignment,
            and_(
                Assignment.project_role == PermissionRule.project_role,
                Assignment.project_id == Document.project_id,
                Assignment.user_id == utente.id,
                Assignment.revoked_at.is_(None),
            ),
        )
        .where(
            PermissionRule.classification_id == Document.classification_id,
            PermissionRule.can_view.is_(True),
        )
    )


def classificazioni_caricabili(
    db: Session, progetto: Project, utente: User
) -> list[Classification]:
    """Le classificazioni con cui questa persona puo' caricare in un progetto.

    Serve al menu a tendina della pagina di caricamento: proporre una
    classificazione con cui il caricamento verrebbe poi rifiutato e' un modo
    di far perdere tempo a chi ha appena aspettato il caricamento di un file
    da 300 MB.

    Le classificazioni sono quattro righe: si leggono tutte e si filtrano in
    Python. Con quattro valori un'interrogazione piu' furba costerebbe piu' a
    leggerla di quanto faccia risparmiare.
    """
    tutte = list(
        db.scalars(
            select(Classification).order_by(
                Classification.sort_order, Classification.name
            )
        ).all()
    )

    if utente.is_creatore:
        return tutte

    return [
        classificazione
        for classificazione in tutte
        if permessi(
            db,
            progetto=progetto,
            utente=utente,
            classification_id=classificazione.id,
        ).caricare
    ]


def elenco_classificazioni(db: Session) -> list[Classification]:
    """Tutte le classificazioni, nell'ordine in cui vanno mostrate.

    Serve ai filtri degli elenchi, dove non c'e' un progetto solo su cui
    calcolare i permessi: si propongono tutte, e i documenti che la persona
    non puo' vedere non compaiono comunque perche' li toglie
    filtro_visibilita().
    """
    return list(
        db.scalars(
            select(Classification).order_by(
                Classification.sort_order, Classification.name
            )
        ).all()
    )
