from app.database.database import init_db, async_session
import asyncio
from sqlalchemy import text

async def check_database():
    print("Inicializando base de datos...")
    await init_db()
    
    async with async_session() as session:
        print("\nVerificando productos activos:")
        result = await session.execute(
            text("SELECT nombre, precio_base, es_combo FROM hatsu.productos WHERE activo = true")
        )
        products = result.fetchall()
        print(f"Productos encontrados: {len(products)}")
        for p in products:
            print(f"- {p.nombre} (${p.precio_base})")
            
        print("\nVerificando locales activos:")
        result = await session.execute(
            text("SELECT nombre, direccion FROM hatsu.locales WHERE activo = true")
        )
        locales = result.fetchall()
        print(f"Locales encontrados: {len(locales)}")
        for l in locales:
            print(f"- {l.nombre}: {l.direccion}")

if __name__ == "__main__":
    asyncio.run(check_database()) 