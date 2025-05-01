-- Agregar campo observaciones a la tabla ordenes
ALTER TABLE hatsu.ordenes ADD COLUMN IF NOT EXISTS observaciones TEXT; 