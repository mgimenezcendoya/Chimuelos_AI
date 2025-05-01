-- Agregar campo is_takeaway a la tabla hatsu.ordenes
ALTER TABLE hatsu.ordenes
ADD COLUMN is_takeaway BOOLEAN DEFAULT false;

-- Actualizar registros existentes (asumimos que todos los pedidos anteriores fueron delivery)
UPDATE hatsu.ordenes
SET is_takeaway = false
WHERE is_takeaway IS NULL;

-- Hacer el campo NOT NULL después de actualizar los registros existentes
ALTER TABLE hatsu.ordenes
ALTER COLUMN is_takeaway SET NOT NULL;

-- Agregar un comentario al campo para documentación
COMMENT ON COLUMN hatsu.ordenes.is_takeaway IS 'Indica si el pedido es para retirar en el local (true) o para delivery (false)'; 