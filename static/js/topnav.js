(function () {
    'use strict';

    var THEME_KEY = 'lla-theme';

    function currentTheme() {
        return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }

    function updateThemeIcon() {
        var icon = document.getElementById('theme-toggle-icon');
        if (icon) {
            icon.textContent = currentTheme() === 'light' ? 'light_mode' : 'dark_mode';
        }
    }

    function initTheme() {
        updateThemeIcon();
        var btn = document.getElementById('theme-toggle-btn');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var next = currentTheme() === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
            updateThemeIcon();
        });
    }

    function initLanguage() {
        var btn = document.getElementById('lang-toggle-btn');
        var label = document.getElementById('lang-toggle-label');
        var csrfInput = document.getElementById('csrf-token');
        if (!btn || !label || !csrfInput) return;

        btn.addEventListener('click', function () {
            var next = label.textContent.trim() === 'EN' ? 'sw' : 'en';
            btn.disabled = true;
            fetch('/set-language/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfInput.value,
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'language=' + encodeURIComponent(next),
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('set-language failed');
                    return resp.json();
                })
                .then(function () {
                    window.location.reload();
                })
                .catch(function () {
                    btn.disabled = false;
                });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTheme();
        initLanguage();
    });
})();
