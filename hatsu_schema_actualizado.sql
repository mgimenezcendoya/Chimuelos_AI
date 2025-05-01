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
    source TEXT
);

-- Tabla: productos
CREATE TABLE IF NOT EXISTS productos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre TEXT,
    descripcion TEXT,
    precio_base DECIMAL,
    es_combo BOOLEAN DEFAULT FALSE,
    activo BOOLEAN DEFAULT TRUE
);

-- Tabla: producto_local (productos disponibles por local)
CREATE TABLE IF NOT EXISTS producto_local (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos(id),
    local_id UUID REFERENCES locales(id),
    activo BOOLEAN DEFAULT TRUE
);

-- Tabla: historial_precios
CREATE TABLE IF NOT EXISTS historial_precios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos(id),
    precio_anterior DECIMAL,
    precio_nuevo DECIMAL,
    fecha_cambio TIMESTAMP DEFAULT NOW(),
    motivo TEXT,
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Tabla: ordenes
CREATE TABLE IF NOT EXISTS ordenes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID REFERENCES usuarios(id),
    local_id UUID REFERENCES locales(id),
    fecha_hora TIMESTAMP DEFAULT NOW(),
    estado TEXT,
    monto_total DECIMAL,
    medio_pago TEXT
);

-- Tabla: orden_detalle
CREATE TABLE IF NOT EXISTS orden_detalle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    orden_id UUID REFERENCES ordenes(id),
    producto_id UUID REFERENCES productos(id),
    cantidad INTEGER,
    precio_unitario DECIMAL,
    subtotal DECIMAL
);

-- Tabla: combos_detalle
CREATE TABLE IF NOT EXISTS combos_detalle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    combo_id UUID REFERENCES productos(id),
    producto_id UUID REFERENCES productos(id),
    cantidad INTEGER
);

-- Tabla: inventario
CREATE TABLE IF NOT EXISTS inventario (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos(id),
    local_id UUID REFERENCES locales(id),
    stock_actual INTEGER,
    stock_minimo INTEGER,
    ultima_actualizacion TIMESTAMP DEFAULT NOW()
);

-- Tabla: pedidos_proveedor
CREATE TABLE IF NOT EXISTS pedidos_proveedor (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos(id),
    local_id UUID REFERENCES locales(id),
    cantidad INTEGER,
    fecha_pedido TIMESTAMP DEFAULT NOW(),
    estado TEXT
);


-- Crear la tabla de mensajes
CREATE TABLE if not exists mensajes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL REFERENCES hatsu.usuarios(id),
  orden_id UUID REFERENCES hatsu.ordenes(id),
  rol TEXT NOT NULL CHECK (rol IN ('usuario', 'agente', 'humano')),
  mensaje TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  canal TEXT CHECK (canal IN ('whatsapp', 'console', 'web')) DEFAULT 'whatsapp',
  intervencion_humana BOOLEAN DEFAULT false,
  leido BOOLEAN DEFAULT false
);