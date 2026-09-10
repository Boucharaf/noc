-- =====================================================================
--  Compte de lecture du NOC sur une base NetXMS
-- =====================================================================
--
-- CE FICHIER EST AUSSI LA DEMANDE À ADRESSER À L'AGENCE. En local, il est
-- joué par database/restore_netxms_dump.sh sur la copie restaurée ; en
-- production, c'est ce même script que l'administrateur de la base NetXMS
-- exécute — ou qu'il lit pour savoir exactement ce qu'on lui demande :
--
--   psql -d netxms -v reader_password='…' -f database/netxms_readonly_role.sql
--
-- CE QUE LE COMPTE PEUT FAIRE, et rien d'autre :
--   * lire l'inventaire (nœuds, propriétés d'objets, appartenance aux
--     conteneurs) et les alarmes ;
--   * sur des COLONNES choisies : la table `nodes` contient aussi les
--     communautés SNMP et les secrets des agents, qui ne sont PAS accordés ;
--   * en lecture seule imposée par le serveur (default_transaction_read_only)
--     — une requête d'écriture échouerait même si le code en émettait une ;
--   * trois connexions au plus, quinze secondes par requête : le collecteur
--     ne peut pas peser sur le serveur de supervision de production.
--
-- Charge réelle : une requête d'inventaire et une requête d'alarmes toutes
-- les COLLECT_INTERVAL_S secondes (300 par défaut), quel que soit le nombre
-- d'opérateurs connectés au NOC.
--
-- Rejouable : le compte existant voit son mot de passe et ses droits remis
-- à jour.

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE noc_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'noc_reader')
\gexec

ALTER ROLE noc_reader WITH LOGIN PASSWORD :'reader_password' CONNECTION LIMIT 3;
ALTER ROLE noc_reader SET default_transaction_read_only = on;
ALTER ROLE noc_reader SET statement_timeout = '15s';

GRANT CONNECT ON DATABASE :"DBNAME" TO noc_reader;
GRANT USAGE ON SCHEMA public TO noc_reader;

-- Version du schéma, pour le contrôle de santé.
GRANT SELECT (var_name, var_value) ON public.metadata TO noc_reader;

-- Inventaire. PAS de community, usm_*_password, secret, agent_cert_* :
-- ce sont les clés d'accès aux équipements.
GRANT SELECT (id, primary_name, primary_ip, platform_name, snmp_sys_name, snmp_sys_location)
    ON public.nodes TO noc_reader;

GRANT SELECT (object_id, name, alias, status, is_deleted, is_system,
              latitude, longitude, country, region, city, district)
    ON public.object_properties TO noc_reader;

-- Alarmes actives et leur équipement source. Une alarme d'interface a pour
-- source l'interface : interfaces.node_id la rattache à son équipement.
GRANT SELECT (alarm_id, alarm_state, current_severity, message, creation_time,
              last_state_change_time, source_object_id)
    ON public.alarms TO noc_reader;
GRANT SELECT (id, node_id) ON public.interfaces TO noc_reader;

-- Appartenance aux conteneurs NetXMS : aucune donnée sensible.
GRANT SELECT ON public.container_members TO noc_reader;

-- Référentiel de sites PROPRE À L'AGENCE (colonne siteadmin_id ajoutée à
-- object_properties, schéma donnebase). Accordé seulement s'il existe : ce
-- fichier reste applicable à une base NetXMS standard.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'object_properties'
                 AND column_name = 'siteadmin_id')
       AND to_regclass('donnebase.siteadministratif') IS NOT NULL THEN
        GRANT SELECT (siteadmin_id) ON public.object_properties TO noc_reader;
        GRANT USAGE ON SCHEMA donnebase TO noc_reader;
        GRANT SELECT (id_siteadministratif, nomsiteadministratif)
            ON donnebase.siteadministratif TO noc_reader;
    END IF;
END $$;
