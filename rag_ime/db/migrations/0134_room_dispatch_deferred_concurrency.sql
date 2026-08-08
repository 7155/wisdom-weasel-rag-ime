ALTER TABLE room_kernel_dispatch_resource_reservations
ADD COLUMN concurrency_acquired INTEGER NOT NULL DEFAULT 0
CHECK(concurrency_acquired IN (0, 1));

UPDATE room_kernel_dispatch_resource_reservations
SET concurrency_acquired = 1
WHERE state = 'reserved';
