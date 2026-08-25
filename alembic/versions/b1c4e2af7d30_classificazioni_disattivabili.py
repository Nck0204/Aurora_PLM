"""Le classificazioni si disattivano: colonna is_active su classifications.

La sessione 7 aggiunge la pagina che amministra le classificazioni. Fra le
operazioni che deve saper fare c'e' togliere dai menu una classe che non serve
piu', e in Aurora "togliere" non vuol mai dire cancellare (regola 5 di
CLAUDE.md): vuol dire mettere a falso una colonna di disattivazione, come
hanno gia' users, customers, products e phase_templates.

La colonna nasce a **vero** per tutte le righe esistenti: le quattro
classificazioni messe da scripts/seed.py restano attive esattamente come
prima, e nessun documento cambia comportamento.

Non c'e' nessun'altra modifica allo schema: la matrice dei permessi, che
questa sessione rende modificabile dall'interfaccia, c'era gia' tutta dalla
sessione 2.

Revision ID: b1c4e2af7d30
Revises: 897359b06e69
Create Date: 25 agosto 2026
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b1c4e2af7d30"
down_revision: Union[str, Sequence[str], None] = "897359b06e69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aggiunge classifications.is_active, vera per tutte le righe."""
    # server_default="true" fa due lavori insieme: riempie le righe che ci
    # sono gia' - senza, la colonna NOT NULL non si potrebbe aggiungere a una
    # tabella piena - e stabilisce il valore di partenza per quelle future.
    op.add_column(
        "classifications",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Toglie la colonna. Le classificazioni disattivate tornano attive.

    E' l'unica discesa possibile e va detta: scendendo, una classificazione
    che era stata messa da parte ricompare nei menu a tendina. Non si perde
    nessun dato - i documenti e le caselle della matrice non vengono toccati -
    ma chi scende deve sapere che quella scelta non e' scritta da nessun'altra
    parte.
    """
    op.drop_column("classifications", "is_active")
