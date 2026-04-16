document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'https://chatbot-3-hpx2.onrender.com';
    
    // State
    let authToken = localStorage.getItem('token');
    let userEmail = localStorage.getItem('email');
    let currentConversationId = localStorage.getItem('currentConversationId');

    function updateAuthState() {
        authToken = localStorage.getItem('token');
        userEmail = localStorage.getItem('email');
        if (authToken) {
            document.documentElement.classList.add('is-authenticated');
            document.getElementById('authModal').classList.add('hidden');
            document.getElementById('chat-container').classList.remove('hidden');
            
            // Update sidebar profile
            if (userEmail) {
                const emailSidebar = document.getElementById('user-email-sidebar');
                const nameSidebar = document.getElementById('user-name-sidebar');
                const avatarSidebar = document.getElementById('user-avatar-sidebar');
                
                if (emailSidebar) emailSidebar.innerText = userEmail;
                if (nameSidebar) nameSidebar.innerText = userEmail.split('@')[0];
                if (avatarSidebar) avatarSidebar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(userEmail)}&background=10a37f&color=fff`;
            }
            
            loadChatHistory();
            if (currentConversationId) loadConversation(currentConversationId);
        } else {
            document.documentElement.classList.remove('is-authenticated');
            document.getElementById('authModal').classList.remove('hidden');
            document.getElementById('chat-container').classList.add('hidden');
        }
    }

    // Parse Token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const tokenParam = urlParams.get('token');
    const emailParam = urlParams.get('email');
    if (tokenParam) {
        localStorage.setItem('token', tokenParam);
        if (emailParam) localStorage.setItem('email', emailParam);
        window.history.replaceState({}, document.title, window.location.pathname);
        authToken = tokenParam;
        userEmail = emailParam || localStorage.getItem('email');
    }
    
    // Elements
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const chatForm = document.getElementById('chat-form');
    const sendBtn = document.getElementById('send-btn');
    const sidebar = document.getElementById('sidebar');
    const historyList = document.getElementById('chat-history-list');
    
    // Initialize marked
    marked.setOptions({ gfm: true, breaks: true });

    function renderMessage(text, sender) {
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = `flex flex-col mb-10 message-animate group w-full`;
        
        const isBot = sender === 'bot';
        const avatarUrl = isBot ? 'https://ui-avatars.com/api/?name=IA&background=10a37f&color=fff' : `https://ui-avatars.com/api/?name=${encodeURIComponent(localStorage.getItem('email') || 'U')}&background=cbd5e1&color=475569`;
        
        // Handle Code Blocks for Bot
        let messageContent = isBot ? marked.parse(DOMPurify.sanitize(text)) : `<p>${text}</p>`;
        
        // Tabbed code block simulation
        if (isBot && text.includes('```')) {
            messageContent = messageContent.replace(/<pre><code class="language-(\w+)">([^]*?)<\/code><\/pre>/g, (match, lang, code) => {
                return `
                    <div class="code-block-container">
                        <div class="code-header">
                            <div class="code-tabs">
                                <span class="code-tab active">${lang.toUpperCase()}</span>
                                <span class="code-tab" onclick="showToast('Info', 'Additional tabs coming soon', 'info')">CSS</span>
                                <span class="code-tab" onclick="showToast('Info', 'Additional tabs coming soon', 'info')">JS</span>
                            </div>
                            <button onclick="copyToClipboard(\`${code.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`, this)" class="flex items-center gap-1 hover:text-green-400 transition-colors">
                                <i class="bi bi-copy"></i> Copy code
                            </button>
                        </div>
                        <div class="code-content">
                            <pre><code class="language-${lang}">${code}</code></pre>
                        </div>
                    </div>
                `;
            });
        }

        div.innerHTML = `
            <div class="max-w-4xl mx-auto flex items-start gap-5 w-full px-4">
                <!-- Avatar -->
                <div class="flex-shrink-0 mt-1">
                    <div class="w-9 h-9 rounded-full overflow-hidden border border-slate-200 dark:border-gray-800 shadow-sm">
                        <img src="${avatarUrl}" class="w-full h-full object-cover">
                    </div>
                </div>

                <!-- Message Content -->
                <div class="flex-1 min-w-0">
                    <h4 class="font-black text-xs uppercase tracking-widest mb-1 text-slate-500 dark:text-slate-400">
                        ${isBot ? 'Inclusivity AI' : (userEmail ? userEmail.split('@')[0] : 'You')}
                    </h4>
                    <div class="${isBot ? 'bot-bubble' : 'user-bubble p-4'}">
                        <div class="prose dark:prose-invert max-w-none text-slate-800 dark:text-slate-200 leading-relaxed text-sm">
                            ${messageContent}
                        </div>
                    </div>
                    
                    <!-- Action Bar (Bot Only) -->
                    ${isBot ? `
                        <div class="flex items-center gap-3 mt-4 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button class="message-action-btn" onclick="speakText(\`${text.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)" title="Listen"><i class="bi bi-volume-up text-lg"></i></button>
                            <button class="message-action-btn" onclick="copyToClipboard(\`${text.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)" title="Copy"><i class="bi bi-copy text-lg"></i></button>
                            <button class="message-action-btn" title="Regenerate" onclick="showToast('Info', 'Regeneration coming soon', 'info')"><i class="bi bi-arrow-repeat text-lg"></i></button>
                            <button class="message-action-btn" title="Like"><i class="bi bi-hand-thumbs-up text-lg"></i></button>
                            <button class="message-action-btn" title="Dislike"><i class="bi bi-hand-thumbs-down text-lg"></i></button>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
        
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Typing Indicators
    function showTyping() {
        document.getElementById('typing-indicator')?.remove();
        const div = document.createElement('div');
        div.id = 'typing-indicator';
        div.className = 'max-w-4xl mx-auto flex items-start gap-5 mb-10 message-animate w-full px-4';
        div.innerHTML = `
            <div class="flex-shrink-0">
                <div class="w-9 h-9 rounded-full overflow-hidden border border-slate-200 dark:border-gray-800 shadow-sm">
                    <img src="https://ui-avatars.com/api/?name=IA&background=10a37f&color=fff" class="w-full h-full object-cover">
                </div>
            </div>
            <div class="flex-1">
                <h4 class="font-black text-xs uppercase tracking-widest mb-1 text-slate-500">Inclusivity AI</h4>
                <div class="flex gap-2 p-2">
                    <span class="w-1.5 h-1.5 bg-green-500 rounded-full animate-bounce"></span>
                    <span class="w-1.5 h-1.5 bg-green-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                    <span class="w-1.5 h-1.5 bg-green-500 rounded-full animate-bounce [animation-delay:0.4s]"></span>
                </div>
            </div>
        `;
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    async function sendMessage(text) {
        if (!text.trim()) return;
        renderMessage(text, 'user');
        userInput.value = '';
        userInput.style.height = 'auto';
        showTyping();
        
        try {
            const response = await fetch(`${API_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-auth-token': authToken },
                body: JSON.stringify({ message: text, conversationId: currentConversationId })
            });
            const data = await response.json();
            document.getElementById('typing-indicator')?.remove();
            
            if (response.ok) {
                renderMessage(data.reply, 'bot');
                if (data.conversationId && data.conversationId !== currentConversationId) {
                    currentConversationId = data.conversationId;
                    localStorage.setItem('currentConversationId', data.conversationId);
                    loadChatHistory();
                }
            } else {
                renderMessage('Error: ' + data.msg, 'bot');
            }
        } catch (err) {
            document.getElementById('typing-indicator')?.remove();
            renderMessage('Connection error', 'bot');
        }
    }

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
                    historyList.innerHTML = `<div class="text-center py-10 opacity-30 text-[10px] font-black uppercase tracking-widest">No History</div>`;
                    return;
                }
                data.history.forEach(chat => {
                    const isActive = currentConversationId === chat.id;
                    const item = document.createElement('button');
                    item.className = `w-full text-left p-3 rounded-xl transition-all flex items-center gap-3 group ${isActive ? 'bg-slate-100 dark:bg-gray-800 border-l-4 border-green-500' : 'hover:bg-slate-50 dark:hover:bg-gray-900 border-l-4 border-transparent text-slate-600 dark:text-slate-400'}`;
                    item.innerHTML = `
                        <i class="bi bi-chat-left text-sm"></i>
                        <span class="truncate font-medium text-xs flex-1">${chat.title || 'New Chat'}</span>
                    `;
                    item.onclick = () => loadConversation(chat.id);
                    historyList.appendChild(item);
                });
            }
        } catch (e) { console.error(e); }
    }

    async function loadConversation(id) {
        currentConversationId = id;
        localStorage.setItem('currentConversationId', id);
        chatBox.innerHTML = '';
        if (window.innerWidth < 768) toggleSidebar();
        showTyping();
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
        } catch (e) { showToast('Error', 'Failed to load chat', 'error'); }
    }

    function toggleSidebar() {
        sidebar.classList.toggle('-translate-x-full');
        document.getElementById('sidebar-overlay').classList.toggle('hidden');
    }

    window.showToast = (title, msg, type) => {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        const colors = type === 'error' ? 'bg-red-600' : (type === 'info' ? 'bg-blue-600' : 'bg-green-600');
        toast.className = `${colors} text-white px-6 py-4 rounded-2xl shadow-2xl flex items-center gap-4 animate-in slide-in-from-bottom duration-500 mb-2 z-[200]`;
        toast.innerHTML = `
            <i class="bi ${type === 'error' ? 'bi-x-circle' : 'bi-info-circle'} text-xl"></i>
            <div>
                <p class="font-black text-[9px] uppercase tracking-widest">${title}</p>
                <p class="text-xs font-bold opacity-90">${msg}</p>
            </div>
        `;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('animate-out', 'fade-out', 'slide-out-to-bottom');
            setTimeout(() => toast.remove(), 500);
        }, 3000);
    };

    const attachIconListeners = () => {
        // Sidebar Navigation
        document.getElementById('nav-search-btn-sidebar').onclick = () => {
            if (sidebar.classList.contains('-translate-x-full')) toggleSidebar();
            setTimeout(() => document.getElementById('history-search-input').focus(), 300);
        };
        
        document.getElementById('nav-chats-btn').onclick = () => {
            if (sidebar.classList.contains('-translate-x-full')) toggleSidebar();
        };

        document.getElementById('nav-marketplace-btn').onclick = () => showToast('Market Place', 'Inclusivity Store coming soon!', 'info');
        document.getElementById('nav-saved-btn').onclick = () => showToast('Saved', 'Access your saved command library', 'info');
        document.getElementById('nav-settings-btn-sidebar').onclick = () => document.getElementById('settingsModal').classList.remove('hidden');

        // Brand Dropdown (Model Selection)
        const brandBtn = document.getElementById('brand-dropdown-btn');
        const modelMenu = document.getElementById('model-select-menu');
        brandBtn.onclick = (e) => {
            e.stopPropagation();
            const isHidden = modelMenu.classList.contains('hidden');
            if (isHidden) {
                modelMenu.classList.remove('hidden');
                setTimeout(() => {
                    modelMenu.classList.remove('scale-95', 'opacity-0');
                    modelMenu.classList.add('scale-100', 'opacity-100');
                }, 10);
            } else {
                modelMenu.classList.add('scale-95', 'opacity-0');
                modelMenu.classList.remove('scale-100', 'opacity-100');
                setTimeout(() => modelMenu.classList.add('hidden'), 200);
            }
        };

        document.querySelectorAll('.model-option').forEach(opt => {
            opt.onclick = () => {
                const model = opt.getAttribute('data-model');
                document.getElementById('active-model-name').innerText = model;
                document.querySelectorAll('.model-option').forEach(o => o.classList.remove('active'));
                opt.classList.add('active');
                modelMenu.classList.add('scale-95', 'opacity-0');
                setTimeout(() => modelMenu.classList.add('hidden'), 200);
                showToast('Model Changed', `Switched to ${model}`, 'success');
            };
        });

        document.addEventListener('click', () => {
            modelMenu.classList.add('scale-95', 'opacity-0');
            setTimeout(() => modelMenu.classList.add('hidden'), 200);
        });

        // Header Icons
        const headerButtons = document.querySelectorAll('header button:not(#new-chat-btn):not(#history-drawer-btn):not(#nav-theme-toggle)');
        
        // Bookmark
        headerButtons[0].onclick = () => {
            if (!currentConversationId) return showToast('Error', 'Start a chat first', 'error');
            showToast('Bookmarked', 'Thread saved to library', 'success');
        };

        // Download (Export)
        headerButtons[1].onclick = () => {
            const messages = Array.from(chatBox.querySelectorAll('.prose')).map(p => {
                const isBot = p.closest('.message-animate').querySelector('h4').innerText.includes('Inclusivity');
                return `${isBot ? 'BOT' : (userEmail || 'USER')}: ${p.innerText}`;
            }).join('\n\n');
            if (!messages) return showToast('Error', 'No chat to export', 'error');
            
            const blob = new Blob([messages], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `Inclusivity_AI_Chat_${new Date().getTime()}.txt`;
            a.click();
            showToast('Exported', 'Chat history saved to downloads', 'success');
        };

        // Share
        headerButtons[2].onclick = () => showToast('Share', 'Secure link generated for sharing', 'info');

        document.getElementById('view-plans-btn').onclick = () => showToast('Plans', 'Premium plans unlock next-gen empathy models', 'info');
        
        // History Search
        document.getElementById('history-search-input').oninput = (e) => {
            const query = e.target.value.toLowerCase();
            document.querySelectorAll('#chat-history-list button').forEach(item => {
                const title = item.querySelector('span').innerText.toLowerCase();
                item.style.display = title.includes(query) ? 'flex' : 'none';
            });
        };
    };

    // Text to Speech
    window.speakText = (text) => {
        if (!window.speechSynthesis) return showToast('Error', 'Speech not supported', 'error');
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        window.speechSynthesis.speak(utterance);
        showToast('Speaking', 'Reading message aloud...', 'info');
    };

    // Copy to Clipboard (Global helper)
    window.copyToClipboard = (text, btn) => {
        navigator.clipboard.writeText(text).then(() => {
            const originalIcon = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check2 text-green-400"></i> Copied!';
            setTimeout(() => { btn.innerHTML = originalIcon; }, 2000);
            showToast('Copied', 'Content saved to clipboard', 'success');
        });
    };


    document.getElementById('history-drawer-btn').onclick = toggleSidebar;
    document.getElementById('sidebar-close-btn').onclick = toggleSidebar;
    document.getElementById('sidebar-overlay').onclick = toggleSidebar;
    document.getElementById('nav-theme-toggle').onclick = () => {
        const isDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    };

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

    document.getElementById('new-chat-btn').onclick = () => {
        currentConversationId = null;
        localStorage.removeItem('currentConversationId');
        chatBox.innerHTML = '';
        document.getElementById('welcome-screen').style.display = 'block';
        loadChatHistory();
    };

    document.getElementById('logout-btn').onclick = () => {
        localStorage.clear();
        location.reload();
    };

    // Auth
    document.getElementById('login-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('login', { email: document.getElementById('login-email').value, password: document.getElementById('login-password').value });
    };
    document.getElementById('register-form').onsubmit = (e) => {
        e.preventDefault();
        handleAuth('register', { email: document.getElementById('register-email').value, password: document.getElementById('register-password').value });
    };
    document.getElementById('guest-login-btn').onclick = () => handleAuth('guest', {});

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
            if (res.ok && data.token) {
                localStorage.setItem('token', data.token);
                localStorage.setItem('email', data.email || body.email || 'Guest');
                updateAuthState();
            } else {
                showToast('Auth Failed', data.msg || 'Invalid credentials', 'error');
            }
        } catch (e) {
            showToast('Error', 'Connection failed', 'error');
        } finally { spinner?.classList.add('hidden'); }
    }

    document.querySelectorAll('.suggestion-card').forEach(card => {
        card.onclick = () => sendMessage(card.querySelectorAll('p')[1].innerText);
    });

    // Modals
    document.getElementById('close-settings-btn').onclick = () => document.getElementById('settingsModal').classList.add('hidden');
    document.getElementById('settings-form').onsubmit = (e) => {
        e.preventDefault();
        showToast('Settings Saved', 'Inclusivity preferences updated', 'success');
        document.getElementById('settingsModal').classList.add('hidden');
    };

    // Init
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.classList.toggle('dark', savedTheme === 'dark');
    updateAuthState();
    attachIconListeners();
});

