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

        // ---------- report modal (shared by "Report" and "Report photo") ----------

        var reportModal = document.getElementById('report-modal');
        var reportError = document.getElementById('report-modal-error');
        var reportDescription = document.getElementById('report-modal-description');
        var reportSubmitBtn = document.getElementById('report-modal-submit');
        var reportCancelBtn = document.getElementById('report-modal-cancel');
        var reportTargetArticle = null;
        var reportTargetUrl = null;

        function openReportModal(article, url) {
            if (!reportModal) return;
            reportTargetArticle = article;
            reportTargetUrl = url;
            reportModal.querySelectorAll('input[name="report-category"]').forEach(function (input) { input.checked = false; });
            reportDescription.value = '';
            reportError.hidden = true;
            reportModal.hidden = false;
        }

        function closeReportModal() {
            if (!reportModal) return;
            reportModal.hidden = true;
            reportTargetArticle = null;
            reportTargetUrl = null;
        }

        if (reportCancelBtn) reportCancelBtn.addEventListener('click', closeReportModal);
        if (reportModal) reportModal.addEventListener('click', function (e) {
            if (e.target === reportModal) closeReportModal();
        });

        if (reportSubmitBtn) reportSubmitBtn.addEventListener('click', function () {
            var checked = reportModal.querySelector('input[name="report-category"]:checked');
            if (!checked) {
                reportError.textContent = 'Choose a reason for the report.';
                reportError.hidden = false;
                return;
            }
            reportError.hidden = true;
            reportSubmitBtn.disabled = true;

            fetch(reportTargetUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'category=' + encodeURIComponent(checked.value) + '&description=' + encodeURIComponent(reportDescription.value.trim()),
            })
                .then(function (resp) {
                    if (!resp.ok) return resp.json().then(function (data) { throw new Error(data.error || 'Could not submit report'); });
                    return resp.json();
                })
                .then(function () {
                    var article = reportTargetArticle;
                    var wasMedia = reportTargetUrl.indexOf('/report-media/') !== -1;
                    closeReportModal();
                    if (wasMedia) {
                        var img = article.querySelector('.feed-post-image');
                        if (img) img.remove();
                        window.alert('Photo reported. Thanks — it has been hidden pending review.');
                    } else {
                        removeCard(article);
                        window.alert('Post reported. Thanks — it has been hidden pending review.');
                    }
                })
                .catch(function (err) {
                    reportError.textContent = err.message || 'Could not submit report.';
                    reportError.hidden = false;
                })
                .finally(function () {
                    reportSubmitBtn.disabled = false;
                });
        });

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
                return;
            }

            if (action === 'report') {
                openReportModal(article, '/posts/' + postId + '/report/');
                return;
            }

            if (action === 'report-media') {
                openReportModal(article, '/posts/' + postId + '/report-media/');
            }
        });
    });
})();
