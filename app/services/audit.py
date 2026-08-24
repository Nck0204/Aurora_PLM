"""Scrittura nel registro delle operazioni (audit trail).

La tabella audit_logs esiste dalla sessione 2; questa e' la funzione che ci
scrive dentro, ed e' l'unica. Il motivo per cui e' una sola sta in
docs/DECISIONI.md, D-018: la colonna entity_id non ha chiave esterna, quindi
l'integrita' del registro non la garantisce il database ma il codice che lo
riempie. Un codice solo si controlla; venti sparsi per il programma no.

Regola 6 di CLAUDE.md: ogni operazione significativa finisce qui, e ogni riga
dice sempre chi, che cosa, su quale oggetto, quando e da quale indirizzo IP.

I nomi delle azioni sono in inglese e in forma "oggetto.verbo", come vuole
docs/MODELLO_DATI.md: sono identificatori, non testo mostrato. Quelli usati
dall'accesso e dalla gestione utenti sono raccolti qui sotto come costanti,
cosi' che una svista di battitura non produca due azioni diverse che sembrano
la stessa.
"""

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

logger = logging.getLogger("aurora.audit")

# --- Azioni registrate da questa sessione ----------------------------------

# Accesso e sessioni
ACTION_LOGIN = "user.login"
ACTION_LOGIN_FAILED = "user.login_failed"
ACTION_LOGIN_BLOCKED = "user.login_blocked"
ACTION_LOGOUT = "user.logout"
ACTION_LOGOUT_ALL = "user.logout_all"
ACTION_REMEMBER_ROTATED = "user.remember_rotated"

# Password
ACTION_PASSWORD_CHANGED = "user.password_changed"
ACTION_PASSWORD_RESET = "user.password_reset"

# Gestione utenti
ACTION_USER_CREATED = "user.created"
ACTION_USER_DEACTIVATED = "user.deactivated"
ACTION_USER_REACTIVATED = "user.reactivated"

# Nome della tabella a cui si riferiscono tutte le azioni qui sopra.
ENTITY_USERS = "users"


def client_ip(request: Request | None) -> str | None:
    """Estrae l'indirizzo IP di chi ha fatto la richiesta.

    Restituisce None quando l'indirizzo non e' disponibile: succede nei test,
    dove non c'e' nessuna connessione di rete vera.

    Attenzione per la sessione 13: se un giorno Aurora verra' messa dietro a
    un proxy inverso (IIS, nginx), qui arrivera' l'indirizzo del proxy e non
    quello dell'utente. In quel caso andra' letta l'intestazione
    X-Forwarded-For, ma **solo** fidandosi del proxy, altrimenti chiunque
    potrebbe scrivere nel registro l'indirizzo che preferisce.
    """
    if request is None or request.client is None:
        return None
    return request.client.host


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    request: Request | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> AuditLog:
    """Aggiunge una riga al registro delle operazioni.

    La riga viene solo aggiunta alla sessione del database: **non** viene
    scritta subito. Il commit lo fa chi sta gestendo la richiesta, insieme
    all'operazione che la riga descrive. Cosi' o si scrivono tutte e due o non
    se ne scrive nessuna, e non capita mai di leggere nel registro un fatto
    che poi non e' avvenuto.

    Gli argomenti dopo "db" si passano per nome (e' quello che impone
    l'asterisco): sono otto, tutti dello stesso tipo, e passarli per posizione
    sarebbe un invito a scambiarne due.

    In old_value e new_value vanno **solo i campi cambiati**, mai la riga
    intera, e mai niente che riguardi le password: nemmeno l'impronta.
    """
    riga = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        ip=client_ip(request),
        old_value=old_value,
        new_value=new_value,
    )
    db.add(riga)

    # Una copia nel registro su file: quando si indaga su un problema si
    # guarda logs/aurora.log, e avere le due tracce affiancate nel tempo fa
    # risparmiare mezz'ora.
    logger.info(
        "audit %s su %s/%s da utente=%s ip=%s",
        action,
        entity_type,
        entity_id,
        user_id,
        riga.ip,
    )

    return riga
