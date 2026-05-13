        /* LIGHTS PREMIUM UI */
        function toggleLegacyControls() {
            const block = document.getElementById('legacyControls');
            const icon = document.getElementById('legacyToggleIcon');
            if (!block) return;

            const open = block.classList.toggle('open');
            if (icon) icon.textContent = open ? 'Ocultar' : 'Mostrar';
        }

        function updateBrightnessLabel(value) {
            const brightnessValue = document.getElementById('brightnessValue');
            const miniBrightness = document.getElementById('miniBrightness');
            if (brightnessValue) brightnessValue.textContent = value;
            if (miniBrightness) miniBrightness.textContent = value;
        }

        function setLightMode(mode) {
            const miniMode = document.getElementById('miniMode');
            const lightIndicator = document.getElementById('lightIndicator');
            if (miniMode) miniMode.textContent = mode;
            if (lightIndicator) {
                lightIndicator.textContent = mode === 'Off' ? 'IDLE' : 'ACTIVE';
            }
        }

        function runScene(command, mode) {
            setLightMode(mode || 'Custom');
            sendQuickCommand(command);
        }

        function runEncodedScene(encodedCommand, mode) {
            runScene(decodeURIComponent(encodedCommand), mode);
        }

        function sendEncodedQuickCommand(encodedCommand) {
            sendQuickCommand(decodeURIComponent(encodedCommand));
        }

        function applyBrightness() {
            const slider = document.getElementById('brightnessSlider');
            if (!slider) return;

            const value = parseInt(slider.value, 10);
            let command = '';
            let mode = 'Custom';

            if (value <= 150) {
                command = 'brillo min';
                mode = 'Mínimo';
            } else if (value >= 950) {
                command = 'brillo max';
                mode = 'Máximo';
            } else if (value < 500) {
                command = 'luz noche';
                mode = 'Noche';
            } else if (value < 700) {
                command = 'luz relax';
                mode = 'Relax';
            } else if (value < 900) {
                command = 'prende la lámpara';
                mode = 'Normal';
            } else {
                command = 'luz lectura';
                mode = 'Lectura';
            }

            setLightMode(mode);
            sendQuickCommand(command);
        }
