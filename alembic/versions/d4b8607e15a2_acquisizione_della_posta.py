"""Acquisizione della posta: motivi ammessi, quarantena, classe Corrispondenza.

La sessione 10 costruisce il motore che legge i messaggi e li attacca alla
versione di prodotto giusta. Le due tabelle della posta - `email_messages` e
`email_attachments` - ci sono dalla sessione 2 e non cambiano forma; questa
migrazione aggiunge le tre cose che il motore ha scoperto di volere.

**Una tabella nuova, `email_reasons`.** Sono i motivi ammessi nella terza
parentesi dell'oggetto (`[RMS1100-24-110SW][V2][SPECS]`). La sessione chiede
che l'elenco sia modificabile dall'interfaccia, quindi e' una tabella e non un
elenco scritto nel programma: e' la stessa scelta delle fasi (D-055) applicata
a un elenco piu' piccolo. Le otto voci di partenza le inserisce questa
migrazione, cosi' che il motore funzioni dal primo avvio.

**Due colonne su `email_messages`.** `quarantine_reason` dice in italiano
perche' un messaggio non e' stato attribuito - chi apre la quarantena deve
decidere, e "nessun codice nell'oggetto" e "la versione V7 non esiste" sono due
decisioni diverse. `source_reference` dice da quale file e' arrivato, cosi' chi
indaga lo ritrova nella cartella `elaborate/`. Tutte e due nascono nulle: i
messaggi archiviati prima non ne avevano una.

**La classificazione "Corrispondenza" e le sue tre caselle della matrice.** La
sessione stabilisce che la posta si vede secondo le regole di permesso gia'
esistenti, trattata come una classificazione sua (D-069). Senza la riga e senza
le caselle, la regola direbbe "no" a tutti tranne al creatore e la sezione
sembrerebbe rotta: la classificazione va creata insieme al codice che la usa,
non lasciata da inserire a mano. L'inserimento e' idempotente e ricalca quello
di `scripts/seed.py`, che fa la stessa cosa per le installazioni nuove.

Revision ID: d4b8607e15a2
Revises: e2f5a91c73d8
Create Date: 26 agosto 2026
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4b8607e15a2"
down_revision: Union[str, Sequence[str], None] = "e2f5a91c73d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# I motivi di partenza, quelli che l'azienda ha indicato all'inizio della
# sessione 10. Da qui in avanti si amministrano da `/posta/motivi`: questo
# elenco e' il punto di partenza, non la fonte della verita'.
MOTIVI_INIZIALI: tuple[tuple[str, str], ...] = (
    ("SPECS", "Specifiche tecniche: requisiti, chiarimenti, revisioni."),
    ("RFQ", "Richiesta di offerta ricevuta dal cliente."),
    ("QUOTE", "Offerta mandata al cliente e trattativa che ne segue."),
    ("DESIGN", "Progettazione: scelte, schemi, revisioni del disegno."),
    ("TEST", "Prove e collaudi: piani, esiti, non conformita'."),
    ("CHANGE", "Richieste di modifica a qualcosa gia' concordato."),
    ("DELIVERY", "Consegne, spedizioni, tempi."),
    ("ADMIN", "Amministrazione: ordini, fatture, contratti."),
)

# La classificazione della posta e il posto che occupa nell'elenco. Il numero
# e' 5 perche' le quattro di scripts/seed.py sono 1, 2, 3 e 4.
CLASSE_POSTA = "Corrispondenza"
CLASSE_POSTA_DESCRIZIONE = (
    "I messaggi di posta archiviati da Aurora e i loro allegati."
)
CLASSE_POSTA_ORDINE = 5

# Le caselle di partenza della matrice per la corrispondenza, una per ruolo:
# (vedere, caricare, modificare).
#
# Il project manager puo' tutto, come su ogni altra classificazione dei suoi
# progetti. L'ingegnere legge la posta del prodotto su cui lavora e ne puo'
# correggere l'attribuzione, perche' e' lui che si accorge quando un messaggio
# e' finito sulla versione sbagliata. Il lettore legge e basta.
#
# "caricare" resta falso per tutti tranne il project manager e non e' una
# dimenticanza: in Aurora i messaggi non si caricano a mano, arrivano dalla
# casella. La casella c'e' lo stesso perche' la matrice ha tre colonne per
# tutte le classificazioni, e una casella che manca a distanza di mesi non si
# distingue da una dimenticanza.
CASELLE_INIZIALI: tuple[tuple[str, bool, bool, bool], ...] = (
    ("project_manager", True, True, True),
    ("ingegnere", True, False, True),
    ("lettore", True, False, False),
)


def upgrade() -> None:
    """Crea email_reasons, le due colonne e la classificazione della posta."""
    op.create_table(
        "email_reasons",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
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
        sa.UniqueConstraint("code", name="uq_email_reasons_code"),
    )

    # I motivi di partenza. gen_random_uuid() e' in PostgreSQL dalla 13 e non
    # chiede nessuna estensione: qui serve perche' la chiave primaria la
    # genera di norma Python, che in una migrazione non c'e'.
    for posizione, (codice, descrizione) in enumerate(MOTIVI_INIZIALI, start=1):
        op.execute(
            sa.text(
                "insert into email_reasons "
                "  (id, code, description, sort_order, is_active) "
                "values (gen_random_uuid(), :codice, :descrizione, :ordine, true) "
                "on conflict (code) do nothing"
            ).bindparams(codice=codice, descrizione=descrizione, ordine=posizione)
        )

    op.add_column(
        "email_messages",
        sa.Column("quarantine_reason", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("source_reference", sa.String(length=400), nullable=True),
    )

    _crea_classificazione_corrispondenza()


def _crea_classificazione_corrispondenza() -> None:
    """Inserisce la classificazione della posta e le sue tre caselle.

    E' idempotente due volte: la classificazione si inserisce solo se non c'e'
    gia' con quel nome, e ogni casella solo se non esiste gia' la coppia
    (ruolo, classificazione). Chi avesse gia' creato "Corrispondenza" a mano
    dalla pagina delle classificazioni ritrova le sue caselle come le aveva
    lasciate: questa migrazione non sovrascrive una scelta di nessuno.
    """
    connessione = op.get_bind()

    connessione.execute(
        sa.text(
            "insert into classifications "
            "  (id, name, description, sort_order, is_active) "
            "select gen_random_uuid(), :nome, :descrizione, :ordine, true "
            "where not exists (select 1 from classifications where name = :nome)"
        ).bindparams(
            nome=CLASSE_POSTA,
            descrizione=CLASSE_POSTA_DESCRIZIONE,
            ordine=CLASSE_POSTA_ORDINE,
        )
    )

    for ruolo, vedere, caricare, modificare in CASELLE_INIZIALI:
        connessione.execute(
            sa.text(
                "insert into permission_rules "
                "  (id, project_role, classification_id, "
                "   can_view, can_upload, can_edit) "
                "select gen_random_uuid(), cast(:ruolo as project_role), c.id, "
                "       :vedere, :caricare, :modificare "
                "  from classifications c "
                " where c.name = :nome "
                "   and not exists ("
                "         select 1 from permission_rules r "
                "          where r.classification_id = c.id "
                "            and r.project_role = cast(:ruolo as project_role))"
            ).bindparams(
                ruolo=ruolo,
                nome=CLASSE_POSTA,
                vedere=vedere,
                caricare=caricare,
                modificare=modificare,
            )
        )


def downgrade() -> None:
    """Toglie la tabella e le due colonne. La classificazione resta.

    **La classificazione "Corrispondenza" e le sue caselle non si tolgono**, e
    va detto perche' non e' una svista. Scendendo di una migrazione si torna
    indietro con il programma, non con i dati: se nel frattempo qualcuno ha
    classificato dei documenti come "Corrispondenza", cancellare la riga li
    lascerebbe senza classificazione, che e' esattamente il guasto che
    l'is_active delle classificazioni esiste per evitare (D-054). Chi scende e
    non la vuole piu' la **disattiva** dalla pagina delle classificazioni,
    come si fa con tutte le altre.

    I motivi scritti in email_reasons invece si perdono, perche' la tabella
    sparisce: e' l'unico dato che questa discesa distrugge, ed e' un elenco di
    otto sigle che la salita successiva rimette com'erano.
    """
    op.drop_column("email_messages", "source_reference")
    op.drop_column("email_messages", "quarantine_reason")
    op.drop_table("email_reasons")
