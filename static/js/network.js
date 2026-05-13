        async function loadNetworkInfo() {
            const localUrl = document.getElementById('localUrl');
            const lanIp = document.getElementById('lanIp');
            const lanUrl = document.getElementById('lanUrl');
            const networkStatus = document.getElementById('networkStatus');

            try {
                const data = await apiFetch('/network');

                if (localUrl) localUrl.innerText = data.localhost || 'http://127.0.0.1:5004';
                if (lanIp) lanIp.innerText = data.lan_ip || 'No disponible';
                if (lanUrl) lanUrl.innerText = data.lan_url || 'No disponible';
                if (networkStatus) networkStatus.innerText = 'ONLINE';
            } catch (e) {
                console.error('Error /network:', e);

                if (lanIp) lanIp.innerText = 'No disponible';
                if (lanUrl) lanUrl.innerText = 'No disponible';
                if (networkStatus) networkStatus.innerText = 'SIN RED';
            }
        }
