from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import UserModel
from schemas.user import UserCreate


async def get_all_users(
    session: AsyncSession,
) -> Sequence[UserModel]:
    stmt = select(UserModel).order_by(UserModel.id)
    result = await session.scalars(stmt)
    return result.all()


async def create_user(
    session: AsyncSession,
    user_create: UserCreate,
) -> UserModel:
    user = UserModel(username=user_create.username)
    session.add(user)
    await session.commit()
    return user
