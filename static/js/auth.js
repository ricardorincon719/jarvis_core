        /* AUTH */
        async function authenticate() {
            const pinInput = document.getElementById('pinInput');
            const authError = document.getElementById('authError');
            const authSuccess = document.getElementById('authSuccess');
            const authOverlay = document.getElementById('authOverlay');
            const mainInterface = document.getElementById('mainInterface');
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
                    body: JSON.stringify({ pin })
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
                        if (authOverlay) authOverlay.classList.add('hidden');
                        if (mainInterface) mainInterface.classList.add('active');

                        await loadPluginsStatus();
                        await loadAiStatus();
                        await loadNetworkInfo();
                        await loadMusicStatus();
                        await loadDeviceRegistry();

                        setInterval(loadNetworkInfo, 10000);
                        setInterval(loadMusicStatus, 5000);
                        setInterval(loadAiStatus, 10000);

                        playAudio('audioWelcome');
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
