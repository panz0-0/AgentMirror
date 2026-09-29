"""SQLAlchemy 声明式基类，所有 ORM 模型继承此类，由 init_db() 统一建表。"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()
