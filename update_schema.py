import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Cargar variables de entorno
load_dotenv()

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

async def update_schema():
    # Crear el motor de base de datos
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    # Leer el archivo SQL
    with open('hatsu_schema_actualizado.sql', 'r') as file:
        sql_script = file.read()
    
    # Ejecutar el script SQL
    async with engine.begin() as conn:
        await conn.execute(text(sql_script))
        await conn.commit()
    
    print("Schema actualizado exitosamente")

if __name__ == "__main__":
    asyncio.run(update_schema()) 