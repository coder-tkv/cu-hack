from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from .base import Base


class UserModel(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column()