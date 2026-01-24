"""Initial migration

Revision ID: 2265f91b3a26
Revises:
Create Date: 2026-01-23 14:23:58.485504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2265f91b3a26'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sourcetype = postgresql.ENUM(
    'site', 'tg', name='sourcetype', create_type=False
)
poststatus = postgresql.ENUM(
    'new', 'generated', 'published', 'failed',
    name='poststatus', create_type=False
)


def upgrade() -> None:
    op.execute("CREATE TYPE sourcetype AS ENUM ('site', 'tg')")
    op.execute(
        "CREATE TYPE poststatus AS ENUM "
        "('new', 'generated', 'published', 'failed')"
    )

    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sourcetype, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column(
            'created_at', sa.DateTime(), server_default=sa.text('now()')
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sources_id'), 'sources', ['id'], unique=False)

    op.create_table(
        'keywords',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('word', sa.String(100), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(), server_default=sa.text('now()')
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('word', name='keywords_word_key'),
    )
    op.create_index(op.f('ix_keywords_id'), 'keywords', ['id'], unique=False)

    op.create_table(
        'news_items',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('url', sa.String(1000), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('source', sa.String(255), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(), server_default=sa.text('now()')
        ),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_news_items_id'), 'news_items', ['id'], unique=True
    )
    op.create_index(
        'ix_news_items_source_id', 'news_items', ['source_id'], unique=False
    )

    op.create_table(
        'posts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('news_id', sa.String(36), nullable=False),
        sa.Column('generated_text', sa.Text(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('status', poststatus, server_default='new'),
        sa.Column(
            'created_at', sa.DateTime(), server_default=sa.text('now()')
        ),
        sa.ForeignKeyConstraint(['news_id'], ['news_items.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_posts_id'), 'posts', ['id'], unique=False)
    op.create_index('ix_posts_news_id', 'posts', ['news_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_posts_id'), table_name='posts')
    op.drop_index('ix_posts_news_id', table_name='posts')
    op.drop_table('posts')

    op.drop_index('ix_news_items_source_id', table_name='news_items')
    op.drop_index(op.f('ix_news_items_id'), table_name='news_items')
    op.drop_table('news_items')

    op.drop_index(op.f('ix_keywords_id'), table_name='keywords')
    op.drop_table('keywords')

    op.drop_index(op.f('ix_sources_id'), table_name='sources')
    op.drop_table('sources')

    op.execute('DROP TYPE IF EXISTS poststatus')
    op.execute('DROP TYPE IF EXISTS sourcetype')
