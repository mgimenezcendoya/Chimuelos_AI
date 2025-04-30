import os
import psycopg2
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Obtener credenciales de las variables de entorno
host = os.getenv("PGHOST")
database = os.getenv("PGDATABASE")
user = os.getenv("PGUSER")
password = os.getenv("PGPASSWORD")
port = int(os.getenv("PGPORT", "52278"))

try:
    # Establecer conexión
    print("Conectando a la base de datos...")
    conn = psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password,
        port=port
    )
    
    # Crear cursor y ejecutar el script SQL
    with conn.cursor() as cur:
        print("Leyendo archivo SQL...")
        with open("hatsu_schema_actualizado.sql", "r") as f:
            sql_script = f.read()
            print("Ejecutando script SQL...")
            cur.execute(sql_script)
        
        # Confirmar los cambios
        conn.commit()
        print("Schema creado exitosamente!")

except Exception as e:
    print(f"Error: {str(e)}")
    
finally:
    # Cerrar la conexión
    if 'conn' in locals():
        conn.close()
        print("Conexión cerrada.") 