/* Phase 7 Network: progressive enhancement over plain server-rendered forms.
   Every form works with JS off (POST + redirect). With JS on we submit via
   fetch, update the card + counters from the server's JSON reply, and keep the
   page/scroll position. The server stays the source of truth: counters are
   whatever it returns, never computed here. */
(function () {
    'use strict';

    var csrfInput = document.getElementById('csrf-token');
    var toast = document.getElementById('net-toast');
    var toastTimer = null;

    function csrf() { return csrfInput ? csrfInput.value : ''; }

    function say(message, isError) {
        if (!toast || !message) return;
        toast.textContent = message;
        toast.classList.toggle('error', !!isError);
        toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { toast.hidden = true; }, 3500);
    }

    function post(url, body) {
        var data = new URLSearchParams(body || {});
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': csrf(),
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            },
            body: data.toString()
        }).then(function (resp) {
            return resp.json().catch(function () { return { ok: false, message: '' }; }).then(function (json) {
                json._status = resp.status;
                return json;
            });
        });
    }

    function updateCounts(json) {
        if (typeof json.connections_count === 'number') {
            var c = document.getElementById('net-connections-count');
            if (c) c.textContent = json.connections_count;
        }
        if (typeof json.pending_count === 'number') {
            var p = document.getElementById('net-pending-count');
            if (p) p.textContent = json.pending_count;
            var badge = document.getElementById('net-pending-badge');
            var badgeCount = document.getElementById('net-pending-badge-count');
            if (badgeCount) badgeCount.textContent = json.pending_count;
            if (badge) badge.hidden = json.pending_count === 0;
        }
    }

    function fieldsOf(form) {
        var out = {};
        new FormData(form).forEach(function (value, key) { out[key] = value; });
        return out;
    }

    // If a list just emptied, reload so the server renders the right empty
    // state (with its call to action) instead of us duplicating it here.
    function removeCard(card) {
        var list = card.parentNode;
        card.remove();
        if (list && !list.querySelector('.net-card')) {
            var group = list.closest('.net-group');
            if (group && list.id !== 'net-list') {
                group.remove();
                if (document.querySelector('.net-group')) return;
            }
            window.location.reload();
        }
    }

    // ---- Connect (with optional note) -------------------------------------
    var sheet = document.getElementById('net-connect-sheet');
    var noteInput = document.getElementById('net-connect-note');
    var nameSlot = document.getElementById('net-connect-name');
    var remaining = document.getElementById('net-note-remaining');
    var errorEl = document.getElementById('net-connect-error');
    var sendBtn = document.getElementById('net-connect-send');
    var cancelBtn = document.getElementById('net-connect-cancel');
    var pendingConnectForm = null;
    var lastFocus = null;

    function openSheet(form) {
        if (!sheet) { form.submit(); return; }
        pendingConnectForm = form;
        lastFocus = document.activeElement;
        nameSlot.textContent = form.getAttribute('data-name') || '';
        noteInput.value = '';
        remaining.textContent = noteInput.maxLength;
        errorEl.hidden = true;
        sendBtn.disabled = false;
        sheet.hidden = false;
        noteInput.focus();
    }

    function closeSheet() {
        if (!sheet) return;
        sheet.hidden = true;
        pendingConnectForm = null;
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    if (sheet) {
        noteInput.addEventListener('input', function () {
            remaining.textContent = noteInput.maxLength - noteInput.value.length;
        });
        cancelBtn.addEventListener('click', closeSheet);
        sheet.addEventListener('click', function (e) { if (e.target === sheet) closeSheet(); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !sheet.hidden) closeSheet();
        });
        sendBtn.addEventListener('click', function () {
            var form = pendingConnectForm;
            if (!form) return;
            var body = fieldsOf(form);
            body.message = noteInput.value;
            sendBtn.disabled = true;      // one request per tap: no duplicate sends
            post(form.getAttribute('action'), body).then(function (json) {
                updateCounts(json);
                if (json.ok) {
                    var actions = form.closest('.person-actions');
                    if (actions) {
                        actions.innerHTML = '<span class="btn btn-line is-disabled net-sent">' + (window.NET && window.NET.sentLabel || 'Request Sent') + '</span>';
                    }
                    closeSheet();
                    say(json.message, false);
                } else {
                    errorEl.textContent = json.message || 'Something went wrong. Please try again.';
                    errorEl.hidden = false;
                    sendBtn.disabled = false;
                }
            }).catch(function () {
                errorEl.textContent = 'Network problem. Please try again.';
                errorEl.hidden = false;
                sendBtn.disabled = false;
            });
        });
    }

    // ---- generic form handlers -------------------------------------------
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!(form instanceof HTMLFormElement)) return;

        if (form.hasAttribute('data-net-connect')) {
            e.preventDefault();
            openSheet(form);
            return;
        }

        var confirmText = form.getAttribute('data-net-confirm');
        var isRemove = form.hasAttribute('data-net-remove');
        if (confirmText || isRemove) {
            var text = confirmText || ('Remove your connection with ' + (form.getAttribute('data-name') || 'this person') + '?');
            if (!window.confirm(text)) { e.preventDefault(); return; }
        }

        var card = form.closest('.net-card');
        var ajaxKind = form.hasAttribute('data-net-respond') || isRemove || form.hasAttribute('data-net-dismiss');
        if (!ajaxKind || !card) return;   // block etc. stay plain POST + redirect

        e.preventDefault();
        var buttons = card.querySelectorAll('button');
        buttons.forEach(function (b) { b.disabled = true; });
        post(form.getAttribute('action'), fieldsOf(form)).then(function (json) {
            updateCounts(json);
            if (json.ok) {
                removeCard(card);
                say(json.message, false);
            } else {
                buttons.forEach(function (b) { b.disabled = false; });
                say(json.message || 'Something went wrong.', true);
                // A stale card (already answered / removed elsewhere): drop it.
                if (json.code === 'already_resolved' || json.code === 'not_found') removeCard(card);
            }
        }).catch(function () {
            buttons.forEach(function (b) { b.disabled = false; });
            say('Network problem. Please try again.', true);
        });
    });

    // ---- three-dot menus: one open at a time, close on outside tap/Escape --
    document.addEventListener('click', function (e) {
        document.querySelectorAll('details.net-menu[open]').forEach(function (d) {
            if (!d.contains(e.target)) d.removeAttribute('open');
        });
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('details.net-menu[open]').forEach(function (d) { d.removeAttribute('open'); });
    });

    // ---- allowlisted click beacons (e.g. WhatsApp invite) ------------------
    document.addEventListener('click', function (e) {
        var el = e.target.closest ? e.target.closest('[data-net-track]') : null;
        if (!el || !window.NET || !window.NET.trackUrl) return;
        try {
            fetch(window.NET.trackUrl, {
                method: 'POST',
                credentials: 'same-origin',
                keepalive: true,
                headers: {
                    'X-CSRFToken': csrf(),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: 'event=' + encodeURIComponent(el.getAttribute('data-net-track'))
            });
        } catch (err) { /* analytics must never block the click */ }
    });
})();
