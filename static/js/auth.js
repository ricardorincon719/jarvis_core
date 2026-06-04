        /* AUTH */
        let authStatusIntervalsStarted = false;

        async function openAuthenticatedInterface(playWelcome = false) {
            const authOverlay = document.getElementById('authOverlay');
            const mainInterface = document.getElementById('mainInterface');
            isAuthenticated = true;

            if (authOverlay) authOverlay.classList.add('hidden');
            if (mainInterface) mainInterface.classList.add('active');

            await Promise.allSettled([
                loadPluginsStatus(),
                loadAiStatus(),
                loadNetworkInfo(),
                loadMusicStatus(),
                loadDeviceRegistry()
            ]);

            if (!authStatusIntervalsStarted) {
                authStatusIntervalsStarted = true;
                setInterval(loadNetworkInfo, 10000);
                setInterval(loadMusicStatus, 5000);
                setInterval(loadAiStatus, 10000);
            }

            if (playWelcome) playAudio('audioWelcome');
        }

        async function resumeRememberedSession() {
            if (!TOKEN) return;
            try {
                await apiFetch('/api/v1/auth/session');
                await openAuthenticatedInterface(false);
            } catch (err) {
                console.warn('Sesión recordada no válida:', err);
                setApiToken('');
            }
        }

        async function logoutSession() {
            try {
                if (TOKEN) await apiFetch('/api/v1/auth/logout', { method: 'POST' });
            } catch (err) {
                console.warn('No se pudo revocar la sesión remota:', err);
            } finally {
                setApiToken('');
                isAuthenticated = false;
                window.location.reload();
            }
        }

        async function authenticate() {
            const pinInput = document.getElementById('pinInput');
            const authError = document.getElementById('authError');
            const authSuccess = document.getElementById('authSuccess');
            const pin = pinInput ? pinInput.value.trim() : '';

            if (authError) authError.style.display = 'none';
            if (authSuccess) authSuccess.style.display = 'none';

            if (!pin || pin.length < 4) {
                if (authError) {
                    authError.innerText = '🔒 Acceso denegado';
                    authError.style.display = 'block';
                }
                playAudio('audioDenied');
                return;
            }

            try {
                const data = await apiFetch('/ask_auth', {
                    method: 'POST',
                    body: JSON.stringify({
                        pin,
                        device_id: getOrCreateDeviceId(),
                        device_name: 'PEARL Web Client'
                    })
                });

                if (data.success) {
                    setApiToken(data.token || '');
                    isAuthenticated = true;

                    if (authSuccess) {
                        authSuccess.innerText = data.message || '✅ Acceso concedido';
                        authSuccess.style.display = 'block';
                    }

                    if (authError) authError.style.display = 'none';
                    playAudio('audioGranted');

                    setTimeout(async () => {
                        await openAuthenticatedInterface(true);
                    }, 800);
                } else {
                    throw new Error(data.message || 'PIN incorrecto');
                }
            } catch (err) {
                console.error('Error en authenticate():', err);

                if (authError) {
                    authError.innerText = `🔒 ${err.message || 'Acceso denegado'}`;
                    authError.style.display = 'block';
                }

                if (pinInput) pinInput.value = '';
                playAudio('audioDenied');
            }
        }

        document.getElementById('pinInput')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') authenticate();
        });

        window.addEventListener('load', resumeRememberedSession);
