document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'https://chatbot-3-hpx2.onrender.com';
    
    // State
    let authToken = localStorage.getItem('token');
    let userEmail = localStorage.getItem('email');
    let currentConversationId = localStorage.getItem('currentConversationId');
    
    // ⭐ CONCURRENCY: Message queue for parallel processing
    let messageQueue = [];
    let isProcessingQueue = false;
    
    // Elements
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const chatForm = document.getElementById('chat-form');
    const sendBtn = document.getElementById('send-btn');
    const sidebar = document.getElementById('sidebar');
    const historyList = document.getElementById('chat-history-list');
    
    // Initialize marked
    marked.setOptions({ gfm: true, breaks: true });

    // --- Core Chat Rendering ---

    function renderMessage(content, sender = 'bot') {
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = `flex ${sender === 'user' ? 'justify-end' : 'justify-start'} mb-10 animate-in slide-in-from-bottom-8 duration-700`;
        
        const bubbleContent = sender === 'bot' ? marked.parse(content || '') : content;
        
        div.innerHTML = `
            <div class="flex max-w-[92%] md:max-w-[80%] ${sender === 'user' ? 'flex-row-reverse' : 'flex-row'} gap-5">
                <div class="w-11 h-11 rounded-2xl flex-shrink-0 flex items-center justify-center text-xl shadow-lg transition-transform hover:scale-110 ${
                    sender === 'user' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-800 text-blue-600 border border-slate-100 dark:border-gray-700'
                }">
                    <i class="bi ${sender === 'user' ? 'bi-person-fill' : 'bi-robot'}"></i>
                </div>
                <div class="flex flex-col ${sender === 'user' ? 'items-end' : 'items-start'}">
                    <div class="px-6 py-4 rounded-[1.8rem] shadow-sm ${
                        sender === 'user' 
                        ? 'bg-blue-600 text-white rounded-tr-none' 
                        : 'bg-white dark:bg-gray-900 border border-slate-100 dark:border-gray-800 text-slate-800 dark:text-slate-100 rounded-tl-none'
                    } prose prose-slate dark:prose-invert max-w-none font-medium">
                        ${bubbleContent}
                    </div>
                    <span class="text-[9px] mt-2 text-slate-400 uppercase font-black tracking-[0.2em] opacity-60">
                        ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                </div>
            </div>
        `;
        
        chatBox.appendChild(div);
        chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: 'smooth' });
    }

    function showQueueTyping() {
        // Remove old typing
        document.getElementById('queue-typing')?.remove();
        
        const div = document.createElement('div');
        div.id = 'queue-typing';
        div.className = 'flex justify-start mb-10';
        div.innerHTML = `
            <div class="flex gap-5 items-center">
                <div class="w-11 h-11 rounded-2xl bg-white dark:bg-gray-800 border border-slate-100 dark:border-gray-700 flex items-center justify-center text-blue-600 shadow-sm">
                    <i class="bi bi-robot"></i>
                </div>
                <div class="flex gap-2 bg-slate-100/50 dark:bg-gray-800/50 px-6 py-5 rounded-[1.8rem] rounded-tl-none">
                    <span>🤖 ${messageQueue.length} task${messageQueue.length > 1 ? 's' : ''}....</span>
                    <span class="w-2 h-2 bg-blue-400 rounded-full animate-bounce ml-2"></span>
                    <span class="w-2 h-2 bg-blue-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                    <span class="w-2 h-2 bg-blue-600 rounded-full animate-bounce [animation-delay:0.4s]"></span>
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
        const isOpen = !sidebar.classList.contains('-translate-x-full');
        sidebar.classList.toggle('-translate-x-full', isOpen);
        document.getElementById('sidebar-overlay').classList.toggle('hidden', isOpen);
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
    document.getElementById('sidebar-close-btn').onclick = toggleSidebar;
    document.getElementById('sidebar-overlay').onclick = toggleSidebar;
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

    // Auth Actions (Unchanged Logic)
    document.getElementById('login-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('login', { email: document.getElementById('login-email').value, password: document.getElementById('login-password').value });
    };
    document.getElementById('register-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('register', { email: document.getElementById('register-email').value, password: document.getElementById('register-password').value });
    };
    document.getElementById('guest-login-btn').onclick = () => handleAuth('guest', {});
    document.getElementById('show-register').onclick = () => {
        document.getElementById('login-view').classList.add('hidden');
        document.getElementById('register-view').classList.remove('hidden');
    };
    document.getElementById('show-login').onclick = () => {
        document.getElementById('register-view').classList.add('hidden');
        document.getElementById('login-view').classList.remove('hidden');
    };

    async function handleAuth(type, body) {
        const spinner = document.getElementById(`${type}-spinner`);
        spinner?.classList.remove('hidden');
        try {
            const res = await fetch(`${API_URL}/api/auth/${type}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (res.ok) {
                localStorage.setItem('token', data.token);
                localStorage.setItem('email', data.email || body.email);
                location.reload(); 
            } else { showToast('Auth Failed', data.msg || 'Error', 'error'); }
        } catch (e) { showToast('Server Error', 'Backend offline', 'error'); }
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

    document.getElementById('settings-btn').onclick = () => document.getElementById('settingsModal').classList.remove('hidden');
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
        document.getElementById('username-display').innerText = userEmail ? userEmail.split('@')[0] : 'User';
        loadChatHistory();
        if (currentConversationId) loadConversation(currentConversationId);
    }
});
