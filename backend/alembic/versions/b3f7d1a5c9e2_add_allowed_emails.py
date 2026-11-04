"""allowed_emails table and jobs.held_at

Revision ID: b3f7d1a5c9e2
Revises: e4b8d2f6a1c3
Create Date: 2026-11-02 12:00:00.000000

v69: the login allowlist moves from the `ALLOWED_EMAILS` env list into a table the admin
manages in `/users`, and a removed user's unstarted jobs are held (`jobs.held_at`).

**Only adds data, never rewrites or deletes any.** The data step imports today's
`ALLOWED_EMAILS` plus `ADMIN_EMAIL`, normalized (trimmed, lowercased), with
`ON CONFLICT DO NOTHING`: running it again (or over rows the admin already added) changes
nothing. Every existing job gets `held_at = NULL`. A `pg_backup` before the production deploy is
still the rule (master v4).

`downgrade()` drops the table and the column; the env list still exists then, so the login
check falls back to it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3f7d1a5c9e2'
down_revision: Union[str, Sequence[str], None] = 'e4b8d2f6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _imported_addresses() -> list[str]:
    """`ALLOWED_EMAILS` ∪ {`ADMIN_EMAIL`}, normalized as the app normalizes a login's address,
    blanks dropped, in a stable order."""
    from app.config import get_settings
    from app.services.users import normalize_email

    settings = get_settings()
    addresses = {normalize_email(email) for email in [*settings.allowed_emails, settings.admin_email]}
    return sorted(address for address in addresses if address)


def upgrade() -> None:
    """Upgrade schema."""
    allowed_emails = op.create_table(
        'allowed_emails',
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('added_by', sa.UUID(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['added_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('email'),
    )
    op.add_column('jobs', sa.Column('held_at', sa.DateTime(timezone=True), nullable=True))

    addresses = _imported_addresses()
    if addresses:
        op.get_bind().execute(
            postgresql.insert(allowed_emails)
            .values([{'email': address} for address in addresses])
            .on_conflict_do_nothing(index_elements=['email'])
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('jobs', 'held_at')
    op.drop_table('allowed_emails')
