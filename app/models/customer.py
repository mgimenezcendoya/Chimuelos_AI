from sqlalchemy import Column, Integer, String, Boolean
from app.models.base import Base

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, index=True)
    is_active = Column(Boolean, default=True)
    whatsapp_id = Column(String, unique=True, index=True)
    language_preference = Column(String, default="es")
    last_interaction = Column(String)  # Store the last context/state of interaction 