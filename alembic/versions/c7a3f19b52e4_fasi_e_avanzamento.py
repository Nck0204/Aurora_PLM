"""Le fasi diventano un percorso percorribile: proprieta' e passaggi.

La sessione 8 non aggiunge tabelle: le tabelle delle fasi ci sono dalla
sessione 2. Aggiunge le colonne che servono a **percorrerle**, e sono di due
famiglie.

Sulle fasi, due proprieta' che rendono il percorso un dato invece che un
pezzo di programma (D-055):

  blocks_return    da questa fase non si torna indietro;
  closes_project   entrando in questa fase il progetto si chiude.

Senza di loro, "da Development non si torna indietro" e "Chiuso chiude il
progetto" andrebbero scritti come due `if` sul nome della fase, e da quel
momento rinominare una fase sarebbe una modifica al programma.

Sui passaggi, quello che serve perche' un passaggio possa essere **chiesto**
invece che soltanto fatto:

  state             richiesta / approvata / respinta;
  decided_at        quando la decisione e' stata presa;
  decision_reason   perche' e' stata approvata o respinta;
  seen_at           quando chi ha chiesto ha letto l'esito.

E una colonna cambia nome: `approved_by_id` diventa `decided_by_id`, perche'
adesso ci finisce dentro anche chi **respinge** (D-057). Il rinomino e'
indolore: la tabella e' vuota su tutti i database, il flusso che la riempie
nasce con questa sessione.

Revision ID: c7a3f19b52e4
Revises: b1c4e2af7d30
Create Date: 26 agosto 2026
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7a3f19b52e4"
down_revision: Union[str, Sequence[str], None] = "b1c4e2af7d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Il tipo enumerato nuovo. Si crea e si cancella a mano, come vuole D-019:
# le colonne lo dichiarano con create_type=False, e DROP COLUMN non porta via
# il tipo.
STATO_PASSAGGIO = "phase_transition_state"
VALORI_STATO = ("richiesta", "approvata", "respinta")

# Il nome della fase che, fino a ieri, la sessione descriveva a parole come
# quella da cui non si torna indietro. Compare qui e in nessun altro posto del
# programma: questa e' una migrazione di **dati**, che traduce in una spunta
# una regola che prima non era scritta da nessuna parte. Da domani la spunta
# la mette chi crea il modello di fasi, e il programma non sa piu' come si
# chiami la fase che blocca.
FASE_SENZA_RITORNO = "Development"


def upgrade() -> None:
    """Aggiunge le due spunte alle fasi e le quattro colonne ai passaggi."""
    bind = op.get_bind()
    postgresql.ENUM(*VALORI_STATO, name=STATO_PASSAGGIO).create(bind)

    # --- Le proprieta' delle fasi -----------------------------------------
    # Nascono tutte e due a falso: un percorso senza spunte si attraversa
    # dall'inizio alla fine e non chiude niente, che e' il comportamento piu'
    # prudente possibile.
    op.add_column(
        "phases",
        sa.Column(
            "blocks_return",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "phases",
        sa.Column(
            "closes_project",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # --- I passaggi -------------------------------------------------------
    op.add_column(
        "phase_transitions",
        sa.Column(
            "state",
            postgresql.ENUM(*VALORI_STATO, name=STATO_PASSAGGIO, create_type=False),
            nullable=False,
            server_default="approvata",
        ),
    )
    op.create_index(
        "ix_phase_transitions_state", "phase_transitions", ["state"]
    )

    op.add_column(
        "phase_transitions",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "phase_transitions", sa.Column("decision_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "phase_transitions",
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # "approvato da" diventa "deciso da": ci finisce anche chi respinge.
    op.alter_column(
        "phase_transitions", "approved_by_id", new_column_name="decided_by_id"
    )

    # L'indice su chi ha chiesto serve al cruscotto, che cerca le richieste di
    # una persona per dirle come sono andate a finire.
    op.create_index(
        "ix_phase_transitions_requested_by_id",
        "phase_transitions",
        ["requested_by_id"],
    )

    # --- I dati che c'erano gia' ------------------------------------------
    # Questa e' l'unica parte della migrazione che tocca delle righe, e vale
    # la pena di dire perche'. Sui database in cui il modello "Standard" e'
    # gia' stato creato da scripts/seed.py, le sue sei fasi non hanno nessuna
    # spunta: senza queste due UPDATE, un progetto non si chiuderebbe piu' e
    # da Development si potrebbe tornare indietro.
    #
    # Il nome della fase compare qui perche' qui si sta scrivendo un dato, non
    # una regola. E' l'unico posto di Aurora in cui succede.
    op.execute(
        sa.text(
            "update phases set blocks_return = true where name = :nome"
        ).bindparams(nome=FASE_SENZA_RITORNO)
    )

    # L'ultima fase di ciascun modello chiude il progetto. Qui non si guarda
    # nessun nome: si guarda l'ordine, che e' il dato che dice qual e' la fine
    # del percorso.
    op.execute(
        """
        update phases
           set closes_project = true
         where (phase_template_id, sort_order) in (
                   select phase_template_id, max(sort_order)
                     from phases
                    group by phase_template_id
               )
        """
    )


def downgrade() -> None:
    """Toglie le colonne e il tipo enumerato.

    Va detto che cosa si perde scendendo: le richieste di passaggio in attesa
    e gli esiti non ancora letti diventano indistinguibili dai passaggi
    avvenuti - tutte le righe di phase_transitions tornano a essere fatti
    compiuti - e le due proprieta' delle fasi spariscono. I passaggi restano,
    i progetti restano: si perde il "come" e non il "che cosa".
    """
    op.drop_index("ix_phase_transitions_requested_by_id", "phase_transitions")
    op.alter_column(
        "phase_transitions", "decided_by_id", new_column_name="approved_by_id"
    )
    op.drop_column("phase_transitions", "seen_at")
    op.drop_column("phase_transitions", "decision_reason")
    op.drop_column("phase_transitions", "decided_at")
    op.drop_index("ix_phase_transitions_state", "phase_transitions")
    op.drop_column("phase_transitions", "state")

    op.drop_column("phases", "closes_project")
    op.drop_column("phases", "blocks_return")

    # DROP COLUMN si lascia dietro il tipo enumerato, che al prossimo upgrade
    # farebbe fallire la creazione con "il tipo esiste gia'" (D-019).
    postgresql.ENUM(name=STATO_PASSAGGIO).drop(op.get_bind())
