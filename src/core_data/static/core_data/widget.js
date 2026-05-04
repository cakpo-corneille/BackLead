/**
 * WiFi Marketing Widget v4.0.0
 * Collecte de leads avec double opt-in pour portails captifs WiFi.
 *
 * Architecture : modules fonctionnels purs + orchestrateur unique.
 * Chaque section a une responsabilité unique et ne dépend pas des autres
 * sauf via les interfaces explicitement exportées.
 *
 * @license MIT
 */

(function bootstrap(window, document) {
    'use strict';

    // ─────────────────────────────────────────────────────────────────────────
    // FOUC GUARD
    // Exécuté en premier, de manière synchrone, avant tout rendu navigateur.
    // Masque la page hôte pendant l'initialisation du widget.
    // Un garde-fou libère automatiquement la page après FOUC_TIMEOUT ms.
    // ─────────────────────────────────────────────────────────────────────────

    const FOUC_TIMEOUT_MS = 10_000;

    (function installFoucGuard() {
        const style = document.createElement('style');
        style.id = 'cdw-fouc';
        style.textContent = 'body{visibility:hidden!important}';
        (document.head || document.documentElement).appendChild(style);

        setTimeout(() => Dom.revealPage(), FOUC_TIMEOUT_MS);
    })();


    // ─────────────────────────────────────────────────────────────────────────
    // CONFIG
    // Toutes les constantes de configuration en un seul endroit.
    // ─────────────────────────────────────────────────────────────────────────

    const _script  = document.currentScript;
    const _origin  = _script ? new URL(_script.src).origin : '';

    const CONFIG = Object.freeze({
        API_BASE:           `${_origin}/api/v1/portal/`,
        STORAGE_PREFIX:     'cdw_',
        OVERLAY_Z_INDEX:    99_999,
        ANIMATION_MS:       400,
        RESEND_COOLDOWN_MS: 60_000,
        TOAST_DURATION_MS:  4_000,
        GEO_TIMEOUT_MS:     2_000,
        OTP_LENGTH:         6,
        FOUC_TIMEOUT_MS,
        ITI: {
            CSS: `${_origin}/static/core_data/intl-tel-input/css/intlTelInput.min.css`,
            JS:  `${_origin}/static/core_data/intl-tel-input/js/intlTelInputWithUtils.min.js`,
        },
        /** Ordre d'affichage des pays dans le sélecteur téléphone. */
        COUNTRY_ORDER: [
            'bj','ci','sn','tg','ml','bf','ne','fr','be','ch','ca','us','gb',
            'dz','ao','bw','cd','cg','cm','cv','dj','eg','er','et','ga','gh',
            'gm','gn','gq','gw','ke','km','lr','ls','ly','ma','mg','mr','mu',
            'mw','mz','na','ng','rw','sc','sd','sl','so','ss','st','sz','td',
            'tn','tz','ug','za','zm','zw',
        ],
        /** Paramètres URL connus pour l'adresse MAC selon les constructeurs. */
        MAC_URL_PARAMS: [
            'mac','mac_address','client_mac','clientmac','id','clt_mac',
            'chilli_mac','clientMac','ap_mac','usermac','sta_mac','aruba_mac',
            'UserMac','user_mac','mac_addr','client-mac','sip',
        ],
    });


    // ─────────────────────────────────────────────────────────────────────────
    // LOGGER
    // Wrapping console pour préfixage uniforme et désactivation future facile.
    // ─────────────────────────────────────────────────────────────────────────

    const Log = {
        info:  (...a) => console.log('[CDW]',  ...a),
        warn:  (...a) => console.warn('[CDW]', ...a),
        error: (...a) => console.error('[CDW]',...a),
    };


    // ─────────────────────────────────────────────────────────────────────────
    // STORAGE
    // Abstraction localStorage : gestion des erreurs + préfixe automatique.
    // ─────────────────────────────────────────────────────────────────────────

    const Storage = {
        _key: (k) => `${CONFIG.STORAGE_PREFIX}${k}`,

        set(key, value) {
            try { localStorage.setItem(this._key(key), value); }
            catch { Log.warn('localStorage indisponible.'); }
        },

        get(key) {
            try { return localStorage.getItem(this._key(key)); }
            catch { return null; }
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // API CLIENT
    // Couche fetch centralisée : parsing JSON, normalisation des erreurs.
    // ─────────────────────────────────────────────────────────────────────────

    class ApiError extends Error {
        constructor(message, status, data) {
            super(message);
            this.name   = 'ApiError';
            this.status = status;
            this.data   = data;
        }
    }

    const Api = {
        async request(url, options = {}) {
            const response = await fetch(url, { ...options, credentials: 'include' });
            const data     = await response.json();

            if (!response.ok) {
                const message = (
                    data.detail ??
                    data.error  ??
                    data.message ??
                    (typeof data.payload === 'string' ? data.payload : null) ??
                    'Une erreur est survenue'
                );
                throw new ApiError(message, response.status, data);
            }

            return data;
        },

        post(endpoint, body) {
            return this.request(CONFIG.API_BASE + endpoint, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify(body),
            });
        },

        get(endpoint) {
            return this.request(CONFIG.API_BASE + endpoint, { method: 'GET' });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // PORTAL API
    // Appels métier : chaque méthode mappe 1-pour-1 un endpoint du portail.
    // ─────────────────────────────────────────────────────────────────────────

    const PortalApi = {
        provision(publicKey) {
            return Api.get(`provision/?public_key=${encodeURIComponent(publicKey)}`);
        },

        recognize(publicKey, macAddress, clientToken = null) {
            const body = { public_key: publicKey, mac_address: macAddress };
            if (clientToken) body.client_token = clientToken;
            return Api.post('recognize/', body);
        },

        submit(publicKey, macAddress, payload, clientToken, identityConfirmed = false) {
            return Api.post('submit/', {
                public_key:   publicKey,
                mac_address:  macAddress,
                payload,
                client_token: clientToken,
                ...(identityConfirmed && { identity_confirmed: true }),
            });
        },

        confirm(clientToken, code) {
            return Api.post('confirm/', { client_token: clientToken, code });
        },

        resend(clientToken) {
            return Api.post('resend/', { client_token: clientToken });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // DEVICE DETECTION
    // Résolution de la clé publique et de l'adresse MAC du client.
    // ─────────────────────────────────────────────────────────────────────────

    const MAC_REGEX = /^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$/;

    const Device = {
        _normalize: (mac) => mac.toUpperCase().replace(/-/g, ':'),
        _isValid:   (mac) => MAC_REGEX.test(mac),

        _scriptTag() {
            return document.currentScript
                ?? document.querySelector('script[data-public-key]')
                ?? null;
        },

        _urlParam(name) {
            const match = new RegExp(`[?&]${name}=([^&]*)`, 'i').exec(window.location.search);
            return match ? decodeURIComponent(match[1]) : null;
        },

        resolvePublicKey(options = {}) {
            const tag = this._scriptTag();
            return (
                options.public_key                           ??
                tag?.getAttribute('data-public-key')         ??
                this._urlParam('public_key')                 ??
                null
            );
        },

        resolveMAC() {
            // 1. Attribut data-mac (MikroTik, OpenNDS via template serveur)
            const tag     = this._scriptTag();
            const rawAttr = tag?.getAttribute('data-mac');

            if (rawAttr && rawAttr !== '$(mac)') {
                const normalized = this._normalize(rawAttr);
                if (this._isValid(normalized)) {
                    Log.info('MAC depuis data-mac :', normalized);
                    return normalized;
                }
            }

            // 2. Paramètres URL (UniFi, Coova-Chilli, Meraki, Aruba…)
            for (const param of CONFIG.MAC_URL_PARAMS) {
                const val = this._urlParam(param);
                if (!val) continue;
                const normalized = this._normalize(val);
                if (this._isValid(normalized)) {
                    Log.info(`MAC depuis ?${param}= :`, normalized);
                    return normalized;
                }
            }

            Log.warn(
                'Adresse MAC introuvable.\n' +
                '  → MikroTik / OpenNDS : ajoutez data-mac="$(mac)" sur <script>.\n' +
                '  → UniFi / Coova-Chilli / Meraki : vérifiez le paramètre MAC dans la redirection.'
            );
            return null;
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // ASSET LOADER
    // Chargement idempotent de feuilles de style et scripts externes.
    // ─────────────────────────────────────────────────────────────────────────

    const Loader = {
        style(url) {
            if (document.querySelector(`link[href="${url}"]`)) return;
            const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', href: url });
            document.head.appendChild(link);
        },

        script(url) {
            if (document.querySelector(`script[src="${url}"]`)) return Promise.resolve();
            return new Promise((resolve, reject) => {
                const s   = Object.assign(document.createElement('script'), { src: url });
                s.onload  = resolve;
                s.onerror = () => reject(new Error(`Impossible de charger : ${url}`));
                document.head.appendChild(s);
            });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // DOM HELPERS
    // Utilitaires DOM purs : pas d'état, pas d'effets de bord globaux.
    // ─────────────────────────────────────────────────────────────────────────

    const Dom = {
        revealPage() {
            document.body.style.visibility = '';
            document.getElementById('cdw-fouc')?.remove();
        },

        lockScroll() {
            document.documentElement.style.overflow = 'hidden';
            document.body.style.overflow = 'hidden';
        },

        unlockScroll() {
            document.documentElement.style.overflow = '';
            document.body.style.overflow = '';
        },

        /**
         * Crée un élément HTML avec props et enfants en une seule passe.
         * @param {string} tag
         * @param {Object} [props]
         * @param {...(HTMLElement|string|null)} children
         */
        el(tag, props = {}, ...children) {
            const element = Object.assign(document.createElement(tag), props);
            for (const child of children) {
                if (child == null) continue;
                element.append(typeof child === 'string' ? document.createTextNode(child) : child);
            }
            return element;
        },

        /** Remplace tous les enfants d'un conteneur. */
        replace(container, ...children) {
            container.replaceChildren(...children.filter(Boolean));
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // STYLES
    // Injection CSS unique et idempotente. Préfixe cdw- sur toutes les classes.
    // ─────────────────────────────────────────────────────────────────────────

    const Styles = {
        inject() {
            if (document.getElementById('cdw-styles')) return;

            const Z = CONFIG.OVERLAY_Z_INDEX;
            const D = CONFIG.ANIMATION_MS;

            const css = `
                *{box-sizing:border-box}
                #cdw-overlay{
                    position:fixed;inset:0;
                    background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(139,92,246,.1)),rgba(0,0,0,.75);
                    backdrop-filter:blur(8px);
                    display:flex;align-items:center;justify-content:center;
                    z-index:${Z};padding:20px;
                    opacity:0;animation:cdw-fadeIn ${D}ms cubic-bezier(.4,0,.2,1) forwards;
                }
                @keyframes cdw-fadeIn{to{opacity:1}}
                @keyframes cdw-fadeOut{to{opacity:0}}
                @keyframes cdw-slideUp{
                    from{opacity:0;transform:translateY(30px) scale(.95)}
                    to{opacity:1;transform:translateY(0) scale(1)}
                }
                @keyframes cdw-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
                @keyframes cdw-slideInRight{
                    from{opacity:0;transform:translateX(100px)}
                    to{opacity:1;transform:translateX(0)}
                }
                @keyframes cdw-spin{to{transform:rotate(360deg)}}
                .cdw-modal{
                    background:#fff;border-radius:20px;
                    max-width:440px;width:100%;max-height:85vh;overflow:hidden;
                    box-shadow:0 25px 50px -12px rgba(0,0,0,.4),0 0 0 1px rgba(0,0,0,.05);
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;
                    animation:cdw-slideUp ${D}ms cubic-bezier(.4,0,.2,1);
                    display:flex;flex-direction:column;
                }
                .cdw-modal-content{overflow-y:auto;padding:32px 28px;flex:1}
                .cdw-modal-content::-webkit-scrollbar{width:8px}
                .cdw-modal-content::-webkit-scrollbar-track{background:transparent;margin:12px 0}
                .cdw-modal-content::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:4px}
                .cdw-modal-content::-webkit-scrollbar-thumb:hover{background:#9ca3af}
                .cdw-header{text-align:center;margin-bottom:28px}
                .cdw-brand{display:flex;align-items:center;justify-content:center;gap:12px;margin-bottom:12px}
                .cdw-logo{width:56px;height:56px;border-radius:50%;object-fit:cover;
                    box-shadow:0 4px 12px rgba(0,0,0,.15);border:3px solid #fff;flex-shrink:0}
                .cdw-business-name{font-size:22px;font-weight:700;color:#111827;margin:0;
                    letter-spacing:-.02em;line-height:1.2;text-align:left;flex:1;word-break:break-word}
                .cdw-cta{font-size:15px;color:#6b7280;margin:0;line-height:1.5}
                .cdw-form{display:flex;flex-direction:column;gap:18px}
                .cdw-field{display:flex;flex-direction:column;gap:8px}
                .cdw-label{font-size:14px;font-weight:600;color:#374151;display:flex;align-items:center;gap:4px}
                .cdw-required{color:#ef4444;font-size:16px}
                .cdw-input,.cdw-select{
                    width:100%;padding:12px 16px;border:2px solid #e5e7eb;border-radius:12px;
                    font-size:15px;background:#f9fafb;color:#111827;
                    transition:all .2s cubic-bezier(.4,0,.2,1);font-family:inherit;
                }
                .cdw-input::placeholder{color:#9ca3af}
                .cdw-input:hover,.cdw-select:hover{border-color:#d1d5db;background:#fff}
                .cdw-input:focus,.cdw-select:focus{
                    outline:none;border-color:#6366f1;background:#fff;
                    box-shadow:0 0 0 4px rgba(99,102,241,.1);
                }
                .cdw-input:disabled,.cdw-select:disabled{background:#f3f4f6;cursor:not-allowed;opacity:.6}
                .cdw-checkbox-wrapper{
                    display:flex;align-items:flex-start;gap:12px;padding:12px;
                    background:#f9fafb;border-radius:12px;border:2px solid #e5e7eb;
                    transition:all .2s;cursor:pointer;
                }
                .cdw-checkbox-wrapper:hover{border-color:#d1d5db;background:#fff}
                .cdw-checkbox{width:20px;height:20px;cursor:pointer;margin-top:2px;flex-shrink:0}
                .cdw-checkbox-label{flex:1;font-size:14px;color:#374151;line-height:1.5;cursor:pointer}
                .cdw-submit{
                    margin-top:8px;width:100%;padding:14px 24px;border:none;border-radius:12px;
                    font-size:16px;font-weight:600;
                    background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);
                    color:#fff;cursor:pointer;transition:all .2s ease;
                    box-shadow:0 4px 12px rgba(99,102,241,.4);
                }
                .cdw-submit:hover:not(:disabled){box-shadow:0 6px 16px rgba(99,102,241,.5);transform:translateY(-1px)}
                .cdw-submit:active:not(:disabled){transform:translateY(0)}
                .cdw-submit:disabled{background:#9ca3af;cursor:not-allowed;box-shadow:none;transform:none}
                .cdw-spinner{
                    display:inline-block;width:16px;height:16px;
                    border:2px solid rgba(255,255,255,.3);border-top-color:#fff;
                    border-radius:50%;animation:cdw-spin .8s linear infinite;
                    margin-right:8px;vertical-align:middle;
                }
                .cdw-toast{
                    position:fixed;top:20px;right:20px;max-width:400px;
                    padding:16px 20px;border-radius:12px;font-size:14px;
                    display:flex;align-items:flex-start;gap:12px;
                    z-index:${Z + 1};box-shadow:0 10px 25px rgba(0,0,0,.2);
                    animation:cdw-slideInRight .3s ease;
                }
                .cdw-toast-icon{
                    flex-shrink:0;width:24px;height:24px;border-radius:50%;
                    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;
                }
                .cdw-toast-content{flex:1;line-height:1.5}
                .cdw-toast-error{background:#fef2f2;border:2px solid #fecaca;color:#991b1b}
                .cdw-toast-error .cdw-toast-icon{background:#dc2626;color:#fff}
                .cdw-toast-success{background:#f0fdf4;border:2px solid #bbf7d0;color:#166534}
                .cdw-toast-success .cdw-toast-icon{background:#22c55e;color:#fff}
                .cdw-toast-info{background:#eff6ff;border:2px solid #bfdbfe;color:#1e40af}
                .cdw-toast-info .cdw-toast-icon{background:#3b82f6;color:#fff}
                .cdw-message{
                    padding:14px 16px;border-radius:12px;font-size:14px;
                    margin-bottom:16px;display:flex;align-items:flex-start;gap:12px;line-height:1.5;
                }
                .cdw-message-icon{
                    flex-shrink:0;width:20px;height:20px;border-radius:50%;
                    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;
                }
                .cdw-message-content{flex:1}
                .cdw-message-error{background:#fef2f2;border:2px solid #fecaca;color:#991b1b}
                .cdw-message-error .cdw-message-icon{background:#dc2626;color:#fff}
                .cdw-message-success{background:#f0fdf4;border:2px solid #bbf7d0;color:#166534}
                .cdw-message-success .cdw-message-icon{background:#22c55e;color:#fff}
                .cdw-message-info{background:#eff6ff;border:2px solid #bfdbfe;color:#1e40af}
                .cdw-message-info .cdw-message-icon{background:#3b82f6;color:#fff}
                .cdw-verification{text-align:center;padding:24px 0}
                .cdw-verification-icon{
                    width:64px;height:64px;margin:0 auto 16px;
                    background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);
                    border-radius:50%;display:flex;align-items:center;justify-content:center;
                    color:#fff;font-size:32px;animation:cdw-pulse 2s infinite;
                }
                .cdw-verification-title{font-size:20px;font-weight:700;color:#111827;margin:0 0 8px}
                .cdw-verification-text{font-size:14px;color:#6b7280;margin:0 0 24px;line-height:1.6}
                .cdw-code-inputs{display:flex;gap:12px;justify-content:center;margin-bottom:24px}
                .cdw-code-input{
                    width:52px;height:60px;font-size:24px;font-weight:700;
                    text-align:center;border:2px solid #e5e7eb;border-radius:12px;
                    background:#f9fafb;color:#111827;transition:all .2s;
                }
                .cdw-code-input:focus{
                    outline:none;border-color:#6366f1;background:#fff;
                    box-shadow:0 0 0 4px rgba(99,102,241,.1);
                }
                .cdw-resend-link{
                    display:inline-block;color:#6366f1;text-decoration:none;
                    font-size:14px;font-weight:600;margin-top:16px;transition:color .2s;cursor:pointer;
                }
                .cdw-resend-link:hover:not(.cdw-disabled){color:#4f46e5;text-decoration:underline}
                .cdw-resend-link.cdw-disabled{color:#9ca3af;cursor:not-allowed;text-decoration:none}
                .cdw-identity-confirm{text-align:center;padding:16px 0}
                .cdw-identity-msg{font-size:15px;color:#374151;margin:0 0 20px;line-height:1.6}
                .cdw-identity-actions{display:flex;flex-direction:column;gap:12px}
                .cdw-btn{
                    width:100%;padding:12px 24px;border-radius:12px;font-size:15px;
                    font-weight:600;cursor:pointer;border:2px solid transparent;transition:all .2s;
                }
                .cdw-btn-primary{background:#6366f1;color:#fff;border-color:#6366f1}
                .cdw-btn-primary:hover{background:#4f46e5;border-color:#4f46e5}
                .cdw-btn-secondary{background:#fff;color:#374151;border-color:#e5e7eb}
                .cdw-btn-secondary:hover{border-color:#d1d5db;background:#f9fafb}
                .cdw-field-error,.cdw-phone-error,.cdw-verification-error{
                    font-size:13px;color:#dc2626;margin-top:4px;display:none;
                }
                .cdw-field-error.visible,.cdw-phone-error.visible,.cdw-verification-error.visible{display:block}
                .cdw-verification-error{margin-top:8px;margin-bottom:4px;min-height:18px}
                .cdw-phone-error{margin-top:6px}
                .cdw-verification-spinner{margin-top:12px;text-align:center}
                .cdw-verification-spinner .cdw-spinner{width:22px;height:22px;border-width:3px}
                .iti{width:100%}
                .iti__input,.iti input[type=tel]{
                    width:100%!important;padding:12px 16px!important;padding-left:58px!important;
                    border:2px solid #e5e7eb!important;border-radius:12px!important;
                    font-size:15px!important;background:#f9fafb!important;color:#111827!important;
                    transition:all .2s cubic-bezier(.4,0,.2,1)!important;
                    height:auto!important;font-family:inherit!important;
                }
                .iti__input:focus,.iti input[type=tel]:focus{
                    outline:none!important;border-color:#6366f1!important;background:#fff!important;
                    box-shadow:0 0 0 4px rgba(99,102,241,.1)!important;
                }
                .iti__selected-dial-code{display:none!important}
                .iti__dropdown-content{z-index:${Z + 10}!important;max-height:220px!important}
                .iti__country-list{
                    border-radius:12px!important;box-shadow:0 10px 25px rgba(0,0,0,.15)!important;
                    border:1px solid #e5e7eb!important;max-height:200px!important;overflow-y:auto!important;
                }
                .iti__search-input{
                    padding:10px 14px!important;font-size:14px!important;height:42px!important;
                    border-bottom:1px solid #e5e7eb!important;width:100%!important;
                    box-sizing:border-box!important;outline:none!important;
                }
                .iti__dial-code{color:#6366f1!important}
                @media(max-width:480px){
                    .cdw-modal-content{padding:24px 20px}
                    .cdw-business-name{font-size:18px}
                    .cdw-logo{width:48px;height:48px}
                    .cdw-code-input{width:44px;height:52px;font-size:20px}
                    .cdw-toast{left:20px;right:20px;max-width:none}
                }
            `;

            document.head.appendChild(
                Object.assign(document.createElement('style'), { id: 'cdw-styles', textContent: css })
            );
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // UI — COMPOSANTS ATOMIQUES
    // Fonctions pures retournant des éléments DOM. Aucun effet de bord.
    // ─────────────────────────────────────────────────────────────────────────

    const UI = {

        /** Écran de chargement plein écran affiché pendant l'init. */
        loadingScreen() {
            const el = Dom.el('div', { id: 'cdw-loading-screen' });
            el.style.cssText = [
                'position:fixed','inset:0',
                `z-index:${CONFIG.OVERLAY_Z_INDEX + 1}`,
                'display:flex','align-items:center','justify-content:center',
                'background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(139,92,246,.1)),rgba(0,0,0,.65)',
                'backdrop-filter:blur(8px)',
                'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
            ].join(';');

            el.appendChild(Dom.el('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:20px' },
                Dom.el('div', {
                    style: 'width:48px;height:48px;border:4px solid rgba(255,255,255,.25);' +
                           'border-top-color:#fff;border-radius:50%;animation:cdw-spin .8s linear infinite',
                }),
                Dom.el('p', {
                    style: 'color:rgba(255,255,255,.9);font-size:15px;font-weight:500;margin:0',
                    textContent: 'Connexion en cours\u2026',
                }),
            ));

            document.body.appendChild(el);
            return el;
        },

        removeLoadingScreen(el) {
            if (!el?.parentNode) return;
            el.style.transition = 'opacity .25s ease';
            el.style.opacity = '0';
            setTimeout(() => el.parentNode?.removeChild(el), 260);
        },

        overlay() {
            return Dom.el('div', { id: 'cdw-overlay' });
        },

        modal() {
            const content = Dom.el('div', { className: 'cdw-modal-content' });
            const modal   = Dom.el('div', { className: 'cdw-modal' }, content);
            return { modal, content };
        },

        toast(type, text) {
            document.querySelector('.cdw-toast')?.remove();
            const ICONS = { error: '!', success: '✓', info: 'i' };

            const el = Dom.el('div', { className: `cdw-toast cdw-toast-${type}` },
                Dom.el('div', { className: 'cdw-toast-icon', textContent: ICONS[type] ?? 'i' }),
                Dom.el('div', { className: 'cdw-toast-content', textContent: text }),
            );

            document.body.appendChild(el);
            setTimeout(() => {
                el.style.animation = 'cdw-fadeOut .3s ease';
                setTimeout(() => el.remove(), 300);
            }, CONFIG.TOAST_DURATION_MS);
        },

        inlineMessage(container, type, text) {
            container.querySelector('.cdw-message')?.remove();
            const ICONS = { error: '!', success: '✓', info: 'i' };
            container.insertBefore(
                Dom.el('div', { className: `cdw-message cdw-message-${type}` },
                    Dom.el('div', { className: 'cdw-message-icon', textContent: ICONS[type] ?? 'i' }),
                    Dom.el('div', { className: 'cdw-message-content', textContent: text }),
                ),
                container.firstChild,
            );
        },

        header(provision) {
            const owner        = provision?.owner ?? {};
            const logoUrl      = provision?.logo_url ?? owner.logo_url ?? owner.logo ?? null;
            const businessName = provision?.title ?? owner.name ?? owner.business_name ?? 'WiFi Public';
            const description  = provision?.description ?? 'Partagez vos coordonnées pour profiter du WiFi gratuit';

            return Dom.el('div', { className: 'cdw-header' },
                Dom.el('div', { className: 'cdw-brand' },
                    logoUrl ? Dom.el('img', { src: logoUrl, className: 'cdw-logo', alt: businessName }) : null,
                    Dom.el('div', { className: 'cdw-business-name', textContent: businessName }),
                ),
                Dom.el('p', { className: 'cdw-cta', textContent: description }),
            );
        },

        _fieldLabel(fieldData) {
            return Dom.el('label', { className: 'cdw-label', htmlFor: `cdw-field-${fieldData.name}` },
                Dom.el('span', { textContent: fieldData.label ?? fieldData.name }),
                fieldData.required ? Dom.el('span', { className: 'cdw-required', textContent: '*' }) : null,
            );
        },

        _booleanField(fieldData) {
            return Dom.el('div', { className: 'cdw-field' },
                Dom.el('label', { className: 'cdw-checkbox-wrapper' },
                    Dom.el('input', { type: 'checkbox', name: fieldData.name,
                        className: 'cdw-checkbox', id: `cdw-field-${fieldData.name}` }),
                    Dom.el('span', { className: 'cdw-checkbox-label',
                        textContent: fieldData.label ?? fieldData.name }),
                ),
            );
        },

        _phoneField(fieldData) {
            const error = Dom.el('div', { className: 'cdw-field-error cdw-phone-error',
                textContent: 'Numéro de téléphone invalide' });
            error.dataset.field = fieldData.name;
            return Dom.el('div', { className: 'cdw-field' },
                this._fieldLabel(fieldData),
                Dom.el('input', { id: `cdw-field-${fieldData.name}`, name: fieldData.name,
                    type: 'tel', className: 'cdw-input cdw-phone-input', required: !!fieldData.required }),
                error,
            );
        },

        _selectField(fieldData) {
            const sel = Dom.el('select', {
                className: 'cdw-select', name: fieldData.name,
                id: `cdw-field-${fieldData.name}`, required: !!fieldData.required,
            });
            sel.appendChild(Dom.el('option', { value: '', textContent: 'Sélectionnez une option',
                disabled: true, selected: true }));
            (fieldData.choices ?? []).forEach((c) =>
                sel.appendChild(Dom.el('option', { value: c, textContent: c }))
            );
            return sel;
        },

        _inputField(fieldData) {
            const TYPE_MAP = {
                email:  { type: 'email',  placeholder: 'exemple@email.com', autocomplete: 'email' },
                number: { type: 'number', placeholder: 'Entrez un nombre' },
            };
            const cfg = TYPE_MAP[fieldData.type] ?? {
                type: 'text',
                placeholder: fieldData.placeholder
                    ?? `Entrez ${(fieldData.label ?? fieldData.name).toLowerCase()}`,
                autocomplete: 'off',
            };
            return Dom.el('input', { ...cfg, className: 'cdw-input',
                name: fieldData.name, id: `cdw-field-${fieldData.name}`,
                required: !!fieldData.required });
        },

        formField(fieldData) {
            if (fieldData.type === 'boolean') return this._booleanField(fieldData);
            if (fieldData.type === 'phone')   return this._phoneField(fieldData);

            const inputEl = fieldData.type === 'choice'
                ? this._selectField(fieldData)
                : this._inputField(fieldData);

            const error = Dom.el('div', { className: 'cdw-field-error' });
            error.dataset.field = fieldData.name;

            return Dom.el('div', { className: 'cdw-field' },
                this._fieldLabel(fieldData), inputEl, error,
            );
        },

        form(schema, provision) {
            const buttonLabel = provision?.button_label ?? 'Accéder au WiFi';
            const submitBtn   = Dom.el('button', {
                type: 'submit', className: 'cdw-submit', textContent: buttonLabel,
            });

            const form = Dom.el('form', { className: 'cdw-form', noValidate: true },
                ...(schema.fields ?? []).map((f) => this.formField(f)),
                submitBtn,
            );

            const container = Dom.el('div', {}, this.header(provision), form);
            return { container, form, submitBtn, buttonLabel };
        },

        verificationView(onComplete) {
            const errorZone   = Dom.el('div', { className: 'cdw-verification-error' });
            const spinnerZone = Dom.el('div', { className: 'cdw-verification-spinner',
                style: 'display:none' },
                Dom.el('span', { className: 'cdw-spinner',
                    style: 'border-color:rgba(99,102,241,.3);border-top-color:#6366f1' }),
            );
            const codeInputs = Dom.el('div', { className: 'cdw-code-inputs' });

            const showError = (msg) => {
                errorZone.textContent = msg;
                errorZone.classList.add('visible');
                spinnerZone.style.display = 'none';
                this.clearOtpInputs(codeInputs);
            };

            const setLoading = (loading) => {
                spinnerZone.style.display = loading ? 'block' : 'none';
                errorZone.classList.remove('visible');
                Array.from(codeInputs.children).forEach((inp) => { inp.disabled = loading; });
            };

            for (let idx = 0; idx < CONFIG.OTP_LENGTH; idx++) {
                const input = Dom.el('input', {
                    type: 'text', className: 'cdw-code-input',
                    maxLength: 1, pattern: '[0-9]', inputMode: 'numeric',
                });
                input.dataset.index = idx;

                input.addEventListener('input', (e) => {
                    e.target.value = e.target.value.replace(/\D/g, '');
                    errorZone.classList.remove('visible');
                    if (e.target.value.length !== 1) return;
                    if (idx < CONFIG.OTP_LENGTH - 1) {
                        codeInputs.children[idx + 1].focus();
                        return;
                    }
                    const code = Array.from(codeInputs.children).map((i) => i.value).join('');
                    if (code.length === CONFIG.OTP_LENGTH) {
                        setLoading(true);
                        onComplete(code, showError, setLoading);
                    }
                });

                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Backspace' && !e.target.value && idx > 0) {
                        codeInputs.children[idx - 1].focus();
                    }
                });

                codeInputs.appendChild(input);
            }

            const resendLink = Dom.el('a', {
                href: '#', className: 'cdw-resend-link', textContent: 'Renvoyer le code',
            });

            const container = Dom.el('div', { className: 'cdw-verification' },
                Dom.el('div', { className: 'cdw-verification-icon', textContent: '📱' }),
                Dom.el('h2', { className: 'cdw-verification-title', textContent: 'Vérification requise' }),
                Dom.el('p', { className: 'cdw-verification-text',
                    textContent: 'Un code de vérification a été envoyé. Veuillez le saisir ci-dessous.' }),
                codeInputs, errorZone, spinnerZone, resendLink,
            );

            return { container, codeInputs, resendLink };
        },

        identityConfirmView(onConfirm, onDeny) {
            const btnYes = Dom.el('button', { type: 'button', className: 'cdw-btn cdw-btn-primary',
                textContent: "Oui, c'est moi" });
            const btnNo  = Dom.el('button', { type: 'button', className: 'cdw-btn cdw-btn-secondary',
                textContent: "Non, ce n'est pas moi" });
            btnYes.addEventListener('click', onConfirm);
            btnNo.addEventListener('click', onDeny);
            return Dom.el('div', { className: 'cdw-identity-confirm' },
                Dom.el('p', { className: 'cdw-identity-msg',
                    textContent: 'Ce contact est déjà associé à un compte. Est-ce bien vous ?' }),
                Dom.el('div', { className: 'cdw-identity-actions' }, btnYes, btnNo),
            );
        },

        clearOtpInputs(codeInputs) {
            Array.from(codeInputs.children).forEach((inp) => { inp.value = ''; inp.disabled = false; });
            codeInputs.children[0]?.focus();
        },

        setButtonLoading(btn, loading, label) {
            btn.disabled = loading;
            btn.innerHTML = loading ? `<span class="cdw-spinner"></span>${label}` : label;
        },

        showFieldErrors(form, payloadErrors) {
            let hasErrors = false;
            for (const [field, msg] of Object.entries(payloadErrors)) {
                const el = form.querySelector(`.cdw-field-error[data-field="${field}"]`);
                if (!el) continue;
                el.textContent = Array.isArray(msg) ? msg.join(' ') : msg;
                el.classList.add('visible');
                hasErrors = true;
            }
            return hasErrors;
        },

        clearFieldErrors(form) {
            form.querySelectorAll('.cdw-field-error').forEach((el) => {
                el.textContent = '';
                el.classList.remove('visible');
            });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // PHONE CONTROLLER
    // Initialisation et validation intl-tel-input.
    // ─────────────────────────────────────────────────────────────────────────

    const PhoneController = {
        async _detectCountry() {
            try {
                const data = await Promise.race([
                    fetch('https://ipapi.co/json').then((r) => r.json()),
                    new Promise((_, reject) =>
                        setTimeout(() => reject(new Error('timeout')), CONFIG.GEO_TIMEOUT_MS)
                    ),
                ]);
                return data?.country_code ?? 'bj';
            } catch {
                return 'bj';
            }
        },

        async init(phoneInput) {
            if (!phoneInput || !window.intlTelInput) return null;

            const iti = window.intlTelInput(phoneInput, {
                initialCountry:       'auto',
                geoIpLookup:          (cb) => this._detectCountry().then(cb),
                countryOrder:         CONFIG.COUNTRY_ORDER,
                separateDialCode:     false,
                showSelectedDialCode: false,
                allowDropdown:        true,
            });

            phoneInput.addEventListener('open:countrydropdown', () => {
                requestAnimationFrame(() => {
                    const dropdown = document.querySelector('.iti__dropdown-content');
                    if (!dropdown) return;
                    const overflow = dropdown.getBoundingClientRect().bottom - window.innerHeight + 10;
                    if (overflow > 0) {
                        dropdown.style.top = `${parseFloat(dropdown.style.top || '0') - overflow}px`;
                    }
                });
            });

            return iti;
        },

        attachValidation(phoneInput, iti) {
            if (!phoneInput || !iti) return;
            const errorEl = phoneInput.closest('.cdw-field')?.querySelector('.cdw-phone-error');
            if (!errorEl) return;
            phoneInput.addEventListener('blur', () => {
                if (!phoneInput.value) return;
                errorEl.classList.toggle('visible', !iti.isValidNumber());
            });
            phoneInput.addEventListener('input', () => errorEl.classList.remove('visible'));
        },

        getValue(input, iti) {
            return iti ? iti.getNumber() : (input?.value ?? null);
        },

        validate(form, iti) {
            if (!iti || iti.isValidNumber()) return true;
            const errorEl = form.querySelector('.cdw-phone-error');
            if (errorEl) {
                errorEl.textContent = 'Veuillez saisir un numéro de téléphone valide.';
                errorEl.classList.add('visible');
            }
            return false;
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // RESEND CONTROLLER
    // Gestion du lien "renvoyer le code" avec cooldown.
    // ─────────────────────────────────────────────────────────────────────────

    const ResendController = {
        attach(resendLink, clientToken, codeInputs) {
            resendLink.addEventListener('click', async (e) => {
                e.preventDefault();
                if (resendLink.classList.contains('cdw-disabled')) return;

                resendLink.classList.add('cdw-disabled');
                const label = resendLink.textContent;
                resendLink.textContent = 'Envoi en cours…';

                try {
                    await PortalApi.resend(clientToken);
                    resendLink.textContent = label;
                    UI.toast('success', 'Nouveau code envoyé');
                    UI.clearOtpInputs(codeInputs);
                    setTimeout(() => resendLink.classList.remove('cdw-disabled'), CONFIG.RESEND_COOLDOWN_MS);
                } catch (err) {
                    resendLink.classList.remove('cdw-disabled');
                    resendLink.textContent = label;
                    UI.toast('error', err.message);
                }
            });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // MODAL CONTROLLER
    // Cycle de vie du modal : montage, animation, démontage.
    // ─────────────────────────────────────────────────────────────────────────

    const ModalController = {
        mount(overlay, modal, content, loadingScreen) {
            overlay.appendChild(modal);
            document.body.appendChild(overlay);
            Dom.lockScroll();
            Dom.revealPage();
            UI.removeLoadingScreen(loadingScreen);
        },

        dismiss(overlay, callback) {
            Dom.unlockScroll();
            overlay.style.animation = `cdw-fadeOut ${CONFIG.ANIMATION_MS}ms ease`;
            setTimeout(() => { overlay.remove(); callback?.(); }, CONFIG.ANIMATION_MS);
        },

        showVerification(modalContent, provision, clientToken, { onSuccess, onClose }) {
            const verif = UI.verificationView(async (code, showError) => {
                try {
                    await PortalApi.confirm(clientToken, code);
                    onSuccess();
                } catch (err) {
                    (err.status === 400 || err.status === 422)
                        ? showError(err.message ?? 'Code incorrect, veuillez réessayer.')
                        : onClose();
                }
            });

            Dom.replace(modalContent, UI.header(provision), verif.container);
            verif.codeInputs.children[0]?.focus();
            ResendController.attach(verif.resendLink, clientToken, verif.codeInputs);
        },

        showIdentityConflict(modalContent, provision, submitBody, { onClose, onRestore }) {
            const view = UI.identityConfirmView(
                async () => {
                    try {
                        const result = await PortalApi.submit(
                            submitBody.public_key, submitBody.mac_address,
                            submitBody.payload, submitBody.client_token, true
                        );
                        if (result.client_token) Storage.set(`token_${submitBody.public_key}`, result.client_token);
                        UI.toast('success', 'Informations enregistrées avec succès.');
                        onClose();
                    } catch { onClose(); }
                },
                () => onRestore(),
            );
            Dom.replace(modalContent, UI.header(provision), view);
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // FORM CONTROLLER
    // Sérialisation du formulaire et dispatch des résultats API.
    // ─────────────────────────────────────────────────────────────────────────

    const FormController = {
        serialize(form, iti) {
            const payload = {};
            for (const [key, value] of new FormData(form).entries()) {
                const input = form.querySelector(`[name="${key}"]`);
                if (!input) continue;

                if (input.classList.contains('cdw-phone-input')) {
                    payload[key] = PhoneController.getValue(input, iti);
                } else if (input.type === 'checkbox') {
                    payload[key] = input.checked;
                } else if (input.type === 'number') {
                    payload[key] = value ? Number(value) : null;
                } else {
                    payload[key] = value || null;
                }
            }
            return payload;
        },

        attachSubmitHandler({ formData, modalContent, overlay, provision, publicKey, macAddress, storedToken, iti, doubleOpt }) {
            formData.form.addEventListener('submit', async (e) => {
                e.preventDefault();
                UI.clearFieldErrors(formData.form);

                if (!PhoneController.validate(formData.form, iti)) return;
                if (!formData.form.checkValidity()) { formData.form.reportValidity(); return; }

                UI.setButtonLoading(formData.submitBtn, true, 'Envoi en cours…');

                const payload    = this.serialize(formData.form, iti);
                const submitBody = { public_key: publicKey, mac_address: macAddress,
                    payload, client_token: storedToken };

                const close = (msg) => {
                    if (msg) UI.toast('success', msg);
                    ModalController.dismiss(overlay);
                };

                try {
                    const result = await PortalApi.submit(publicKey, macAddress, payload, storedToken);

                    if (result.client_token) Storage.set(`token_${publicKey}`, result.client_token);

                    if (result.identity_conflict) {
                        ModalController.showIdentityConflict(modalContent, provision, submitBody, {
                            onClose:   () => close(),
                            onRestore: () => {
                                Dom.replace(modalContent, formData.container);
                                formData.form.reset();
                                UI.setButtonLoading(formData.submitBtn, false, formData.buttonLabel);
                            },
                        });
                        return;
                    }

                    if (doubleOpt && result.requires_verification) {
                        if (result.message) UI.toast('info', result.message);
                        ModalController.showVerification(modalContent, provision, result.client_token, {
                            onSuccess: () => close('Informations enregistrées avec succès !'),
                            onClose:   () => ModalController.dismiss(overlay),
                        });
                        return;
                    }

                    close('Merci ! Vos informations ont été enregistrées.');

                } catch (err) {
                    if (!err.status || err.status >= 500) { ModalController.dismiss(overlay); return; }

                    UI.setButtonLoading(formData.submitBtn, false, formData.buttonLabel);

                    const payloadErrors = err.data?.payload;
                    const hasFieldErrors = (
                        err.status === 400 &&
                        payloadErrors &&
                        typeof payloadErrors === 'object' &&
                        !Array.isArray(payloadErrors) &&
                        UI.showFieldErrors(formData.form, payloadErrors)
                    );

                    if (!hasFieldErrors) {
                        UI.inlineMessage(formData.container, 'error',
                            err.status === 404
                                ? "Service introuvable. Contactez l'administrateur."
                                : (err.message ?? 'Une erreur est survenue')
                        );
                    }
                }
            });
        },
    };


    // ─────────────────────────────────────────────────────────────────────────
    // ORCHESTRATEUR
    // Point d'entrée unique. Séquence linéaire et lisible de bout en bout.
    // Toute la logique métier est déléguée aux modules ci-dessus.
    // ─────────────────────────────────────────────────────────────────────────

    async function init(options = {}) {
        const publicKey  = Device.resolvePublicKey(options);
        const macAddress = Device.resolveMAC();

        if (!publicKey)  { Log.error('Clé publique manquante.'); return; }
        if (!macAddress) { Log.error('Adresse MAC introuvable.'); return; }

        Styles.inject();
        const loadingScreen = UI.loadingScreen();

        try {
            const storedToken = Storage.get(`token_${publicKey}`);

            // Appels parallèles : reconnaissance client + configuration portail
            const [recognizeResult, provision] = await Promise.all([
                PortalApi.recognize(publicKey, macAddress, storedToken).catch(() =>
                    ({ recognized: false, is_verified: false })
                ),
                PortalApi.provision(publicKey),
            ]);

            if (provision.enable === false) {
                Log.info('Widget désactivé par le portail owner.');
                return;
            }

            const doubleOpt = provision.opt === true;

            Loader.style(CONFIG.ITI.CSS);
            const itiScriptPromise = Loader.script(CONFIG.ITI.JS);

            // Branche A : client reconnu
            if (recognizeResult.recognized) {
                Log.info('Client reconnu.');
                if (recognizeResult.client_token) Storage.set(`token_${publicKey}`, recognizeResult.client_token);

                if (doubleOpt && !recognizeResult.is_verified) {
                    const { modal, content } = UI.modal();
                    const overlay = UI.overlay();

                    ModalController.showVerification(content, provision, recognizeResult.client_token, {
                        onSuccess: () => { UI.toast('success', 'Compte vérifié avec succès !'); ModalController.dismiss(overlay); },
                        onClose:   () => ModalController.dismiss(overlay),
                    });

                    ModalController.mount(overlay, modal, content, loadingScreen);
                    UI.toast('info', 'Veuillez vérifier votre compte pour continuer.');
                    return;
                }

                return; // Client déjà vérifié → accès direct
            }

            // Branche B : nouveau client → affichage du formulaire
            Log.info('Nouveau client. Chargement du formulaire…');

            const hasPhone = (provision.schema?.fields ?? []).some((f) => f.type === 'phone');
            if (hasPhone) await itiScriptPromise;

            const { modal, content } = UI.modal();
            const overlay  = UI.overlay();
            const formData = UI.form(provision.schema ?? { fields: [] }, provision);

            content.appendChild(formData.container);
            ModalController.mount(overlay, modal, content, loadingScreen);

            const phoneInput = formData.form.querySelector('.cdw-phone-input');
            const iti        = await PhoneController.init(phoneInput);
            PhoneController.attachValidation(phoneInput, iti);

            FormController.attachSubmitHandler({
                formData, modalContent: content, overlay, provision,
                publicKey, macAddress, storedToken, iti, doubleOpt,
            });

        } catch (err) {
            Log.error("Erreur d'initialisation :", err);
        } finally {
            UI.removeLoadingScreen(loadingScreen);
            Dom.unlockScroll();
            Dom.revealPage();
        }
    }


    // ─────────────────────────────────────────────────────────────────────────
    // EXPORT PUBLIC
    // ─────────────────────────────────────────────────────────────────────────

    window.CoreDataWidget = Object.freeze({ init, version: '4.0.0' });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => init(), { once: true });
    } else {
        init();
    }

})(window, document);
