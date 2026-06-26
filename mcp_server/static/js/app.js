$(function () {
    /* ========= 全局变量 ========= */
    let currentSessionId = null;
    let lastHistoryLength = -1;
    let lastLogsLength = -1;
    let isUserScrolling = false;
    let scrollTimeout = null;
    let isCreatingSession = false;
    let uploadLocked = false;
    let sessionState = 'idle';
    let isUserScrollingLogs = false;
    let logsScrollTimeout = null;
    let sseSource = null;
    let streamingMessageEl = null;
    let streamingSessionId = null;
    let lastStreamRendered = '';
    let streamingPlainBuffer = '';

    function getDisplayName(payload = {}) {
        return payload.role || '助手';
    }

    marked.setOptions({breaks: true});
    const nocache = url => `${url}${url.includes('?') ? '&' : '?'}_=${Date.now()}`;

    /* ========= 初始化 ========= */
    loadSessions();
    setupEventHandlers();
    setupScrollDetection();
    setupGlobalDragAndDrop();

    /* ========= 会话管理 ========= */
    function loadSessions() {
        $.getJSON(nocache('/api/sessions'), res => {
            const sessions = res.sessions || [];
            const list = $('#sessionList').empty();

            if (sessions.length === 0) {
                list.append('<li class="text-center text-secondary py-3">暂无会话,请新建。</li>');
                clearChatUI();
                return;
            }

            sessions.forEach(session => {
                const fullName = session.name || '未命名会话';
                const shortName = truncateName(fullName, SIDEBAR_NAME_LIMIT);
                const li = $(`
                     <li class="session-item" data-session-id="${session.id}">
                        <span class="session-name" data-full-name="${fullName}" title="${fullName}">${shortName}</span>
                        <div class="session-item-actions">
                            <button class="rename-session-btn" title="重命名"><i class="fas fa-pencil-alt"></i></button>
                            <button class="delete-session-btn" title="删除"><i class="fas fa-trash-alt"></i></button>
                        </div>
                    </li>`);
                list.append(li);
            });

            // 自动选择会话
            let targetSessionId = null;
            const sessionIds = sessions.map(s => s.id);

            if (currentSessionId && sessionIds.includes(currentSessionId)) {
                targetSessionId = currentSessionId;
            } else {
                const urlParams = new URLSearchParams(window.location.search);
                const urlId = parseInt(urlParams.get('session_id'));
                const localId = parseInt(localStorage.getItem('mcp_last_session_id'));
                if (urlId && sessionIds.includes(urlId)) targetSessionId = urlId;
                else if (localId && sessionIds.includes(localId)) targetSessionId = localId;
            }
            if (!targetSessionId && sessions.length > 0) targetSessionId = sessions[0].id;

            if (!isCreatingSession && targetSessionId) switchSession(targetSessionId);
            else if (!targetSessionId) disableChat();
        }).fail(() => {
            $('#sessionList').html('<li class="text-center text-danger py-2">会话加载失败</li>');
        });
    }

    function updateSessionUI(state) {
        const loadingDiv = $('#loading');
        const text = $('#taskText');
        const btn = $('#sessionStateBtn');
        sessionState = state;

        if (state === 'idle') {
            loadingDiv.hide();
            return;
        }
        loadingDiv.show();

        // 不显示“任务执行中/已中止”文字，但保留判断逻辑：把 text 设为空
        const setEmptyTaskText = () => text.text('');

        // 动态状态按钮（不改变原有接口/点击逻辑）
        const renderStateBtn = (isRunning, actionText) => {
            const indicatorClass = isRunning ? 'is-running' : 'is-paused';
            const labelText = isRunning ? '任务执行中' : '已暂停';
            btn.html(
                `<span class="state-indicator ${indicatorClass}" aria-hidden="true">
                    <span class="state-dot"></span>
                    <span class="state-spin">⟳</span>
                 </span>
                 <span class="state-label">${labelText}</span>
                 <span class="state-sep">·</span>
                 <span class="state-action">${actionText}</span>`
            );
        };

        // 统一使用浅蓝色系按钮样式（不再用黄色/绿色的 bootstrap outline-*）
        const applyBtnBase = () => {
            btn.removeClass().addClass('btn btn-lg session-state-btn');
        };

        if (state === 'running') {
            setEmptyTaskText();
            applyBtnBase();
            btn.removeClass('is-paused').addClass('is-running');
            renderStateBtn(true, '⏸ 暂停');
        } else if (state === 'paused') {
            setEmptyTaskText();
            applyBtnBase();
            btn.removeClass('is-running').addClass('is-paused');
            renderStateBtn(false, '▶️ 继续');
        } else if (state === 'resumed') {
            setEmptyTaskText();
            applyBtnBase();
            btn.removeClass('is-paused').addClass('is-running');
            renderStateBtn(true, '⏸ 暂停');
        } else {
            loadingDiv.hide();
        }
    }

    $('#sessionStateBtn').on('click', function () {
        let newState;
        if (sessionState === 'running' || sessionState === 'resumed') newState = 'paused';
        else if (sessionState === 'paused') newState = 'resumed';
        else return;

        $.ajax({
            url: '/api/session/state',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({session_id: currentSessionId, state: newState})
        }).done(res => updateSessionUI(res.state));
    });

    function refreshSessionState() {
        if (!currentSessionId) return;
        $.getJSON(`/api/session/state?session_id=${currentSessionId}`, res => {
            updateSessionUI(res.state);
        }).fail(() => {
        });
    }

    setInterval(refreshSessionState, 5000);

    function switchSession(sessionId) {
        if (!sessionId) return disableChat();

        // 切会话：移除流式气泡并清基线
        if (streamingMessageEl && streamingSessionId !== sessionId) {
            streamingMessageEl.remove();
            streamingMessageEl = null;
            streamingSessionId = null;
            lastStreamRendered = ''; // 关键
        }

        currentSessionId = sessionId;

        // URL + 本地存储
        const url = new URL(window.location);
        if (url.searchParams.get('session_id') != sessionId) {
            url.searchParams.set('session_id', sessionId);
            window.history.pushState({path: url.href}, '', url.href);
        }
        localStorage.setItem('mcp_last_session_id', sessionId);

        // 激活会话 UI
        $('.session-item').removeClass('active');
        const activeItem = $(`.session-item[data-session-id="${sessionId}"]`).addClass('active');
        const fullName = activeItem.find('.session-name').data('full-name')
            || activeItem.find('.session-name').attr('data-full-name')
            || activeItem.find('.session-name').text();

        setChatTitle(fullName);

        lastHistoryLength = -1;
        lastLogsLength = -1;

        $('#chatMessages').empty();
        $('#callLogList').html('<li class="text-center text-secondary py-2">(加载中...)</li>');

        loadHistory();
        loadLogs();
        enableChat();
        refreshSessionState();
        connectSSE(sessionId);
    }

    function connectSSE(sessionId) {
        if (!window.EventSource) return;

        if (sseSource) {
            try {
                sseSource.close();
            } catch {
            }
            sseSource = null;
        }
        sseSource = new EventSource(`/sse/stream?session_id=${sessionId}`);

        sseSource.onerror = () => {
            try {
                sseSource.close();
            } catch {
            }
            sseSource = null;
            if (streamingMessageEl) {
                const bubble = streamingMessageEl.find('.bubble');
                streamingMessageEl.removeClass('streaming');
                bubble.removeClass('streaming-bubble');
                streamingMessageEl = null;
                streamingSessionId = null;
                streamingPlainBuffer = '';
                lastStreamRendered = '';
            }
        };

        sseSource.onmessage = (e) => {
            if (!e.data) return;
            let evt;
            try {
                evt = JSON.parse(e.data);
            } catch {
                return;
            }

            if (evt.type === 'chat') {
                const payload = evt.payload || {};
                const role = payload.role;
                const content = payload.content || '';
                const serverName = payload.server_name;

                if (role === 'assistant' || role === 'conversationalist') {
                    if (streamingMessageEl) {
                        streamingMessageEl.find('.name').text(getDisplayName(payload));
                        const bubble = streamingMessageEl.find('.bubble');
                        bubble.html(DOMPurify.sanitize(marked.parse(content || '')));
                        streamingMessageEl.removeClass('streaming');
                        bubble.removeClass('streaming-bubble');
                        streamingMessageEl = null;
                        streamingSessionId = null;
                        streamingPlainBuffer = '';
                        lastStreamRendered = '';
                    } else {
                        renderMessage('assistant', content, serverName);
                    }
                    return;
                }

                if (role === 'user') return;
                renderMessage(role, content, serverName);
                return;
            } else if (evt.type === 'chat_stream') {
                handleStreamingAssistant(evt.payload || {}, sessionId);
            } else if (evt.type === 'log') {
                loadLogs();
            } else if (evt.event === 'file_uploaded') {
                loadHistory();
            }
        };
    }

    function handleStreamingAssistant(payload, sessionId) {
        if (sessionId !== currentSessionId) return;

        let content = payload.content || '';
        if (content === '') return;

        const box = $('#chatMessages');
        box.find('.placeholder').remove();

        if (!streamingMessageEl || streamingSessionId !== sessionId) {
            const html = `
        <div class="message assistant streaming">
          <div class="message-inner">
            <div class="meta">🧠 <span class="name">${DOMPurify.sanitize(getDisplayName(payload))}</span></div>
            <div class="bubble streaming-bubble" style="white-space:pre-wrap;"></div>
          </div>
        </div>`;
            streamingMessageEl = $(html);
            streamingSessionId = sessionId;
            lastStreamRendered = '';
            box.append(streamingMessageEl);
        } else {
            streamingMessageEl.find('.name').text(getDisplayName(payload));
        }

        const norm = s => (s || '').replace(/\s+$/, '');
        if (norm(content) === norm(lastStreamRendered)) return;

        content = content.replace(/\n{3,}/g, '\n\n');
        const lines = content.split('\n');
        const dedupedLines = [];
        for (let i = 0; i < lines.length; i++) {
            const cur = lines[i];
            const prev = dedupedLines.length ? dedupedLines[dedupedLines.length - 1] : null;
            if (prev !== null && cur.trim() !== '' && cur === prev) continue;
            const dedupInLine = cur.replace(/(.{2,40}?)\1{1,}/g, '$1');
            dedupedLines.push(dedupInLine);
        }
        const displayContent = dedupedLines.join('\n');

        const bubble = streamingMessageEl.find('.bubble');
        bubble.html(DOMPurify.sanitize(marked.parse(displayContent))); // 保持“每帧都跑 Markdown”

        lastStreamRendered = content; // 用原始累计全文更新基线

        if (!isUserScrolling) box.scrollTop(box[0].scrollHeight);
    }

    /* ========= 新建会话 ========= */
    async function createSession() {
        if (isCreatingSession) return;
        isCreatingSession = true;

        const loading = $('#pageLoading');
        const loadingText = $('#pageLoadingText');
        const btn = $('#createSessionBtn').prop('disabled', true);

        loadingText.text('正在创建新会话...');
        loading.css({display: 'flex', opacity: 0}).animate({opacity: 1}, 300);

        try {
            const apiPromise = $.ajax({
                url: '/api/sessions/create',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    name: "新会话_" + new Date().toLocaleString('zh-CN', {
                        year: 'numeric', month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                        hour12: false
                    }).replace(/\//g, '-').replace(/ /g, '_')
                })
            });
            const delayPromise = new Promise(r => setTimeout(r, 1000));
            const [res] = await Promise.all([apiPromise, delayPromise]);

            if (res.session_id) currentSessionId = res.session_id;
            else if (res.error) throw new Error(res.error);
        } catch (e) {
            alert(`创建新会话失败:${e.message || ''}`);
        } finally {
            loading.animate({opacity: 0}, 450, () => loading.hide());
            isCreatingSession = false;
            btn.prop('disabled', false);
            loadSessions();
        }
    }

    function clearChatUI() {
        $('#chatHeader').text('💬 对话窗口');
        $('#chatMessages').html('');
        $('#callLogList').html('<li class="text-center text-secondary py-2">(暂无日志)</li>');
        $('#userInput').val('').prop('disabled', true);
        $('#sendButton').prop('disabled', true);
        $('#loading').hide();
    }

    function deleteSession(sessionId) {
        if (!confirm('确定要删除这个会话吗?其所有聊天记录将无法恢复。')) return;
        $.ajax({
            url: '/api/sessions/delete',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({session_id: sessionId})
        }).done(() => {
            if (currentSessionId === sessionId) currentSessionId = null;
            loadSessions();
        }).fail(() => alert('删除会话失败!'));
    }


    function startRenameSession(sessionId, $nameEl) {
        const oldName = String($nameEl.text() || '');

        const $input = $('<input type="text" class="session-name-input" />').val(oldName);

        $nameEl.replaceWith($input);
        $input.focus().select();

        let composing = false;
        let submitted = false;
        let finished = false;

        function restore(text) {
            if (finished) return;
            finished = true;
            $nameEl.text(text);
            $input.replaceWith($nameEl);
        }

        function submit() {
            if (submitted || finished) return;

            const raw = String($input.val() || '');
            const newName = raw.trim();

            if (!newName || newName === oldName) {
                return restore(oldName);
            }

            submitted = true;
            $input.prop('disabled', true);

            $.ajax({
                url: '/api/sessions/rename',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    session_id: sessionId,
                    name: newName
                })
            }).done(() => {
                restore(newName);
                if (typeof currentSessionId !== 'undefined' && currentSessionId === sessionId) {
                    $('#chatHeader').text(`💬 ${newName}`);
                }
            }).fail(() => {
                alert('重命名失败！');
                restore(oldName);
            });
        }

        // ===== 事件绑定 =====
        $input.on('compositionstart', () => {
            composing = true;
        });
        $input.on('compositionend', () => {
            composing = false;
        });

        $input.on('keydown', (e) => {
            if (e.key === 'Enter' && !composing) {
                e.preventDefault();
                submit();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                restore(oldName);
            }
        });

        $input.on('blur', submit);
    }

    /* ========= 聊天与日志 ========= */
    function loadHistory() {
        if (!currentSessionId) return;

        const box = $('#chatMessages');
        const el = box[0];

        $.getJSON(nocache(`/api/chat_history?session_id=${currentSessionId}`), res => {
            const logs = res.logs || [];

            // 仅在长度变化时重渲（避免打断流式）
            if (logs.length !== lastHistoryLength) {
                const prevScrollHeight = el ? el.scrollHeight : 0;
                const prevScrollTop = el ? el.scrollTop : 0;
                const BOTTOM_THRESHOLD = 2;
                const wasAtBottom = el
                    ? (el.scrollTop + el.clientHeight >= el.scrollHeight - BOTTOM_THRESHOLD)
                    : true;

                // 清理流式元素（历史变化时才清）
                if (streamingMessageEl) {
                    streamingMessageEl.remove();
                    streamingMessageEl = null;
                    streamingSessionId = null;
                }

                box.empty();

                if (logs.length > 0) {
                    logs.forEach(log => renderMessage(log.role, log.content, log.server_name));
                }

                lastHistoryLength = logs.length;

                requestAnimationFrame(() => {
                    if (!el) return;
                    if (wasAtBottom && !isUserScrolling) {
                        box.scrollTop(el.scrollHeight);
                    } else {
                        const delta = el.scrollHeight - prevScrollHeight;
                        box.scrollTop(prevScrollTop + Math.max(0, delta));
                    }
                });
            }
        }).fail(() => {
        });
    }

    function loadLogs() {
        if (!currentSessionId) return;

        const list = $('#callLogList');
        const el = list[0];

        $.getJSON(nocache(`/api/logs?session_id=${currentSessionId}`), res => {
            const logs = res.logs || [];
            if (logs.length === lastLogsLength) return;

            const prevScrollHeight = el ? el.scrollHeight : 0;
            const prevScrollTop = el ? el.scrollTop : 0;
            const BOTTOM_THRESHOLD = 2;
            const wasAtBottom = el
                ? (el.scrollTop + el.clientHeight >= el.scrollHeight - BOTTOM_THRESHOLD)
                : true;

            list.empty();
            if (logs.length === 0) {
                list.append('<li class="text-center text-secondary py-2">(暂无日志)</li>');
            } else {
                logs.reverse().forEach(l => {
                    const time = (l.created_at ?? '').toString();
                    const serverName = l.server_name ?? l.server_namme ?? '-';
                    list.append(`<li>
          <div><strong>${l.action}</strong></div>
          <div class="text-secondary small">${l.detail || ''}</div>
          <div class="time">${time}</div>
        </li>`);
                });
            }
            lastLogsLength = logs.length;

            requestAnimationFrame(() => {
                if (!el) return;
                if (wasAtBottom && !isUserScrollingLogs) {
                    list.scrollTop(el.scrollHeight);
                } else {
                    const delta = el.scrollHeight - prevScrollHeight;
                    list.scrollTop(prevScrollTop + Math.max(0, delta));
                }
            });
        }).fail(() => {
        });
    }

    // 定时刷新历史与日志（不打断流式）
    setInterval(() => {
        if (currentSessionId) {
            loadHistory();
            loadLogs();
        }
    }, 3000);

    const SIDEBAR_NAME_LIMIT = 12;
    const HEADER_NAME_LIMIT = 24;

    function setChatTitle(fullName) {
        const title = truncateName(fullName, HEADER_NAME_LIMIT);
        $('#chatTitle').text(`💬 ${title}`);
    }

    function truncateName(name, limit = 12) {
        const arr = Array.from(String(name || '')); // 按 Unicode 码点算，接近 Python len()
        return arr.length > limit ? arr.slice(0, limit).join('') + '...' : arr.join('');
    }

    function scrollChatToBottom(force = false) {
        const box = $('#chatMessages');
        const el = box[0];
        if (!el) return;
        if (force) {
            box.scrollTop(el.scrollHeight);
            return;
        }
        if (!isUserScrolling) box.scrollTop(el.scrollHeight);
    }

    // HTML 文本转义（用于我们自己拼接的 caption 等）
    function escapeHtml(str) {
        return String(str ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch]));
    }

    const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico', 'tiff', 'avif']);

    function isImageUrl(url) {
        if (!url) return false;
        const u = String(url).trim();
        if (u.startsWith('blob:') || u.startsWith('data:image/')) return true;
        const clean = u.split('?')[0].split('#')[0];
        const ext = (clean.split('.').pop() || '').toLowerCase();
        return IMAGE_EXTS.has(ext);
    }

    // 从 markdown / 文本里尽量提取第一个 URL（支持 ![]() / []() / 纯文本 URL / 相对路径）
    function extractFirstUrl(text) {
        const s = String(text || '').trim();
        if (!s) return null;

        let m = s.match(/!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/); // ![alt](url "title")
        if (m && m[1]) return m[1];

        m = s.match(/\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/); // [text](url)
        if (m && m[1]) return m[1];

        // 纯文本 URL：支持 blob: / data:image / http(s) / 相对路径
        m = s.match(/(blob:[^\s)]+|data:image\/[^\s)]+|https?:\/\/[^\s)]+|\/[^\s)]+)/);
        if (m && m[1]) return m[1];

        return null;
    }

    function renderImageBubble($bubble, imageUrl, fileName) {
        const img = document.createElement('img');
        img.className = 'chat-image';
        img.alt = fileName || 'image';
        img.loading = 'lazy';
        img.referrerPolicy = 'no-referrer';
        img.src = imageUrl;
        $bubble.empty().append(img);
        if (fileName) {
            $bubble.append(`<div class="file-caption">${escapeHtml(fileName)}</div>`);
        }
    }

    function renderImageMessage(role, imageUrl, fileName, serverName) {
        const box = $('#chatMessages');
        let cls = '', label = '', style = '';

        if (box.find('.placeholder').length > 0) box.empty();

        if (role === 'user_file') {
            cls = 'user';
            label = '📎 文件上传';
            const c = getRoleColor('user_file');
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        } else if (role === 'assistant_file') {
            cls = 'assistant';
            label = '📦 文件响应';
            const c = getRoleColor('assistant_file');
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        } else if (role === 'assistant') {
            cls = 'assistant';
            label = '🧠 助手';
        } else {
            cls = 'tool';
            const roleKey = serverName ? `${role}-${serverName}` : role;
            label = `🤖 ${role}${serverName ? ` (${serverName})` : ''}`;
            const c = getRoleColor(roleKey);
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        }

        const $msg = $(
            `<div class="message ${cls}">
              <div class="message-inner">
                <div class="meta">${label}</div>
                <div class="bubble" style="${style}"></div>
              </div>
            </div>`
        );

        renderImageBubble($msg.find('.bubble'), imageUrl, fileName);
        box.append($msg);
        scrollChatToBottom(false);
    }

    function sendMessage() {
        const input = $('#userInput');
        const text = input.val().trim();
        if (!text || !currentSessionId) return;

        const firstLine = text.split('\n')[0].replace(/\s+/g, ' ').trim();

        if (firstLine) {
            const $nameEl = $(`[data-session-id="${currentSessionId}"] .session-name`);
            const currentName = ($nameEl.text() || '').trim();
            const isDefault = !currentName || currentName.startsWith("新会话") || (currentName === "默认会话");
            if (isDefault) {

                const sidebarName = truncateName(firstLine, SIDEBAR_NAME_LIMIT);
                $nameEl.text(sidebarName);
                $nameEl.attr('data-full-name', firstLine).data('full-name', firstLine);
                $nameEl.attr('title', firstLine);

                setChatTitle(firstLine);
                $.ajax({
                    url: '/api/sessions/rename',
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({
                        session_id: currentSessionId,
                        name: firstLine
                    })
                }).done(() => {
                    console.log('[sendMessage] /api/sessions/rename 成功');
                }).fail(xhr => {
                    console.error('[sendMessage] 重命名失败', xhr.status, xhr.responseText);
                });
            }
        }

        if ($('#chatMessages').find('.placeholder').length > 0) {
            $('#chatMessages').empty();
        }

        renderMessage('user', text);
        scrollChatToBottom(true);
        input.val('').prop('disabled', true);
        $('#sendButton').prop('disabled', true);

        $.ajax({
            url: '/api/chat',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({query: text, session_id: currentSessionId})
        }).fail(xhr => {
            renderMessage('assistant', `❌ 请求失败: ${xhr.responseJSON?.error || '网络错误'}`);
        }).always(() => {
            input.prop('disabled', false).focus();
            $('#sendButton').prop('disabled', false);
        });
    }


    /* ========= 消息渲染与颜色系统 ========= */
    const COLOR_MAP_KEY = 'mcp_tool_color_map';
    const colorPalette = [
        {bg: '#dcfce7', text: '#064e3b', border: '#22c55e'},
        {bg: '#fef3c7', text: '#78350f', border: '#fbbf24'},
        {bg: '#fee2e2', text: '#7f1d1d', border: '#ef4444'},
        {bg: '#e0e7ff', text: '#312e81', border: '#6366f1'},
        {bg: '#cffafe', text: '#083344', border: '#06b6d4'},
        {bg: '#f5f5f5', text: '#262626', border: '#a3a3a3'},
    ];
    let roleColors = {};

    function getRoleColor(serverName) {
        try {
            roleColors = JSON.parse(localStorage.getItem(COLOR_MAP_KEY) || '{}');
        } catch {
            roleColors = {};
        }

        if (roleColors[serverName]) return roleColors[serverName];

        const usedIndices = new Set(
            Object.values(roleColors).map(c =>
                colorPalette.findIndex(p =>
                    p.bg === c.bg && p.text === c.text && p.border === c.border
                )
            ).filter(idx => idx !== -1)
        );

        let colorIndex = 0;
        for (let i = 0; i < colorPalette.length; i++) {
            if (!usedIndices.has(i)) {
                colorIndex = i;
                break;
            }
        }
        if (usedIndices.size >= colorPalette.length) {
            colorIndex = Math.floor(Math.random() * colorPalette.length);
        }

        const color = colorPalette[colorIndex];
        roleColors[serverName] = color;
        localStorage.setItem(COLOR_MAP_KEY, JSON.stringify(roleColors));
        return color;
    }

    function renderMessage(role, content, serverName) {
        const box = $('#chatMessages');
        let cls = '', label = '', style = '';

        if (role === 'assistant' && streamingMessageEl) {
            streamingMessageEl.remove();
            streamingMessageEl = null;
            streamingSessionId = null;
        }

        if (box.find('.placeholder').length > 0) box.empty();

        if (role === 'user') {
            cls = 'user';
            label = '👤 用户';
        } else if (role === 'assistant') {
            cls = 'assistant';
            label = '🧠 助手';
        } else if (role === 'user_file') {
            cls = 'user';
            label = '📎 文件上传';
            const c = getRoleColor('user_file');
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        } else if (role === 'assistant_file') {
            cls = 'assistant';
            label = '📦 文件响应';
            const c = getRoleColor('assistant_file');
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        } else {
            cls = 'tool';
            const roleKey = serverName ? `${role}-${serverName}` : role;
            label = `🤖 ${role}${serverName ? ` (${serverName})` : ''}`;
            const c = getRoleColor(roleKey);
            style = `background:${c.bg}; color:${c.text}; border-left:4px solid ${c.border};`;
        }

        // 文件消息：如果内容里能提取到图片 URL，则直接展示图片
        let imageUrl = null;
        let imageName = '';
        if (role === 'user_file' || role === 'assistant_file') {
            const url = extractFirstUrl(content);
            if (isImageUrl(url)) {
                imageUrl = url;
                const clean = String(url).split('?')[0].split('#')[0];
                imageName = decodeURIComponent(clean.split('/').pop() || '');
            }
        }

        const $msg = $(`
          <div class="message ${cls}">
            <div class="message-inner">
              <div class="meta">${label}</div>
              <div class="bubble" style="${style}"></div>
            </div>
          </div>
        `);

        const $bubble = $msg.find('.bubble');
        if (imageUrl) {
            renderImageBubble($bubble, imageUrl, imageName);
        } else {
            $bubble.html(DOMPurify.sanitize(marked.parse(content || '')));
        }

        box.append($msg);
        scrollChatToBottom(false);
    }

    /* ========= UI & 事件 ========= */
    function setupEventHandlers() {
        $('#createSessionBtn').on('click', createSession);

        $('#sessionList').on('click', '.session-item', function (e) {
            if (!$(e.target).closest('.session-item-actions').length) {
                switchSession($(this).data('session-id'));
            }
        });

        $('#sessionList').on('click', '.rename-session-btn', function (e) {
            e.stopPropagation();
            const li = $(this).closest('.session-item');
            startRenameSession(li.data('session-id'), li.find('.session-name'));
        });

        $('#sessionList').on('click', '.delete-session-btn', function (e) {
            e.stopPropagation();
            deleteSession($(this).closest('.session-item').data('session-id'));
        });

        $('#sendButton').on('click', sendMessage);

        $('#userInput').on('keypress', e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        $('#userInput').on('input', function () {
            autoResizeTextarea($(this));
        });

        // 左侧
        $('#toggleSessionPanel').on('click', function (e) {
            e.stopPropagation();
            const panel = $('#sessionPanel');
            const icon = $(this).find('i');
            panel.toggleClass('collapsed');
            if (panel.hasClass('collapsed')) {
                icon.removeClass('fa-angles-left').addClass('fa-angles-right');
                $(this).attr('title', '展开侧边栏');
            } else {
                icon.removeClass('fa-angles-right').addClass('fa-angles-left');
                $(this).attr('title', '收起侧边栏');
            }
        });

        // 右侧
        $('#toggleRightPanel').on('click', function (e) {
            e.stopPropagation();
            const panel = $('#rightPanel');
            const icon = $(this).find('i');
            panel.toggleClass('collapsed');
            if (panel.hasClass('collapsed')) {
                icon.removeClass('fa-angles-right').addClass('fa-angles-left');
                $(this).attr('title', '展开侧边栏');
            } else {
                icon.removeClass('fa-angles-left').addClass('fa-angles-right');
                $(this).attr('title', '收起侧边栏');
            }
        });
    }

    /* ========= 滚动检测 ========= */
    function setupScrollDetection() {
        const box = $('#chatMessages');
        box.on('scroll', () => {
            if (scrollTimeout) clearTimeout(scrollTimeout);
            isUserScrolling = true;
            scrollTimeout = setTimeout(() => {
                isUserScrolling = false;
            }, 1500);
        });

        const logBox = $('#callLogList');
        logBox.on('scroll', () => {
            if (logsScrollTimeout) clearTimeout(logsScrollTimeout);
            isUserScrollingLogs = true;
            logsScrollTimeout = setTimeout(() => {
                isUserScrollingLogs = false;
            }, 1500);
        });
    }

    function enableChat() {
        $('#userInput, #sendButton').prop('disabled', false);
    }

    function disableChat() {
        $('#userInput, #sendButton').prop('disabled', true);
    }

    /* ========= 输入框自适应 ========= */
    function autoResizeTextarea(el) {
        el.css('height', 'auto');
        el.css('height', Math.min(el[0].scrollHeight, 180) + 'px');
    }

    /* ========= 文件上传 ========= */
    $('#fileInput').on('change', function (e) {
        const file = e.target.files[0];
        if (!currentSessionId) return alert('请先选择一个会话!');
        if (file) {
            uploadFile(file);
            $(this).val('');
        }
    });

    function setupGlobalDragAndDrop() {
        const overlay = $('#dragOverlay');
        let dragCounter = 0;

        $(document).on('dragenter', function (e) {
            dragCounter++;
            if (e.originalEvent.dataTransfer?.types?.includes('Files')) overlay.addClass('active');
        });

        $(document).on('dragleave', function () {
            dragCounter--;
            if (dragCounter <= 0) overlay.removeClass('active');
        });

        $(document).on('dragover', function (e) {
            e.preventDefault();
        });

        $(document).on('drop', function (e) {
            e.preventDefault();
            overlay.removeClass('active');
            dragCounter = 0;
            if (!currentSessionId) return alert('请先选择一个会话!');
            const file = e.originalEvent.dataTransfer.files[0];
            if (file) uploadFile(file);
        });
    }

    function uploadFile(file) {
        if (uploadLocked) return;
        uploadLocked = true;
        setTimeout(() => uploadLocked = false, 1000);

        // 图片：先本地预览（秒出效果），等后端入库后再由 loadHistory 刷新为最终记录
        let previewObjectUrl = null;
        if (file?.type?.startsWith('image/')) {
            try {
                previewObjectUrl = URL.createObjectURL(file);
                renderImageMessage('user_file', previewObjectUrl, file.name);
                scrollChatToBottom(true);
                // 释放内存（不影响已渲染图片的显示）
                setTimeout(() => {
                    try {
                        if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
                    } catch {
                    }
                }, 60_000);
            } catch {
            }
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', currentSessionId);

        $.ajax({
            url: '/api/upload',
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false
        }).done(() => {
            setTimeout(loadHistory, 200);
        }).fail(xhr => {
            renderMessage('assistant_file', `❌ 上传失败:${xhr.responseJSON?.error || '未知错误'}`);
        });
    }
});
