document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'https://chatbot-3-hpx2.onrender.com';
    
    // State
    let authToken = localStorage.getItem('token');
    let userEmail = localStorage.getItem('email');
    let currentConversationId = localStorage.getItem('currentConversationId');

    // Parse Token from URL (for Google OAuth callback)
    const urlParams = new URLSearchParams(window.location.search);
    const tokenParam = urlParams.get('token');
    const emailParam = urlParams.get('email');
    if (tokenParam) {
        localStorage.setItem('token', tokenParam);
        if (emailParam) localStorage.setItem('email', emailParam);
        
        // Clean up the URL to remove the token hash
        window.history.replaceState({}, document.title, window.location.pathname);
        
        authToken = tokenParam;
        userEmail = emailParam || localStorage.getItem('email');
    }
    
    // ⭐ CONCURRENCY: Message queue for parallel processing
    let messageQueue = [];
    let isProcessingQueue = false;
    
    // Elements
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const chatForm = document.getElementById('chat-form');
    const sendBtn = document.getElementById('send-btn');
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');
    const historyList = document.getElementById('chat-history-list');
    
    // Initialize marked
    marked.setOptions({ gfm: true, breaks: true });

    function renderMessage(text, sender) {
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = `flex ${sender === 'user' ? 'justify-end' : 'justify-start'} mb-8 message-animate group`;
        
        const isBot = sender === 'bot';
        const avatarUrl = isBot ? 'https://ui-avatars.com/api/?name=IA&background=6366f1&color=fff' : `https://ui-avatars.com/api/?name=${encodeURIComponent(localStorage.getItem('email') || 'U')}&background=cbd5e1&color=475569`;
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        div.innerHTML = `
            <div class="flex ${isBot ? 'flex-row' : 'flex-row-reverse'} gap-4 max-w-[85%] md:max-w-[70%]">
                <!-- Avatar -->
                <div class="flex-shrink-0 mt-1">
                    <div class="w-10 h-10 rounded-full overflow-hidden border-2 border-slate-100 dark:border-gray-800 shadow-sm">
                        <img src="${avatarUrl}" class="w-full h-full object-cover">
                    </div>
                </div>

                <!-- Bubble Container -->
                <div class="flex flex-col ${isBot ? 'items-start' : 'items-end'} gap-2">
                    <div class="${isBot ? 'bot-bubble' : 'user-bubble'} px-6 py-4 relative">
                        <div class="prose dark:prose-invert max-w-none text-inherit">
                            ${isBot ? marked.parse(DOMPurify.sanitize(text)) : `<p>${text}</p>`}
                        </div>
                        
                        <!-- Status & Time -->
                        <div class="flex items-center gap-1.5 mt-2 opacity-50 text-[10px] font-bold">
                            <span>${time}</span>
                            ${!isBot ? '<i class="bi bi-check2-all text-indigo-200"></i>' : ''}
                        </div>
                    </div>

                    <!-- Action Bar (Bot Only) -->
                    ${isBot ? `
                        <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-1">
                            <button class="message-action-btn" onclick="speakText(\`${text.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)" title="Listen"><i class="bi bi-volume-up"></i></button>
                            <button class="message-action-btn" onclick="copyToClipboard(\`${text.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)" title="Copy"><i class="bi bi-copy"></i></button>
                            <button class="message-action-btn" title="Refine"><i class="bi bi-arrow-repeat"></i></button>
                            <button class="message-action-btn" title="Report"><i class="bi bi-hand-thumbs-down"></i></button>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
        
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function showQueueTyping() {
        document.getElementById('queue-typing')?.remove();
        const div = document.createElement('div');
        div.id = 'queue-typing';
        div.className = 'flex justify-start mb-8 message-animate';
        div.innerHTML = `
            <div class="flex gap-4 items-center">
                <div class="w-10 h-10 rounded-full border border-slate-200 dark:border-gray-800 flex items-center justify-center text-indigo-600 shadow-sm">
                    <i class="bi bi-robot"></i>
                </div>
                <div class="flex gap-2 bg-slate-50 dark:bg-gray-900 border border-slate-100 dark:border-gray-800 px-6 py-4 rounded-3xl rounded-tl-none font-bold text-xs text-slate-500">
                    <span class="animate-pulse">Thinking (${messageQueue.length})</span>
                    <span class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce"></span>
                    <span class="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                </div>
            </div>
        `;
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
    
    function updateQueueUI() {
        document.getElementById('queue-typing')?.remove();
        if (messageQueue.length > 0 && isProcessingQueue) {
            showQueueTyping();
        }
    }

    function showTyping() {
        document.getElementById('typing-indicator')?.remove();
        const div = document.createElement('div');
        div.id = 'typing-indicator';
        div.className = 'flex justify-start mb-10 message-animate';
        div.innerHTML = `
            <div class="flex gap-5 items-center">
                <div class="w-11 h-11 rounded-2xl glass-effect flex items-center justify-center text-blue-600 shadow-sm">
                    <i class="bi bi-robot"></i>
                </div>
                <div class="flex gap-2 glass-effect px-6 py-5 rounded-[1.8rem] rounded-tl-none border border-slate-100 dark:border-gray-800">
                    <span class="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></span>
                    <span class="w-2 h-2 bg-blue-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                    <span class="w-2 h-2 bg-blue-600 rounded-full animate-bounce [animation-delay:0.4s]"></span>
                </div>
            </div>
        `;
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // --- API Interactions ---

    async function sendMessage(text) {
        if (!text.trim()) return;
        
        // ⭐ CONCURRENCY: Queue message instead of blocking send
        const queuedMsg = { text, id: Date.now(), status: 'queued' };
        messageQueue.push(queuedMsg);
        renderMessage(text, 'user');
        userInput.value = '';
        userInput.style.height = 'auto';
        updateQueueUI();
        
        // Process queue if not already processing
        if (!isProcessingQueue) {
            processQueue();
        }
    }
    
    async function processQueue() {
        if (isProcessingQueue || messageQueue.length === 0) return;
        
        isProcessingQueue = true;
        showQueueTyping();
        
        // ⭐ FIRE CONCURRENT REQUESTS (no await between)
        const promises = messageQueue.map(async (msg, index) => {
            try {
                const response = await fetch(`${API_URL}/api/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'x-auth-token': authToken },
                    body: JSON.stringify({ message: msg.text, conversationId: currentConversationId })
                });
                const data = await response.json();
                
                if (response.ok) {
                    msg.reply = data.reply;
                    msg.status = 'complete';
                    // Render as SOON AS ready (concurrent!)
                    renderMessage(data.reply, 'bot');
                    if (data.conversationId && data.conversationId !== currentConversationId) {
                        currentConversationId = data.conversationId;
                        localStorage.setItem('currentConversationId', data.conversationId);
                        loadChatHistory();
                    }
                } else {
                    msg.status = 'error';
                    renderMessage('Error: ' + data.msg, 'bot');
                }
            } catch (err) {
                msg.status = 'error';
                renderMessage('Connection error', 'bot');
            }
        });
        
        // Wait for ALL to complete, then cleanup
        await Promise.all(promises);
        messageQueue = messageQueue.filter(m => m.status !== 'complete');
        isProcessingQueue = false;
        updateQueueUI();
        if (messageQueue.length > 0) processQueue(); // Process next batch
    }

    // --- History Loader ---

    async function loadChatHistory() {
        if (!authToken) return;
        try {
            const res = await fetch(`${API_URL}/api/chat/history`, {
                headers: { 'x-auth-token': authToken }
            });
            const data = await res.json();
            
            if (res.ok && data.history) {
                historyList.innerHTML = '';
                if (data.history.length === 0) {
                    historyList.innerHTML = `<div class="text-center py-10 opacity-30 text-[10px] font-black uppercase tracking-widest">No Threads</div>`;
                    return;
                }

                data.history.forEach(chat => {
                    const isActive = currentConversationId === chat.id;
                    const item = document.createElement('button');
                    item.className = `w-full text-left p-4 rounded-2xl transition-all flex items-center gap-4 group relative ${
                        isActive 
                        ? 'bg-blue-600 text-white shadow-xl shadow-blue-500/20 active-chat' 
                        : 'hover:bg-slate-50 dark:hover:bg-gray-800 text-slate-700 dark:text-slate-300'
                    }`;
                    
                    item.innerHTML = `
                        <div class="w-8 h-8 rounded-lg flex items-center justify-center text-sm ${isActive ? 'bg-white/20' : 'bg-slate-100 dark:bg-gray-800 text-slate-400 group-hover:text-blue-500'}">
                            <i class="bi bi-chat-fill"></i>
                        </div>
                        <div class="min-w-0 flex-1">
                            <p class="font-bold text-xs truncate uppercase tracking-tight">${chat.title || 'New Thread'}</p>
                            <p class="text-[9px] opacity-60 font-black uppercase tracking-widest mt-0.5">Resume Conversation</p>
                        </div>
                    `;
                    
                    item.onclick = () => {
                        if (currentConversationId !== chat.id) loadConversation(chat.id);
                    };
                    historyList.appendChild(item);
                });
            }
        } catch (e) { console.error(e); }
    }

    async function loadConversation(id) {
        currentConversationId = id;
        localStorage.setItem('currentConversationId', id);
        chatBox.innerHTML = '';
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';
        showTyping();
        if (window.innerWidth < 768) toggleSidebar();
        
        try {
            const res = await fetch(`${API_URL}/api/chat/history/${id}`, {
                headers: { 'x-auth-token': authToken }
            });
            const data = await res.json();
            document.getElementById('typing-indicator')?.remove();
            if (res.ok && data.messages) {
                data.messages.forEach(m => renderMessage(m.content, m.sender));
                loadChatHistory();
            }
        } catch (e) { showToast('Error', 'Failed to reload thread', 'error'); }
    }

    // --- UI Controls ---

    function toggleSidebar() {
        const isMobile = window.innerWidth < 768;
        const isClosed = sidebar.classList.contains('-translate-x-full');
        
        if (isClosed) {
            // Opening
            sidebar.classList.remove('-translate-x-full');
            if (!isMobile) mainContent.classList.add('md:ml-80');
            if (isMobile) document.getElementById('sidebar-overlay').classList.remove('hidden');
        } else {
            // Closing
            sidebar.classList.add('-translate-x-full');
            if (!isMobile) mainContent.classList.remove('md:ml-80');
            if (isMobile) document.getElementById('sidebar-overlay').classList.add('hidden');
        }
    }

    function toggleTheme() {
        const isDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
        document.getElementById('theme-switch-modal').checked = isDark;
    }

    window.showToast = (title, msg, type) => {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        const colors = type === 'error' ? 'bg-red-600' : 'bg-slate-900';
        toast.className = `${colors} text-white px-8 py-5 rounded-3xl shadow-2xl flex items-center gap-5 animate-in slide-in-from-right duration-500`;
        toast.innerHTML = `
            <div class="w-10 h-10 bg-white/20 rounded-xl flex items-center justify-center"><i class="bi ${type === 'error' ? 'bi-x-circle-fill' : 'bi-check-circle-fill'}"></i></div>
            <div>
                <p class="font-black text-[10px] uppercase tracking-widest">${title}</p>
                <p class="text-xs font-bold opacity-80">${msg}</p>
            </div>
        `;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('animate-out', 'fade-out', 'slide-out-to-right');
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    };

    // --- Event Listeners ---

    document.getElementById('sidebar-toggle-btn').onclick = toggleSidebar;
    // Global Nav & History Drawer
    const historyBtn = document.getElementById('history-drawer-btn');
    const sidebarClose = document.getElementById('sidebar-close-btn');

    historyBtn.onclick = () => {
        sidebar.classList.toggle('-translate-x-full');
    };

    sidebarClose.onclick = () => {
        sidebar.classList.add('-translate-x-full');
    };

    document.getElementById('nav-theme-toggle').onclick = toggleTheme;

    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        sendMessage(userInput.value);
    });

    userInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 192) + 'px';
        sendBtn.disabled = !this.value.trim();
    });

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (userInput.value.trim()) chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Auth Actions (Enhanced Split-Pane Logic)
    document.getElementById('login-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('login', { email: document.getElementById('login-email').value, password: document.getElementById('login-password').value });
    };
    document.getElementById('register-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('register', { email: document.getElementById('register-email').value, password: document.getElementById('register-password').value });
    };
    document.getElementById('guest-login-btn').onclick = () => handleAuth('guest', {});

    // Toggle Logic
    const authContainer = document.getElementById('auth-container');
    const loginView = document.getElementById('login-view');
    const registerView = document.getElementById('register-view');
    const onboardingLogin = document.getElementById('onboarding-content-login');
    const onboardingRegister = document.getElementById('onboarding-content-register');

    function switchAuthMode(mode) {
        if (mode === 'register') {
            loginView.classList.add('hidden');
            registerView.classList.remove('hidden');
            onboardingLogin.classList.add('hidden');
            onboardingRegister.classList.remove('hidden');
            if (window.innerWidth >= 1024) {
                authContainer.classList.add('lg:flex-row-reverse');
                authContainer.classList.add('shadow-[0_0_50px_rgba(79,70,229,0.3)]'); // Indigo glow for register
            }
        } else {
            registerView.classList.add('hidden');
            loginView.classList.remove('hidden');
            onboardingRegister.classList.add('hidden');
            onboardingLogin.classList.remove('hidden');
            if (window.innerWidth >= 1024) {
                authContainer.classList.remove('lg:flex-row-reverse');
                authContainer.classList.remove('shadow-[0_0_50px_rgba(79,70,229,0.3)]');
            }
        }
    }

    document.getElementById('show-register').onclick = () => switchAuthMode('register');
    document.getElementById('show-login').onclick = () => switchAuthMode('login');
    document.getElementById('show-register-desktop').onclick = () => switchAuthMode('register');
    document.getElementById('show-login-desktop').onclick = () => switchAuthMode('login');

    async function handleAuth(type, body) {
        const spinner = document.getElementById(`${type}-spinner`);
        spinner?.classList.remove('hidden');
        try {
            console.log(`Attempting ${type} auth at: ${API_URL}/api/auth/${type}`);
            const res = await fetch(`${API_URL}/api/auth/${type}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            console.log('Auth response status:', res.status, data);
            
            if (res.ok) {
                localStorage.setItem('token', data.token);
                localStorage.setItem('email', data.email || body.email);
                location.reload(); 
            } else { 
                showToast('Auth Failed', data.msg || data.error || 'Error', 'error'); 
            }
        } catch (e) { 
            console.error('Auth fetch error:', e);
            showToast('Server Error', 'Could not reach backend. Possible CORS error or backend offline.', 'error'); 
        }
        finally { spinner?.classList.add('hidden'); }
    }

    document.getElementById('new-chat-btn').onclick = () => {
        currentConversationId = null;
        localStorage.removeItem('currentConversationId');
        chatBox.innerHTML = '';
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'block';
        loadChatHistory();
        if (window.innerWidth < 768) toggleSidebar();
    };

    document.getElementById('logout-btn').onclick = () => {
        localStorage.clear();
        location.reload();
    };

    document.querySelectorAll('.suggestion-card').forEach(card => {
        card.onclick = () => sendMessage(card.querySelector('p:last-child').innerText);
    });

    // Init Theme & Auth
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.classList.toggle('dark', savedTheme === 'dark');
    document.getElementById('theme-switch-modal').checked = savedTheme === 'dark';

    document.getElementById('nav-settings-btn').onclick = () => document.getElementById('settingsModal').classList.remove('hidden');
    document.getElementById('close-settings-btn').onclick = () => document.getElementById('settingsModal').classList.add('hidden');
    document.getElementById('settings-form').onsubmit = (e) => {
        e.preventDefault();
        const isDark = document.getElementById('theme-switch-modal').checked;
        document.documentElement.classList.toggle('dark', isDark);
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
        showToast('Settings Saved', 'Interface preferences updated', 'success');
        document.getElementById('settingsModal').classList.add('hidden');
    };

    if (authToken) {
        document.getElementById('authModal').classList.add('hidden');
        document.getElementById('chat-container').classList.remove('hidden');
        
        // Initialize Global Sidebar (Narrow)
        const globalSidebar = document.getElementById('global-sidebar');
        if (window.innerWidth >= 1024) {
            mainContent.style.marginLeft = '5rem'; // Match w-20 sidebar
        }
        
        loadChatHistory();
        if (currentConversationId) loadConversation(currentConversationId);
    }
});
