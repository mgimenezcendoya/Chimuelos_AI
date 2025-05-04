-- Crear extensión para UUID en el esquema público
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

-- Crear esquema
CREATE SCHEMA IF NOT EXISTS hatsu;
SET search_path TO hatsu, public;

-- Tabla: locales
CREATE TABLE IF NOT EXISTS locales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre TEXT,
    direccion TEXT,
    telefono TEXT,
    activo BOOLEAN DEFAULT TRUE
);

-- Tabla: usuarios
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre TEXT,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    fecha_registro TIMESTAMP DEFAULT NOW(),
    local_id UUID REFERENCES locales(id),
    origen TEXT
);

-- Tabla: productos
CREATE TABLE IF NOT EXISTS productos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre TEXT,
    descripcion TEXT,
    precio_base NUMERIC,
    es_combo BOOLEAN DEFAULT FALSE,
    activo BOOLEAN DEFAULT TRUE,
    categoria TEXT,
    numero_de_piezas INTEGER,
    url_imagen TEXT
);

-- Tabla: ordenes
CREATE TABLE IF NOT EXISTS ordenes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID REFERENCES usuarios(id),
    local_id UUID REFERENCES locales(id),
    fecha_hora TIMESTAMP DEFAULT NOW(),
    estado TEXT,
    monto_total NUMERIC,
    medio_pago TEXT,
    is_takeaway BOOLEAN,
    fecha_procesada TIMESTAMP,
    fecha_entregada TIMESTAMP,
    origen TEXT,
    observaciones TEXT
);

-- Tabla: orden_detalle
CREATE TABLE IF NOT EXISTS orden_detalle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    orden_id UUID REFERENCES ordenes(id),
    producto_id UUID REFERENCES productos(id),
    cantidad INTEGER,
    precio_unitario NUMERIC,
    subtotal NUMERIC
);

-- Tabla: mensajes
CREATE TABLE IF NOT EXISTS mensajes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID REFERENCES usuarios(id),
    orden_id UUID REFERENCES ordenes(id),
    rol TEXT,
    mensaje TEXT,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    canal TEXT DEFAULT 'whatsapp'::text,
    intervencion_humana BOOLEAN DEFAULT false,
    leido BOOLEAN DEFAULT false,
    intervencion_humana_historial BOOLEAN DEFAULT false,
    media_url TEXT,
    flag_imagen_validada BOOLEAN DEFAULT false,
    tokens INT4 DEFAULT 0,
    sesion_id UUID
);

-- Tabla: producto_local
CREATE TABLE IF NOT EXISTS producto_local (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos(id),
    local_id UUID REFERENCES locales(id),
    activo BOOLEAN DEFAULT true,
    nombre TEXT,
    descripcion TEXT,
    precio_base NUMERIC,
    es_combo BOOLEAN DEFAULT false,
    categoria TEXT,
    numero_de_piezas INT4,
    url_imagen TEXT
);

-- Eliminar tabla que ya no existe en el schema
DROP TABLE IF EXISTS combos_detalle;