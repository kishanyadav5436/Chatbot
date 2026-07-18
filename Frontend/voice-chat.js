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
    
    // Language Mapping for Speech Recognition
    const langMap = {
        'en': 'en-US', 'hi': 'hi-IN', 'es': 'es-ES', 'fr': 'fr-FR',
        'de': 'de-DE', 'bn': 'bn-IN', 'mr': 'mr-IN', 'te': 'te-IN',
        'ta': 'ta-IN', 'gu': 'gu-IN', 'kn': 'kn-IN', 'ml': 'ml-IN'
    };
    const currentLang = localStorage.getItem('language') || 'en';
    window.recognition.lang = langMap[currentLang] || 'en-US';
    
    window.recognition.interimResults = false;

    window.recognition.onstart = () => {
        voiceControls.classList.remove('hidden');
        voiceControls.classList.add('active');
        voiceBtn.classList.add('voice-active');
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
        voiceControls.classList.remove('active');
        voiceBtn.classList.remove('voice-active');
    };

    window.recognition.start();
}