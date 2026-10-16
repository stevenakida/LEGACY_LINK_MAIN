(function () {
    function debounce(fn, delay) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    // ---------- "My school isn't listed" request form ----------
    // Built from DOM calls on first use (no template edits per page) and styled
    // with the page's own theme variables, falling back to neutral colours
    // for pages like onboarding that don't load the shared stylesheet.

    const REQUEST_STYLES = [
        '.school-autocomplete-notlisted{display:block;width:100%;text-align:left;padding:0.65rem 0.8rem;background:transparent;border:0;border-top:1px solid var(--border,#d8dee9);color:var(--gold,#c98a1b);font:inherit;font-size:0.85rem;font-weight:600;cursor:pointer}',
        '.school-req-overlay{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.55);display:none;align-items:flex-end;justify-content:center}',
        '.school-req-overlay.open{display:flex}',
        '.school-req-box{box-sizing:border-box;background:var(--card,#fff);color:var(--ink,#1a2233);width:100%;max-width:480px;max-height:90vh;overflow-y:auto;border-radius:16px 16px 0 0;padding:1.2rem}',
        '.school-req-box h3{margin:0 0 0.4rem;font-size:1.05rem}',
        '.school-req-box p{margin:0 0 0.8rem;font-size:0.82rem;opacity:0.8}',
        '.school-req-box input{box-sizing:border-box;display:block;width:100%;margin:0 0 0.55rem;padding:0.65rem 0.8rem;font:inherit;font-size:0.9rem;color:inherit;background:var(--card-soft,#f4f6fa);border:1px solid var(--border,#d8dee9);border-radius:10px}',
        '.school-req-status{font-size:0.82rem;margin:0.2rem 0 0.7rem}',
        '.school-req-status.error{color:#d64545}',
        '.school-req-match{display:block;width:100%;text-align:left;margin:0 0 0.4rem;padding:0.6rem 0.8rem;font:inherit;font-size:0.88rem;color:inherit;background:var(--card-soft,#f4f6fa);border:1px solid var(--border,#d8dee9);border-radius:10px;cursor:pointer}',
        '.school-req-actions{display:flex;gap:0.6rem}',
        '.school-req-actions button{flex:1;padding:0.7rem;font:inherit;font-weight:700;border-radius:999px;cursor:pointer;border:1px solid var(--border,#d8dee9);background:transparent;color:inherit}',
        '.school-req-actions button.primary{background:var(--gold,#E8A63C);border-color:transparent;color:#15202f}',
        '.school-req-actions button:disabled{opacity:0.55;cursor:default}',
    ].join('');

    let modal = null;
    let current = null; // {root, type, select}
    let stylesAdded = false;

    // Needed as soon as a result list can show the "not listed" link, not only
    // once the form opens.
    function ensureStyles() {
        if (stylesAdded) return;
        stylesAdded = true;
        const style = document.createElement('style');
        style.textContent = REQUEST_STYLES;
        document.head.appendChild(style);
    }

    function csrfToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input) return input.value;
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text) node.textContent = text;
        return node;
    }

    function buildModal() {
        ensureStyles();

        const overlay = el('div', 'school-req-overlay');
        const box = el('div', 'school-req-box');
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');

        const name = el('input');
        name.type = 'text';
        name.maxLength = 200;
        name.placeholder = 'School name';
        name.setAttribute('aria-label', 'School name');
        const region = el('input');
        region.type = 'text';
        region.maxLength = 100;
        region.placeholder = 'Region (e.g. Arusha)';
        region.setAttribute('aria-label', 'Region');
        const district = el('input');
        district.type = 'text';
        district.maxLength = 100;
        district.placeholder = 'District (optional)';
        district.setAttribute('aria-label', 'District');

        const status = el('div', 'school-req-status');
        const matches = el('div');
        const send = el('button', 'primary', 'Send request');
        send.type = 'button';
        const cancel = el('button', '', 'Cancel');
        cancel.type = 'button';
        const actions = el('div', 'school-req-actions');
        actions.appendChild(cancel);
        actions.appendChild(send);

        box.appendChild(el('h3', '', "My school isn't listed"));
        box.appendChild(el('p', '', "Tell us about it and we'll add it to the list. You'll get a notification when it's ready, and it will fill in on your profile automatically."));
        box.appendChild(name);
        box.appendChild(region);
        box.appendChild(district);
        box.appendChild(status);
        box.appendChild(matches);
        box.appendChild(actions);
        overlay.appendChild(box);
        document.body.appendChild(overlay);

        function close() {
            overlay.classList.remove('open');
            current = null;
        }
        cancel.addEventListener('click', close);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && overlay.classList.contains('open')) close();
        });

        function setStatus(text, isError) {
            status.textContent = text || '';
            status.className = 'school-req-status' + (isError ? ' error' : '');
        }

        send.addEventListener('click', function () {
            if (!current) return;
            const schoolName = name.value.trim();
            if (schoolName.length < 3) {
                setStatus("Please type the school's name.", true);
                return;
            }
            setStatus('Sending…', false);
            matches.innerHTML = '';
            send.disabled = true;

            const body = new URLSearchParams({
                school_type: current.type,
                name: schoolName,
                region: region.value.trim(),
                district: district.value.trim(),
            });
            fetch(current.root.dataset.requestEndpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/x-www-form-urlencoded' },
                body: body.toString(),
            })
                .then(function (res) { return res.json().then(function (data) { return { status: res.status, data: data }; }); })
                .then(function (r) {
                    if (r.status === 409 && r.data.listed) {
                        setStatus('That school is already on the list. Pick it here:', false);
                        r.data.matches.forEach(function (item) {
                            const btn = el('button', 'school-req-match');
                            btn.type = 'button';
                            btn.textContent = item.name + (item.region ? ' (' + item.region + ')' : '');
                            btn.addEventListener('click', function () {
                                if (current) current.select(item);
                                close();
                            });
                            matches.appendChild(btn);
                        });
                        send.disabled = false;
                    } else if (r.data.ok) {
                        setStatus(r.data.created
                            ? "Thanks! We'll review “" + r.data.name + "” and notify you when it's added. You can finish the rest of your profile meanwhile."
                            : "You've already asked for this school — we're still reviewing it.", false);
                        cancel.textContent = 'Close';
                    } else {
                        setStatus(r.data.error || 'Could not send your request. Please try again.', true);
                        send.disabled = false;
                    }
                })
                .catch(function () {
                    setStatus('Could not send your request. Check your connection and try again.', true);
                    send.disabled = false;
                });
        });

        return {
            open: function (prefill) {
                name.value = prefill || '';
                region.value = '';
                district.value = '';
                matches.innerHTML = '';
                setStatus('', false);
                send.disabled = false;
                cancel.textContent = 'Cancel';
                overlay.classList.add('open');
                name.focus();
            },
        };
    }

    function openRequestModal(root, schoolType, prefill, select) {
        if (!modal) modal = buildModal();
        current = { root: root, type: schoolType, select: select };
        modal.open(prefill);
    }

    // ---------- the autocomplete itself ----------

    function initAutocomplete(root) {
        const input = root.querySelector('.school-autocomplete-input');
        const hidden = root.querySelector('.school-autocomplete-hidden');
        const results = root.querySelector('.school-autocomplete-results');
        const schoolType = root.dataset.type;
        const endpoint = root.dataset.endpoint;
        const canRequest = Boolean(root.dataset.requestEndpoint);
        if (canRequest) ensureStyles();

        function closeResults() {
            results.innerHTML = '';
            results.classList.remove('open');
        }

        function selectSchool(item) {
            hidden.value = item.id;
            input.value = item.name;
            closeResults();
        }

        function appendNotListed() {
            if (!canRequest) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'school-autocomplete-notlisted';
            btn.textContent = "My school isn't listed";
            results.appendChild(btn);
        }

        function renderResults(items) {
            if (!items.length) {
                results.innerHTML = '<div class="school-autocomplete-empty">No matches found. Try a different spelling.</div>';
                appendNotListed();
                results.classList.add('open');
                return;
            }
            results.innerHTML = items.map(function (item) {
                const meta = [item.district, item.region].filter(Boolean).join(', ');
                const safeName = String(item.name).replace(/"/g, '&quot;');
                return (
                    '<button type="button" class="school-autocomplete-option" data-id="' + item.id + '" data-name="' + safeName + '">' +
                    '<span class="option-name"></span>' +
                    (meta ? '<span class="option-meta"></span>' : '') +
                    '</button>'
                );
            }).join('');

            // Set text via textContent (not innerHTML) to avoid XSS from school names.
            const buttons = results.querySelectorAll('.school-autocomplete-option');
            items.forEach(function (item, i) {
                const btn = buttons[i];
                btn.querySelector('.option-name').textContent = item.name;
                const metaEl = btn.querySelector('.option-meta');
                if (metaEl) {
                    metaEl.textContent = [item.district, item.region].filter(Boolean).join(', ');
                }
            });

            appendNotListed();
            results.classList.add('open');
        }

        const search = debounce(function () {
            const q = input.value.trim();
            if (q.length < 2) {
                closeResults();
                return;
            }
            fetch(endpoint + '?type=' + encodeURIComponent(schoolType) + '&q=' + encodeURIComponent(q), {
                credentials: 'same-origin'
            })
                .then(function (res) { return res.json(); })
                .then(function (data) { renderResults(data.results || []); })
                .catch(function () { closeResults(); });
        }, 250);

        input.addEventListener('input', function () {
            hidden.value = '';
            search();
        });

        input.addEventListener('focus', function () {
            if (input.value.trim().length >= 2 && results.children.length) {
                results.classList.add('open');
            }
        });

        results.addEventListener('click', function (e) {
            if (e.target.closest('.school-autocomplete-notlisted')) {
                const typed = input.value.trim();
                closeResults();
                openRequestModal(root, schoolType, typed, selectSchool);
                return;
            }
            const btn = e.target.closest('.school-autocomplete-option');
            if (!btn) return;
            selectSchool({ id: btn.dataset.id, name: btn.dataset.name });
        });

        document.addEventListener('click', function (e) {
            if (!root.contains(e.target)) {
                closeResults();
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.school-autocomplete').forEach(initAutocomplete);
    });
})();
