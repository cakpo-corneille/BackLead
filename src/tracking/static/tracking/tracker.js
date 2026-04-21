/**
 * WiFiLeads Tracker v1.0.0
 *
 * Lit les données de session MikroTik depuis les data-* attributes
 * du script tag (substitution MikroTik côté serveur).
 * Envoie un heartbeat à chaque chargement (=chaque refresh MikroTik).
 * Ferme la session sur logout via navigator.sendBeacon().
 *
 * Aucun parsing DOM. Aucune dépendance externe.
 */
(function (document, navigator) {
    'use strict';

    // --- Lire les attributs depuis le script tag lui-même ---
    const script    = document.currentScript;
    const BACKEND   = new URL(script.src).origin;
    const API       = BACKEND + '/api/v1/tracking/';
    const STORE_KEY = 'wfl_sk_'; // wfl_session_key_<mac>

    const get = function (attr) {
        return script.getAttribute('data-' + attr) || null;
    };

    const publicKey = get('public-key');
    const mac       = (get('mac') || '').toUpperCase();

    // Garde-fou : configuration incomplète → sortir silencieusement
    if (!publicKey || !mac || mac === '$(MAC)') {
        console.warn('[WFL Tracker] Configuration incomplète. Tracker inactif.');
        return;
    }

    const storeKey  = STORE_KEY + mac.replace(/:/g, '');
    const isLogout  = window.location.pathname.toLowerCase().includes('logout');

    // ----------------------------------------------------------------
    // CAS LOGOUT : fermeture de session via sendBeacon
    // sendBeacon garantit l'envoi même si la page se ferme ou navigue.
    // ----------------------------------------------------------------
    if (isLogout) {
        var sessionKey = localStorage.getItem(storeKey);
        if (sessionKey) {
            navigator.sendBeacon(
                API + 'end/',
                new Blob(
                    [JSON.stringify({ session_key: sessionKey })],
                    { type: 'application/json' }
                )
            );
            localStorage.removeItem(storeKey);
        }
        return;
    }

    // ----------------------------------------------------------------
    // CAS STATUS : heartbeat avec toutes les données MikroTik
    // Appelé à chaque reload automatique de status.html (meta refresh).
    // ----------------------------------------------------------------
    var payload = {
        public_key:  publicKey,
        mac_address: mac,
        session_key: localStorage.getItem(storeKey) || null,
        ip_address:  get('ip'),
        uptime:      get('uptime')   || '',
        bytes_in:    get('bytes-in') || '0',
        bytes_out:   get('bytes-out')|| '0',
        rx_limit:    get('rx-limit'),
        tx_limit:    get('tx-limit'),
        username:    get('username'),
        session_id:  get('session-id'),
    };

    fetch(API + 'heartbeat/', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
        // Stocker la session_key pour les heartbeats suivants
        if (data.session_key) {
            localStorage.setItem(storeKey, data.session_key);
        }
    })
    .catch(function (err) {
        // Non bloquant : le client doit toujours voir sa page status
        console.warn('[WFL Tracker] Heartbeat silencieux :', err.message);
    });

}(document, navigator));
