        const TOKEN_STORAGE_KEY = 'pearl.device_token';
        const DEVICE_ID_STORAGE_KEY = 'pearl.device_id';
        let TOKEN = window.PEARL_CONFIG?.token || localStorage.getItem(TOKEN_STORAGE_KEY) || '';

        function notifyNativeSessionToken(token) {
            try {
                if (window.PearlAndroid?.onSessionToken) {
                    window.PearlAndroid.onSessionToken(token || '');
                }
            } catch (err) {
                console.warn('No se pudo sincronizar sesión nativa:', err);
            }
        }

        function getNativeDeviceIdentity() {
            try {
                if (!window.PearlAndroid?.getDeviceIdentity) return {};
                const identity = JSON.parse(window.PearlAndroid.getDeviceIdentity() || '{}');
                return identity && typeof identity === 'object' ? identity : {};
            } catch (err) {
                console.warn('Identidad nativa no disponible:', err);
                return {};
            }
        }

        function setApiToken(token) {
            TOKEN = token || '';
            window.PEARL_CONFIG = window.PEARL_CONFIG || {};
            window.PEARL_CONFIG.token = TOKEN;
            if (TOKEN) {
                localStorage.setItem(TOKEN_STORAGE_KEY, TOKEN);
            } else {
                localStorage.removeItem(TOKEN_STORAGE_KEY);
            }
            notifyNativeSessionToken(TOKEN);
        }

        function getOrCreateDeviceId() {
            let deviceId = localStorage.getItem(DEVICE_ID_STORAGE_KEY) || '';
            if (!deviceId) {
                if (window.crypto?.randomUUID) {
                    deviceId = window.crypto.randomUUID();
                } else {
                    deviceId = `pearl-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                }
                localStorage.setItem(DEVICE_ID_STORAGE_KEY, deviceId);
            }
            return deviceId;
        }

        const cursor = document.getElementById('cursor');
        const cursorDot = document.getElementById('cursor-dot');
        const chatContainer = document.getElementById('chat-container');
        const userInput = document.getElementById('userInput');
        const loader = document.getElementById('loader');

        let isAuthenticated = false;
        let activeLightName = 'lamp_sala';
        let activeLightDevices = {};

        /* CURSOR */
        document.addEventListener('mousemove', (e) => {
            if (cursor) {
                cursor.style.left = e.clientX + 'px';
                cursor.style.top = e.clientY + 'px';
            }
            if (cursorDot) {
                cursorDot.style.left = e.clientX + 'px';
                cursorDot.style.top = e.clientY + 'px';
            }
        });

        const interactiveElements = ['button', 'input', '.auth-btn'];
        document.querySelectorAll(interactiveElements.join(',')).forEach(el => {
            el.addEventListener('mouseenter', () => {
                if (cursor) cursor.classList.add('hover');
            });
            el.addEventListener('mouseleave', () => {
                if (cursor) cursor.classList.remove('hover');
            });
        });

        /* HELPERS */
        function playAudio(id) {
            const audio = document.getElementById(id);
            if (audio) {
                audio.play().catch(err => console.log('Audio:', err));
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            return String(text).replace(/[&<>]/g, function(m) {
                if (m === '&') return '&amp;';
                if (m === '<') return '&lt;';
                if (m === '>') return '&gt;';
                return m;
            }).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        function getTimeString() {
            const now = new Date();
            return now.toLocaleTimeString('es-ES', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        function updateClock() {
            const clockChip = document.getElementById('clockChip');
            if (clockChip) {
                clockChip.textContent = getTimeString();
            }
        }

        function setBootTime() {
            const bootTime = document.getElementById('bootTime');
            if (bootTime) {
                bootTime.textContent = getTimeString();
            }
        }

        setInterval(updateClock, 1000);
        updateClock();
        setBootTime();

        async function apiFetch(url, options = {}) {
            const headers = {
                ...(TOKEN ? { 'Authorization': TOKEN } : {}),
                ...(options.body ? { 'Content-Type': 'application/json' } : {}),
                ...(options.headers || {})
            };

            const config = {
                ...options,
                headers
            };

            const response = await fetch(url, config);

            let data = {};
            try {
                data = await response.json();
            } catch (e) {
                data = {};
            }

            if (!response.ok) {
                const message = data.error || data.message || `HTTP ${response.status}`;
                throw new Error(message);
            }

            return data;
        }

        /* SCREEN NAV */
        function switchScreen(screenId, btn) {
            document.querySelectorAll('.screen').forEach(screen => {
                screen.classList.remove('active');
            });

            document.querySelectorAll('.nav-btn').forEach(button => {
                button.classList.remove('active');
            });

            const screen = document.getElementById(screenId);
            if (screen) screen.classList.add('active');
            if (btn) btn.classList.add('active');

            if (screenId === 'musicScreen') {
                loadMusicStatus();
            }
            if (screenId === 'lightsScreen') {
                loadDeviceRegistry();
            }
            if (screenId === 'networkScreen') {
                loadNetworkInfo();
            }
        }
