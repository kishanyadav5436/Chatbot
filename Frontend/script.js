document.addEventListener('DOMContentLoaded', () => {
    // ── API ──────────────────────────────────────────────────────────────────
    const getApiUrl = () => {
        const local = ['localhost', '127.0.0.1'];
        return local.includes(window.location.hostname)
            ? 'http://127.0.0.1:5056'
            : 'https://chatbot-3-hpx2.onrender.com';
    };
    const API_URL = getApiUrl();

    // ── State ────────────────────────────────────────────────────────────────
    let authToken = localStorage.getItem('token');
    let userEmail = localStorage.getItem('email');
    let currentConversationId = localStorage.getItem('currentConversationId');
    let currentLanguage = localStorage.getItem('language') || 'en';

    // ── Token from URL (OAuth redirect) ─────────────────────────────────────
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

    // ── DOM refs ─────────────────────────────────────────────────────────────
    const chatBox    = document.getElementById('chat-box');
    const userInput  = document.getElementById('user-input');
    const chatForm   = document.getElementById('chat-form');
    const sendBtn    = document.getElementById('send-btn');
    const historyList = document.getElementById('chat-history-list');

    // ── Marked config ────────────────────────────────────────────────────────
    marked.setOptions({ gfm: true, breaks: true });

    // ════════════════════════════════════════════════════════════════════════
    //  AUTH STATE
    // ════════════════════════════════════════════════════════════════════════
    function updateAuthState() {
        authToken = localStorage.getItem('token');
        userEmail = localStorage.getItem('email');

        if (authToken) {
            document.documentElement.classList.add('is-authenticated');
            document.getElementById('authModal').style.display = 'none';
            document.getElementById('chat-container').classList.remove('hidden');
            document.getElementById('chat-container').style.display = 'flex';

            // Sidebar profile
            if (userEmail) {
                const emailEl = document.getElementById('user-email-sidebar');
                const nameEl  = document.getElementById('user-name-sidebar');
                if (emailEl) emailEl.textContent = userEmail;
                if (nameEl)  nameEl.textContent  = userEmail.split('@')[0];
            }

            loadChatHistory();
            if (currentConversationId) loadConversation(currentConversationId);
        } else {
            document.documentElement.classList.remove('is-authenticated');
            document.getElementById('authModal').style.display = 'flex';
            document.getElementById('chat-container').classList.add('hidden');
            currentConversationId = null;
            if (chatBox) chatBox.innerHTML = '';
        }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  TOAST
    // ════════════════════════════════════════════════════════════════════════
    window.showToast = (title, msg, type = 'info') => {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');

        const bgMap = { error: 'bg-error', success: 'bg-primary-container', info: 'bg-secondary-container' };
        const textMap = { error: 'text-on-error', success: 'text-on-primary-container', info: 'text-on-secondary-container' };
        const iconMap = { error: 'error', success: 'check_circle', info: 'info' };

        toast.className = `${bgMap[type] || bgMap.info} ${textMap[type] || textMap.info} px-5 py-4 rounded-xl shadow-xl flex items-center gap-3 transition-all duration-300`;
        toast.innerHTML = `
            <span class="material-symbols-outlined mat-fill text-xl">${iconMap[type]}</span>
            <div>
                <p class="font-label-sm text-label-sm font-bold uppercase tracking-wide">${title}</p>
                <p class="font-body-md text-sm opacity-90">${msg}</p>
            </div>
        `;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-8px)';
            setTimeout(() => toast.remove(), 400);
        }, 3000);
    };

    // ════════════════════════════════════════════════════════════════════════
    //  RENDER MESSAGE
    // ════════════════════════════════════════════════════════════════════════
    function renderMessage(text, sender) {
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';

        const isBot = sender === 'bot';
        let messageContent = isBot
            ? marked.parse(DOMPurify.sanitize(text))
            : `<p>${DOMPurify.sanitize(text)}</p>`;

        // Replace code blocks with styled containers
        if (isBot && text.includes('```')) {
            messageContent = messageContent.replace(/<pre><code class="language-(\w+)">([^]*?)<\/code><\/pre>/g, (match, lang, code) => `
                <div class="code-block-container">
                    <div class="code-header">
                        <div style="display:flex;gap:0.75rem;">
                            <span style="opacity:1;">${lang.toUpperCase()}</span>
                        </div>
                        <button onclick="copyToClipboard(\`${code.replace(/`/g,'\\`').replace(/\$/g,'\\$')}\`, this)" style="display:flex;align-items:center;gap:4px;cursor:pointer;hover:color:#6bd8cb;transition:color 0.2s">
                            <span class="material-symbols-outlined" style="font-size:16px;">content_copy</span> Copy
                        </button>
                    </div>
                    <div class="code-content"><pre><code class="language-${lang}">${code}</code></pre></div>
                </div>
            `);
        }

        // Bot avatar: green circle with icon
        const botAvatarHTML = `
            <div class="w-9 h-9 rounded-full bg-surface-container-high flex-shrink-0 flex items-center justify-center mt-1">
                <span class="material-symbols-outlined text-primary mat-fill" style="font-size:20px;">smart_toy</span>
            </div>`;

        // User avatar: initials
        const initials = (userEmail || 'U').charAt(0).toUpperCase();
        const userAvatarHTML = `
            <div class="w-9 h-9 rounded-full bg-primary flex-shrink-0 flex items-center justify-center mt-1">
                <span class="material-symbols-outlined text-on-primary" style="font-size:20px;">person</span>
            </div>`;

        const div = document.createElement('div');
        div.className = 'message-animate mb-6 group';

        if (isBot) {
            div.innerHTML = `
                <div class="max-w-[800px] mx-auto flex gap-4 items-start">
                    ${botAvatarHTML}
                    <div class="flex-1 min-w-0">
                        <p class="font-label-sm text-label-sm text-primary uppercase tracking-widest mb-2">Inclusivity AI</p>
                        <div class="bot-bubble p-4 shadow-sm">
                            <div class="font-body-md text-body-md text-on-surface leading-relaxed prose max-w-none">
                                ${messageContent}
                            </div>
                        </div>
                        <!-- Action Bar -->
                        <div class="flex items-center gap-1 mt-3 opacity-0 group-hover:opacity-100 transition-all duration-200">
                            <button class="flex items-center gap-1 px-3 py-1.5 rounded-full bg-surface-container-low border border-outline-variant font-label-sm text-label-sm text-on-surface-variant hover:bg-surface-container transition-colors"
                                onclick="speakText(\`${text.replace(/`/g,'\\`').replace(/\$/g,'\\$')}\`)">
                                <span class="material-symbols-outlined" style="font-size:14px;">volume_up</span>
                            </button>
                            <button class="flex items-center gap-1 px-3 py-1.5 rounded-full bg-surface-container-low border border-outline-variant font-label-sm text-label-sm text-on-surface-variant hover:bg-surface-container transition-colors"
                                onclick="copyToClipboard(\`${text.replace(/`/g,'\\`').replace(/\$/g,'\\$')}\`, this)">
                                <span class="material-symbols-outlined" style="font-size:14px;">content_copy</span>
                            </button>
                            <button class="flex items-center gap-1 px-3 py-1.5 rounded-full bg-surface-container-low border border-outline-variant font-label-sm text-label-sm text-on-surface-variant hover:bg-surface-container transition-colors">
                                <span class="material-symbols-outlined" style="font-size:14px;">thumb_up</span>
                            </button>
                        </div>
                    </div>
                </div>`;
        } else {
            div.innerHTML = `
                <div class="max-w-[800px] mx-auto flex flex-row-reverse gap-4 items-start">
                    ${userAvatarHTML}
                    <div class="max-w-[80%]">
                        <p class="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-widest mb-2 text-right">${userEmail ? userEmail.split('@')[0] : 'You'}</p>
                        <div class="user-bubble p-4 shadow-md">
                            <div class="font-body-md text-body-md text-white leading-relaxed">
                                ${messageContent}
                            </div>
                        </div>
                    </div>
                </div>`;
        }

        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // ════════════════════════════════════════════════════════════════════════
    //  TYPING INDICATOR
    // ════════════════════════════════════════════════════════════════════════
    function showTyping() {
        removeTyping();
        const div = document.createElement('div');
        div.id = 'typing-indicator-wrapper';
        div.className = 'message-animate mb-6';
        div.innerHTML = `
            <div class="max-w-[800px] mx-auto flex gap-4 items-start">
                <div class="w-9 h-9 rounded-full bg-surface-container-high flex-shrink-0 flex items-center justify-center mt-1">
                    <span class="material-symbols-outlined text-primary mat-fill" style="font-size:20px;">smart_toy</span>
                </div>
                <div class="bot-bubble p-4 shadow-sm flex items-center gap-2">
                    <div class="flex gap-1 items-center">
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                    </div>
                    <span class="font-label-sm text-label-sm text-on-surface-variant ml-1">Thinking…</span>
                </div>
            </div>`;
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function removeTyping() {
        document.getElementById('typing-indicator-wrapper')?.remove();
    }

    // ════════════════════════════════════════════════════════════════════════
    //  SEND MESSAGE
    // ════════════════════════════════════════════════════════════════════════
    async function sendMessage(text) {
        if (!text.trim()) return;
        renderMessage(text, 'user');
        userInput.value = '';
        userInput.style.height = 'auto';
        sendBtn.disabled = true;
        showTyping();

        try {
            const res = await fetch(`${API_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-auth-token': authToken },
                body: JSON.stringify({ message: text, conversationId: currentConversationId, language: currentLanguage })
            });
            const data = await res.json();
            removeTyping();

            if (res.ok) {
                renderMessage(data.reply, 'bot');
                if (data.conversationId && data.conversationId !== currentConversationId) {
                    currentConversationId = data.conversationId;
                    localStorage.setItem('currentConversationId', data.conversationId);
                    loadChatHistory();
                }
            } else {
                renderMessage('Error: ' + (data.msg || 'Something went wrong.'), 'bot');
            }
        } catch {
            removeTyping();
            renderMessage('Connection error. Please check your network and try again.', 'bot');
        } finally {
            sendBtn.disabled = false;
        }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  CHAT HISTORY
    // ════════════════════════════════════════════════════════════════════════
    async function loadChatHistory() {
        if (!authToken || !historyList) return;
        try {
            const res = await fetch(`${API_URL}/api/chat/history`, { headers: { 'x-auth-token': authToken } });
            const data = await res.json();
            if (!res.ok || !data.history) return;

            historyList.innerHTML = '';
            if (data.history.length === 0) {
                historyList.innerHTML = `<div class="text-center py-10 font-label-sm text-label-sm text-outline opacity-60">No conversations yet</div>`;
                return;
            }
            data.history.forEach(chat => {
                const isActive = currentConversationId === chat.id;
                const item = document.createElement('button');
                item.className = `w-full text-left p-3 rounded-xl transition-all flex items-center gap-3 ${
                    isActive
                        ? 'bg-secondary-container text-on-secondary-container'
                        : 'text-on-surface-variant hover:bg-surface-container-high'
                }`;
                item.innerHTML = `
                    <span class="material-symbols-outlined text-lg shrink-0">${isActive ? 'chat_bubble' : 'chat'}</span>
                    <span class="font-label-md text-label-md truncate flex-1">${chat.title || 'New Chat'}</span>
                `;
                item.onclick = () => loadConversation(chat.id);
                historyList.appendChild(item);
            });
        } catch (e) { console.error(e); }
    }

    async function loadConversation(id) {
        currentConversationId = id;
        localStorage.setItem('currentConversationId', id);
        chatBox.innerHTML = '';
        showTyping();
        try {
            const res = await fetch(`${API_URL}/api/chat/history/${id}`, { headers: { 'x-auth-token': authToken } });
            const data = await res.json();
            removeTyping();
            if (res.ok && data.messages) {
                data.messages.forEach(m => renderMessage(m.content, m.sender));
                loadChatHistory();
                if (data.language) {
                    currentLanguage = data.language;
                    const langSel = document.getElementById('language-select-modal');
                    if (langSel) langSel.value = currentLanguage;
                }
            }
        } catch { showToast('Error', 'Failed to load conversation', 'error'); }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  SIDEBAR TOGGLES
    // ════════════════════════════════════════════════════════════════════════
    const mainSidebar      = document.getElementById('main-sidebar');
    const mobileSidebarOverlay = document.getElementById('mobile-sidebar-overlay');
    const mainSidebarToggle = document.getElementById('main-sidebar-toggle');
    const mobileMenuBtn    = document.getElementById('mobile-menu-btn');

    // Restore desktop sidebar state
    if (localStorage.getItem('sidebarState') === 'closed' && window.innerWidth >= 768) {
        mainSidebar?.classList.add('sidebar-closed');
    }

    mainSidebarToggle?.addEventListener('click', () => {
        const closed = mainSidebar.classList.toggle('sidebar-closed');
        localStorage.setItem('sidebarState', closed ? 'closed' : 'open');
    });

    mobileMenuBtn?.addEventListener('click', () => {
        mainSidebar?.classList.toggle('mobile-open');
        mobileSidebarOverlay?.classList.toggle('active');
    });

    mobileSidebarOverlay?.addEventListener('click', () => {
        mainSidebar?.classList.remove('mobile-open');
        mobileSidebarOverlay?.classList.remove('active');
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth >= 768) {
            mainSidebar?.classList.remove('mobile-open');
            mobileSidebarOverlay?.classList.remove('active');
        }
    });

    // ── History drawer ────────────────────────────────────────────────────
    function openHistoryDrawer() {
        document.getElementById('history-drawer')?.classList.add('drawer-open');
        document.getElementById('drawer-backdrop')?.classList.remove('hidden');
    }
    function closeHistoryDrawer() {
        document.getElementById('history-drawer')?.classList.remove('drawer-open');
        document.getElementById('drawer-backdrop')?.classList.add('hidden');
    }
    document.getElementById('history-drawer-btn')?.addEventListener('click', openHistoryDrawer);
    document.getElementById('nav-history-btn')?.addEventListener('click', openHistoryDrawer);
    document.getElementById('history-drawer-close-btn')?.addEventListener('click', closeHistoryDrawer);
    document.getElementById('drawer-backdrop')?.addEventListener('click', closeHistoryDrawer);

    // ── History search ────────────────────────────────────────────────────
    document.getElementById('history-search-input')?.addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        document.querySelectorAll('#chat-history-list button').forEach(btn => {
            const title = btn.querySelector('span:last-child')?.textContent.toLowerCase() || '';
            btn.style.display = title.includes(q) ? 'flex' : 'none';
        });
    });

    // ════════════════════════════════════════════════════════════════════════
    //  MODALS (open)
    // ════════════════════════════════════════════════════════════════════════
    const openModal  = (id) => document.getElementById(id)?.classList.remove('hidden');
    const closeModal = (id) => document.getElementById(id)?.classList.add('hidden');

    document.getElementById('nav-settings-btn-sidebar')?.addEventListener('click', () => { openModal('settingsModal'); closeMobile(); });
    document.getElementById('nav-saved-btn')?.addEventListener('click', () => { openModal('savedCommandsModal'); closeMobile(); });
    document.getElementById('nav-resources-btn')?.addEventListener('click', () => { openModal('marketplaceModal'); closeMobile(); });

    function closeMobile() {
        mainSidebar?.classList.remove('mobile-open');
        mobileSidebarOverlay?.classList.remove('active');
    }

    // ════════════════════════════════════════════════════════════════════════
    //  MODAL CLOSE BUTTONS
    // ════════════════════════════════════════════════════════════════════════
    ['settingsModal','marketplaceModal','savedCommandsModal','aboutModal','adminModal'].forEach(id => {
        const modal = document.getElementById(id);
        if (!modal) return;
        // Backdrop click
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(id); });
    });

    document.getElementById('close-settings-btn')?.addEventListener('click', () => closeModal('settingsModal'));
    document.getElementById('close-marketplace-btn')?.addEventListener('click', () => closeModal('marketplaceModal'));
    document.getElementById('close-savedCommands-btn')?.addEventListener('click', () => closeModal('savedCommandsModal'));
    document.getElementById('close-about-btn')?.addEventListener('click', () => closeModal('aboutModal'));
    document.getElementById('close-admin-btn')?.addEventListener('click', () => closeModal('adminModal'));

    // ════════════════════════════════════════════════════════════════════════
    //  SETTINGS FORM
    // ════════════════════════════════════════════════════════════════════════
    const langSelect = document.getElementById('language-select-modal');
    if (langSelect) langSelect.value = currentLanguage;

    document.getElementById('settings-form')?.addEventListener('submit', (e) => {
        e.preventDefault();
        currentLanguage = langSelect?.value || 'en';
        localStorage.setItem('language', currentLanguage);
        showToast('Saved', 'Language preference updated', 'success');
        closeModal('settingsModal');
    });

    // ════════════════════════════════════════════════════════════════════════
    //  PROMPT ITEMS (Saved Insights)
    // ════════════════════════════════════════════════════════════════════════
    document.querySelectorAll('.prompt-item').forEach(item => {
        item.addEventListener('click', () => {
            const text = item.querySelector('p:last-child')?.textContent?.replace(/["""]/g, '').trim();
            if (text && userInput) {
                userInput.value = text;
                userInput.dispatchEvent(new Event('input'));
                userInput.focus();
                closeModal('savedCommandsModal');
                showToast('Loaded', 'Prompt added to input', 'success');
            }
        });
    });

    // ════════════════════════════════════════════════════════════════════════
    //  MARKETPLACE "Install" BUTTONS
    // ════════════════════════════════════════════════════════════════════════
    document.querySelectorAll('#marketplaceModal button').forEach(btn => {
        if (btn.textContent.trim() === 'Install Tool') {
            btn.addEventListener('click', () => {
                const name = btn.closest('.p-5')?.querySelector('h4')?.textContent || 'Tool';
                btn.textContent = 'Installed ✓';
                btn.disabled = true;
                showToast('Installed', `${name} added to your workspace`, 'success');
            });
        }
    });

    // ════════════════════════════════════════════════════════════════════════
    //  HEADER SECONDARY BUTTONS
    // ════════════════════════════════════════════════════════════════════════
    const headerSecondary = document.querySelectorAll('.header-secondary-btn');
    // [0] history is already wired above
    // [1] bookmark
    if (headerSecondary[1]) {
        headerSecondary[1].addEventListener('click', () => {
            if (!currentConversationId) return showToast('Info', 'Start a chat first', 'info');
            showToast('Bookmarked', 'Thread saved to your library', 'success');
        });
    }
    // [2] download
    if (headerSecondary[2]) {
        headerSecondary[2].addEventListener('click', () => {
            const messages = Array.from(chatBox.querySelectorAll('.message-animate')).map(el => {
                const nameEl = el.querySelector('.font-label-sm');
                const bodyEl = el.querySelector('.font-body-md');
                return `${nameEl?.textContent.trim() || 'Unknown'}: ${bodyEl?.textContent.trim() || ''}`;
            }).join('\n\n');
            if (!messages) return showToast('Info', 'No chat to export', 'info');
            const blob = new Blob([messages], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `Inclusivity_AI_${Date.now()}.txt`; a.click();
            showToast('Exported', 'Chat saved to downloads', 'success');
        });
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ATTACHMENT
    // ════════════════════════════════════════════════════════════════════════
    document.getElementById('attach-btn')?.addEventListener('click', () =>
        showToast('Coming Soon', 'File attachments will be available soon!', 'info'));

    // ════════════════════════════════════════════════════════════════════════
    //  SUGGESTION CARDS
    // ════════════════════════════════════════════════════════════════════════
    document.querySelectorAll('.suggestion-card').forEach(card => {
        card.addEventListener('click', () => {
            const prompt = card.querySelector('.font-label-sm')?.textContent?.trim();
            if (prompt) sendMessage(prompt);
        });
    });

    // ════════════════════════════════════════════════════════════════════════
    //  NEW CHAT / CLEAR
    // ════════════════════════════════════════════════════════════════════════
    document.getElementById('new-chat-btn')?.addEventListener('click', () => {
        currentConversationId = null;
        localStorage.removeItem('currentConversationId');
        chatBox.innerHTML = '';
        const ws = document.getElementById('welcome-screen');
        if (ws) ws.style.display = 'block';
        loadChatHistory();
    });

    document.getElementById('clear-chat-btn')?.addEventListener('click', async () => {
        if (!currentConversationId) return showToast('Info', 'No active chat to clear.', 'info');
        if (!confirm('Clear this chat? This cannot be undone.')) return;
        try {
            const res = await fetch(`${API_URL}/api/chat/reset`, {
                method: 'POST', headers: { 'x-auth-token': authToken }
            });
            if (res.ok) {
                chatBox.innerHTML = '';
                const ws = document.getElementById('welcome-screen');
                if (ws) ws.style.display = 'block';
                showToast('Cleared', 'Chat context has been reset.', 'success');
            }
        } catch { showToast('Error', 'Failed to clear chat.', 'error'); }
    });

    // ════════════════════════════════════════════════════════════════════════
    //  LOGOUT
    // ════════════════════════════════════════════════════════════════════════
    const handleLogout = () => { localStorage.clear(); location.reload(); };
    document.getElementById('logout-btn')?.addEventListener('click', handleLogout);
    document.getElementById('logout-btn-sidebar')?.addEventListener('click', handleLogout);

    // ════════════════════════════════════════════════════════════════════════
    //  AUTH FORMS
    // ════════════════════════════════════════════════════════════════════════
    // Toggle login ↔ register
    const loginSection    = document.getElementById('login-section');
    const registerSection = document.getElementById('register-section');
    const authTitle       = document.getElementById('auth-title');

    document.getElementById('register-toggle-btn')?.addEventListener('click', () => {
        loginSection.classList.add('hidden');
        registerSection.classList.remove('hidden');
        if (authTitle) authTitle.textContent = 'Join Inclusivity AI';
    });
    document.getElementById('login-toggle-btn')?.addEventListener('click', () => {
        registerSection.classList.add('hidden');
        loginSection.classList.remove('hidden');
        if (authTitle) authTitle.textContent = 'Welcome to Inclusivity AI';
    });

    // Form submissions
    document.getElementById('login-form')?.addEventListener('submit', (e) => {
        e.preventDefault();
        handleAuth('login', {
            email: document.getElementById('login-email').value,
            password: document.getElementById('login-password').value
        });
    });
    document.getElementById('register-form')?.addEventListener('submit', (e) => {
        e.preventDefault();
        handleAuth('register', {
            email: document.getElementById('register-email').value,
            password: document.getElementById('register-password').value
        });
    });
    document.getElementById('guest-login-btn')?.addEventListener('click', () => handleAuth('guest', {}));
    document.getElementById('google-btn')?.addEventListener('click', () => {
        window.location.href = `${API_URL}/api/auth/google`;
    });

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
        } catch {
            showToast('Error', 'Connection failed. Is the server running?', 'error');
        } finally {
            spinner?.classList.add('hidden');
        }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  CHAT FORM SUBMIT
    // ════════════════════════════════════════════════════════════════════════
    chatForm?.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = userInput?.value?.trim();
        if (!text) return;
        // Secret admin command
        if (text === '/admin') {
            document.getElementById('adminModal')?.classList.remove('hidden');
            userInput.value = '';
            userInput.style.height = 'auto';
            return;
        }
        sendMessage(text);
    });

    // Textarea auto-resize
    userInput?.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 192) + 'px';
        if (sendBtn) sendBtn.disabled = !this.value.trim();
    });

    userInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (userInput.value.trim()) chatForm.requestSubmit();
        }
    });

    // ════════════════════════════════════════════════════════════════════════
    //  THEME TOGGLE
    // ════════════════════════════════════════════════════════════════════════
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.classList.toggle('dark', savedTheme === 'dark');
    const themeBtn = document.getElementById('nav-theme-toggle');
    if (themeBtn) themeBtn.textContent = savedTheme === 'dark' ? 'dark_mode' : 'light_mode';

    themeBtn?.addEventListener('click', () => {
        const isDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
        if (themeBtn) themeBtn.textContent = isDark ? 'dark_mode' : 'light_mode';
    });

    // ════════════════════════════════════════════════════════════════════════
    //  ADMIN PANEL
    // ════════════════════════════════════════════════════════════════════════
    const logToAdmin = (msg) => {
        const el = document.getElementById('admin-log');
        if (el) { el.innerHTML += `&gt; ${msg}<br>`; el.scrollTop = el.scrollHeight; }
    };

    document.getElementById('admin-load-data-btn')?.addEventListener('click', async () => {
        logToAdmin('Requesting root data reload…');
        try {
            const res = await fetch(`${API_URL}/api/admin/load-data`, {
                method: 'POST', headers: { 'x-auth-token': authToken }
            });
            const data = await res.json();
            logToAdmin(res.ok ? `Success: ${data.status}` : `Error: ${data.error || 'Failed'}`);
        } catch { logToAdmin('Error: Network failed'); }
    });

    document.getElementById('admin-append-data-btn')?.addEventListener('click', async () => {
        logToAdmin('Requesting new data append…');
        try {
            const res = await fetch(`${API_URL}/api/admin/append-data`, {
                method: 'POST', headers: { 'x-auth-token': authToken }
            });
            const data = await res.json();
            logToAdmin(res.ok ? `Success: ${data.status}` : `Error: ${data.error || 'Failed'}`);
        } catch { logToAdmin('Error: Network failed'); }
    });

    // ════════════════════════════════════════════════════════════════════════
    //  INIT
    // ════════════════════════════════════════════════════════════════════════
    updateAuthState();
});

// ── Global helpers ───────────────────────────────────────────────────────────
window.copyToClipboard = (text, btn) => {
    navigator.clipboard.writeText(text).then(() => {
        if (btn) {
            const icon = btn.querySelector('.material-symbols-outlined');
            if (icon) { const orig = icon.textContent; icon.textContent = 'check'; setTimeout(() => icon.textContent = orig, 2000); }
        }
        window.showToast?.('Copied', 'Content copied to clipboard', 'success');
    });
};

window.speakText = (text) => {
    if (!window.speechSynthesis) return window.showToast?.('Error', 'Speech not supported', 'error');
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0; utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
    window.showToast?.('Speaking', 'Reading message aloud…', 'info');
};
