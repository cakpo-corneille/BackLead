/**
 * WiFiLeads Tracker v1.2.0
 *
 * Lit les données de session MikroTik depuis les data-* attributes.
 * Doit être inclus dans status.html ET logout.html du hotspot MikroTik.
 *
 * Sur status.html  → envoie un heartbeat + stocke la session_key
 * Sur logout.html  → ferme la session via sendBeacon (survit fermeture navigateur)
 *
 * Note : depuis v2.0, Celery synchronise les sessions directement
 * via l'API MikroTik toutes les 2 minutes. Ce script reste utile pour :
 *   - créer la session immédiatement à la connexion (sans attendre Celery)
 *   - fermer proprement la session au logout (signal instantané)
 */
(function (document, navigator, localStorage) {
    'use strict';

    var script    = document.currentScript;
    var BACKEND   = new URL(script.src).origin;
    var API       = BACKEND + '/api/v1/tracking/';
    var STORE_KEY = 'wfl_sk_';

    // Lecture d'un data-* attribute du tag <script>
    function get(attr) {
        return script.getAttribute('data-' + attr) || null;
    }

    var publicKey = get('public-key');
    var mac       = (get('mac') || '').toUpperCase();

    // Guard : si MikroTik n'a pas remplacé les variables,
    // on est probablement sur une page de test — ne pas envoyer de données.
    // $(mac).toUpperCase() → '$(MAC)' si non remplacé
    if (!publicKey || !mac || mac === '$(MAC)') {
        console.warn('[WFL Tracker] Variables MikroTik non remplacées. Tracker inactif.');
        return;
    }

    // Clé localStorage unique par adresse MAC (sans les deux-points)
    var storeKey = STORE_KEY + mac.replace(/:/g, '');

    // Détection de la page courante via le pathname
    var path     = window.location.pathname.toLowerCase();
    var isLogout = path.indexOf('logout') !== -1;
    var isStatus = path.indexOf('status') !== -1 || (!isLogout);

    // ----------------------------------------------------------------
    // CAS LOGOUT : fermeture instantanée de la session
    // sendBeacon garantit l'envoi même si le navigateur se ferme
    // ----------------------------------------------------------------
    if (isLogout) {
        var sessionKey = localStorage.getItem(storeKey);
        if (sessionKey) {
            var body = JSON.stringify({ session_key: sessionKey });
            navigator.sendBeacon(
                API + 'end/',
                new Blob([body], { type: 'application/json' })
            );
            localStorage.removeItem(storeKey);
        }
        return;
    }

    // ----------------------------------------------------------------
    // CAS STATUS : heartbeat
    //
    // session_timeout = durée TOTALE du ticket ($(session-timeout))
    //   ex: '4h' → le plan tarifaire est identifié côté serveur
    //   Cette valeur est fixée à la connexion et ne change jamais.
    //
    // uptime = temps CONSOMMÉ depuis la connexion ($(uptime))
    //   Cette valeur grandit à chaque refresh de status.html.
    // ----------------------------------------------------------------
    var payload = {
        public_key:      publicKey,
        mac_address:     mac,
        session_key:     localStorage.getItem(storeKey) || null,
        ip_address:      get('ip'),
        uptime:          get('uptime')          || '',
        session_timeout: get('session-timeout') || '',
        bytes_in:        get('bytes-in')        || '0',
        bytes_out:       get('bytes-out')       || '0',
        username:        get('username'),
        session_id:      get('session-id'),
    };

    fetch(API + 'heartbeat/', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
    })
    .then(function (res) {
        if (!res.ok) { return; }
        return res.json();
    })
    .then(function (data) {
        // Stocker la session_key pour les heartbeats suivants
        // et pour le sendBeacon du logout
        if (data && data.session_key) {
            localStorage.setItem(storeKey, data.session_key);
        }
    })
    .catch(function (err) {
        // Erreur réseau silencieuse : ne pas alerter le client
        // Celery prend le relais de toute façon
        console.warn('[WFL Tracker] Heartbeat silencieux :', err.message);
    });

}(document, navigator, window.localStorage));
