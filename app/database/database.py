from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, Numeric, UUID
import os
from dotenv import load_dotenv
from uuid import uuid4

load_dotenv()

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Crear el motor de base de datos
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Crear la base para los modelos
Base = declarative_base()

# Definir los modelos
class Producto(Base):
    __tablename__ = "productos"
    __table_args__ = {"schema": "hatsu"}

    id = Column(UUID, primary_key=True, default=uuid4)
    nombre = Column(Text)
    descripcion = Column(Text)
    precio_base = Column(Numeric)
    es_combo = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)

class Orden(Base):
    __tablename__ = "ordenes"
    __table_args__ = {"schema": "hatsu"}

    id = Column(UUID, primary_key=True, default=uuid4)
    usuario_id = Column(UUID, ForeignKey("hatsu.usuarios.id"))
    local_id = Column(UUID, ForeignKey("hatsu.locales.id"))
    fecha_hora = Column(DateTime)
    estado = Column(Text)
    monto_total = Column(Numeric)
    medio_pago = Column(Text)

class OrdenDetalle(Base):
    __tablename__ = "orden_detalle"
    __table_args__ = {"schema": "hatsu"}

    id = Column(UUID, primary_key=True, default=uuid4)
    orden_id = Column(UUID, ForeignKey("hatsu.ordenes.id"))
    producto_id = Column(UUID, ForeignKey("hatsu.productos.id"))
    cantidad = Column(Integer)
    precio_unitario = Column(Numeric)
    subtotal = Column(Numeric)

# Función para obtener una sesión
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session

# Función para inicializar la base de datos
async def init_db():
    """Inicializa la conexión a la base de datos"""
    try:
        async with engine.begin() as conn:
            # Aquí podrías agregar migraciones o creación de tablas si es necesario
            pass
    except Exception as e:
        print(f"Error inicializando la base de datos: {str(e)}")
        raise 