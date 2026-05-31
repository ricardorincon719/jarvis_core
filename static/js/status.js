        /* STATUS */
        async function loadPluginsStatus() {
            const pluginStatus = document.getElementById('pluginStatus');

            try {
                const data = await apiFetch('/plugins');
                if (pluginStatus) pluginStatus.innerText = data.total ?? '?';
            } catch (e) {
                console.error('Error /plugins:', e);
                if (pluginStatus) pluginStatus.innerText = '?';
            }
        }

        function formatAiStatus(data) {
            const active = data.active || data.provider || 'local';
            const local = data.local || {};
            const cloud = data.cloud || {};

            if (active === 'cloud') {
                if (!cloud.enabled) return 'CLOUD OFF';
                return cloud.connected ? 'CLOUD OK' : 'CLOUD ERR';
            }

            if (!local.enabled) return 'LOCAL OFF';
            if (!local.connected) return 'LOCAL OFF';
            if (local.model_loaded) return 'LOCAL OK';
            if (local.model_available) return 'LOCAL LISTA';
            return 'SIN MODELO';
        }

        async function loadAiStatus() {
            const aiStatus = document.getElementById('aiStatus');

            try {
                const data = await apiFetch('/ai/status');
                if (aiStatus) {
                    aiStatus.innerText = formatAiStatus(data);
                    aiStatus.classList.toggle('status-online', Boolean(data.connected));
                    aiStatus.title = JSON.stringify({
                        active: data.active,
                        local: data.local?.status,
                        local_model: data.local?.model,
                        cloud: data.cloud?.status,
                        cloud_provider: data.cloud?.provider
                    });
                }
            } catch (e) {
                console.error('Error /ai/status:', e);
                if (aiStatus) {
                    aiStatus.innerText = 'IA ERR';
                    aiStatus.classList.remove('status-online');
                }
            }
        }
