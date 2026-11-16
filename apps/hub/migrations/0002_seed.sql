-- Demo seed: one tenant, one bench device.
--
-- Idempotent, so it is safe on a database that already has the rows.

insert into core.tenant (id, name)
values ('0192a000-0000-7000-8000-000000000001', 'Demo tenant')
on conflict (id) do nothing;

insert into core.device (id, tenant_id, external_id, name, kind, model, fw_version)
values (
    '0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f',
    '0192a000-0000-7000-8000-000000000001',
    'nano-01',
    'Bench Nano',
    'real',
    'Arduino Nano (ATmega328P)',
    '0.1.0'
)
on conflict (id) do nothing;
