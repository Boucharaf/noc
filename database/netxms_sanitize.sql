-- =====================================================================
--  Purge des secrets d'un dump de production NetXMS
-- =====================================================================
--
-- Exécuté par database/restore_netxms_dump.sh juste après la restauration.
--
-- Le NOC n'a besoin que de l'inventaire et des alarmes. Le dump porte en
-- plus des secrets RÉELS de l'agence, qu'aucun écran n'utilise et dont la
-- présence sur un poste de développement est un risque sans contrepartie :
--
--   * communautés SNMP et mots de passe SNMPv3 — ils ouvrent l'accès aux
--     équipements du réseau, parfois en écriture ;
--   * secrets partagés des agents, clés SSH, jetons d'authentification ;
--   * empreintes des mots de passe des comptes NetXMS — attaquables hors
--     ligne, et souvent réutilisés ailleurs ;
--   * configuration des canaux de notification (jetons de bot Telegram,
--     identifiants SMTP) et coordonnées personnelles des destinataires.
--
-- Chaque cible est vérifiée avant d'être touchée : une table ou une colonne
-- absente (autre version de NetXMS) est ignorée, jamais une erreur. Le
-- fichier se rejoue sans effet de bord.

\set ON_ERROR_STOP on

BEGIN;

-- Colonnes vidées : NULL quand la colonne l'accepte, chaîne vide sinon.
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT c.table_name, c.column_name, c.is_nullable
        FROM information_schema.columns c
        JOIN (VALUES
            ('nodes', 'community'),
            ('nodes', 'usm_auth_password'),
            ('nodes', 'usm_priv_password'),
            ('nodes', 'secret'),
            ('nodes', 'agent_cert_mapping_data'),
            ('users', 'password'),
            ('users', 'password_history'),
            ('users', 'email'),
            ('users', 'phone_number'),
            ('users', 'cert_mapping_data'),
            ('users', 'ldap_dn'),
            ('notification_channels', 'configuration'),
            ('actions', 'rcpt_addr')
        ) AS wanted(table_name, column_name)
          ON wanted.table_name = c.table_name AND wanted.column_name = c.column_name
        WHERE c.table_schema = 'public'
          AND c.data_type IN ('text', 'character varying', 'character')
    LOOP
        EXECUTE format(
            'UPDATE public.%I SET %I = %s',
            target.table_name,
            target.column_name,
            CASE WHEN target.is_nullable = 'YES' THEN 'NULL' ELSE '''''' END
        );
        RAISE NOTICE 'vidé : %.%', target.table_name, target.column_name;
    END LOOP;
END $$;

-- Tables vidées entièrement : elles ne contiennent QUE des secrets ou des
-- données de session.
DO $$
DECLARE
    name text;
BEGIN
    FOREACH name IN ARRAY ARRAY[
        'auth_tokens', 'snmp_communities', 'usm_credentials', 'shared_secrets',
        'ssh_keys', 'nc_persistent_storage', 'persistent_storage',
        'two_factor_auth_bindings', 'user_agent_notifications', 'agent_configs'
    ] LOOP
        IF to_regclass(format('public.%I', name)) IS NOT NULL THEN
            EXECUTE format('DELETE FROM public.%I', name);
            RAISE NOTICE 'vidée : %', name;
        END IF;
    END LOOP;
END $$;

-- Paramètres dont le NOM trahit un secret, quelle que soit la table.
DO $$
DECLARE
    pattern constant text := '(password|passwd|secret|token|apikey|api_key|privatekey|community)';
BEGIN
    IF to_regclass('public.config') IS NOT NULL THEN
        UPDATE public.config SET var_value = '' WHERE var_name ~* pattern;
    END IF;
    IF to_regclass('public.config_clob') IS NOT NULL THEN
        UPDATE public.config_clob SET var_value = '' WHERE var_name ~* pattern;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'object_custom_attributes'
          AND column_name IN ('attr_name', 'attr_value')
        HAVING count(*) = 2
    ) THEN
        UPDATE public.object_custom_attributes SET attr_value = '' WHERE attr_name ~* pattern;
    END IF;
END $$;

COMMIT;
