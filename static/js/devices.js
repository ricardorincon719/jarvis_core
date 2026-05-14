        function setDeviceStatus(text) {
            const el = document.getElementById('deviceStatus');
            if (el) el.textContent = text;
        }

        function normalizeDeviceText(text) {
            return String(text || '')
                .toLowerCase()
                .normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '')
                .replace(/[^a-z0-9_ ]+/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
        }

        function deviceTargetPhrase(name, cfg) {
            return normalizeDeviceText(name).replace(/\s+/g, '_') || normalizeDeviceText(cfg?.label).replace(/\s+/g, '_');
        }

        function commandForDevice(baseCommand, name, cfg) {
            const target = deviceTargetPhrase(name, cfg);
            return target ? `${baseCommand} ${target}` : baseCommand;
        }

        function deviceCapabilities(cfg) {
            const caps = Array.isArray(cfg?.capabilities) ? cfg.capabilities : [];
            if (caps.length) return caps;
            if (cfg?.type === 'plug' || String(cfg?.driver || '').includes('plug')) return ['switch'];
            if (cfg?.type === 'light' || String(cfg?.driver || '').includes('light')) {
                return ['switch', 'brightness', 'temperature', 'color'];
            }
            return ['switch'];
        }

        function preferredDeviceOrder(entries) {
            const rank = (name, cfg) => {
                    const value = `${normalizeDeviceText(name)} ${normalizeDeviceText(cfg?.type)}`;
                    if (value.includes('sala')) return 0;
                    if (value.includes('quarto') || value.includes('cuarto')) return 1;
                    if (value.includes('plug')) return 2;
                    return 3;
            };
            return entries.sort(([a, cfgA], [b, cfgB]) => rank(a, cfgA) - rank(b, cfgB) || a.localeCompare(b));
        }

        function selectLight(name) {
            activeLightName = decodeURIComponent(name);
            renderActiveLights(activeLightDevices);
        }

        function renderActiveLights(devices) {
            const selector = document.getElementById('lightSelector');
            const panel = document.getElementById('lightControlPanel');
            if (!selector || !panel) return;

            activeLightDevices = devices || {};
            const entries = preferredDeviceOrder(Object.entries(activeLightDevices)
                .filter(([, cfg]) => cfg && cfg.enabled !== false));

            if (!entries.length) {
                selector.innerHTML = '';
                panel.innerHTML = '<div class="device-status">No hay dispositivos activos registrados.</div>';
                return;
            }

            if (!entries.some(([name]) => name === activeLightName)) {
                activeLightName = entries[0][0];
            }

            selector.innerHTML = entries.map(([name, cfg]) => {
                const label = cfg.label || name;
                const isActive = name === activeLightName;
                const type = cfg.type || 'device';
                return `
                    <button class="light-select-btn ${isActive ? 'active' : ''}" onclick="selectLight('${encodeURIComponent(name)}')">
                        <strong>${escapeHtml(label)}</strong>
                        <span>${escapeHtml(type)} · ${escapeHtml(name)} · ${escapeHtml(cfg.ip || 'sin IP')}</span>
                    </button>
                `;
            }).join('');

            const cfg = activeLightDevices[activeLightName] || {};
            const label = cfg.label || activeLightName;
            const target = deviceTargetPhrase(activeLightName, cfg);
            const statusLabel = cfg.has_local_key === false ? 'SIN KEY' : 'ACTIVA';
            const enc = (base) => encodeURIComponent(commandForDevice(base, activeLightName, cfg));
            const caps = deviceCapabilities(cfg);
            const has = (cap) => caps.includes(cap);
            const switchControls = has('switch') ? `
                <div class="light-panel-controls">
                    <button class="btn btn-primary" onclick="runEncodedScene('${enc('prende dispositivo')}', 'On')">Encender</button>
                    <button class="btn btn-danger" onclick="runEncodedScene('${enc('apaga dispositivo')}', 'Off')">Apagar</button>
                    <button class="btn" onclick="sendEncodedQuickCommand('${enc('estado dispositivo')}')">Estado</button>
                </div>
            ` : '';
            const sceneControls = (has('brightness') || has('temperature')) ? `
                <div class="light-panel-controls scenes">
                    <button class="btn" onclick="runEncodedScene('${enc('luz normal')}', 'Normal')">Normal</button>
                    <button class="btn" onclick="runEncodedScene('${enc('luz lectura')}', 'Lectura')">Lectura</button>
                    <button class="btn" onclick="runEncodedScene('${enc('luz relax')}', 'Relax')">Relax</button>
                    <button class="btn" onclick="runEncodedScene('${enc('luz noche')}', 'Noche')">Noche</button>
                    ${has('temperature') ? `<button class="btn" onclick="runEncodedScene('${enc('luz cálida')}', 'Cálida')">Cálida</button>` : ''}
                    ${has('temperature') ? `<button class="btn" onclick="runEncodedScene('${enc('luz fría')}', 'Fría')">Fría</button>` : ''}
                </div>
            ` : '';
            const colorControls = has('color') ? `
                <div class="light-panel-controls">
                    <button class="btn color-red" onclick="runEncodedScene('${enc('luz rojo')}', 'Rojo')">Rojo</button>
                    <button class="btn color-blue" onclick="runEncodedScene('${enc('luz azul')}', 'Azul')">Azul</button>
                    <button class="btn color-green" onclick="runEncodedScene('${enc('luz verde')}', 'Verde')">Verde</button>
                </div>
            ` : '';
            const energyPanel = has('energy') ? `
                <div class="device-status">Consumo disponible cuando el driver reporte energía.</div>
            ` : '';

            panel.innerHTML = `
                <div class="light-panel-top">
                    <div>
                        <div class="light-panel-title">${escapeHtml(label)}</div>
                        <div class="light-panel-subtitle">${escapeHtml(cfg.type || 'device')} · ${escapeHtml(activeLightName)} · ${escapeHtml(cfg.ip || 'sin IP')}</div>
                    </div>
                    <div class="device-badge">${statusLabel}</div>
                </div>
                ${switchControls}
                ${sceneControls}
                ${colorControls}
                ${energyPanel}
            `;
        }

        function renderDevices(devices) {
            const list = document.getElementById('deviceList');
            if (!list) return;

            const entries = Object.entries(devices || {});
            if (!entries.length) {
                list.innerHTML = '<div class="device-status">No hay dispositivos registrados.</div>';
                return;
            }

            list.innerHTML = entries.map(([name, cfg]) => `
                <div class="device-row">
                    <div class="device-row-head">
                        <div>
                            <div class="device-name">${escapeHtml(cfg.label || name)}</div>
                            <div class="device-meta">${escapeHtml(cfg.room || 'sin sala')} · ${escapeHtml(cfg.ip || 'sin IP')} · ${escapeHtml(cfg.device_id || 'sin id')}</div>
                        </div>
                        <div class="device-badge">${cfg.enabled === false ? 'OFF' : 'ACTIVO'}</div>
                    </div>
                </div>
            `).join('');
        }

        function renderDeviceCandidates(candidates) {
            const container = document.getElementById('deviceCandidates');
            if (!container) return;

            if (!candidates || !candidates.length) {
                container.innerHTML = '';
                return;
            }

            container.innerHTML = candidates.map(candidate => {
                const id = candidate.candidate_id;
                return `
                    <div class="device-row">
                        <div class="device-row-head">
                            <div>
                                <div class="device-name">${escapeHtml(candidate.name_hint || 'Lámpara Tuya')}</div>
                                <div class="device-meta">${escapeHtml(candidate.ip || 'sin IP')} · ${escapeHtml(candidate.mac || 'sin MAC')} · ${escapeHtml(candidate.device_id || 'sin id')}</div>
                            </div>
                            <div class="device-badge">PENDIENTE</div>
                        </div>
                        <div class="device-form">
                            <input id="name-${id}" type="text" placeholder="Nombre" value="${escapeHtml(candidate.name_hint || 'Lámpara Tuya')}">
                            <input id="room-${id}" type="text" placeholder="Sala" value="cuarto">
                            <input id="key-${id}" type="password" placeholder="Local key Tuya">
                            <button class="btn btn-primary" onclick="approveDevice('${id}')">Aprobar</button>
                        </div>
                        <div class="device-actions">
                            <button class="btn" onclick="rejectDevice('${id}')">Rechazar</button>
                            <button class="btn" onclick="sendQuickCommand('estado de la lámpara')">Probar estado</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function loadDeviceRegistry() {
            try {
                const [devicesData, candidatesData] = await Promise.all([
                    apiFetch('/devices'),
                    apiFetch('/devices/candidates')
                ]);
                renderDevices(devicesData.devices || {});
                renderActiveLights(devicesData.devices || {});
                renderDeviceCandidates(candidatesData.candidates || []);
                const pending = (candidatesData.candidates || []).length;
                setDeviceStatus(pending ? `${pending} dispositivo(s) pendiente(s) de aprobación.` : 'Sin candidatos pendientes.');
            } catch (e) {
                console.error('Error cargando dispositivos:', e);
                setDeviceStatus(`Dispositivos no disponibles: ${e.message}`);
            }
        }

        async function discoverDevices() {
            setDeviceStatus('Escaneando red local Tuya...');
            try {
                const data = await apiFetch('/devices/discover', {
                    method: 'POST',
                    body: JSON.stringify({ timeout: 8 })
                });
                const summary = data.summary || {};
                renderDeviceCandidates(data.pending || []);
                setDeviceStatus(`Detectados: ${summary.total || 0}. Nuevos: ${summary.new || 0}. Registrados: ${summary.known || 0}.`);
                await loadDeviceRegistry();
            } catch (e) {
                console.error('Error descubriendo dispositivos:', e);
                setDeviceStatus(`Discovery falló: ${e.message}`);
            }
        }

        async function approveDevice(candidateId) {
            const name = document.getElementById(`name-${candidateId}`)?.value || '';
            const room = document.getElementById(`room-${candidateId}`)?.value || '';
            const localKey = document.getElementById(`key-${candidateId}`)?.value || '';

            setDeviceStatus('Aprobando dispositivo...');
            try {
                await apiFetch(`/devices/candidates/${candidateId}/approve`, {
                    method: 'POST',
                    body: JSON.stringify({ name, room, local_key: localKey })
                });
                setDeviceStatus('Dispositivo aprobado y registrado.');
                await loadDeviceRegistry();
            } catch (e) {
                console.error('Error aprobando dispositivo:', e);
                const message = e.message === 'local_key_required'
                    ? 'Falta la local key de Tuya para controlar este dispositivo localmente.'
                    : `No se pudo aprobar: ${e.message}`;
                setDeviceStatus(message);
            }
        }

        async function rejectDevice(candidateId) {
            setDeviceStatus('Rechazando candidato...');
            try {
                await apiFetch(`/devices/candidates/${candidateId}/reject`, { method: 'POST' });
                setDeviceStatus('Candidato rechazado.');
                await loadDeviceRegistry();
            } catch (e) {
                console.error('Error rechazando dispositivo:', e);
                setDeviceStatus(`No se pudo rechazar: ${e.message}`);
            }
        }
