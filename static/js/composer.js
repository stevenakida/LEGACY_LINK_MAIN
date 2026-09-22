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
        var photoCropBtn = document.getElementById('post-photo-crop-btn');
        var submitBtn = document.getElementById('post-submit-btn');
        var errorEl = document.getElementById('post-error');
        var csrfInput = document.getElementById('csrf-token');
        var audienceSwitch = document.getElementById('post-audience-switch');
        var audienceHint = document.getElementById('post-audience-hint');

        if (!bodyInput || !photoBtn || !submitBtn || !csrfInput) return;

        var csrfToken = csrfInput.value;
        var pendingMediaId = null; // set once the photo has finished uploading + processing
        var selectedAudience = 'connections';
        var originalFile = null; // the untouched picked file -- cropping always starts from this, never from a previous crop, so repeated adjustments never compound quality loss
        var previewObjectUrl = null;

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
            originalFile = null;
            photoInput.value = '';
            photoPreview.hidden = true;
            photoPreviewImg.removeAttribute('src');
            if (previewObjectUrl) {
                URL.revokeObjectURL(previewObjectUrl);
                previewObjectUrl = null;
            }
        }

        function setPhotoPreview(file) {
            if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
            previewObjectUrl = URL.createObjectURL(file);
            photoPreviewImg.src = previewObjectUrl;
            photoPreview.hidden = false;
        }

        function startUpload(file) {
            clearError();
            pendingMediaId = null;
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
            originalFile = file;
            setPhotoPreview(file);
            startUpload(file);
        });

        // ---------- crop ----------

        var cropModal = document.getElementById('post-crop-modal');
        var cropStage = document.getElementById('crop-stage');
        var cropImg = document.getElementById('crop-stage-img');
        var cropBox = document.getElementById('crop-box');
        var cropApplyBtn = document.getElementById('crop-apply-btn');
        var cropCancelBtn = document.getElementById('crop-cancel-btn');
        var cropObjectUrl = null;
        var dragMode = null; // null | 'move' | 'nw' | 'ne' | 'sw' | 'se'
        var dragStart = null;

        function imageDisplayRect() {
            var r = cropImg.getBoundingClientRect();
            var s = cropStage.getBoundingClientRect();
            return { left: r.left - s.left, top: r.top - s.top, width: r.width, height: r.height };
        }

        function currentBoxRect() {
            return {
                left: parseFloat(cropBox.style.left) || 0,
                top: parseFloat(cropBox.style.top) || 0,
                width: parseFloat(cropBox.style.width) || 0,
                height: parseFloat(cropBox.style.height) || 0,
            };
        }

        function applyBoxRect(box) {
            cropBox.style.left = box.left + 'px';
            cropBox.style.top = box.top + 'px';
            cropBox.style.width = box.width + 'px';
            cropBox.style.height = box.height + 'px';
        }

        function clampBox(box, bounds) {
            var minSize = 32;
            box.width = Math.max(minSize, Math.min(box.width, bounds.width));
            box.height = Math.max(minSize, Math.min(box.height, bounds.height));
            box.left = Math.max(bounds.left, Math.min(box.left, bounds.left + bounds.width - box.width));
            box.top = Math.max(bounds.top, Math.min(box.top, bounds.top + bounds.height - box.height));
            return box;
        }

        function openCropModal() {
            if (!originalFile || !cropModal) return;
            cropObjectUrl = URL.createObjectURL(originalFile);
            cropImg.src = cropObjectUrl;
            cropModal.hidden = false;
        }

        function closeCropModal() {
            if (cropModal) cropModal.hidden = true;
            if (cropObjectUrl) {
                URL.revokeObjectURL(cropObjectUrl);
                cropObjectUrl = null;
            }
        }

        // The crop box starts covering the whole displayed image -- only
        // known once the image has actually loaded and has real layout
        // dimensions to read.
        cropImg.addEventListener('load', function () {
            applyBoxRect(imageDisplayRect());
        });

        function onCropPointerDown(evt) {
            var handle = evt.target.closest('.crop-handle');
            dragMode = handle ? handle.dataset.handle : 'move';
            dragStart = { x: evt.clientX, y: evt.clientY, box: currentBoxRect() };
            evt.preventDefault();
        }

        function onCropPointerMove(evt) {
            if (!dragMode) return;
            var dx = evt.clientX - dragStart.x;
            var dy = evt.clientY - dragStart.y;
            var bounds = imageDisplayRect();
            var box = {
                left: dragStart.box.left, top: dragStart.box.top,
                width: dragStart.box.width, height: dragStart.box.height,
            };

            if (dragMode === 'move') {
                box.left = dragStart.box.left + dx;
                box.top = dragStart.box.top + dy;
            } else {
                if (dragMode.indexOf('w') !== -1) { box.left = dragStart.box.left + dx; box.width = dragStart.box.width - dx; }
                if (dragMode.indexOf('e') !== -1) { box.width = dragStart.box.width + dx; }
                if (dragMode.indexOf('n') !== -1) { box.top = dragStart.box.top + dy; box.height = dragStart.box.height - dy; }
                if (dragMode.indexOf('s') !== -1) { box.height = dragStart.box.height + dy; }
            }
            applyBoxRect(clampBox(box, bounds));
        }

        function onCropPointerUp() {
            dragMode = null;
            dragStart = null;
        }

        function applyCrop() {
            var box = currentBoxRect();
            var bounds = imageDisplayRect();
            var scaleX = cropImg.naturalWidth / bounds.width;
            var scaleY = cropImg.naturalHeight / bounds.height;

            var sx = (box.left - bounds.left) * scaleX;
            var sy = (box.top - bounds.top) * scaleY;
            var sw = box.width * scaleX;
            var sh = box.height * scaleY;

            var canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round(sw));
            canvas.height = Math.max(1, Math.round(sh));
            canvas.getContext('2d').drawImage(cropImg, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

            var mimeType = (originalFile.type && originalFile.type.indexOf('image/') === 0) ? originalFile.type : 'image/jpeg';
            canvas.toBlob(function (blob) {
                if (!blob) {
                    showError('Could not crop photo — please try again.');
                    return;
                }
                var croppedFile = new File([blob], originalFile.name, { type: mimeType });
                closeCropModal();
                setPhotoPreview(croppedFile);
                startUpload(croppedFile);
            }, mimeType, 0.92);
        }

        if (photoCropBtn) photoCropBtn.addEventListener('click', openCropModal);
        if (cropCancelBtn) cropCancelBtn.addEventListener('click', closeCropModal);
        if (cropApplyBtn) cropApplyBtn.addEventListener('click', applyCrop);
        if (cropBox) cropBox.addEventListener('pointerdown', onCropPointerDown);
        document.addEventListener('pointermove', onCropPointerMove);
        document.addEventListener('pointerup', onCropPointerUp);

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
