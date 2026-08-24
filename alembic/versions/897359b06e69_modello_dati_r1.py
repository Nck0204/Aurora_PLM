"""Modello dati del rilascio R1: le diciannove tabelle di partenza.

Crea da zero l'intero schema di Aurora: persone e accessi, anagrafiche,
prodotti e loro versioni, progetti e assegnazioni, permessi, documenti e
versioni dei documenti, modelli di fasi e passaggi di fase, posta archiviata,
registro delle operazioni.

E' stata generata con "alembic revision --autogenerate" e poi corretta a mano
in due punti, entrambi segnalati sotto da un commento in maiuscolo:

  - i tipi enumerati vengono creati esplicitamente all'inizio, perche'
    "project_role" e' usato da due tabelle e l'autogenerazione proverebbe a
    crearlo due volte;
  - la discesa cancella anche i tipi enumerati, che DROP TABLE si lascia
    dietro.

Revision ID: 897359b06e69
Revises: (nessuna, e' la prima)
Create Date: 24 agosto 2026
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# I tipi enumerati dello schema, elencati una volta sola e riusati due volte:
# in salita per crearli, in discesa per cancellarli. I valori sono quelli di
# app/models/enums.py; se cambiano li', si scrive una migrazione nuova, non si
# modifica questa.
ENUM_TYPES = {
    "global_role": ("creatore", "utente"),
    "session_kind": ("sessione", "ricordami"),
    "lifecycle_state": (
        "in_sviluppo",
        "rilasciato",
        "in_produzione",
        "superato",
        "obsoleto",
    ),
    "project_role": ("project_manager", "ingegnere", "lettore"),
    "document_state": ("bozza", "in_verifica", "rilasciato", "superato"),
    "email_assignment_state": ("automatica", "manuale", "quarantena"),
}

# revision identifiers, used by Alembic.
revision: str = '897359b06e69'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea i tipi enumerati e le diciannove tabelle."""
    # CORREZIONE A MANO. I tipi enumerati si creano qui, uno per uno, prima
    # delle tabelle che li usano. Le colonne piu' sotto li dichiarano con
    # create_type=False, cioe' "questo tipo esiste gia', non ricrearlo":
    # "project_role" e' usato sia da permission_rules sia da assignments e
    # senza questa accortezza PostgreSQL rifiuterebbe la seconda creazione.
    bind = op.get_bind()
    for type_name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=type_name).create(bind)

    # ### comandi generati da Alembic ###
    op.create_table('classifications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('customers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_login_attempts_ip_created', 'login_attempts', ['ip', 'created_at'], unique=False)
    op.create_index('ix_login_attempts_username_created', 'login_attempts', ['username', 'created_at'], unique=False)
    op.create_table('phase_templates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('standards', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'version', name='uq_phase_templates_name_version')
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('first_name', sa.String(length=80), nullable=False),
    sa.Column('last_name', sa.String(length=80), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('global_role', postgresql.ENUM('creatore', 'utente', name='global_role', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('entity_type', sa.String(length=60), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_occurred_at'), 'audit_logs', ['occurred_at'], unique=False)
    op.create_index('ix_audit_logs_user_occurred', 'audit_logs', ['user_id', 'occurred_at'], unique=False)
    op.create_table('contacts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('role', sa.String(length=120), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contacts_customer_id'), 'contacts', ['customer_id'], unique=False)
    op.create_index(op.f('ix_contacts_email'), 'contacts', ['email'], unique=False)
    op.create_table('permission_rules',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_role', postgresql.ENUM('project_manager', 'ingegnere', 'lettore', name='project_role', create_type=False), nullable=False),
    sa.Column('classification_id', sa.UUID(), nullable=False),
    sa.Column('can_view', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('can_upload', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('can_edit', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['classification_id'], ['classifications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_role', 'classification_id', name='uq_permission_rules_role_classification')
    )
    op.create_index(op.f('ix_permission_rules_classification_id'), 'permission_rules', ['classification_id'], unique=False)
    op.create_table('phases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('phase_template_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['phase_template_id'], ['phase_templates.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phase_template_id', 'name', name='uq_phases_template_name'),
    sa.UniqueConstraint('phase_template_id', 'sort_order', name='uq_phases_template_order')
    )
    op.create_index(op.f('ix_phases_phase_template_id'), 'phases', ['phase_template_id'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('code_parts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_products_customer_id'), 'products', ['customer_id'], unique=False)
    op.create_table('user_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('kind', postgresql.ENUM('sessione', 'ricordami', name='session_kind', create_type=False), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_user_sessions_expires_at'), 'user_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_table('product_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('lifecycle_state', postgresql.ENUM('in_sviluppo', 'rilasciato', 'in_produzione', 'superato', 'obsoleto', name='lifecycle_state', create_type=False), nullable=False),
    sa.Column('derived_from_id', sa.UUID(), nullable=True),
    sa.Column('derivation_reason', sa.Text(), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['derived_from_id'], ['product_versions.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'version_number', name='uq_product_versions_product_number')
    )
    op.create_index(op.f('ix_product_versions_derived_from_id'), 'product_versions', ['derived_from_id'], unique=False)
    op.create_index(op.f('ix_product_versions_lifecycle_state'), 'product_versions', ['lifecycle_state'], unique=False)
    op.create_index(op.f('ix_product_versions_product_id'), 'product_versions', ['product_id'], unique=False)
    op.create_table('email_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=True),
    sa.Column('internet_message_id', sa.String(length=998), nullable=False),
    sa.Column('in_reply_to', sa.String(length=998), nullable=True),
    sa.Column('thread_references', sa.Text(), nullable=True),
    sa.Column('sender', sa.String(length=320), nullable=False),
    sa.Column('recipients', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('subject_parsed', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('storage_hash', sa.String(length=64), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=True),
    sa.Column('assignment_state', postgresql.ENUM('automatica', 'manuale', 'quarantena', name='email_assignment_state', create_type=False), nullable=False),
    sa.Column('assigned_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('internet_message_id')
    )
    op.create_index(op.f('ix_email_messages_assignment_state'), 'email_messages', ['assignment_state'], unique=False)
    op.create_index(op.f('ix_email_messages_product_version_id'), 'email_messages', ['product_version_id'], unique=False)
    op.create_index(op.f('ix_email_messages_received_at'), 'email_messages', ['received_at'], unique=False)
    op.create_index(op.f('ix_email_messages_sender'), 'email_messages', ['sender'], unique=False)
    op.create_index(op.f('ix_email_messages_sent_at'), 'email_messages', ['sent_at'], unique=False)
    op.create_index(op.f('ix_email_messages_storage_hash'), 'email_messages', ['storage_hash'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=False),
    sa.Column('project_manager_id', sa.UUID(), nullable=False),
    sa.Column('phase_template_id', sa.UUID(), nullable=False),
    sa.Column('current_phase_id', sa.UUID(), nullable=True),
    sa.Column('standards', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_phase_id'], ['phases.id'], ),
    sa.ForeignKeyConstraint(['phase_template_id'], ['phase_templates.id'], ),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ),
    sa.ForeignKeyConstraint(['project_manager_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_version_id')
    )
    op.create_index(op.f('ix_projects_current_phase_id'), 'projects', ['current_phase_id'], unique=False)
    op.create_index(op.f('ix_projects_phase_template_id'), 'projects', ['phase_template_id'], unique=False)
    op.create_index(op.f('ix_projects_project_manager_id'), 'projects', ['project_manager_id'], unique=False)
    op.create_table('assignments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('project_role', postgresql.ENUM('project_manager', 'ingegnere', 'lettore', name='project_role', create_type=False), nullable=False),
    sa.Column('assigned_by_id', sa.UUID(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['revoked_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assignments_project_id'), 'assignments', ['project_id'], unique=False)
    op.create_index(op.f('ix_assignments_user_id'), 'assignments', ['user_id'], unique=False)
    op.create_index('uq_assignments_active_user_per_project', 'assignments', ['project_id', 'user_id'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('doc_type', sa.String(length=80), nullable=False),
    sa.Column('classification_id', sa.UUID(), nullable=False),
    sa.Column('state', postgresql.ENUM('bozza', 'in_verifica', 'rilasciato', 'superato', name='document_state', create_type=False), nullable=False),
    sa.Column('checked_out_by_id', sa.UUID(), nullable=True),
    sa.Column('checked_out_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['checked_out_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['classification_id'], ['classifications.id'], ),
    sa.ForeignKeyConstraint(['deleted_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_classification_id'), 'documents', ['classification_id'], unique=False)
    op.create_index(op.f('ix_documents_deleted_at'), 'documents', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_documents_project_id'), 'documents', ['project_id'], unique=False)
    op.create_index(op.f('ix_documents_state'), 'documents', ['state'], unique=False)
    op.create_table('email_attachments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email_message_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('storage_hash', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('mime_type', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['email_message_id'], ['email_messages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_attachments_email_message_id'), 'email_attachments', ['email_message_id'], unique=False)
    op.create_index(op.f('ix_email_attachments_storage_hash'), 'email_attachments', ['storage_hash'], unique=False)
    op.create_table('phase_transitions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('from_phase_id', sa.UUID(), nullable=True),
    sa.Column('to_phase_id', sa.UUID(), nullable=False),
    sa.Column('requested_by_id', sa.UUID(), nullable=False),
    sa.Column('approved_by_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['from_phase_id'], ['phases.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['to_phase_id'], ['phases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_phase_transitions_project_id'), 'phase_transitions', ['project_id'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('storage_hash', sa.String(length=64), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('mime_type', sa.String(length=120), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version_number', name='uq_document_versions_doc_number')
    )
    op.create_index(op.f('ix_document_versions_author_id'), 'document_versions', ['author_id'], unique=False)
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_versions_storage_hash'), 'document_versions', ['storage_hash'], unique=False)
    # ### fine dei comandi generati da Alembic ###


def downgrade() -> None:
    """Cancella le tabelle e poi i tipi enumerati, in ordine inverso."""
    # ### comandi generati da Alembic ###
    op.drop_index(op.f('ix_document_versions_storage_hash'), table_name='document_versions')
    op.drop_index(op.f('ix_document_versions_document_id'), table_name='document_versions')
    op.drop_index(op.f('ix_document_versions_author_id'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index(op.f('ix_phase_transitions_project_id'), table_name='phase_transitions')
    op.drop_table('phase_transitions')
    op.drop_index(op.f('ix_email_attachments_storage_hash'), table_name='email_attachments')
    op.drop_index(op.f('ix_email_attachments_email_message_id'), table_name='email_attachments')
    op.drop_table('email_attachments')
    op.drop_index(op.f('ix_documents_state'), table_name='documents')
    op.drop_index(op.f('ix_documents_project_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_deleted_at'), table_name='documents')
    op.drop_index(op.f('ix_documents_classification_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index('uq_assignments_active_user_per_project', table_name='assignments', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_assignments_user_id'), table_name='assignments')
    op.drop_index(op.f('ix_assignments_project_id'), table_name='assignments')
    op.drop_table('assignments')
    op.drop_index(op.f('ix_projects_project_manager_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_phase_template_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_current_phase_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_email_messages_storage_hash'), table_name='email_messages')
    op.drop_index(op.f('ix_email_messages_sent_at'), table_name='email_messages')
    op.drop_index(op.f('ix_email_messages_sender'), table_name='email_messages')
    op.drop_index(op.f('ix_email_messages_received_at'), table_name='email_messages')
    op.drop_index(op.f('ix_email_messages_product_version_id'), table_name='email_messages')
    op.drop_index(op.f('ix_email_messages_assignment_state'), table_name='email_messages')
    op.drop_table('email_messages')
    op.drop_index(op.f('ix_product_versions_product_id'), table_name='product_versions')
    op.drop_index(op.f('ix_product_versions_lifecycle_state'), table_name='product_versions')
    op.drop_index(op.f('ix_product_versions_derived_from_id'), table_name='product_versions')
    op.drop_table('product_versions')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_expires_at'), table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_index(op.f('ix_products_customer_id'), table_name='products')
    op.drop_table('products')
    op.drop_index(op.f('ix_phases_phase_template_id'), table_name='phases')
    op.drop_table('phases')
    op.drop_index(op.f('ix_permission_rules_classification_id'), table_name='permission_rules')
    op.drop_table('permission_rules')
    op.drop_index(op.f('ix_contacts_email'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_customer_id'), table_name='contacts')
    op.drop_table('contacts')
    op.drop_index('ix_audit_logs_user_occurred', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_occurred_at'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('phase_templates')
    op.drop_index('ix_login_attempts_username_created', table_name='login_attempts')
    op.drop_index('ix_login_attempts_ip_created', table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_table('customers')
    op.drop_table('classifications')
    # ### fine dei comandi generati da Alembic ###

    # CORREZIONE A MANO. DROP TABLE non cancella i tipi enumerati: senza queste
    # righe resterebbero nel database e un "alembic upgrade head" successivo
    # fallirebbe dicendo che il tipo esiste gia'.
    bind = op.get_bind()
    for type_name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=type_name).drop(bind)
