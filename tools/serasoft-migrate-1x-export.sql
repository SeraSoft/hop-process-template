-- Export of the template 1.0.x configuration, input of tools/serasoft-migrate-1x.py.
-- Run on the old integrations database (PostgreSQL):
--   psql "<connection string>" -v ON_ERROR_STOP=1 --csv -f tools/serasoft-migrate-1x-export.sql > export.csv
SELECT 'process' AS kind, CAST(id AS varchar) AS id, short_name, description, CAST(is_active AS varchar) AS is_active,
       CAST(NULL AS varchar) AS event_category_id, CAST(NULL AS varchar) AS event_type, CAST(NULL AS varchar) AS name
FROM config.integrations_processes
UNION ALL
SELECT 'category', CAST(id AS varchar), NULL, NULL, NULL, NULL, CAST(event_type AS varchar), name
FROM config.event_category
UNION ALL
SELECT 'subcategory', CAST(id AS varchar), NULL, NULL, NULL, CAST(event_category_id AS varchar), NULL, name
FROM config.event_subcategory
ORDER BY 1, 2;
