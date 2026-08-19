(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var feedList = document.getElementById('feed-list');
        var csrfInput = document.getElementById('csrf-token');
        if (!feedList || !csrfInput) return;

        var csrfToken = csrfInput.value;

        function post(url) {
            return fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
            }).then(function (resp) {
                if (!resp.ok) return resp.json().then(function (data) { throw new Error(data.error || 'Request failed'); });
                return resp.json();
            });
        }

        function removeCard(article) {
            article.remove();
            if (!feedList.querySelector('.feed-post')) {
                window.location.reload(); // let the server re-render the empty state
            }
        }

        function startEdit(article) {
            var bodyEl = article.querySelector('[data-post-body]');
            var actions = article.querySelector('.feed-post-actions');
            if (!bodyEl || !actions || article.querySelector('.feed-post-edit-box')) return;

            var postId = article.dataset.postId;
            var originalText = bodyEl.textContent;

            var box = document.createElement('div');
            box.className = 'feed-post-edit-box';

            var textarea = document.createElement('textarea');
            textarea.className = 'feed-post-edit-input';
            textarea.maxLength = 2000;
            textarea.value = originalText;

            var errorEl = document.createElement('p');
            errorEl.className = 'feed-post-edit-error';
            errorEl.hidden = true;

            var row = document.createElement('div');
            row.className = 'feed-post-edit-actions';

            var saveBtn = document.createElement('button');
            saveBtn.type = 'button';
            saveBtn.className = 'btn btn-gold';
            saveBtn.textContent = 'Save';

            var cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn btn-line';
            cancelBtn.textContent = 'Cancel';

            row.appendChild(saveBtn);
            row.appendChild(cancelBtn);
            box.appendChild(textarea);
            box.appendChild(errorEl);
            box.appendChild(row);

            bodyEl.hidden = true;
            actions.hidden = true;
            bodyEl.insertAdjacentElement('afterend', box);
            textarea.focus();

            function exitEdit() {
                box.remove();
                bodyEl.hidden = !bodyEl.textContent;
                actions.hidden = false;
            }

            cancelBtn.addEventListener('click', exitEdit);

            saveBtn.addEventListener('click', function () {
                var newBody = textarea.value.trim();
                errorEl.hidden = true;
                saveBtn.disabled = true;

                fetch('/posts/' + postId + '/edit/', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: 'body=' + encodeURIComponent(newBody),
                })
                    .then(function (resp) {
                        if (!resp.ok) return resp.json().then(function (data) { throw new Error(data.error || 'Could not save changes'); });
                        return resp.json();
                    })
                    .then(function (data) {
                        bodyEl.textContent = data.body;
                        var timeEl = article.querySelector('.feed-post-time');
                        if (timeEl && timeEl.textContent.indexOf('edited') === -1) {
                            timeEl.textContent += ' · edited';
                        }
                        exitEdit();
                    })
                    .catch(function (err) {
                        errorEl.textContent = err.message || 'Could not save changes.';
                        errorEl.hidden = false;
                    })
                    .finally(function () {
                        saveBtn.disabled = false;
                    });
            });
        }

        feedList.addEventListener('click', function (evt) {
            var btn = evt.target.closest('.feed-post-action');
            if (!btn) return;
            var article = btn.closest('.feed-post');
            if (!article) return;
            var postId = article.dataset.postId;
            var action = btn.dataset.action;

            if (action === 'edit') {
                startEdit(article);
                return;
            }

            if (action === 'delete') {
                if (!window.confirm('Delete this post? This cannot be undone.')) return;
                post('/posts/' + postId + '/delete/')
                    .then(function () { removeCard(article); })
                    .catch(function (err) { window.alert(err.message || 'Could not delete post.'); });
                return;
            }

            if (action === 'hide') {
                post('/posts/' + postId + '/hide/')
                    .then(function () { removeCard(article); })
                    .catch(function (err) { window.alert(err.message || 'Could not hide post.'); });
            }
        });
    });
})();
