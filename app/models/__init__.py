"""Modelli dei dati, cioe' le tabelle del database.

Al momento vuoto: nessuna tabella e' ancora stata definita.

Quando nelle prossime sessioni verranno aggiunti dei modelli, ogni file dovra'
essere importato qui sotto. Il motivo e' che Alembic, per generare le
migrazioni, legge Base.metadata: una classe che nessuno importa non risulta
registrata in Base.metadata e Alembic la ignorerebbe in silenzio.

Esempio di come sara':

    from app.models.user import User          # noqa: F401
    from app.models.project import Project    # noqa: F401
"""
