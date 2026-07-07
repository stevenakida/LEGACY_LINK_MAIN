(function () {
    function debounce(fn, delay) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    function initAutocomplete(root) {
        const input = root.querySelector('.school-autocomplete-input');
        const hidden = root.querySelector('.school-autocomplete-hidden');
        const results = root.querySelector('.school-autocomplete-results');
        const schoolType = root.dataset.type;
        const endpoint = root.dataset.endpoint;

        function closeResults() {
            results.innerHTML = '';
            results.classList.remove('open');
        }

        function renderResults(items) {
            if (!items.length) {
                results.innerHTML = '<div class="school-autocomplete-empty">No matches found. Try a different spelling.</div>';
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
            const btn = e.target.closest('.school-autocomplete-option');
            if (!btn) return;
            hidden.value = btn.dataset.id;
            input.value = btn.dataset.name;
            closeResults();
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
