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

        async function loadBatteryStatus() {
            const batteryStatus = document.getElementById('batteryStatus');

            try {
                const data = await apiFetch('/battery');
                if (batteryStatus) batteryStatus.innerText = `${data.percentage ?? '--'}%`;
            } catch (e) {
                console.error('Error /battery:', e);
                if (batteryStatus) batteryStatus.innerText = '--%';
            }
        }
