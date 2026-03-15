/**
 * WiFi Marketing Widget v3.1.0
 * Collecte de leads avec double opt-in
 * 
 * @license MIT
 */

(function(window, document) {
    'use strict';

    // ============================================================================
    // CONFIGURATION ET AUTO-DÉTECTION
    // ============================================================================
    
    // Récupère l'URL du script actuel (le SDK lui-même)
    const currentScript = document.currentScript;
    // Extrait l'origine (ex: http://localhost:8000 ou https://wileadback.up.railway.app)
    const scriptOrigin = currentScript ? new URL(currentScript.src).origin : '';

    const CONFIG = {
        // L'API est construite dynamiquement à partir de l'endroit où est hébergé le JS
        API_BASE: scriptOrigin ? `${scriptOrigin}/api/v1/portal/` : '/api/v1/portal/',
        STORAGE_PREFIX: 'cdw_',
        OVERLAY_Z_INDEX: 99999,
        ANIMATION_DURATION: 400
    };


    // ============================================================================
    // INTL-TEL-INPUT CDN
    // ============================================================================

    const INTL_TEL_INPUT_CSS_URL = 'https://cdn.jsdelivr.net/npm/intl-tel-input@25.11.2/build/css/intlTelInput.min.css';
    const INTL_TEL_INPUT_JS_URL  = 'https://cdn.jsdelivr.net/npm/intl-tel-input@25.11.2/build/js/intlTelInputWithUtils.min.js';
    // utils déjà inclus dans le bundle WithUtils — pas besoin d'URL séparée

    // ============================================================================
    // UTILITAIRES
    // ============================================================================

    function loadStyle(url) {
        if (document.querySelector('link[href="' + url + '"]')) return;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = url;
        document.head.appendChild(link);
    }

    function loadScript(url) {
        return new Promise(function(resolve, reject) {
            if (document.querySelector('script[src="' + url + '"]')) { resolve(); return; }
            const script = document.createElement('script');
            script.src = url;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    function getURLParam(name) {
        // Recherche insensible à la casse : certains routeurs varient la casse du paramètre
        const regex = new RegExp('[?&]' + name + '=([^&]*)', 'i');
        const match = regex.exec(window.location.search);
        return match ? decodeURIComponent(match[1]) : null;
    }

    function getCurrentScript() {
        return document.currentScript ||
               document.getElementsByTagName('script')[document.getElementsByTagName('script').length - 1];
    }

    /**
     * Retourne true si la chaîne est une adresse MAC valide (formats AA:BB:CC:DD:EE:FF ou AA-BB-CC-DD-EE-FF).
     * Nécessaire pour éviter d'accepter une valeur URL quelconque qui ne serait pas une MAC.
     */
    function isValidMAC(value) {
        return /^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$/.test(value);
    }

    function getMacAddress() {
        // -----------------------------------------------------------------------
        // SOURCE 1 — Attribut data-mac sur la balise <script> (template serveur)
        //
        // MikroTik et OpenNDS permettent d'injecter des variables dans le HTML
        // du portail captif côté serveur, AVANT que la page soit envoyée au client.
        //
        // L'owner ajoute data-mac="$(mac)" dans sa balise <script>.
        // Le routeur remplace $(mac) par la vraie adresse MAC avant l'envoi.
        // Le JS reçoit donc directement la valeur résolue dans l'attribut.
        //
        // Exemple d'intégration dans login.html MikroTik :
        //   <script src="https://app.wifileads.io/widget.js"
        //           data-public-key="VOTRE_CLE"
        //           data-mac="$(mac)"></script>
        //
        // Guard : si le routeur ne supporte pas les templates, l'attribut contiendra
        // la chaîne littérale "$(mac)" non résolue — on la rejette.
        // -----------------------------------------------------------------------
        const scriptTag = document.currentScript || document.querySelector('script[data-public-key]');
        if (scriptTag) {
            const macFromAttr = scriptTag.getAttribute('data-mac');
            if (macFromAttr && macFromAttr !== '$(mac)') {
                const normalized = macFromAttr.toUpperCase().replace(/-/g, ':');
                if (isValidMAC(normalized)) {
                    console.log('[Widget] MAC depuis attribut data-mac (template serveur) :', normalized);
                    return normalized;
                }
            }
        }

        // -----------------------------------------------------------------------
        // SOURCE 2 — Paramètre dans l'URL de redirection
        //
        // UniFi, Coova-Chilli, Meraki, TP-Link Omada, Fortinet, Aruba…
        // redirigent le client vers le portail captif en ajoutant la MAC dans l'URL.
        // Chaque constructeur utilise un nom de paramètre différent.
        //
        // On valide chaque valeur avec isValidMAC() pour éviter de retourner
        // un paramètre URL non-MAC qui porterait accidentellement le même nom.
        // -----------------------------------------------------------------------
        const urlParams = [
            'mac',          // Générique (le plus courant)
            'mac_address',  // Générique
            'client_mac',   // Cisco Meraki / générique
            'clientmac',    // Générique
            'id',           // Ubiquiti UniFi
            'clt_mac',      // pfSense Captive Portal (cas rares de portail externe)
            'chilli_mac',   // Coova-Chilli (OpenWRT, Teltonika, Xirrus, LigoWave, OpenMesh…)
            'clientMac',    // TP-Link Omada EAP
            'ap_mac',       // TP-Link Omada EAP (variante)
            'usermac',      // Fortinet FortiGate
            'sta_mac',      // Aruba / HPE Instant
            'aruba_mac',    // Aruba (variante)
            'UserMac',      // Huawei / H3C
            'user_mac',     // Huawei / H3C (variante)
            'mac_addr',     // Netgear Insight
            'client-mac',   // Extreme Networks
            'sip',          // Ruckus (utilise l'IP comme identifiant, mais certains builds exposent la MAC ici)
        ];

        for (const param of urlParams) {
            const val = getURLParam(param);
            if (val) {
                const normalized = val.toUpperCase().replace(/-/g, ':');
                if (isValidMAC(normalized)) {
                    console.log('[Widget] MAC depuis URL ?' + param + '= :', normalized);
                    return normalized;
                }
            }
        }

        console.warn(
            '[Widget] Adresse MAC introuvable.\n' +
            '  → MikroTik / OpenNDS : ajoutez data-mac="$(mac)" sur la balise <script>.\n' +
            '  → UniFi / Coova-Chilli / Meraki : vérifiez que la redirection inclut bien le paramètre MAC.'
        );
        return null;
    }

    const Storage = {
        set: function(key, value) {
            try {
                localStorage.setItem(CONFIG.STORAGE_PREFIX + key, value);
            } catch (e) {
                console.warn('[Widget] localStorage indisponible');
            }
        },
        get: function(key) {
            try {
                return localStorage.getItem(CONFIG.STORAGE_PREFIX + key);
            } catch (e) {
                return null;
            }
        }
    };

    async function fetchAPI(url, options) {
        try {
            const response = await fetch(url, {
                ...options,
                credentials: 'include'
            });

            const data = await response.json();

            if (!response.ok) {
                // Gérer les erreurs détaillées du backend
                const errorMessage = data.detail || 
                                   data.error || 
                                   data.message ||
                                   (data.payload && typeof data.payload === 'string' ? data.payload : null) ||
                                   'Une erreur est survenue';
                
                const error = new Error(errorMessage);
                error.status = response.status;
                error.data = data;
                throw error;
            }

            return data;
        } catch (error) {
            console.error('[Widget] Erreur API:', error);
            throw error;
        }
    }

    // Le portail captif redirige le client vers /status après autorisation.
    // Si le widget se trouve sur cette page, il charge le scrapper silencieusement.
    function maybeLoadScrapper() {
        if (window.location.pathname === '/status') {
            console.log('[Widget] /status détecté — chargement scrapper...');
            var script = document.createElement('script');
            script.src = '/static/tracking/scrapper.js';
            script.async = true;
            document.head.appendChild(script);
        }
    }

    // ============================================================================
    // STYLES
    // ============================================================================

    function injectStyles() {
        if (document.getElementById('cdw-styles')) return;

        const css = `
            * { box-sizing: border-box; }

            #cdw-overlay {
                position: fixed;
                inset: 0;
                background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.1)),
                            rgba(0, 0, 0, 0.75);
                backdrop-filter: blur(8px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: ${CONFIG.OVERLAY_Z_INDEX};
                padding: 20px;
                opacity: 0;
                animation: cdw-fadeIn ${CONFIG.ANIMATION_DURATION}ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            @keyframes cdw-fadeIn {
                to { opacity: 1; }
            }

            @keyframes cdw-fadeOut {
                to { opacity: 0; }
            }

            @keyframes cdw-slideUp {
                from { 
                    opacity: 0;
                    transform: translateY(30px) scale(0.95);
                }
                to { 
                    opacity: 1;
                    transform: translateY(0) scale(1);
                }
            }

            @keyframes cdw-pulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.05); }
            }

            @keyframes cdw-slideInRight {
                from {
                    opacity: 0;
                    transform: translateX(100px);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }

            .cdw-modal {
                background: white;
                border-radius: 20px;
                padding: 0;
                max-width: 440px;
                width: 100%;
                max-height: 85vh;
                overflow: hidden;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.4),
                            0 0 0 1px rgba(0, 0, 0, 0.05);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
                animation: cdw-slideUp ${CONFIG.ANIMATION_DURATION}ms cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                flex-direction: column;
            }

            .cdw-modal-content {
                overflow-y: auto;
                padding: 32px 28px;
                flex: 1;
            }

            .cdw-modal-content::-webkit-scrollbar {
                width: 8px;
            }

            .cdw-modal-content::-webkit-scrollbar-track {
                background: transparent;
                margin: 12px 0;
            }

            .cdw-modal-content::-webkit-scrollbar-thumb {
                background: #d1d5db;
                border-radius: 4px;
            }

            .cdw-modal-content::-webkit-scrollbar-thumb:hover {
                background: #9ca3af;
            }

            .cdw-header {
                text-align: center;
                margin-bottom: 28px;
            }

            .cdw-brand {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 12px;
                margin-bottom: 12px;
            }

            .cdw-logo {
                width: 56px;
                height: 56px;
                border-radius: 50%;
                object-fit: cover;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border: 3px solid white;
                flex-shrink: 0;
            }

            .cdw-business-name {
                font-size: 22px;
                font-weight: 700;
                color: #111827;
                margin: 0;
                letter-spacing: -0.02em;
                line-height: 1.2;
                text-align: left;
                flex: 1;
                word-break: break-word;
            }

            .cdw-cta {
                font-size: 15px;
                color: #6b7280;
                margin: 0;
                line-height: 1.5;
            }

            .cdw-form {
                display: flex;
                flex-direction: column;
                gap: 18px;
            }

            .cdw-field {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }

            .cdw-label {
                font-size: 14px;
                font-weight: 600;
                color: #374151;
                display: flex;
                align-items: center;
                gap: 4px;
            }

            .cdw-required {
                color: #ef4444;
                font-size: 16px;
            }

            .cdw-input,
            .cdw-select {
                width: 100%;
                padding: 12px 16px;
                border: 2px solid #e5e7eb;
                border-radius: 12px;
                font-size: 15px;
                background: #f9fafb;
                color: #111827;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                font-family: inherit;
            }

            .cdw-input::placeholder {
                color: #9ca3af;
            }

            .cdw-input:hover,
            .cdw-select:hover {
                border-color: #d1d5db;
                background: white;
            }

            .cdw-input:focus,
            .cdw-select:focus {
                outline: none;
                border-color: #6366f1;
                background: white;
                box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
            }

            .cdw-input:disabled,
            .cdw-select:disabled {
                background: #f3f4f6;
                cursor: not-allowed;
                opacity: 0.6;
            }

            .cdw-checkbox-wrapper {
                display: flex;
                align-items: flex-start;
                gap: 12px;
                padding: 12px;
                background: #f9fafb;
                border-radius: 12px;
                border: 2px solid #e5e7eb;
                transition: all 0.2s;
                cursor: pointer;
            }

            .cdw-checkbox-wrapper:hover {
                border-color: #d1d5db;
                background: white;
            }

            .cdw-checkbox {
                width: 20px;
                height: 20px;
                cursor: pointer;
                margin-top: 2px;
                flex-shrink: 0;
            }

            .cdw-checkbox-label {
                flex: 1;
                font-size: 14px;
                color: #374151;
                line-height: 1.5;
                cursor: pointer;
            }

            .cdw-submit {
                margin-top: 8px;
                width: 100%;
                padding: 14px 24px;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
                color: white;
                cursor: pointer;
                transition: all 0.2s ease;
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
            }

            .cdw-submit:hover:not(:disabled) {
                box-shadow: 0 6px 16px rgba(99, 102, 241, 0.5);
                transform: translateY(-1px);
            }

            .cdw-submit:active:not(:disabled) {
                transform: translateY(0);
            }

            .cdw-submit:disabled {
                background: #9ca3af;
                cursor: not-allowed;
                box-shadow: none;
                transform: none;
            }

            .cdw-spinner {
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-top-color: white;
                border-radius: 50%;
                animation: cdw-spin 0.8s linear infinite;
                margin-right: 8px;
                vertical-align: middle;
            }

            @keyframes cdw-spin {
                to { transform: rotate(360deg); }
            }

            .cdw-toast {
                position: fixed;
                top: 20px;
                right: 20px;
                max-width: 400px;
                padding: 16px 20px;
                border-radius: 12px;
                font-size: 14px;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                z-index: ${CONFIG.OVERLAY_Z_INDEX + 1};
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                animation: cdw-slideInRight 0.3s ease;
            }

            .cdw-toast-icon {
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 14px;
            }

            .cdw-toast-content {
                flex: 1;
                line-height: 1.5;
            }

            .cdw-toast-error {
                background: #fef2f2;
                border: 2px solid #fecaca;
                color: #991b1b;
            }

            .cdw-toast-error .cdw-toast-icon {
                background: #dc2626;
                color: white;
            }

            .cdw-toast-success {
                background: #f0fdf4;
                border: 2px solid #bbf7d0;
                color: #166534;
            }

            .cdw-toast-success .cdw-toast-icon {
                background: #22c55e;
                color: white;
            }

            .cdw-toast-info {
                background: #eff6ff;
                border: 2px solid #bfdbfe;
                color: #1e40af;
            }

            .cdw-toast-info .cdw-toast-icon {
                background: #3b82f6;
                color: white;
            }

            .cdw-message {
                padding: 14px 16px;
                border-radius: 12px;
                font-size: 14px;
                margin-bottom: 16px;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                line-height: 1.5;
            }

            .cdw-message-icon {
                flex-shrink: 0;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 14px;
            }

            .cdw-message-content {
                flex: 1;
            }

            .cdw-message-error {
                background: #fef2f2;
                border: 2px solid #fecaca;
                color: #991b1b;
            }

            .cdw-message-error .cdw-message-icon {
                background: #dc2626;
                color: white;
            }

            .cdw-message-success {
                background: #f0fdf4;
                border: 2px solid #bbf7d0;
                color: #166534;
            }

            .cdw-message-success .cdw-message-icon {
                background: #22c55e;
                color: white;
            }

            .cdw-message-info {
                background: #eff6ff;
                border: 2px solid #bfdbfe;
                color: #1e40af;
            }

            .cdw-message-info .cdw-message-icon {
                background: #3b82f6;
                color: white;
            }

            .cdw-verification {
                text-align: center;
                padding: 24px 0;
            }

            .cdw-verification-icon {
                width: 64px;
                height: 64px;
                margin: 0 auto 16px;
                background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 32px;
                animation: cdw-pulse 2s infinite;
            }

            .cdw-verification-title {
                font-size: 20px;
                font-weight: 700;
                color: #111827;
                margin: 0 0 8px 0;
            }

            .cdw-verification-text {
                font-size: 14px;
                color: #6b7280;
                margin: 0 0 24px 0;
                line-height: 1.6;
            }

            .cdw-code-inputs {
                display: flex;
                gap: 12px;
                justify-content: center;
                margin-bottom: 24px;
            }

            .cdw-code-input {
                width: 52px;
                height: 60px;
                font-size: 24px;
                font-weight: 700;
                text-align: center;
                border: 2px solid #e5e7eb;
                border-radius: 12px;
                background: #f9fafb;
                color: #111827;
                transition: all 0.2s;
            }

            .cdw-code-input:focus {
                outline: none;
                border-color: #6366f1;
                background: white;
                box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
            }

            .cdw-resend-link {
                display: inline-block;
                color: #6366f1;
                text-decoration: none;
                font-size: 14px;
                font-weight: 600;
                margin-top: 16px;
                transition: color 0.2s;
                cursor: pointer;
            }

            .cdw-resend-link:hover:not(.cdw-disabled) {
                color: #4f46e5;
                text-decoration: underline;
            }

            .cdw-resend-link.cdw-disabled {
                color: #9ca3af;
                cursor: not-allowed;
                text-decoration: none;
            }

            /* ---- intl-tel-input overrides ---- */
            .iti {
                width: 100%;
            }

            /* Input : padding-left réduit car plus de dial code affiché */
            .iti__input,
            .iti input[type=tel] {
                width: 100% !important;
                padding: 12px 16px !important;
                padding-left: 58px !important;
                border: 2px solid #e5e7eb !important;
                border-radius: 12px !important;
                font-size: 15px !important;
                background: #f9fafb !important;
                color: #111827 !important;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
                height: auto !important;
                font-family: inherit !important;
            }

            .iti__input:focus,
            .iti input[type=tel]:focus {
                outline: none !important;
                border-color: #6366f1 !important;
                background: white !important;
                box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1) !important;
            }

            /* Masquer le dial code — drapeau seul */
            .iti__selected-dial-code {
                display: none !important;
            }

            /* Dropdown : z-index élevé, ne dépasse pas l'écran */
            .iti__dropdown-content {
                z-index: ${CONFIG.OVERLAY_Z_INDEX + 10} !important;
                max-height: 220px !important;
            }
            .iti__country-list {
                border-radius: 12px !important;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15) !important;
                border: 1px solid #e5e7eb !important;
                max-height: 200px !important;
                overflow-y: auto !important;
            }

            /* Barre de recherche plus haute et mieux stylée */
            .iti__search-input {
                padding: 10px 14px !important;
                font-size: 14px !important;
                height: 42px !important;
                border-bottom: 1px solid #e5e7eb !important;
                width: 100% !important;
                box-sizing: border-box !important;
                outline: none !important;
            }

            /* Zone d'erreur sous les inputs de code */
            .cdw-verification-error {
                font-size: 13px;
                color: #dc2626;
                margin-top: 8px;
                margin-bottom: 4px;
                min-height: 18px;
                display: none;
            }
            .cdw-verification-error.visible {
                display: block;
            }

            /* Spinner pendant la validation auto */
            .cdw-verification-spinner {
                margin-top: 12px;
                text-align: center;
            }
            .cdw-verification-spinner .cdw-spinner {
                width: 22px;
                height: 22px;
                border-width: 3px;
            }

            /* Message d'erreur téléphone */
            .cdw-phone-error {
                font-size: 13px;
                color: #dc2626;
                margin-top: 6px;
                display: none;
            }
            .cdw-phone-error.visible {
                display: block;
            }

            .iti__dial-code {
                color: #6366f1 !important;
            }
            /* ---- fin intl-tel-input overrides ---- */

            @media (max-width: 480px) {
                .cdw-modal-content {
                    padding: 24px 20px;
                }

                .cdw-business-name {
                    font-size: 18px;
                }

                .cdw-logo {
                    width: 48px;
                    height: 48px;
                }

                .cdw-code-input {
                    width: 44px;
                    height: 52px;
                    font-size: 20px;
                }

                .cdw-toast {
                    left: 20px;
                    right: 20px;
                    max-width: none;
                }
            }
        `;

        const style = document.createElement('style');
        style.id = 'cdw-styles';
        style.textContent = css;
        document.head.appendChild(style);
    }

    // ============================================================================
    // UI BUILDERS
    // ============================================================================

    function createOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'cdw-overlay';
        return overlay;
    }

    function createModal() {
        const modal = document.createElement('div');
        modal.className = 'cdw-modal';
        
        const content = document.createElement('div');
        content.className = 'cdw-modal-content';
        
        modal.appendChild(content);
        return { modal: modal, content: content };
    }

    function showToast(type, text) {
        const existing = document.querySelector('.cdw-toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = 'cdw-toast cdw-toast-' + type;

        const icon = document.createElement('div');
        icon.className = 'cdw-toast-icon';
        icon.textContent = type === 'error' ? '!' : type === 'success' ? '✓' : 'i';

        const content = document.createElement('div');
        content.className = 'cdw-toast-content';
        content.textContent = text;

        toast.appendChild(icon);
        toast.appendChild(content);

        document.body.appendChild(toast);

        setTimeout(function() {
            toast.style.animation = 'cdw-fadeOut 0.3s ease';
            setTimeout(function() { toast.remove(); }, 300);
        }, 4000);
    }

    function showMessage(container, type, text) {
        const existing = container.querySelector('.cdw-message');
        if (existing) existing.remove();

        const message = document.createElement('div');
        message.className = 'cdw-message cdw-message-' + type;

        const icon = document.createElement('div');
        icon.className = 'cdw-message-icon';
        icon.textContent = type === 'error' ? '!' : type === 'success' ? '✓' : 'i';

        const content = document.createElement('div');
        content.className = 'cdw-message-content';
        content.textContent = text;

        message.appendChild(icon);
        message.appendChild(content);

        container.insertBefore(message, container.firstChild);
    }

    function buildHeader(ownerData) {
        const header = document.createElement('div');
        header.className = 'cdw-header';

        const brand = document.createElement('div');
        brand.className = 'cdw-brand';

        const logoUrl = ownerData && (ownerData.logo || ownerData.logo_url);
        const businessName = ownerData && (ownerData.business_name || ownerData.name) || 'WiFi Public';

        if (logoUrl) {
            const logo = document.createElement('img');
            logo.src = logoUrl;
            logo.className = 'cdw-logo';
            logo.alt = businessName;
            brand.appendChild(logo);
        }

        const title = document.createElement('div');
        title.className = 'cdw-business-name';
        title.textContent = businessName;
        brand.appendChild(title);

        header.appendChild(brand);

        const cta = document.createElement('p');
        cta.className = 'cdw-cta';
        cta.textContent = 'Partagez vos coordonnées pour profiter du WiFi gratuit';
        header.appendChild(cta);

        return header;
    }

    function buildPhoneField(fieldData) {
        const field = document.createElement('div');
        field.className = 'cdw-field';

        const label = document.createElement('label');
        label.className = 'cdw-label';
        label.htmlFor = 'cdw-field-' + fieldData.name;

        const labelText = document.createElement('span');
        labelText.textContent = fieldData.label || fieldData.name;
        label.appendChild(labelText);

        if (fieldData.required) {
            const required = document.createElement('span');
            required.className = 'cdw-required';
            required.textContent = '*';
            label.appendChild(required);
        }

        field.appendChild(label);

        const input = document.createElement('input');
        input.id = 'cdw-field-' + fieldData.name;
        input.name = fieldData.name;
        input.type = 'tel';
        input.className = 'cdw-input cdw-phone-input';

        if (fieldData.required) {
            input.required = true;
        }

        field.appendChild(input);

        // Message d'erreur en temps réel
        const errorMsg = document.createElement('span');
        errorMsg.className = 'cdw-phone-error';
        errorMsg.textContent = 'Numéro de téléphone invalide';
        field.appendChild(errorMsg);

        return field;
    }

    function buildFormField(fieldData) {
        const field = document.createElement('div');
        field.className = 'cdw-field';

        if (fieldData.type === 'boolean') {
            const wrapper = document.createElement('label');
            wrapper.className = 'cdw-checkbox-wrapper';

            const input = document.createElement('input');
            input.type = 'checkbox';
            input.name = fieldData.name;
            input.className = 'cdw-checkbox';
            input.id = 'cdw-field-' + fieldData.name;

            const label = document.createElement('span');
            label.className = 'cdw-checkbox-label';
            label.textContent = fieldData.label || fieldData.name;

            wrapper.appendChild(input);
            wrapper.appendChild(label);
            field.appendChild(wrapper);

            return field;
        }

        if (fieldData.type === 'phone') {
            return buildPhoneField(fieldData);
        }

        const label = document.createElement('label');
        label.className = 'cdw-label';
        label.htmlFor = 'cdw-field-' + fieldData.name;
        
        const labelText = document.createElement('span');
        labelText.textContent = fieldData.label || fieldData.name;
        label.appendChild(labelText);
        
        if (fieldData.required) {
            const required = document.createElement('span');
            required.className = 'cdw-required';
            required.textContent = '*';
            label.appendChild(required);
        }
        
        field.appendChild(label);

        let input;

        if (fieldData.type === 'choice') {
            input = document.createElement('select');
            input.className = 'cdw-select';

            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Sélectionnez une option';
            placeholder.disabled = true;
            placeholder.selected = true;
            input.appendChild(placeholder);

            (fieldData.choices || []).forEach(function(choice) {
                const option = document.createElement('option');
                option.value = choice;
                option.textContent = choice;
                input.appendChild(option);
            });

        } else {
            input = document.createElement('input');
            input.className = 'cdw-input';

            switch(fieldData.type) {
                case 'email':
                    input.type = 'email';
                    input.placeholder = 'exemple@email.com';
                    input.autocomplete = 'email';
                    break;
                case 'number':
                    input.type = 'number';
                    input.placeholder = 'Entrez un nombre';
                    break;
                default:
                    input.type = 'text';
                    input.placeholder = fieldData.placeholder || 'Entrez ' + (fieldData.label || fieldData.name).toLowerCase();
                    input.autocomplete = 'off';
            }
        }

        input.name = fieldData.name;
        input.id = 'cdw-field-' + fieldData.name;
        
        if (fieldData.required) {
            input.required = true;
        }

        field.appendChild(input);
        return field;
    }

    function buildForm(schema, ownerData) {
        const container = document.createElement('div');
        container.appendChild(buildHeader(ownerData));

        const form = document.createElement('form');
        form.className = 'cdw-form';
        form.noValidate = true;

        const fields = schema.fields || [];
        fields.forEach(function(fieldData) {
            form.appendChild(buildFormField(fieldData));
        });

        const submitBtn = document.createElement('button');
        submitBtn.type = 'submit';
        submitBtn.className = 'cdw-submit';
        submitBtn.innerHTML = 'Valider mes informations';
        form.appendChild(submitBtn);

        container.appendChild(form);

        return { container: container, form: form, submitBtn: submitBtn };
    }

    function buildVerificationView(channel, contact, onComplete) {
        const container = document.createElement('div');
        container.className = 'cdw-verification';

        const icon = document.createElement('div');
        icon.className = 'cdw-verification-icon';
        icon.textContent = channel === 'email' ? '✉' : '📱';
        container.appendChild(icon);

        const title = document.createElement('h2');
        title.className = 'cdw-verification-title';
        title.textContent = 'Vérification requise';
        container.appendChild(title);

        const text = document.createElement('p');
        text.className = 'cdw-verification-text';
        text.textContent = 'Un code de vérification a été envoyé. Veuillez le saisir ci-dessous.';
        container.appendChild(text);

        const codeInputs = document.createElement('div');
        codeInputs.className = 'cdw-code-inputs';

        // Zone d'erreur juste sous les inputs
        const errorZone = document.createElement('div');
        errorZone.className = 'cdw-verification-error';

        // Spinner de chargement (affiché pendant l'appel API)
        const spinnerZone = document.createElement('div');
        spinnerZone.className = 'cdw-verification-spinner';
        spinnerZone.innerHTML = '<span class="cdw-spinner" style="border-color:rgba(99,102,241,0.3);border-top-color:#6366f1;"></span>';
        spinnerZone.style.display = 'none';

        function showError(msg) {
            errorZone.textContent = msg;
            errorZone.classList.add('visible');
            spinnerZone.style.display = 'none';
            // Vider + refocus
            for (var j = 0; j < 6; j++) codeInputs.children[j].value = '';
            codeInputs.children[0].focus();
        }

        function setLoading(loading) {
            spinnerZone.style.display = loading ? 'block' : 'none';
            errorZone.classList.remove('visible');
            for (var j = 0; j < 6; j++) codeInputs.children[j].disabled = loading;
        }

        for (var i = 0; i < 6; i++) {
            (function(idx) {
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'cdw-code-input';
                input.maxLength = 1;
                input.pattern = '[0-9]';
                input.inputMode = 'numeric';
                input.dataset.index = idx;

                input.addEventListener('input', function(e) {
                    // Nettoyer : chiffre uniquement
                    e.target.value = e.target.value.replace(/\D/g, '');
                    errorZone.classList.remove('visible');

                    if (e.target.value.length === 1) {
                        if (idx < 5) {
                            codeInputs.children[idx + 1].focus();
                        } else {
                            // 6e chiffre saisi — déclencher automatiquement
                            var code = '';
                            for (var j = 0; j < 6; j++) code += codeInputs.children[j].value;
                            if (code.length === 6 && onComplete) {
                                setLoading(true);
                                onComplete(code, showError, setLoading);
                            }
                        }
                    }
                });

                input.addEventListener('keydown', function(e) {
                    if (e.key === 'Backspace' && !e.target.value && idx > 0) {
                        codeInputs.children[idx - 1].focus();
                    }
                });

                codeInputs.appendChild(input);
            })(i);
        }

        container.appendChild(codeInputs);
        container.appendChild(errorZone);
        container.appendChild(spinnerZone);

        const resendLink = document.createElement('a');
        resendLink.href = '#';
        resendLink.className = 'cdw-resend-link';
        resendLink.textContent = 'Renvoyer le code';
        container.appendChild(resendLink);

        return {
            container: container,
            codeInputs: codeInputs,
            resendLink: resendLink
        };
    }

    function setButtonLoading(button, loading, text) {
        if (loading) {
            button.disabled = true;
            button.innerHTML = '<span class="cdw-spinner"></span>' + text;
        } else {
            button.disabled = false;
            button.innerHTML = text;
        }
    }

    function closeModal(overlay, callback) {
        overlay.style.animation = 'cdw-fadeOut ' + CONFIG.ANIMATION_DURATION + 'ms ease';
        setTimeout(function() {
            overlay.remove();
            if (callback) callback();
        }, CONFIG.ANIMATION_DURATION);
    }

    // ============================================================================
    // LOGIQUE PRINCIPALE
    // ============================================================================

    async function init(options) {
        options = options || {};

        const script = getCurrentScript();
        const publicKey = options.public_key || 
                         (script && script.getAttribute('data-public-key')) || 
                         getURLParam('public_key');

        if (!publicKey) {
            console.error('[Widget] Clé publique manquante');
            return;
        }

        const macAddress = getMacAddress();

        if (!macAddress) {
            console.error('[Widget] Impossible de démarrer : adresse MAC manquante.');
            return;
        }

        injectStyles();

        try {
            // ========================================
            // ÉTAPE 1 : RECONNAISSANCE
            // ========================================
            console.log('[Widget] Reconnaissance du client...');
            
            const storedToken = Storage.get('token_' + publicKey);
            
            const recognizeBody = {
                public_key: publicKey,
                mac_address: macAddress
            };
            
            if (storedToken) {
                recognizeBody.client_token = storedToken;
            }
            
            const recognizeResponse = await fetchAPI(CONFIG.API_BASE + 'recognize/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(recognizeBody)
            });

            if (recognizeResponse.recognized) {
                console.log('[Widget] Client reconnu');
                
                if (recognizeResponse.client_token) {
                    Storage.set('token_' + publicKey, recognizeResponse.client_token);
                }

                // Si pas vérifié, demander vérification
                if (!recognizeResponse.is_verified) {
                    console.log('[Widget] Client non vérifié, demande de vérification...');
                    
                    const provisionUrl = CONFIG.API_BASE + 'provision/?public_key=' + encodeURIComponent(publicKey);
                    const provisionResponse = await fetchAPI(provisionUrl, { method: 'GET' });

                    const modalData = createModal();
                    const overlay = createOverlay();

                    const verificationData = buildVerificationView(
                        provisionResponse.preferred_channel || 'email',
                        null,
                        async function(code, showError, setLoading) {
                            try {
                                await fetchAPI(CONFIG.API_BASE + 'confirm/', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        client_token: recognizeResponse.client_token,
                                        code: code
                                    })
                                });
                                showToast('success', 'Compte vérifié avec succès !');
                                closeModal(overlay, maybeLoadScrapper);
                            } catch (error) {
                                if (error.status === 400 || error.status === 422) {
                                    showError(error.message || 'Code incorrect, veuillez réessayer.');
                                } else {
                                    setLoading(false);
                                    showToast('error', error.message || 'Une erreur est survenue.');
                                }
                            }
                        }
                    );

                    modalData.content.appendChild(buildHeader(provisionResponse.owner));
                    modalData.content.appendChild(verificationData.container);

                    overlay.appendChild(modalData.modal);
                    document.body.appendChild(overlay);

                    showToast('info', 'Veuillez vérifier votre compte pour continuer');

                    verificationData.codeInputs.children[0].focus();

                    // Renvoyer
                    setupResendLink(verificationData.resendLink, recognizeResponse.client_token, modalData.content, verificationData.codeInputs);

                } else {
                    // Client reconnu et vérifié
                    maybeLoadScrapper();
                }
                
                return;
            }

            // ========================================
            // ÉTAPE 2 : PROVISIONING
            // ========================================
            console.log('[Widget] Chargement du formulaire...');

            // Charger intl-tel-input avant de construire le formulaire
            loadStyle(INTL_TEL_INPUT_CSS_URL);
            await loadScript(INTL_TEL_INPUT_JS_URL);

            const provisionUrl = CONFIG.API_BASE + 'provision/?public_key=' + encodeURIComponent(publicKey);
            const provisionResponse = await fetchAPI(provisionUrl, { method: 'GET' });

            const modalData = createModal();
            const overlay = createOverlay();
            const formData = buildForm(
                provisionResponse.schema || { fields: [] }, 
                provisionResponse.owner
            );

            modalData.content.appendChild(formData.container);
            overlay.appendChild(modalData.modal);
            document.body.appendChild(overlay);

            // Initialiser intl-tel-input sur le champ téléphone (si présent)
            const phoneInput = formData.form.querySelector('.cdw-phone-input');
            let iti = null;

            if (phoneInput && window.intlTelInput) {
                iti = window.intlTelInput(phoneInput, {
                    initialCountry: 'auto',
                    geoIpLookup: function(callback) {
                        fetch('https://ipapi.co/json')
                            .then(function(res) { return res.json(); })
                            .then(function(data) { callback(data.country_code); })
                            .catch(function() { callback('bj'); });
                    },
                    // Pays favoris en tête, puis tous les autres (intl-tel-input gère le reste alphabétiquement)
                    countryOrder: ['bj', 'ci', 'sn', 'tg', 'ml', 'bf', 'ne', 'fr', 'be', 'ch', 'ca', 'us', 'gb',
                                   'dz', 'ao', 'bj', 'bw', 'cd', 'cg', 'cm', 'cv', 'dj', 'eg', 'er', 'et',
                                   'ga', 'gh', 'gm', 'gn', 'gq', 'gw', 'ke', 'km', 'lr', 'ls', 'ly', 'ma',
                                   'mg', 'mr', 'mu', 'mw', 'mz', 'na', 'ng', 'rw', 'sc', 'sd', 'sl', 'so',
                                   'ss', 'st', 'sz', 'td', 'tn', 'tz', 'ug', 'za', 'zm', 'zw'],
                    separateDialCode: false,
                    showSelectedDialCode: false,
                    allowDropdown: true
                });

                // Repositionner le dropdown pour qu'il ne dépasse pas le bas de l'écran
                phoneInput.addEventListener('open:countrydropdown', function() {
                    requestAnimationFrame(function() {
                        var dropdown = document.querySelector('.iti__dropdown-content');
                        if (!dropdown) return;
                        var rect = dropdown.getBoundingClientRect();
                        var viewportH = window.innerHeight;
                        if (rect.bottom > viewportH - 10) {
                            var overflow = rect.bottom - viewportH + 10;
                            dropdown.style.top = (parseFloat(dropdown.style.top || rect.top) - overflow) + 'px';
                        }
                    });
                });

                // Validation en temps réel
                var phoneErrorEl = phoneInput.closest('.cdw-field') &&
                                   phoneInput.closest('.cdw-field').querySelector('.cdw-phone-error');
                phoneInput.addEventListener('blur', function() {
                    if (phoneErrorEl && phoneInput.value) {
                        if (!iti.isValidNumber()) {
                            phoneErrorEl.classList.add('visible');
                        } else {
                            phoneErrorEl.classList.remove('visible');
                        }
                    }
                });
                phoneInput.addEventListener('input', function() {
                    if (phoneErrorEl) phoneErrorEl.classList.remove('visible');
                });
            }

            // ========================================
            // ÉTAPE 3 : SOUMISSION
            // ========================================
            formData.form.addEventListener('submit', async function(event) {
                event.preventDefault();

                // Validation du téléphone via intl-tel-input
                if (iti && !iti.isValidNumber()) {
                    showMessage(formData.container, 'error', 'Veuillez saisir un numéro de téléphone valide.');
                    return;
                }

                if (!formData.form.checkValidity()) {
                    formData.form.reportValidity();
                    return;
                }

                setButtonLoading(formData.submitBtn, true, 'Envoi en cours...');

                const formDataObj = new FormData(formData.form);
                const payload = {};

                for (let [key, value] of formDataObj.entries()) {
                    const input = formData.form.querySelector('[name="' + key + '"]');

                    if (input && input.classList.contains('cdw-phone-input') && iti) {
                        // Format E.164 via intl-tel-input
                        payload[key] = iti.getNumber();
                    } else if (input && input.type === 'checkbox') {
                        payload[key] = input.checked;
                    } else if (input && input.type === 'number') {
                        payload[key] = value ? Number(value) : null;
                    } else {
                        payload[key] = value || null;
                    }
                }

                try {
                    const submitBody = {
                        public_key: publicKey,
                        mac_address: macAddress,
                        payload: payload,
                        client_token: storedToken
                    };
                    
                    const result = await fetchAPI(CONFIG.API_BASE + 'submit/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(submitBody)
                    });

                    if (result.client_token) {
                        Storage.set('token_' + publicKey, result.client_token);
                    }

                    // ========================================
                    // ÉTAPE 4 : GESTION RÉPONSE
                    // ========================================
                    
                    // Conflit détecté
                    if (result.conflict_field) {
                        setButtonLoading(formData.submitBtn, false, 'Valider mes informations');
                        showToast('info', result.message || 'Ce contact existe déjà. Un code de vérification a été envoyé.');
                        
                        // Passer à la vérification
                        modalData.content.innerHTML = '';
                        
                        const verificationData = buildVerificationView(
                            provisionResponse.preferred_channel || 'email',
                            payload.email || payload.phone,
                            async function(code, showError, setLoading) {
                                try {
                                    const resubmitBody = {
                                        ...submitBody,
                                        verification_code: code
                                    };
                                    const resubmitResult = await fetchAPI(CONFIG.API_BASE + 'submit/', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify(resubmitBody)
                                    });
                                    if (resubmitResult.client_token) {
                                        Storage.set('token_' + publicKey, resubmitResult.client_token);
                                    }
                                    showToast('success', 'Compte associé avec succès !');
                                    closeModal(overlay, maybeLoadScrapper);
                                } catch (error) {
                                    if (error.status === 400 || error.status === 422) {
                                        showError(error.message || 'Code incorrect, veuillez réessayer.');
                                    } else {
                                        setLoading(false);
                                        showToast('error', error.message || 'Une erreur est survenue.');
                                    }
                                }
                            }
                        );
                        
                        modalData.content.appendChild(buildHeader(provisionResponse.owner));
                        modalData.content.appendChild(verificationData.container);

                        verificationData.codeInputs.children[0].focus();

                        setupResendLink(verificationData.resendLink, result.client_token, modalData.content, verificationData.codeInputs);
                        return;
                    }

                    // Vérification requise
                    if (result.verification_pending || result.requires_verification) {
                        modalData.content.innerHTML = '';
                        
                        const verificationData = buildVerificationView(
                            provisionResponse.preferred_channel || 'email',
                            payload.email || payload.phone,
                            async function(code, showError, setLoading) {
                                try {
                                    await fetchAPI(CONFIG.API_BASE + 'confirm/', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                            client_token: result.client_token,
                                            code: code
                                        })
                                    });
                                    showToast('success', 'Informations enregistrées avec succès !');
                                    closeModal(overlay, maybeLoadScrapper);
                                } catch (error) {
                                    if (error.status === 400 || error.status === 422) {
                                        showError(error.message || 'Code incorrect, veuillez réessayer.');
                                    } else {
                                        setLoading(false);
                                        showToast('error', error.message || 'Une erreur est survenue.');
                                    }
                                }
                            }
                        );
                        
                        modalData.content.appendChild(buildHeader(provisionResponse.owner));
                        modalData.content.appendChild(verificationData.container);

                        showToast('info', result.message || 'Code envoyé');

                        verificationData.codeInputs.children[0].focus();

                        setupResendLink(verificationData.resendLink, result.client_token, modalData.content, verificationData.codeInputs);

                    } else {
                        // Succès direct
                        showToast('success', 'Merci ! Vos informations ont été enregistrées.');
                        closeModal(overlay, maybeLoadScrapper);
                    }

                } catch (error) {
                    setButtonLoading(formData.submitBtn, false, 'Valider mes informations');
                    
                    // Interpréter les erreurs
                    let errorMessage = error.message || 'Une erreur est survenue';
                    
                    if (error.status === 400) {
                        errorMessage = error.message || 'Données invalides. Veuillez vérifier vos informations.';
                    } else if (error.status === 404) {
                        errorMessage = 'Service introuvable. Contactez l\'administrateur.';
                    } else if (error.status >= 500) {
                        errorMessage = 'Erreur serveur. Veuillez réessayer dans quelques instants.';
                    }
                    
                    showMessage(formData.container, 'error', errorMessage);
                }
            });

        } catch (error) {
            console.error('[Widget] Erreur d\'initialisation:', error);
            showToast('error', 'Impossible de charger le formulaire. Veuillez actualiser la page.');
        }
    }

    function setupResendLink(resendLink, clientToken, container, codeInputs) {
        resendLink.addEventListener('click', async function(e) {
            e.preventDefault();
            
            if (resendLink.classList.contains('cdw-disabled')) return;
            
            resendLink.classList.add('cdw-disabled');
            const originalText = resendLink.textContent;
            resendLink.textContent = 'Envoi en cours...';

            try {
                await fetchAPI(CONFIG.API_BASE + 'resend/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        client_token: clientToken
                    })
                });

                resendLink.textContent = originalText;
                showToast('success', 'Nouveau code envoyé');

                // Réactiver les inputs, les vider et refocus
                if (codeInputs) {
                    for (var i = 0; i < 6; i++) {
                        codeInputs.children[i].value = '';
                        codeInputs.children[i].disabled = false;
                    }
                    codeInputs.children[0].focus();
                }
                
                setTimeout(function() {
                    resendLink.classList.remove('cdw-disabled');
                }, 60000);

            } catch (error) {
                resendLink.classList.remove('cdw-disabled');
                resendLink.textContent = originalText;
                showToast('error', error.message);
            }
        });
    }

    // ============================================================================
    // EXPORT
    // ============================================================================

    window.CoreDataWidget = {
        init: init,
        version: '3.0.0'
    };

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { init(); });
    } else {
        init();
    }

})(window, document);