const voiceBtn = document.getElementById('voice-btn');
const stopVoiceBtn = document.getElementById('stop-voice-btn');
const voiceControls = document.getElementById('voice-controls');

voiceBtn.addEventListener('click', startSpeechRecognition);
stopVoiceBtn.addEventListener('click', () => {
    if (window.recognition) window.recognition.stop();
});

function startSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (!SpeechRecognition) {
        window.showToast('Browser Unsupported', 'Try Chrome or Edge for voice.', 'error');
        return;
    }

    window.recognition = new SpeechRecognition();
    window.recognition.lang = 'en-US';
    window.recognition.interimResults = false;

    window.recognition.onstart = () => {
        voiceControls.classList.remove('hidden');
        voiceBtn.classList.add('bg-red-500', 'text-white');
    };

    window.recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        document.getElementById('user-input').value = transcript;
        document.getElementById('send-btn').disabled = false;
        document.getElementById('user-input').dispatchEvent(new Event('input'));
    };

    window.recognition.onerror = () => {
        window.showToast('Mic Error', 'Could not access microphone.', 'error');
    };

    window.recognition.onend = () => {
        voiceControls.classList.add('hidden');
        voiceBtn.classList.remove('bg-red-500', 'text-white');
    };

    window.recognition.start();
}