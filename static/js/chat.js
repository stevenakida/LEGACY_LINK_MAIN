(function () {
    'use strict';

    var STATUS_POLL_INTERVAL_MS = 1200;
    var STATUS_POLL_MAX_ATTEMPTS = 15;

    document.addEventListener('DOMContentLoaded', function () {
        var body = document.getElementById('chat-body');
        if (!body) return; // not on the chat thread page

        var loadEarlierEl = document.getElementById('chat-load-earlier');
        var conversationId = body.dataset.conversationId;
        var hasEarlier = body.dataset.hasEarlier === '1';
        var csrfToken = document.getElementById('csrf-token').value;
        var input = document.getElementById('chat-text');
        var sendBtn = document.getElementById('chat-send');
        var attachBtn = document.getElementById('chat-attach-btn');
        var attachInput = document.getElementById('chat-attach-input');
        var attachPreview = document.getElementById('chat-attach-preview');
        var attachPreviewImg = document.getElementById('chat-attach-preview-img');
        var attachRemoveBtn = document.getElementById('chat-attach-remove');
        var attachErrorEl = document.getElementById('chat-attach-error');
        var replyPreview = document.getElementById('chat-reply-preview');
        var replySenderEl = document.getElementById('chat-reply-sender');
        var replySnippetEl = document.getElementById('chat-reply-snippet');
        var replyCancelBtn = document.getElementById('chat-reply-cancel');
        var lightbox = document.getElementById('chat-lightbox');
        var lightboxImg = document.getElementById('chat-lightbox-img');
        var lightboxDownload = document.getElementById('chat-lightbox-download');
        var lightboxClose = document.getElementById('chat-lightbox-close');
        var forwardModal = document.getElementById('chat-forward-modal');
        var forwardModalList = document.getElementById('forward-modal-list');
        var forwardModalCancel = document.getElementById('forward-modal-cancel');
        var otherConversationsData = document.getElementById('other-conversations-data');
        var otherConversations = otherConversationsData ? JSON.parse(otherConversationsData.textContent) : [];

        var loadingEarlier = false;
        var pendingMediaId = null;
        var pendingReplyId = null;
        var forwardMessageId = null;

        // ---------- attach-photo (composer) ----------

        function showAttachError(msg) {
            attachErrorEl.textContent = msg;
            attachErrorEl.hidden = false;
        }
        function clearAttachError() {
            attachErrorEl.hidden = true;
            attachErrorEl.textContent = '';
        }
        function resetAttachment() {
            pendingMediaId = null;
            attachInput.value = '';
            attachPreview.hidden = true;
            attachPreviewImg.removeAttribute('src');
        }

        attachBtn.addEventListener('click', function () { attachInput.click(); });
        attachRemoveBtn.addEventListener('click', resetAttachment);

        function pollUntilReady(mediaId, currentAsset, attempt) {
            attempt = attempt || 0;
            if (currentAsset.status === 'ready' || currentAsset.status === 'rejected' || currentAsset.status === 'failed') {
                return Promise.resolve(currentAsset);
            }
            if (attempt >= STATUS_POLL_MAX_ATTEMPTS) return Promise.resolve(currentAsset);
            return new Promise(function (resolve) { setTimeout(resolve, STATUS_POLL_INTERVAL_MS); })
                .then(function () { return fetch('/api/media/' + mediaId + '/status/').then(function (r) { return r.json(); }); })
                .then(function (asset) { return pollUntilReady(mediaId, asset, attempt + 1); });
        }

        attachInput.addEventListener('change', function () {
            var file = attachInput.files && attachInput.files[0];
            if (!file) return;
            clearAttachError();
            pendingMediaId = null;

            attachPreviewImg.src = URL.createObjectURL(file);
            attachPreview.hidden = false;
            attachBtn.disabled = true;

            fetch('/api/media/init/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    category: 'image', filename: file.name,
                    declared_mime_type: file.type, declared_size_bytes: file.size,
                }),
            })
                .then(function (resp) {
                    if (!resp.ok) return resp.json().then(function (d) { throw new Error(d.error || 'Could not start upload'); });
                    return resp.json();
                })
                .then(function (initData) {
                    var mediaId = initData.media.id;
                    return fetch(initData.upload_url, { method: initData.upload_method || 'PUT', body: file })
                        .then(function (uploadResp) {
                            if (!uploadResp.ok) throw new Error('Upload failed');
                            return fetch('/api/media/' + mediaId + '/complete/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
                        })
                        .then(function (completeResp) {
                            if (!completeResp.ok) return completeResp.json().then(function (d) { throw new Error(d.error || 'Could not process photo'); });
                            return completeResp.json();
                        })
                        .then(function (asset) { return pollUntilReady(mediaId, asset); });
                })
                .then(function (readyAsset) {
                    if (readyAsset.status !== 'ready') throw new Error('Photo could not be processed — please try a different image.');
                    pendingMediaId = readyAsset.id;
                })
                .catch(function (err) {
                    showAttachError(err.message || 'Photo upload failed.');
                    resetAttachment();
                })
                .finally(function () { attachBtn.disabled = false; });
        });

        // ---------- reply ----------

        function setReply(messageEl) {
            pendingReplyId = messageEl.dataset.messageId;
            var isMe = messageEl.classList.contains('me');
            replySenderEl.textContent = isMe ? 'You' : (body.dataset.otherName || 'Them');
            var hasImage = messageEl.dataset.hasImage === '1';
            var bodyText = messageEl.dataset.body || '';
            replySnippetEl.textContent = bodyText ? bodyText.slice(0, 80) : '📷 Photo';
            replyPreview.hidden = false;
            input.focus();
            closeBubbleActions();
        }
        function clearReply() {
            pendingReplyId = null;
            replyPreview.hidden = true;
        }
        replyCancelBtn.addEventListener('click', clearReply);

        // ---------- delete for me ----------

        function deleteForMe(messageEl) {
            var id = messageEl.dataset.messageId;
            closeBubbleActions();
            fetch('/messages/' + id + '/hide/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
                .then(function (r) { return r.json(); })
                .then(function (data) { if (!data.error) messageEl.remove(); });
        }

        // ---------- forward ----------

        function openForwardModal(messageEl) {
            forwardMessageId = messageEl.dataset.messageId;
            closeBubbleActions();
            forwardModalList.innerHTML = '';
            if (!otherConversations.length) {
                var empty = document.createElement('p');
                empty.className = 'suggested-empty';
                empty.textContent = 'No other conversations to forward to yet.';
                forwardModalList.appendChild(empty);
            } else {
                otherConversations.forEach(function (conv) {
                    var item = document.createElement('button');
                    item.type = 'button';
                    item.className = 'forward-modal-item';
                    item.textContent = conv.name;
                    item.addEventListener('click', function () { forwardTo(conv.id); });
                    forwardModalList.appendChild(item);
                });
            }
            forwardModal.hidden = false;
        }
        function closeForwardModal() {
            forwardModal.hidden = true;
            forwardMessageId = null;
        }
        function forwardTo(targetConversationId) {
            fetch('/messages/' + forwardMessageId + '/forward/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'target_conversation_id=' + encodeURIComponent(targetConversationId),
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    closeForwardModal();
                    if (data.error) { showAttachError(data.error); return; }
                    if (targetConversationId === conversationId) {
                        appendMessage({
                            id: data.id, body: data.body, image_url: data.image_url,
                            is_me: true, is_forwarded: true, reply_to: null, sent_at: nowLabel(),
                        });
                    }
                });
        }
        forwardModalCancel.addEventListener('click', closeForwardModal);

        function nowLabel() {
            var d = new Date();
            var h = String(d.getHours()).padStart(2, '0');
            var m = String(d.getMinutes()).padStart(2, '0');
            return h + ':' + m;
        }

        // ---------- per-bubble action row (tap to reveal Reply/Forward/Delete) ----------

        function closeBubbleActions() {
            var existing = body.querySelector('.bubble-actions');
            if (existing) existing.remove();
        }

        function showBubbleActions(messageEl) {
            var already = messageEl.nextElementSibling;
            if (already && already.classList && already.classList.contains('bubble-actions') && already.dataset.forMessage === messageEl.dataset.messageId) {
                closeBubbleActions();
                return;
            }
            closeBubbleActions();
            var row = document.createElement('div');
            row.className = 'bubble-actions ' + (messageEl.classList.contains('me') ? 'me' : 'them');
            row.dataset.forMessage = messageEl.dataset.messageId;

            var replyBtn = document.createElement('button');
            replyBtn.type = 'button';
            replyBtn.textContent = 'Reply';
            replyBtn.addEventListener('click', function () { setReply(messageEl); });

            var forwardBtn = document.createElement('button');
            forwardBtn.type = 'button';
            forwardBtn.textContent = 'Forward';
            forwardBtn.addEventListener('click', function () { openForwardModal(messageEl); });

            var deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.textContent = 'Delete for me';
            deleteBtn.addEventListener('click', function () { deleteForMe(messageEl); });

            row.appendChild(replyBtn);
            row.appendChild(forwardBtn);
            row.appendChild(deleteBtn);
            messageEl.insertAdjacentElement('afterend', row);
        }

        body.addEventListener('click', function (e) {
            var img = e.target.closest('.bubble-img');
            if (img) {
                e.stopPropagation();
                openLightbox(img);
                return;
            }
            var bubbleEl = e.target.closest('.bubble');
            if (bubbleEl) {
                showBubbleActions(bubbleEl);
            }
        });

        // ---------- lightbox ----------

        function openLightbox(imgEl) {
            var messageEl = imgEl.closest('.bubble');
            var messageId = messageEl ? messageEl.dataset.messageId : null;
            lightboxImg.src = imgEl.src;
            lightboxDownload.href = messageId ? '/messages/attachment/' + messageId + '/download/' : '#';
            lightbox.hidden = false;
        }
        function closeLightbox() {
            lightbox.hidden = true;
            lightboxImg.removeAttribute('src');
        }
        lightboxClose.addEventListener('click', closeLightbox);
        lightbox.addEventListener('click', function (e) {
            if (e.target === lightbox) closeLightbox();
        });

        // ---------- thread rendering ----------

        function lastMessageId() {
            var bubbles = body.querySelectorAll('.bubble');
            return bubbles.length ? bubbles[bubbles.length - 1].dataset.messageId : '';
        }
        function firstMessageId() {
            var bubble = body.querySelector('.bubble');
            return bubble ? bubble.dataset.messageId : '';
        }

        function scrollToBottom() { window.scrollTo(0, document.body.scrollHeight); }
        scrollToBottom();

        function buildBubble(msg) {
            var el = document.createElement('div');
            el.className = 'bubble ' + (msg.is_me ? 'me' : 'them');
            el.dataset.messageId = msg.id;
            el.dataset.body = msg.body || '';
            el.dataset.hasImage = msg.image_url ? '1' : '0';

            if (msg.is_forwarded) {
                var fwd = document.createElement('div');
                fwd.className = 'bubble-forwarded-label';
                fwd.textContent = '➦ Forwarded';
                el.appendChild(fwd);
            }
            if (msg.reply_to) {
                var quote = document.createElement('div');
                quote.className = 'bubble-reply-quote';
                var qs = document.createElement('strong');
                qs.textContent = msg.reply_to.sender_name;
                var qb = document.createElement('span');
                qb.textContent = msg.reply_to.snippet;
                quote.appendChild(qs);
                quote.appendChild(qb);
                el.appendChild(quote);
            }
            if (msg.image_url) {
                var img = document.createElement('img');
                img.className = 'bubble-img';
                img.loading = 'lazy';
                img.alt = '';
                img.src = msg.image_url;
                el.appendChild(img);
            }
            el.appendChild(document.createTextNode(msg.body || ''));
            var tm = document.createElement('span');
            tm.className = 'tm';
            tm.textContent = msg.sent_at;
            el.appendChild(tm);
            return el;
        }

        function appendMessage(msg) {
            body.appendChild(buildBubble(msg));
            scrollToBottom();
        }

        function loadEarlier() {
            if (loadingEarlier || !hasEarlier) return;
            loadingEarlier = true;
            var before = firstMessageId();
            fetch('/messages/' + conversationId + '/earlier/?before=' + encodeURIComponent(before))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    var prevHeight = document.body.scrollHeight;
                    (data.messages || []).slice().reverse().forEach(function (msg) {
                        body.insertBefore(buildBubble(msg), loadEarlierEl.nextSibling);
                    });
                    hasEarlier = !!data.has_earlier;
                    loadEarlierEl.style.display = hasEarlier ? '' : 'none';
                    window.scrollTo(0, document.body.scrollHeight - prevHeight);
                    loadingEarlier = false;
                })
                .catch(function () { loadingEarlier = false; });
        }
        loadEarlierEl.addEventListener('click', loadEarlier);
        window.addEventListener('scroll', function () {
            if (hasEarlier && window.scrollY < 40) loadEarlier();
        });

        function poll() {
            var after = lastMessageId();
            fetch('/messages/' + conversationId + '/poll/?after=' + encodeURIComponent(after))
                .then(function (r) { return r.json(); })
                .then(function (data) { (data.messages || []).forEach(appendMessage); });
        }

        function send() {
            var text = input.value.trim();
            if (!text && !pendingMediaId) return;
            clearAttachError();
            input.value = '';
            var mediaId = pendingMediaId;
            var replyTo = pendingReplyId;
            resetAttachment();
            clearReply();

            var form = new FormData();
            form.append('body', text);
            if (mediaId) form.append('media_id', mediaId);
            if (replyTo) form.append('reply_to', replyTo);
            fetch('/messages/' + conversationId + '/send/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: form,
            })
                .then(function (r) { return r.json(); })
                .then(function (msg) {
                    if (msg.error) { showAttachError(msg.error); return; }
                    appendMessage(msg);
                });
        }

        sendBtn.addEventListener('click', send);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });

        setInterval(poll, 4000);
    });
})();
