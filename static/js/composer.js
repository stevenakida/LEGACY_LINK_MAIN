(function () {
    'use strict';

    var STATUS_POLL_INTERVAL_MS = 1200;
    var STATUS_POLL_MAX_ATTEMPTS = 15;

    document.addEventListener('DOMContentLoaded', function () {
        var bodyInput = document.getElementById('post-body-input');
        var photoBtn = document.getElementById('post-photo-btn');
        var photoInput = document.getElementById('post-photo-input');
        var photoPreview = document.getElementById('post-photo-preview');
        var photoPreviewImg = document.getElementById('post-photo-preview-img');
        var photoRemoveBtn = document.getElementById('post-photo-remove');
        var submitBtn = document.getElementById('post-submit-btn');
        var errorEl = document.getElementById('post-error');
        var csrfInput = document.getElementById('csrf-token');
        var audienceSwitch = document.getElementById('post-audience-switch');
        var audienceHint = document.getElementById('post-audience-hint');

        if (!bodyInput || !photoBtn || !submitBtn || !csrfInput) return;

        var csrfToken = csrfInput.value;
        var pendingMediaId = null; // set once the photo has finished uploading + processing
        var selectedAudience = 'connections';

        if (audienceSwitch) {
            audienceSwitch.addEventListener('click', function (evt) {
                var pill = evt.target.closest('.tab-pill');
                if (!pill) return;
                selectedAudience = pill.dataset.audience;
                audienceSwitch.querySelectorAll('.tab-pill').forEach(function (p) {
                    p.classList.toggle('on', p === pill);
                });
                if (audienceHint) audienceHint.hidden = selectedAudience !== 'public';
            });
        }

        function showError(message) {
            errorEl.textContent = message;
            errorEl.hidden = false;
        }

        function clearError() {
            errorEl.hidden = true;
            errorEl.textContent = '';
        }

        function setBusy(busy) {
            submitBtn.disabled = busy;
            photoBtn.disabled = busy;
        }

        function resetPhoto() {
            pendingMediaId = null;
            photoInput.value = '';
            photoPreview.hidden = true;
            photoPreviewImg.removeAttribute('src');
        }

        photoBtn.addEventListener('click', function () {
            photoInput.click();
        });

        photoRemoveBtn.addEventListener('click', function () {
            resetPhoto();
        });

        photoInput.addEventListener('change', function () {
            var file = photoInput.files && photoInput.files[0];
            if (!file) return;
            clearError();
            pendingMediaId = null;

            var localUrl = URL.createObjectURL(file);
            photoPreviewImg.src = localUrl;
            photoPreview.hidden = false;

            setBusy(true);
            fetch('/api/media/init/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    category: 'image',
                    filename: file.name,
                    declared_mime_type: file.type,
                    declared_size_bytes: file.size,
                }),
            })
                .then(function (resp) {
                    if (!resp.ok) return resp.json().then(function (data) { throw new Error(data.error || 'Could not start upload'); });
                    return resp.json();
                })
                .then(function (initData) {
                    var mediaId = initData.media.id;
                    return fetch(initData.upload_url, {
                        method: initData.upload_method || 'PUT',
                        body: file,
                    }).then(function (uploadResp) {
                        if (!uploadResp.ok) throw new Error('Upload failed');
                        return fetch('/api/media/' + mediaId + '/complete/', {
                            method: 'POST',
                            headers: { 'X-CSRFToken': csrfToken },
                        });
                    }).then(function (completeResp) {
                        if (!completeResp.ok) return completeResp.json().then(function (data) { throw new Error(data.error || 'Could not process photo'); });
                        return completeResp.json();
                    }).then(function (asset) {
                        return pollUntilReady(mediaId, asset);
                    });
                })
                .then(function (readyAsset) {
                    if (readyAsset.status !== 'ready') {
                        throw new Error('Photo could not be processed — please try a different image.');
                    }
                    pendingMediaId = readyAsset.id;
                })
                .catch(function (err) {
                    showError(err.message || 'Photo upload failed.');
                    resetPhoto();
                })
                .finally(function () {
                    setBusy(false);
                });
        });

        function pollUntilReady(mediaId, currentAsset, attempt) {
            attempt = attempt || 0;
            if (currentAsset.status === 'ready' || currentAsset.status === 'rejected' || currentAsset.status === 'failed') {
                return Promise.resolve(currentAsset);
            }
            if (attempt >= STATUS_POLL_MAX_ATTEMPTS) {
                return Promise.resolve(currentAsset);
            }
            return new Promise(function (resolve) {
                setTimeout(resolve, STATUS_POLL_INTERVAL_MS);
            }).then(function () {
                return fetch('/api/media/' + mediaId + '/status/').then(function (resp) {
                    return resp.json();
                });
            }).then(function (asset) {
                return pollUntilReady(mediaId, asset, attempt + 1);
            });
        }

        submitBtn.addEventListener('click', function () {
            var body = bodyInput.value.trim();
            if (!body && !pendingMediaId) {
                showError('Add some text or a photo before posting.');
                return;
            }
            clearError();
            setBusy(true);

            var params = 'body=' + encodeURIComponent(body) + '&audience=' + encodeURIComponent(selectedAudience);
            if (pendingMediaId) params += '&media_id=' + encodeURIComponent(pendingMediaId);

            fetch('/posts/create/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: params,
            })
                .then(function (resp) {
                    if (!resp.ok) return resp.json().then(function (data) { throw new Error(data.error || 'Could not publish post'); });
                    return resp.json();
                })
                .then(function () {
                    // Reload so the new post renders with full server-side
                    // fidelity (avatar, cohort tag) instead of duplicating
                    // that template logic in JS for a one-off insert.
                    window.location.reload();
                })
                .catch(function (err) {
                    showError(err.message || 'Could not publish post.');
                    setBusy(false);
                });
        });
    });
})();
