"""Modelli dei dati, cioe' le tabelle del database.

**Ogni modello nuovo va importato qui sotto.** Non e' una formalita': Alembic,
per generare le migrazioni, legge Base.metadata, e una classe che nessuno
importa non risulta registrata in Base.metadata. Alembic la ignorerebbe in
silenzio e la tabella non verrebbe mai creata.

Un file per tabella, come dice CLAUDE.md. Le classi sono al singolare
(Product), le tabelle al plurale (products).

Le tabelle del rilascio R1, raggruppate per argomento:

  Persone e accessi     users, user_sessions, login_attempts
  Anagrafiche           customers, contacts
  Prodotti              products, product_versions
  Progetti              projects, assignments
  Permessi              classifications, permission_rules
  Documenti             documents, document_versions
  Fasi                  phase_templates, phases, phase_transitions
  Posta                 email_messages, email_attachments, email_reasons
  Tracciabilita'        audit_logs
  Manutenzione          backups

Le tabelle di distinta base e articoli arriveranno con il rilascio R3.
"""

from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.backup import Backup
from app.models.classification import Classification
from app.models.contact import Contact
from app.models.customer import Customer
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.email_attachment import EmailAttachment
from app.models.email_message import EmailMessage
from app.models.email_reason import EmailReason
from app.models.enums import (
    DocumentState,
    EmailAssignmentState,
    GlobalRole,
    LifecycleState,
    PhaseTransitionState,
    ProjectRole,
    SessionKind,
)
from app.models.login_attempt import LoginAttempt
from app.models.permission_rule import PermissionRule
from app.models.phase import Phase
from app.models.phase_template import PhaseTemplate
from app.models.phase_transition import PhaseTransition
from app.models.product import Product
from app.models.product_version import ProductVersion
from app.models.project import Project
from app.models.user import User
from app.models.user_session import UserSession

# Elenco di quello che questo pacchetto mette a disposizione. Serve anche a
# rendere esplicito agli strumenti di analisi che gli import qui sopra non
# sono inutilizzati: sono importati apposta, per registrarli in Base.metadata.
__all__ = [
    # Elenchi di valori ammessi
    "DocumentState",
    "EmailAssignmentState",
    "GlobalRole",
    "LifecycleState",
    "PhaseTransitionState",
    "ProjectRole",
    "SessionKind",
    # Tabelle
    "Assignment",
    "AuditLog",
    "Backup",
    "Classification",
    "Contact",
    "Customer",
    "Document",
    "DocumentVersion",
    "EmailAttachment",
    "EmailMessage",
    "EmailReason",
    "LoginAttempt",
    "PermissionRule",
    "Phase",
    "PhaseTemplate",
    "PhaseTransition",
    "Product",
    "ProductVersion",
    "Project",
    "User",
    "UserSession",
]
