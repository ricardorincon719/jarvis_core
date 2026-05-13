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

            chatContainer.innerHTML += `
                <div class="message user-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead('TÚ', '🧑')}
                        <div class="msg-bubble">${escapeHtml(text)}</div>
                    </div>
                </div>
            `;
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function addBotMessage(text, brain, plugin) {
            if (!chatContainer) return;

            const displayBrain = brain || plugin || 'PEARL';
            const isCritico = displayBrain === 'critical' || String(displayBrain).toLowerCase().includes('crítico');
            const tagClass = isCritico ? 'brain-tag critico' : 'brain-tag';
            const icon = isCritico ? '🖥️' : '💠';

            chatContainer.innerHTML += `
                <div class="message jarvis-msg">
                    <div class="msg-wrap">
                        ${buildMessageHead(displayBrain, icon)}
                        <div class="msg-bubble">
                            <span class="${tagClass}">${isCritico ? '⚠' : '⚡'} ${escapeHtml(displayBrain)}</span>
                            ${escapeHtml(text)}
                        </div>
                    </div>
                </div>
            `;
            chatContainer.scrollTop = chatContainer.scrollHeight;
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
                    'Authorization': TOKEN,
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
                addBotMessage(data.respuesta || data.response || 'Sin respuesta del sistema', data.cerebro, data.plugin);
                return;
            }

            const streamMessage = createStreamingBotMessage('PEARL');
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';

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
                    } else if (event.event === 'error') {
                        throw new Error(event.error || 'Error de streaming');
                    }
                }

                if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
            }
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
