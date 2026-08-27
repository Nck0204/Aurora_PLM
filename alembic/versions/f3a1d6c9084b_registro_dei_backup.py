"""Il registro delle copie di sicurezza: una tabella, "backups".

La sessione 12 chiede che la diagnostica sappia rispondere alla domanda
"l'ultima copia di sicurezza e' andata bene, e quando?". La risposta deve
esistere anche quando il programma non gira - la copia la fa uno script di
notte, con Aurora spenta o accesa che sia - e deve poter essere letta in un
colpo solo da una pagina web.

Una tabella, quindi, e non un file di testo da rileggere e interpretare a ogni
caricamento di pagina.

**Non tocca nessuna tabella esistente.** Non c'e' nessuna colonna aggiunta e
nessun dato riscritto: questa migrazione crea una tabella nuova e vuota, e si
puo' applicare con le credenziali di sempre (`aurora_app`). Le migrazioni che
toccano `audit_logs` vanno fatte come `postgres` per via
dell'irrobustimento della sessione 9; questa no.

Revision ID: f3a1d6c9084b
Revises: d4b8607e15a2
Create Date: 27 agosto 2026
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUuid

# revision identifiers, used by Alembic.
revision: str = "f3a1d6c9084b"
down_revision: Union[str, Sequence[str], None] = "d4b8607e15a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabella "backups"."""
    op.create_table(
        "backups",
        sa.Column("id", PgUuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # Testo e non tipo enumerato: e' l'esito di una procedura di
        # manutenzione, non uno stato del lavoro dell'azienda, e chi indaga su
        # un guasto deve poterlo leggere con un SELECT scritto a mano senza
        # prima scoprire come si chiama il tipo.
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("destination", sa.String(length=500), nullable=False),
        sa.Column(
            "database_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("files_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("hostname", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # I due indici servono alla stessa interrogazione, che e' l'unica che
    # questa tabella riceve spesso: "l'ultima copia riuscita".
    op.create_index("ix_backups_started_at", "backups", ["started_at"])
    op.create_index("ix_backups_outcome", "backups", ["outcome"])


def downgrade() -> None:
    """Toglie la tabella.

    Qui il DROP e' lecito e non contraddice la regola 5 di CLAUDE.md: quella
    vieta di cancellare **dati aziendali**, e il registro delle copie di
    sicurezza e' un dato di manutenzione che si ricostruisce alla copia
    successiva. Tornare indietro di questa migrazione vuol dire che la
    sessione 12 non c'e' mai stata.
    """
    op.drop_index("ix_backups_outcome", table_name="backups")
    op.drop_index("ix_backups_started_at", table_name="backups")
    op.drop_table("backups")
