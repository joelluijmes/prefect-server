"""
merge 3c87ad7e0b71 and b9eedd397f54

Revision ID: 605c6d9b9d6e
Revises: 3c87ad7e0b71, b9eedd397f54
Create Date: 2020-11-13 09:10:26.868181

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = '605c6d9b9d6e'
down_revision = ('3c87ad7e0b71', 'b9eedd397f54')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
