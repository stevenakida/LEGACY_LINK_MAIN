(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var feedList = document.getElementById('feed-list');
        var csrfInput = document.getElementById('csrf-token');
        if (!feedList || !csrfInput) return;

        var csrfToken = csrfInput.value;

        function post(url, body) {
            var opts = { method: 'POST', headers: { 'X-CSRFToken': csrfToken } };
            if (body) {
                opts.headers['Content-Type'] = 'application/x-www-form-urlencoded';
                opts.body = body;
            }
            return fetch(url, opts).then(function (resp) {
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
            var actions = article.querySelector('.feed-post-engage');
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

        // ---------- post options (kebab) menu ----------

        function closeAllMenus(except) {
            feedList.querySelectorAll('[data-post-menu]').forEach(function (menu) {
                if (menu !== except) menu.hidden = true;
            });
        }
        document.addEventListener('click', function (evt) {
            if (!evt.target.closest('.feed-post-menu-wrap')) closeAllMenus(null);
        });

        // ---------- lightbox ----------

        var lightbox = document.getElementById('feed-lightbox');
        var lightboxImg = document.getElementById('feed-lightbox-img');
        var lightboxClose = document.getElementById('feed-lightbox-close');

        function openLightbox(imgEl) {
            if (!lightbox || !lightboxImg) return;
            lightboxImg.src = imgEl.src;
            lightbox.hidden = false;
        }
        function closeLightbox() {
            if (!lightbox) return;
            lightbox.hidden = true;
            lightboxImg.removeAttribute('src');
        }
        if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
        if (lightbox) lightbox.addEventListener('click', function (e) {
            if (e.target === lightbox) closeLightbox();
        });

        // ---------- like ----------

        function composeLikeSummary(liked, count, sampleNames) {
            if (count <= 0) return '';
            var parts = [];
            if (liked) parts.push('You');
            sampleNames.slice(0, liked ? 1 : 2).forEach(function (n) { parts.push(n); });
            var remaining = count - parts.length;
            var text = parts.join(', ');
            if (remaining > 0) text += (parts.length ? ' and ' : '') + remaining + ' other' + (remaining > 1 ? 's' : '');
            return text + ' liked this';
        }

        function applyLikeState(article, liked, count, sampleNames) {
            var btn = article.querySelector('[data-action="like"]');
            var summary = article.querySelector('[data-like-summary]');
            var stats = article.querySelector('[data-post-stats]');
            if (btn) {
                btn.classList.toggle('is-liked', liked);
                btn.setAttribute('aria-pressed', liked ? 'true' : 'false');
            }
            if (summary) {
                var text = composeLikeSummary(liked, count, sampleNames || []);
                summary.textContent = text;
                summary.hidden = !text;
            }
            if (stats) {
                var commentBtn = article.querySelector('[data-action="view-comments"]');
                var hasComments = commentBtn && !commentBtn.hidden;
                stats.hidden = !(count > 0 || hasComments);
            }
        }

        // ---------- comments ----------

        function updateCommentCount(article, count) {
            var btn = article.querySelector('[data-action="view-comments"]');
            var stats = article.querySelector('[data-post-stats]');
            var summary = article.querySelector('[data-like-summary]');
            if (btn) {
                btn.hidden = count <= 0;
                var textEl = btn.querySelector('[data-comment-count-text]');
                if (textEl) textEl.textContent = count + ' comment' + (count === 1 ? '' : 's');
            }
            if (stats) {
                var hasLikeSummary = summary && !summary.hidden;
                stats.hidden = !(count > 0 || hasLikeSummary);
            }
        }

        function renderComment(comment) {
            var row = document.createElement('div');
            row.className = 'feed-post-comment-item';
            row.dataset.commentId = comment.id;

            var strong = document.createElement('strong');
            strong.textContent = comment.author_name + ':';

            var body = document.createElement('span');
            body.className = 'feed-post-comment-body';
            body.textContent = comment.body;

            row.appendChild(strong);
            row.appendChild(body);

            if (comment.can_delete) {
                var del = document.createElement('button');
                del.type = 'button';
                del.className = 'feed-post-comment-delete';
                del.textContent = '✕';
                del.addEventListener('click', function () {
                    var owningArticle = row.closest('.feed-post');
                    post('/posts/comments/' + comment.id + '/delete/')
                        .then(function (data) {
                            row.remove();
                            if (owningArticle) updateCommentCount(owningArticle, data.count);
                        })
                        .catch(function (err) { window.alert(err.message || 'Could not delete comment.'); });
                });
                row.appendChild(del);
            }
            return row;
        }

        function loadComments(article) {
            var list = article.querySelector('[data-comment-list]');
            var postId = article.dataset.postId;
            if (!list) return;
            list.innerHTML = '';
            fetch('/posts/' + postId + '/comments/')
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    (data.comments || []).forEach(function (c) { list.appendChild(renderComment(c)); });
                })
                .catch(function () {});
        }

        function openComments(article, focusInput) {
            var panel = article.querySelector('[data-comments]');
            if (!panel) return;
            if (panel.hidden) {
                panel.hidden = false;
                loadComments(article);
            }
            if (focusInput) {
                var input = panel.querySelector('[data-comment-input]');
                if (input) input.focus();
            }
        }

        feedList.addEventListener('submit', function (evt) {
            var form = evt.target.closest('[data-comment-form]');
            if (!form) return;
            evt.preventDefault();
            var article = form.closest('.feed-post');
            var input = form.querySelector('[data-comment-input]');
            var sendBtn = form.querySelector('.feed-post-comment-send');
            var body = (input.value || '').trim();
            if (!body || !article) return;

            sendBtn.disabled = true;
            post('/posts/' + article.dataset.postId + '/comments/add/', 'body=' + encodeURIComponent(body))
                .then(function (data) {
                    var list = article.querySelector('[data-comment-list]');
                    if (list) list.appendChild(renderComment(data.comment));
                    updateCommentCount(article, data.count);
                    input.value = '';
                })
                .catch(function (err) { window.alert(err.message || 'Could not post comment.'); })
                .finally(function () { sendBtn.disabled = false; });
        });

        // ---------- share ----------

        var shareModal = document.getElementById('feed-share-modal');
        var shareModalList = document.getElementById('feed-share-modal-list');
        var shareModalStatus = document.getElementById('feed-share-modal-status');
        var shareModalCancel = document.getElementById('feed-share-modal-cancel');
        var shareTargetsData = document.getElementById('feed-share-targets-data');
        var shareTargets = shareTargetsData ? JSON.parse(shareTargetsData.textContent) : [];
        var sharePostId = null;

        function closeShareModal() {
            if (shareModal) shareModal.hidden = true;
            sharePostId = null;
        }
        function openShareModal(postId) {
            if (!shareModal || !shareModalList) return;
            sharePostId = postId;
            shareModalStatus.hidden = true;
            shareModalList.innerHTML = '';
            if (!shareTargets.length) {
                var empty = document.createElement('p');
                empty.className = 'suggested-empty';
                empty.textContent = 'Connect with people to start sharing posts with them.';
                shareModalList.appendChild(empty);
            } else {
                shareTargets.forEach(function (t) {
                    var item = document.createElement('button');
                    item.type = 'button';
                    item.className = 'forward-modal-item';
                    item.textContent = t.name;
                    item.addEventListener('click', function () {
                        post('/posts/' + sharePostId + '/share/', 'user_id=' + encodeURIComponent(t.id))
                            .then(function () {
                                shareModalStatus.textContent = 'Shared with ' + t.name + '.';
                                shareModalStatus.hidden = false;
                                setTimeout(closeShareModal, 900);
                            })
                            .catch(function (err) {
                                shareModalStatus.textContent = err.message || 'Could not share this post.';
                                shareModalStatus.hidden = false;
                            });
                    });
                    shareModalList.appendChild(item);
                });
            }
            shareModal.hidden = false;
        }
        if (shareModalCancel) shareModalCancel.addEventListener('click', closeShareModal);
        if (shareModal) shareModal.addEventListener('click', function (e) {
            if (e.target === shareModal) closeShareModal();
        });

        feedList.addEventListener('click', function (evt) {
            var img = evt.target.closest('[data-action="open-lightbox"]');
            if (img) {
                openLightbox(img);
                return;
            }

            var btn = evt.target.closest('[data-action]');
            if (!btn) return;
            var article = btn.closest('.feed-post');
            if (!article) return;
            var postId = article.dataset.postId;
            var action = btn.dataset.action;

            if (action === 'toggle-menu') {
                var menu = article.querySelector('[data-post-menu]');
                var isOpen = menu && !menu.hidden;
                closeAllMenus(null);
                if (menu) menu.hidden = isOpen;
                return;
            }

            if (action === 'edit') {
                closeAllMenus(null);
                startEdit(article);
                return;
            }

            if (action === 'delete') {
                closeAllMenus(null);
                if (!window.confirm('Delete this post? This cannot be undone.')) return;
                post('/posts/' + postId + '/delete/')
                    .then(function () { removeCard(article); })
                    .catch(function (err) { window.alert(err.message || 'Could not delete post.'); });
                return;
            }

            if (action === 'hide') {
                closeAllMenus(null);
                post('/posts/' + postId + '/hide/')
                    .then(function () { removeCard(article); })
                    .catch(function (err) { window.alert(err.message || 'Could not hide post.'); });
                return;
            }

            if (action === 'report') {
                closeAllMenus(null);
                openReportModal(article, '/posts/' + postId + '/report/');
                return;
            }

            if (action === 'report-media') {
                closeAllMenus(null);
                openReportModal(article, '/posts/' + postId + '/report-media/');
                return;
            }

            if (action === 'like') {
                btn.disabled = true;
                post('/posts/' + postId + '/like/')
                    .then(function (data) { applyLikeState(article, data.liked, data.count, data.sample_names); })
                    .catch(function (err) { window.alert(err.message || 'Could not update your like.'); })
                    .finally(function () { btn.disabled = false; });
                return;
            }

            if (action === 'comment') {
                openComments(article, true);
                return;
            }

            if (action === 'view-comments') {
                openComments(article, false);
                return;
            }

            if (action === 'share') {
                openShareModal(postId);
            }
        });
    });
})();
