<?php
/**
 * Crée (ou complète) le compte de service que le collecteur du NOC utilise
 * pour interroger l'API REST d'iTop.
 *
 * DEUX PROFILS SONT NÉCESSAIRES, ET C'EST UN PIÈGE CLASSIQUE :
 *
 *   « REST Services User » n'accorde AUCUN droit sur les données. Il ouvre
 *   seulement la porte de /webservices/rest.php. Un compte qui ne porte que
 *   lui reçoit, sur chaque requête, un HTTP 200 contenant
 *   {"code":1,"message":"The current user does not have enough permissions
 *   for reading data of class Organization"} — un refus qui ressemble à une
 *   panne d'API alors que c'est un défaut d'habilitation.
 *
 *   Les droits de LECTURE viennent donc d'un second profil. iTop 3.2 n'en
 *   livre aucun en lecture seule : les profils standard donnent tous
 *   l'écriture sur leur périmètre. On retient la combinaison la plus étroite
 *   qui couvre ce que le NOC lit — CI, incidents, demandes, seuils de
 *   service — et on la documente pour que l'agence puisse la remplacer par
 *   un profil sur mesure en production.
 *
 * Pourquoi passer par l'ORM d'iTop et non par des INSERT SQL : le modèle
 * applique le hachage du mot de passe, les valeurs par défaut et
 * l'historique. Des INSERT directs produiraient un compte que l'interface
 * refuserait ensuite d'éditer.
 *
 * Usage : php create-rest-user.php <login> <mot de passe> [profil,profil,…]
 * Idempotent : si le compte existe, seuls les profils manquants sont ajoutés.
 */

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Ce script ne s'exécute qu'en ligne de commande.\n");
    exit(1);
}

$sLogin = $argv[1] ?? '';
$sPassword = $argv[2] ?? '';
if ($sLogin === '' || $sPassword === '') {
    fwrite(STDERR, "Usage : php create-rest-user.php <login> <mot de passe> [profils]\n");
    exit(1);
}

// Périmètre par défaut :
//   REST Services User  -> droit d'appeler l'API (obligatoire) ;
//   Configuration Manager -> lecture de la CMDB (Server, NetworkDevice,
//                            Organization, Location) ;
//   Support Agent       -> lecture des Incident ;
//   Service Desk Agent  -> lecture des UserRequest et des SLT.
$sProfiles = $argv[3] ?? 'REST Services User,Configuration Manager,Support Agent,Service Desk Agent';
$aWanted = array_values(array_filter(array_map('trim', explode(',', $sProfiles))));

$sHome = getenv('ITOP_HOME') ?: '/var/www/html';
require_once $sHome.'/approot.inc.php';
require_once APPROOT.'/application/application.inc.php';
require_once APPROOT.'/application/startup.inc.php';

/**
 * Résout les profils par leur NOM. Leur identifiant numérique n'est pas
 * stable d'une installation à l'autre : il dépend de l'ordre dans lequel les
 * modules ont été installés.
 */
function ResolveProfiles(array $aNames): array
{
    $aResolved = [];
    $aMissing = [];
    foreach ($aNames as $sName) {
        $oSet = new DBObjectSet(
            DBObjectSearch::FromOQL('SELECT URP_Profiles WHERE name = :name'),
            [],
            ['name' => $sName]
        );
        $oProfile = $oSet->Fetch();
        if ($oProfile === null) {
            $aMissing[] = $sName;
            continue;
        }
        $aResolved[$sName] = $oProfile->GetKey();
    }
    if ($aMissing !== []) {
        $oAll = new DBObjectSet(DBObjectSearch::FromOQL('SELECT URP_Profiles'));
        $aAvailable = [];
        while ($oOne = $oAll->Fetch()) {
            $aAvailable[] = $oOne->Get('name');
        }
        throw new Exception(sprintf(
            "Profil(s) introuvable(s) : %s. Profils de cette instance : %s",
            implode(', ', $aMissing),
            implode(', ', $aAvailable)
        ));
    }
    return $aResolved;
}

try {
    $aProfiles = ResolveProfiles($aWanted);
    $oUser = MetaModel::GetObjectByColumn('User', 'login', $sLogin, false);

    if ($oUser === null) {
        $oUser = MetaModel::NewObject('UserLocal');
        $oUser->Set('login', $sLogin);
        $oUser->Set('password', $sPassword);
        $oUser->Set('language', MetaModel::GetConfig()->GetDefaultLanguage());
        $oUser->Set('status', 'enabled');

        $oLinks = DBObjectSet::FromScratch('URP_UserProfile');
        foreach ($aProfiles as $sName => $iProfileId) {
            $oLink = MetaModel::NewObject('URP_UserProfile');
            $oLink->Set('profileid', $iProfileId);
            $oLink->Set('reason', 'Compte de service du collecteur NOC');
            $oLinks->AddObject($oLink);
        }
        $oUser->Set('profile_list', $oLinks);
        $oUser->DBInsert();

        printf("Compte « %s » créé avec les profils : %s\n", $sLogin, implode(', ', array_keys($aProfiles)));
        exit(0);
    }

    // Le compte existe : on n'y touche que pour AJOUTER les profils absents.
    // Ne jamais réécrire son mot de passe ni retirer un profil — l'exploitant
    // a pu le régler à la main, et un redémarrage de conteneur ne doit pas
    // défaire son travail.
    $oExistingLinks = $oUser->Get('profile_list');
    $aHeld = [];
    while ($oLink = $oExistingLinks->Fetch()) {
        $aHeld[] = (int) $oLink->Get('profileid');
    }

    $aAdded = [];
    foreach ($aProfiles as $sName => $iProfileId) {
        if (in_array((int) $iProfileId, $aHeld, true)) {
            continue;
        }
        $oLink = MetaModel::NewObject('URP_UserProfile');
        $oLink->Set('profileid', $iProfileId);
        $oLink->Set('reason', 'Compte de service du collecteur NOC');
        $oExistingLinks->AddObject($oLink);
        $aAdded[] = $sName;
    }

    if ($aAdded === []) {
        printf("Le compte « %s » existe déjà avec tous les profils requis.\n", $sLogin);
        exit(0);
    }

    $oUser->Set('profile_list', $oExistingLinks);
    $oUser->DBUpdate();
    printf("Compte « %s » complété — profils ajoutés : %s\n", $sLogin, implode(', ', $aAdded));
    exit(0);
} catch (Exception $e) {
    fwrite(STDERR, 'Échec : '.$e->getMessage()."\n");
    exit(1);
}
