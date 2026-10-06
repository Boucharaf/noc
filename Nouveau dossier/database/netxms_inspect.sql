-- Quick NetXMS source inspection queries.
-- Run with: docker compose exec postgres psql -U netxms -d netxms -f database/netxms_inspect.sql

\echo 'Schemas'
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
ORDER BY schema_name;

\echo '\nTables'
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;

\echo '\nCandidate NetXMS tables'
SELECT 'donnebase.ville' AS table_name, count(*) FROM donnebase.ville
UNION ALL
SELECT 'donnebase.limiteregion', count(*) FROM donnebase.limiteregion
UNION ALL
SELECT 'donnebase.siteadministratif', count(*) FROM donnebase.siteadministratif
UNION ALL
SELECT 'public.nodes', count(*) FROM nodes
UNION ALL
SELECT 'public.object_properties', count(*) FROM object_properties;

\echo '\nColumns: donnebase.ville'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'donnebase' AND table_name = 'ville'
ORDER BY ordinal_position;

\echo '\nColumns: donnebase.limiteregion'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'donnebase' AND table_name = 'limiteregion'
ORDER BY ordinal_position;

\echo '\nColumns: donnebase.siteadministratif'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'donnebase' AND table_name = 'siteadministratif'
ORDER BY ordinal_position;

\echo '\nColumns: public.nodes'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'nodes'
ORDER BY ordinal_position;

\echo '\nColumns: public.object_properties'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'object_properties'
ORDER BY ordinal_position;

\echo '\nSample rows: donnebase.ville'
SELECT * FROM donnebase.ville LIMIT 10;

\echo '\nSample rows: donnebase.limiteregion'
SELECT * FROM donnebase.limiteregion LIMIT 10;

\echo '\nSample rows: donnebase.siteadministratif'
SELECT * FROM donnebase.siteadministratif LIMIT 10;

\echo '\nSample rows: public.nodes'
SELECT * FROM nodes LIMIT 10;

\echo '\nSample rows: public.object_properties'
SELECT * FROM object_properties LIMIT 10;
