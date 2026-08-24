"""Pezzi comuni a tutte le tabelle di Aurora.

Qui non c'e' nessuna tabella: ci sono i tre mattoni che ogni tabella riusa,
tenuti in un posto solo perche' scriverli venti volte significa prima o poi
scriverli venti volte in modo leggermente diverso.

  UuidPrimaryKeyMixin   la chiave primaria: un UUID generato da Python.
  TimestampMixin        le due date "creata il" e "modificata il".
  pg_enum()             la funzione che trasforma un elenco Python in un tipo
                        enumerato di PostgreSQL.

Perche' la chiave primaria e' un UUID e non un numero progressivo, e perche'
i codici parlanti (codice prodotto, nome utente) non sono mai chiavi esterne:
vedi docs/DECISIONI.md, decisione D-013.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SqlEnum, func
from sqlalchemy.dialects.postgresql import UUID as PgUuid
from sqlalchemy.orm import Mapped, mapped_column

# Lunghezza di un'impronta SHA-256 scritta in esadecimale: 32 byte, due
# caratteri per byte. Vale sia per le impronte dei file (D-004) sia per quelle
# dei gettoni di sessione.
SHA256_HEX_LENGTH = 64

# Lunghezza massima di un indirizzo IP scritto in forma testuale. Sono 45
# caratteri nel caso peggiore: un IPv6 che incapsula un IPv4, per esempio
# "0000:0000:0000:0000:0000:ffff:192.168.100.228".
IP_ADDRESS_LENGTH = 45


class UuidPrimaryKeyMixin:
    """Aggiunge alla tabella la colonna "id", chiave primaria di tipo UUID.

    Il valore lo genera Python (uuid4) e non il database. Costa un'inezia in
    piu' ed e' molto piu' comodo: l'oggetto ha gia' il suo identificatore
    appena viene costruito, quindi si possono collegare fra loro righe nuove
    prima ancora di scriverle sul database.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        # Le colonne che arrivano da un mixin finirebbero in coda alla tabella.
        # sort_order negativo le porta davanti: chi apre la tabella con psql o
        # con pgAdmin si aspetta di trovare "id" come prima colonna.
        sort_order=-100,
    )


class TimestampMixin:
    """Aggiunge alla tabella le colonne "created_at" e "updated_at".

    Entrambe con fuso orario, come vuole CLAUDE.md: un'ora senza fuso e'
    un'ora che fra sei mesi nessuno sa piu' leggere.

    Il valore iniziale lo mette il database (server_default=now()), cosi' e'
    corretto anche per le righe inserite da uno script o da una migrazione.
    L'aggiornamento di "updated_at" lo fa invece SQLAlchemy a ogni UPDATE che
    passa dai modelli: un UPDATE scritto a mano in psql non lo aggiorna, ed e'
    bene saperlo prima di fidarsene.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        # sort_order positivo: queste due vanno in fondo alla tabella, dopo le
        # colonne che dicono qualcosa sul contenuto.
        sort_order=100,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=101,
    )


def pg_enum(python_enum: type, type_name: str) -> SqlEnum:
    """Trasforma un elenco Python in un tipo enumerato di PostgreSQL.

    Esiste per una ragione precisa: senza "values_callable" SQLAlchemy userebbe
    come etichette del tipo PostgreSQL i **nomi** dei membri (IN_SVILUPPO), non
    i loro **valori** (in_sviluppo). Nel database finirebbero parole in
    maiuscolo che non corrispondono a quello che il programma scrive e legge.

    Argomenti:
        python_enum: la classe definita in app/models/enums.py.
        type_name:   il nome del tipo dentro PostgreSQL, in inglese e al
                     singolare (esempio: "lifecycle_state").
    """
    return SqlEnum(
        python_enum,
        name=type_name,
        native_enum=True,
        values_callable=lambda enum_class: [member.value for member in enum_class],
    )
