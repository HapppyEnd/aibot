"""change_datetime_to_timestamp_with_timezone

Revision ID: b6ea87d42aec
Revises: a2beccf5b23c
Create Date: 2026-01-23 15:02:39.795566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6ea87d42aec'
down_revision: Union[str, None] = 'a2beccf5b23c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Изменяем все колонки DateTime на TIMESTAMP WITH TIME ZONE
    # Предполагаем, что существующие naive datetime - это UTC
    
    # sources.created_at
    op.execute("""
        ALTER TABLE sources 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # keywords.created_at
    op.execute("""
        ALTER TABLE keywords 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # news_items.published_at
    op.execute("""
        ALTER TABLE news_items 
        ALTER COLUMN published_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING published_at AT TIME ZONE 'UTC'
    """)
    
    # news_items.created_at
    op.execute("""
        ALTER TABLE news_items 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # posts.published_at (nullable - обрабатываем NULL значения)
    op.execute("""
        ALTER TABLE posts 
        ALTER COLUMN published_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING CASE 
            WHEN published_at IS NULL THEN NULL
            ELSE published_at AT TIME ZONE 'UTC'
        END
    """)
    
    # posts.created_at
    op.execute("""
        ALTER TABLE posts 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)


def downgrade() -> None:
    # Возвращаем обратно на TIMESTAMP WITHOUT TIME ZONE
    # Конвертируем timezone-aware datetime в naive (убираем timezone)
    
    # sources.created_at
    op.execute("""
        ALTER TABLE sources 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # keywords.created_at
    op.execute("""
        ALTER TABLE keywords 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # news_items.published_at
    op.execute("""
        ALTER TABLE news_items 
        ALTER COLUMN published_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING published_at AT TIME ZONE 'UTC'
    """)
    
    # news_items.created_at
    op.execute("""
        ALTER TABLE news_items 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # posts.published_at (nullable)
    op.execute("""
        ALTER TABLE posts 
        ALTER COLUMN published_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING CASE 
            WHEN published_at IS NULL THEN NULL
            ELSE published_at AT TIME ZONE 'UTC'
        END
    """)
    
    # posts.created_at
    op.execute("""
        ALTER TABLE posts 
        ALTER COLUMN created_at 
        TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
