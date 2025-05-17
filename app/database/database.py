from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, Numeric, UUID
import os
from dotenv import load_dotenv
from uuid import uuid4
from tenacity import retry, wait_fixed, stop_after_attempt  # 👈 agregado para reintentos

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

class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = {"schema": "hatsu"}

    id = Column(UUID, primary_key=True, default=uuid4)
    nombre = Column(Text)
    telefono = Column(Text)
    email = Column(Text)
    fecha_registro = Column(DateTime)
    local_id = Column(UUID, ForeignKey("hatsu.locales.id"))
    origen = Column(Text)

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
    is_takeaway = Column(Boolean)
    fecha_procesada = Column(DateTime)
    fecha_entregada = Column(DateTime)
    origen = Column(Text)
    observaciones = Column(Text)
    direccion = Column(Text, nullable=True)  # Asegurarnos de que la columna sea nullable

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

# Función para inicializar la base de datos con reintentos
@retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
async def init_db():
    """Inicializa la conexión a la base de datos con reintentos"""
    try:
        print("⏳ Intentando conectar a la base de datos...")
        async with engine.begin() as conn:
            await conn.run_sync(lambda _: None)  # Solo testea conexión
        print("✅ Conexión exitosa a la base de datos.")
    except Exception as e:
        print(f"❌ Error al conectar a la base de datos: {str(e)}")
        raise
