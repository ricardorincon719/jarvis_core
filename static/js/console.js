        /* CONSOLE */
        function buildMessageHead(label, icon) {
            return `
                <div class="msg-head">
                    <span class="msg-avatar">${icon}</span>
                    <span>${escapeHtml(label)}</span>
                    <span class="msg-time">${getTimeString()}</span>
                </div>
            `;
        }

        function addUserMessage(text) {
            if (!chatContainer) return;

            chatContainer.insertAdjacentHTML('beforeend', `
                <div class="message user-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead('TÚ', '🧑')}
                        <div class="msg-bubble">${escapeHtml(text)}</div>
                    </div>
                </div>
            `);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function addBotMessage(text, brain, plugin) {
            if (!chatContainer) return;

            const displayBrain = brain || plugin || 'PEARL';
            const isCritico = displayBrain === 'critical' || String(displayBrain).toLowerCase().includes('crítico');
            const tagClass = isCritico ? 'brain-tag critico' : 'brain-tag';
            const icon = isCritico ? '🖥️' : '💠';

            chatContainer.insertAdjacentHTML('beforeend', `
                <div class="message jarvis-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead(displayBrain, icon)}
                        <div class="msg-bubble">
                            <span class="${tagClass}">${isCritico ? '⚠' : '⚡'} ${escapeHtml(displayBrain)}</span>
                            ${escapeHtml(text)}
                        </div>
                    </div>
                </div>
            `);
            const message = chatContainer.lastElementChild;
            chatContainer.scrollTop = chatContainer.scrollHeight;
            return message;
        }

        function handleBotPayload(data) {
            const responseText = data.respuesta || data.response || 'Sin respuesta del sistema';
            const message = addBotMessage(
                responseText,
                data.cerebro,
                data.plugin
            );
            speakVoiceResponse(responseText);
            const proposal = data.proposal;
            if (!message || !data.requires_confirmation || !proposal?.id) return;

            const bubble = message.querySelector('.msg-bubble');
            if (!bubble) return;
            const controls = document.createElement('div');
            controls.className = 'action-confirmation';
            controls.dataset.proposalId = proposal.id;

            const confirm = document.createElement('button');
            confirm.type = 'button';
            confirm.className = 'action-confirm action-confirm-accept';
            confirm.textContent = 'Confirmar';
            confirm.addEventListener('click', () => decideActionProposal(proposal.id, 'accept', controls));

            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'action-confirm action-confirm-cancel';
            cancel.textContent = 'Rechazar';
            cancel.addEventListener('click', () => decideActionProposal(proposal.id, 'cancel', controls));

            controls.append(confirm, cancel);
            bubble.appendChild(controls);
        }

        async function decideActionProposal(proposalId, decision, controls) {
            const buttons = controls ? controls.querySelectorAll('button') : [];
            buttons.forEach(button => { button.disabled = true; });
            const idempotencyKey = window.crypto?.randomUUID
                ? window.crypto.randomUUID()
                : `decision-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            try {
                const data = await apiFetch(`/api/v1/actions/${encodeURIComponent(proposalId)}/decision`, {
                    method: 'POST',
                    body: JSON.stringify({ decision, idempotency_key: idempotencyKey })
                });
                if (controls) controls.remove();
                addBotMessage(
                    data.respuesta || data.result?.respuesta || (decision === 'accept' ? 'Accion ejecutada.' : 'Accion cancelada.'),
                    'JARVIS',
                    data.result?.plugin
                );
            } catch (error) {
                buttons.forEach(button => { button.disabled = false; });
                addBotMessage(`No pude resolver la confirmacion: ${error.message}`, 'SISTEMA');
            }
        }

        function createStreamingBotMessage(brain, plugin) {
            if (!chatContainer) return null;

            const displayBrain = brain || plugin || 'PEARL';
            const isCritico = displayBrain === 'critical' || String(displayBrain).toLowerCase().includes('critical') || String(displayBrain).toLowerCase().includes('crítico');
            const tagClass = isCritico ? 'brain-tag critico' : 'brain-tag';
            const icon = isCritico ? '🖥️' : '💠';

            chatContainer.insertAdjacentHTML('beforeend', `
                <div class="message jarvis-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead(displayBrain, icon)}
                        <div class="msg-bubble">
                            <span class="${tagClass}" data-role="stream-tag">${isCritico ? '⚠' : '⚡'} ${escapeHtml(displayBrain)}</span>
                            <span data-role="stream-text"></span>
                        </div>
                    </div>
                </div>
            `);

            const message = chatContainer.lastElementChild;
            chatContainer.scrollTop = chatContainer.scrollHeight;
            return {
                textEl: message.querySelector('[data-role="stream-text"]'),
                tagEl: message.querySelector('[data-role="stream-tag"]')
            };
        }

        function updateStreamingMeta(streamMessage, event) {
            if (!streamMessage || !streamMessage.tagEl) return;

            const label = event.brain && event.model
                ? `orchestrator→${event.brain}→${event.model}`
                : (event.brain || event.plugin || 'PEARL');
            const isCritico = String(event.plugin || label).toLowerCase().includes('critical') || String(label).toLowerCase().includes('crítico');
            streamMessage.tagEl.textContent = `${isCritico ? '⚠' : '⚡'} ${label}`;
        }

        async function streamBotResponse(text) {
            const response = await fetch('/ask_stream', {
                method: 'POST',
                headers: {
                    ...(typeof bridgeHeaders === 'function' ? bridgeHeaders() : {}),
                    ...(TOKEN ? { 'Authorization': TOKEN } : {}),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pregunta: text })
            });

            if (!response.ok) {
                let message = `HTTP ${response.status}`;
                try {
                    const data = await response.json();
                    message = data.error || data.message || message;
                } catch (e) {}
                throw new Error(message);
            }

            const contentType = response.headers.get('Content-Type') || '';
            if (!response.body || !contentType.includes('application/x-ndjson')) {
                const data = await response.json();
                handleBotPayload(data);
                return;
            }

            const streamMessage = createStreamingBotMessage('PEARL');
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            let responseSpoken = false;

            function speakFinalResponse() {
                if (responseSpoken || !fullText.trim()) return;
                responseSpoken = true;
                speakVoiceResponse(fullText);
            }

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.trim()) continue;

                    let event;
                    try {
                        event = JSON.parse(line);
                    } catch (e) {
                        continue;
                    }

                    if (event.event === 'meta') {
                        updateStreamingMeta(streamMessage, event);
                    } else if (event.event === 'token') {
                        fullText += event.response || '';
                        if (streamMessage && streamMessage.textEl) {
                            streamMessage.textEl.textContent = fullText;
                        }
                    } else if (event.event === 'done') {
                        if (event.response && (!fullText || event.response.length >= fullText.length)) {
                            fullText = event.response;
                            if (streamMessage && streamMessage.textEl) {
                                streamMessage.textEl.textContent = fullText;
                            }
                        }
                        updateStreamingMeta(streamMessage, event);
                        speakFinalResponse();
                    } else if (event.event === 'error') {
                        throw new Error(event.error || 'Error de streaming');
                    }
                }

                if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            speakFinalResponse();
        }

        function clearChat() {
            if (!chatContainer) return;

            chatContainer.innerHTML = `
                <div class="message jarvis-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead('PEARL SYSTEM', '💠')}
                        <div class="msg-bubble">
                            <span class="brain-tag">⚡ CORE ONLINE</span>
                            Consola reiniciada. Lista para nuevas órdenes.
                        </div>
                    </div>
                </div>
            `;
        }

        function handleKey(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }

        let voiceStateTimer = null;

        function speakVoiceResponse(text) {
            const responseText = String(text || '').trim();
            if (!responseText || !window.PearlAndroid?.speak) return;

            try {
                if (window.PearlAndroid.isSpeechAvailable?.()) {
                    window.PearlAndroid.speak(responseText);
                }
            } catch (error) {
                console.warn('Texto a voz no disponible:', error);
            }
        }

        function setVoiceState(state) {
            const voiceBtn = document.getElementById('voiceBtn');
            if (!voiceBtn) return;
            if (voiceStateTimer) {
                window.clearTimeout(voiceStateTimer);
                voiceStateTimer = null;
            }
            voiceBtn.classList.toggle('listening', state === 'listening');
            voiceBtn.classList.toggle('processing', state === 'processing');
            voiceBtn.disabled = state === 'requesting_permission' || state === 'processing';
            voiceBtn.textContent = state === 'listening' ? '⏹' : (state === 'processing' ? '…' : '🎙');
            voiceBtn.setAttribute('aria-pressed', state === 'listening' ? 'true' : 'false');

            if (state === 'listening' || state === 'processing') {
                const timeout = state === 'listening' ? 17000 : 10000;
                voiceStateTimer = window.setTimeout(() => {
                    voiceStateTimer = null;
                    setVoiceState('idle');
                    addBotMessage('La escucha agotó el tiempo disponible. Intenta nuevamente.', 'SISTEMA');
                }, timeout);
            }
        }

        function startVoiceCommand() {
            if (!window.PearlAndroid?.startVoiceCommand) {
                addBotMessage('El micrófono nativo solo está disponible desde PEARL Client.', 'SISTEMA');
                return;
            }
            window.PearlAndroid.stopSpeaking?.();
            setVoiceState('listening');
            window.PearlAndroid.startVoiceCommand();
        }

        function readSpeechVoices() {
            if (!window.PearlAndroid?.getSpeechVoices) return [];
            try {
                const rawVoices = window.PearlAndroid.getSpeechVoices();
                const voices = JSON.parse(String(rawVoices || '[]'));
                return Array.isArray(voices) ? voices : [];
            } catch (error) {
                console.warn('No pude leer las voces del celular:', error);
                return [];
            }
        }

        function setSpeechVoiceStatus(message, isError = false) {
            const status = document.getElementById('speechVoiceStatus');
            if (!status) return;
            status.textContent = message || '';
            status.style.color = isError ? 'var(--danger)' : 'var(--text-soft)';
        }

        function refreshSpeechVoiceSelector() {
            const panel = document.getElementById('speechVoicePanel');
            const select = document.getElementById('speechVoiceSelect');
            if (!panel || !select || !window.PearlAndroid?.getSpeechVoices) return;

            const voices = readSpeechVoices();
            if (!voices.length) {
                panel.hidden = true;
                return;
            }

            const current = String(
                window.PearlAndroid.getSelectedSpeechVoice?.() || ''
            );
            select.replaceChildren(...voices.map(voice => {
                const option = document.createElement('option');
                option.value = String(voice.id || '');
                option.textContent = String(voice.label || voice.id || 'Voz española');
                option.selected = option.value === current;
                return option;
            }));
            panel.hidden = false;
            setSpeechVoiceStatus(
                `${voices.length} ${voices.length === 1 ? 'voz disponible' : 'voces disponibles'}`
            );
        }

        function saveSelectedSpeechVoice() {
            const select = document.getElementById('speechVoiceSelect');
            const voiceId = String(select?.value || '');
            if (!voiceId || !window.PearlAndroid?.setSpeechVoice) return;
            try {
                const saved = window.PearlAndroid.setSpeechVoice(voiceId);
                setSpeechVoiceStatus(
                    saved ? 'Voz guardada en este celular.' : 'No pude seleccionar esa voz.',
                    !saved
                );
            } catch (error) {
                setSpeechVoiceStatus('No pude guardar la voz seleccionada.', true);
            }
        }

        function previewSelectedSpeechVoice() {
            const select = document.getElementById('speechVoiceSelect');
            const voiceId = String(select?.value || '');
            if (!voiceId || !window.PearlAndroid?.previewSpeechVoice) return;
            try {
                const started = window.PearlAndroid.previewSpeechVoice(voiceId);
                setSpeechVoiceStatus(
                    started ? 'Reproduciendo muestra…' : 'No pude reproducir esa voz.',
                    !started
                );
            } catch (error) {
                setSpeechVoiceStatus('No pude reproducir la muestra.', true);
            }
        }

        window.PEARL_VOICE = {
            onState(state) {
                setVoiceState(state || 'idle');
            },
            onResult(text) {
                setVoiceState('idle');
                const transcript = String(text || '').trim();
                if (!transcript || !userInput) return;
                userInput.value = transcript;
                sendMessage();
            },
            onError(message) {
                setVoiceState('idle');
                addBotMessage(message || 'No pude reconocer el comando de voz.', 'SISTEMA');
            }
        };

        window.PEARL_SPEECH = {
            refresh: refreshSpeechVoiceSelector
        };

        document.getElementById('speechVoiceSelect')
            ?.addEventListener('change', saveSelectedSpeechVoice);
        document.getElementById('speechVoicePreview')
            ?.addEventListener('click', previewSelectedSpeechVoice);
        refreshSpeechVoiceSelector();

        try {
            const voiceBtn = document.getElementById('voiceBtn');
            if (voiceBtn && window.PearlAndroid?.isVoiceAvailable?.()) {
                voiceBtn.hidden = false;
            }
        } catch (error) {
            console.warn('Voz nativa no disponible:', error);
        }

        async function sendMessage() {
            if (!isAuthenticated || !userInput) return;

            const text = userInput.value.trim();
            if (!text) return;

            addUserMessage(text);
            userInput.value = '';
            if (loader) loader.classList.add('active');

            try {
                await streamBotResponse(text);
            } catch (error) {
                console.error('Error /ask_stream:', error);
                addBotMessage(`Error de comunicación: ${error.message}`, 'SISTEMA');
            } finally {
                if (loader) loader.classList.remove('active');
                if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
                loadMusicStatus();
            }
        }

        /* QUICK COMMANDS */
        async function sendQuickCommand(text) {
            if (!isAuthenticated || !text) return;

            addUserMessage(text);
            if (loader) loader.classList.add('active');

            try {
                await streamBotResponse(text);
            } catch (error) {
                console.error('Error /ask_stream rápido:', error);
                addBotMessage(`Error de comunicación: ${error.message}`, 'SISTEMA');
            } finally {
                if (loader) loader.classList.remove('active');
                if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
                loadMusicStatus();
            }
        }
