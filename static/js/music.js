        function formatDuration(seconds) {
            const value = Number(seconds);
            if (!Number.isFinite(value) || value <= 0) return '';
            const mins = Math.floor(value / 60);
            const secs = Math.floor(value % 60).toString().padStart(2, '0');
            return `${mins}:${secs}`;
        }

        function setNowPlayingEmpty(message = 'Nada sonando ahora') {
            const art = document.getElementById('nowPlayingArt');
            const kicker = document.getElementById('nowPlayingKicker');
            const title = document.getElementById('nowPlayingTitle');
            const target = document.getElementById('nowPlayingTarget');
            const query = document.getElementById('nowPlayingQuery');

            if (art) {
                art.innerHTML = '';
                art.textContent = '♪';
            }
            if (kicker) kicker.textContent = 'Sin reproducción activa';
            if (title) title.textContent = message;
            if (target) target.textContent = '--';
            if (query) query.textContent = 'Esperando música';
        }

        function renderNowPlaying(active) {
            const art = document.getElementById('nowPlayingArt');
            const kicker = document.getElementById('nowPlayingKicker');
            const title = document.getElementById('nowPlayingTitle');
            const target = document.getElementById('nowPlayingTarget');
            const query = document.getElementById('nowPlayingQuery');

            if (!active || (!active.running && !active.playing && !active.title && !active.query)) {
                setNowPlayingEmpty();
                return;
            }

            const targetLabel = active.target === 'laptop' ? 'Laptop' : 'Celular';
            const stateLabel = active.paused ? 'En pausa' : 'Sonando ahora';
            const duration = formatDuration(active.duration);
            const queryText = active.query ? `Búsqueda: ${active.query}` : '';
            const metaText = duration ? `${queryText} · ${duration}` : queryText;

            if (art) {
                art.innerHTML = '';
                if (active.thumbnail) {
                    const img = document.createElement('img');
                    img.src = active.thumbnail;
                    img.alt = '';
                    art.appendChild(img);
                } else {
                    art.textContent = '♪';
                }
            }
            if (kicker) kicker.textContent = stateLabel;
            if (title) title.textContent = active.title || active.query || 'Música activa';
            if (target) target.textContent = targetLabel;
            if (query) query.textContent = metaText || 'Reproducción activa';
        }

        async function loadMusicStatus() {
            try {
                const data = await apiFetch('/music/status');
                renderNowPlaying(data.active);
            } catch (e) {
                console.error('Error /music/status:', e);
                setNowPlayingEmpty('Estado musical no disponible');
            }
        }


        /* MUSIC PREMIUM */
        function playQuickMusic() {
            const input = document.getElementById('musicQuickInput');
            const query = input ? input.value.trim() : '';
            if (!query) return;
            sendQuickCommand(`reproduce ${query}`);
            input.value = '';
        }

        function setMusicPreset(name) {
            const input = document.getElementById('musicQuickInput');
            if (input) {
                input.value = name;
            }
            playQuickMusic();
        }
