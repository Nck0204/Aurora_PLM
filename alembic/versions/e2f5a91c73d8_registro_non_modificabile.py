"""Il registro diventa consultabile e verificabile: quattro colonne su audit_logs.

La sessione 9 chiede tre cose al registro delle operazioni, e tutte e tre si
appoggiano a colonne che prima non c'erano.

  seq             il posto della voce nella catena, contato da 1. Serve un
                  ordine totale e certo: due voci scritte nello stesso
                  centesimo di secondo hanno lo stesso "occurred_at", e la
                  catena non saprebbe quale viene prima.

  description     che cosa e' successo, in italiano e per esteso. E' una
                  colonna e non una funzione di visualizzazione apposta: la
                  frase viene fissata quando il fatto accade, e resta quella
                  anche se domani l'oggetto cambia nome.

  previous_hash   l'impronta della voce precedente e quella di questa voce.
  entry_hash      Insieme fanno la catena che rende visibile una manomissione
                  fatta scavalcando il programma (D-063).

**Le righe che ci sono gia' vengono riempite, non buttate.** Il database di
sviluppo ha novantasei voci scritte dalle sessioni da 3 a 8: la descrizione
gliela si compone con lo stesso catalogo che usa il programma, e la catena si
costruisce nell'ordine in cui i fatti sono avvenuti. Da quel momento in poi
quelle righe sono verificabili come tutte le altre.

L'ordine con cui si numerano le voci gia' presenti e' (occurred_at,
created_at, id): le prime due sono i due istanti che la riga conosce, la terza
e' li' solo perche' due righe con gli stessi due istanti devono comunque
avere un ordine, e un ordine qualunque ma **stabile** e' meglio di nessuno.

Revision ID: e2f5a91c73d8
Revises: c7a3f19b52e4
Create Date: 26 agosto 2026
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e2f5a91c73d8"
down_revision: Union[str, Sequence[str], None] = "c7a3f19b52e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aggiunge le quattro colonne, riempie le righe esistenti, mette i vincoli.

    Il giro e' in tre tempi perche' le colonne sono NOT NULL e la tabella e'
    piena: prima si aggiungono ammettendo il nullo, poi si riempiono, poi si
    stringono. Farlo in un colpo solo con un server_default vorrebbe dire
    scrivere in tutte le righe lo stesso valore, e per un'impronta lo stesso
    valore non ha nessun senso.
    """
    # --- 1. Le colonne, per ora tolleranti -----------------------------
    op.add_column("audit_logs", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "audit_logs", sa.Column("previous_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "audit_logs", sa.Column("entry_hash", sa.String(length=64), nullable=True)
    )

    # --- 2. Le righe che ci sono gia' -----------------------------------
    _riempi_le_righe_esistenti()

    # --- 3. I vincoli ---------------------------------------------------
    op.alter_column("audit_logs", "seq", nullable=False)
    op.alter_column("audit_logs", "description", nullable=False)
    op.alter_column("audit_logs", "previous_hash", nullable=False)
    op.alter_column("audit_logs", "entry_hash", nullable=False)

    # L'unicita' del numero di sequenza e' quella che dice "la catena non si
    # e' biforcata". Il programma serializza gia' l'assegnazione con un
    # lucchetto (app/services/audit.py), ma un vincolo che il database fa
    # rispettare vale piu' di un lucchetto che il programma ricorda di
    # prendere.
    op.create_unique_constraint("uq_audit_logs_seq", "audit_logs", ["seq"])
    op.create_unique_constraint(
        "uq_audit_logs_entry_hash", "audit_logs", ["entry_hash"]
    )

    # Il terzo indice del registro: "tutto quello che e' successo di questo
    # tipo, in ordine di tempo". Lo usa il filtro per tipo di azione della
    # pagina /registro.
    op.create_index(
        "ix_audit_logs_action_occurred", "audit_logs", ["action", "occurred_at"]
    )


def _riempi_le_righe_esistenti() -> None:
    """Compone descrizione e catena per le voci scritte prima di oggi.

    La descrizione si compone con audit.descrizione_predefinita(), cioe' con
    lo stesso catalogo che usa il programma: una migrazione che se ne
    inventasse un altro produrrebbe righe vecchie scritte in un italiano
    diverso da quello delle righe nuove.

    L'etichetta dell'oggetto non c'e' e non si puo' ricostruire - quelle
    voci sono state scritte prima che esistesse - quindi le descrizioni delle
    righe storiche dicono l'azione e i valori cambiati, senza il nome
    dell'oggetto. E' il massimo che si puo' dire onestamente.
    """
    from app.services import audit

    connessione = op.get_bind()

    righe = connessione.execute(
        sa.text(
            """
            SELECT id, occurred_at, user_id, action, entity_type, entity_id,
                   old_value, new_value, ip
              FROM audit_logs
             ORDER BY occurred_at, created_at, id
            """
        )
    ).all()

    precedente = audit.IMPRONTA_ZERO

    for numero, riga in enumerate(righe, start=1):
        descrizione = audit.descrizione_predefinita(
            riga.action,
            etichetta=None,
            old_value=riga.old_value,
            new_value=riga.new_value,
        )
        impronta = audit.impronta(
            seq=numero,
            occurred_at=riga.occurred_at,
            user_id=riga.user_id,
            action=riga.action,
            entity_type=riga.entity_type,
            entity_id=riga.entity_id,
            old_value=riga.old_value,
            new_value=riga.new_value,
            ip=riga.ip,
            description=descrizione,
            previous_hash=precedente,
        )

        connessione.execute(
            sa.text(
                """
                UPDATE audit_logs
                   SET seq = :seq,
                       description = :description,
                       previous_hash = :previous_hash,
                       entry_hash = :entry_hash
                 WHERE id = :id
                """
            ),
            {
                "seq": numero,
                "description": descrizione,
                "previous_hash": precedente,
                "entry_hash": impronta,
                "id": riga.id,
            },
        )
        precedente = impronta


def downgrade() -> None:
    """Toglie le quattro colonne e i loro vincoli.

    Scendendo si perde la catena, quindi si perde la possibilita' di
    accorgersi di una manomissione avvenuta prima della discesa. Le voci
    restano tutte: nessun dato del registro viene cancellato, come vuole la
    regola 5 di CLAUDE.md.

    **Chi scende deve anche togliere i permessi ristretti** di
    scripts/hardening_db.sql, altrimenti l'ALTER TABLE qui sotto fallisce
    per mancanza di diritti: dopo l'irrobustimento la tabella non appartiene
    piu' all'utente applicativo. La procedura sta in scripts/hardening_db.md.
    """
    op.drop_index("ix_audit_logs_action_occurred", table_name="audit_logs")
    op.drop_constraint("uq_audit_logs_entry_hash", "audit_logs", type_="unique")
    op.drop_constraint("uq_audit_logs_seq", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "entry_hash")
    op.drop_column("audit_logs", "previous_hash")
    op.drop_column("audit_logs", "description")
    op.drop_column("audit_logs", "seq")
