/** ממשק AI: עורך בקשה עם הדבקת תמונה, מודל לוגים, טבלת ג'ובים */
(function (global) {
  'use strict';

  function initPromptEditor(opts) {
    var textarea = document.getElementById(opts.textareaId || 'id_prompt');
    var fileInput = document.getElementById(opts.fileInputId || 'id_images');
    var max = opts.maxImages || 5;
    if (!textarea || textarea.dataset.aiEditorInit) return;
    textarea.dataset.aiEditorInit = '1';

    var shell = document.createElement('div');
    shell.className = 'ai-prompt-shell';
    var editor = document.createElement('div');
    editor.className = 'ai-prompt-editor';
    editor.id = 'ai-prompt-editor';
    editor.setAttribute('contenteditable', 'true');
    editor.setAttribute('role', 'textbox');
    editor.setAttribute('aria-multiline', 'true');
    editor.dataset.placeholder = opts.placeholder || textarea.getAttribute('placeholder') || 'תאר את השינוי…';

    textarea.classList.add('ai-prompt-hidden');
    textarea.parentNode.insertBefore(shell, textarea);
    shell.appendChild(editor);
    shell.appendChild(textarea);

    if (textarea.value) editor.textContent = textarea.value;

    function syncText() {
      var clone = editor.cloneNode(true);
      clone.querySelectorAll('img').forEach(function (img) { img.remove(); });
      textarea.value = (clone.innerText || '').trim();
    }

    function addFiles(newFiles) {
      if (!fileInput) return;
      var dt = new DataTransfer();
      Array.from(fileInput.files || []).concat(Array.from(newFiles)).slice(0, max).forEach(function (f) {
        dt.items.add(f);
      });
      fileInput.files = dt.files;
      if (opts.onFilesChange) opts.onFilesChange(fileInput.files);
    }

    function insertImageAtCursor(file) {
      var url = URL.createObjectURL(file);
      var img = document.createElement('img');
      img.src = url;
      img.className = 'ai-inline-paste-img';
      img.alt = 'צילום מסך';
      img.title = file.name || 'תמונה';
      var sel = window.getSelection();
      if (sel && sel.rangeCount) {
        var range = sel.getRangeAt(0);
        range.collapse(false);
        range.insertNode(img);
        range.setStartAfter(img);
        range.setEndAfter(img);
        sel.removeAllRanges();
        sel.addRange(range);
      } else {
        editor.appendChild(img);
      }
      var zw = document.createTextNode('\u200B');
      img.after(zw);
      syncText();
    }

    editor.addEventListener('input', syncText);
    editor.addEventListener('blur', syncText);

    editor.addEventListener('paste', function (e) {
      var items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      var images = [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf('image') !== -1) {
          var blob = items[i].getAsFile();
          if (blob) {
            var ext = (blob.type || 'image/png').split('/')[1] || 'png';
            images.push(new File([blob], 'paste-' + Date.now() + '-' + i + '.' + ext, { type: blob.type }));
          }
        }
      }
      if (!images.length) return;
      e.preventDefault();
      images.forEach(function (file) {
        insertImageAtCursor(file);
      });
      addFiles(images);
    });

    var form = textarea.closest('form');
    if (form) {
      form.addEventListener('submit', function () {
        syncText();
      });
    }
  }

  function initAiModal() {
    var modal = document.getElementById('ai-detail-modal');
    if (!modal || modal.dataset.aiModalInit) return null;
    modal.dataset.aiModalInit = '1';

    function close() {
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    function open(title, html) {
      var t = document.getElementById('ai-modal-title');
      var b = document.getElementById('ai-modal-body');
      if (t) t.textContent = title || 'פרטים';
      if (b) b.innerHTML = html || '';
      modal.hidden = false;
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    }

    modal.querySelectorAll('[data-ai-modal-close]').forEach(function (el) {
      el.addEventListener('click', close);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });

    return { open: open, close: close, el: modal };
  }

  function statusBadgeClass(status) {
    if (status === 'running') return 'badge-running';
    if (status === 'completed') return 'badge-green';
    if (status === 'failed') return 'badge-red';
    if (status === 'pending') return 'badge-gold';
    return 'badge-gray';
  }

  function buildJobInfoModalHtml(j, extraPrompt) {
    var prompt = (j.request_prompt || extraPrompt || '').trim() || '—';
    var html = '';
    html += '<p style="margin-bottom:6px"><strong>ג\'וב #' + j.id + '</strong> · ' + escapeHtml(j.type_label || j.type) + '</p>';
    html += '<p style="font-size:.78rem;color:var(--muted);margin-bottom:12px">בקשה #' + j.request_id;
    if (j.request_status_label) html += ' · ' + escapeHtml(j.request_status_label);
    html += '</p>';
    html += '<div class="form-label" style="margin-bottom:6px">על איזה שינוי מדובר</div>';
    html += '<p class="ai-job-prompt-box">' + escapeHtml(prompt) + '</p>';
    if (j.error) {
      html += '<div class="alert alert-error" style="margin-top:12px;font-size:.82rem">' + escapeHtml(j.error) + '</div>';
    }
    html += '<p style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">';
    html += '<a href="/manage/ai/' + j.request_id + '/" class="btn btn-gold btn-sm">פתח בקשה</a>';
    html += '</p>';
    return html;
  }

  function jobNameCell(j) {
    return '<button type="button" class="ai-job-name-link">' + escapeHtml(j.type_label || j.type) + '</button>';
  }

  function renderJobsTableBody(tbody, jobs, opts) {
    if (!tbody) return;
    opts = opts || {};
    tbody.innerHTML = '';
    (jobs || []).forEach(function (j) {
      var tr = document.createElement('tr');
      tr.className = 'ai-row-clickable';
      tr.dataset.jobId = j.id;
      var reqCell = opts.showRequest
        ? '<td class="td-mono"><a href="/manage/ai/' + j.request_id + '/">#' + j.request_id + '</a></td>'
        : '';
      var reqStatusCell = opts.showRequestStatus
        ? '<td style="font-size:.75rem">' + escapeHtml(j.request_status_label || '—') + '</td>'
        : '';
      var dateCell = '<td class="td-mono" style="font-size:.72rem;white-space:nowrap">' + escapeHtml(j.created_at_display || '—') + '</td>';
      if (opts.detailLayout) {
        tr.innerHTML =
          '<td class="td-mono">#' + j.id + '</td>' +
          '<td>' + jobNameCell(j) + '</td>' +
          '<td><span class="badge ' + statusBadgeClass(j.status) + '">' + (j.status_label || j.status) + '</span></td>' +
          '<td class="td-mono">' + (j.attempts || 0) + '/' + (j.max_attempts || 3) + '</td>' +
          '<td style="font-size:.72rem;max-width:220px">' + (j.error ? '<span style="color:var(--loss)">' + escapeHtml(j.error) + '</span>' : '—') + '</td>' +
          dateCell +
          '<td><button type="button" class="btn btn-outline btn-sm ai-btn-details">לוג</button></td>';
      } else {
        tr.innerHTML =
          '<td class="td-mono">#' + j.id + '</td>' +
          reqCell +
          '<td>' + jobNameCell(j) + '</td>' +
          reqStatusCell +
          '<td><span class="badge ' + statusBadgeClass(j.status) + '">' + (j.status_label || j.status) + '</span></td>' +
          '<td class="td-mono">' + (j.attempts || 0) + '/' + (j.max_attempts || 3) + '</td>' +
          dateCell +
          '<td><button type="button" class="btn btn-outline btn-sm ai-btn-details">לוג</button></td>';
      }
      var nameBtn = tr.querySelector('.ai-job-name-link');
      if (nameBtn) {
        nameBtn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (opts.onJobNameClick) opts.onJobNameClick(j, tr);
        });
      }
      var btn = tr.querySelector('.ai-btn-details');
      if (btn) {
        btn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (opts.onRowClick) opts.onRowClick(j, tr);
        });
      }
      tbody.appendChild(tr);
    });
    if (!(jobs || []).length) {
      var cols = opts.detailLayout ? 7 : 7 + (opts.showRequest ? 1 : 0) + (opts.showRequestStatus ? 1 : 0);
      tbody.innerHTML = '<tr><td colspan="' + cols + '" style="text-align:center;color:var(--muted);padding:20px">אין ג\'ובים</td></tr>';
    }
  }

  function buildLogModalHtml(data) {
    var html = '';
    if (data.error) {
      html += '<div class="alert alert-error" style="margin-bottom:12px">' + escapeHtml(data.error) + '</div>';
    }
    if (data.last_log) {
      html += '<p style="margin-bottom:10px"><strong>כרגע:</strong> ' + escapeHtml(data.last_log) + '</p>';
    }
    html += '<div class="form-label" style="margin-bottom:6px">לוג עיבוד</div>';
    html += '<ul class="ai-log-list">';
    (data.logs || []).forEach(function (line) {
      html += '<li><span class="ai-log-ts">' + escapeHtml(line.ts || '') + '</span> ' + escapeHtml(line.msg || '') + '</li>';
    });
    html += '</ul>';
    if (data.queue && (data.queue.jobs || []).length) {
      html += '<div class="form-label" style="margin:14px 0 6px">ג\'ובים לבקשה</div><ul class="ai-queue-jobs">';
      data.queue.jobs.forEach(function (j) {
        html += '<li>#' + j.id + ' ' + escapeHtml(j.type_label) + ' · ' + escapeHtml(j.status_label);
        if (j.error) html += ' <span style="color:var(--loss)">' + escapeHtml(j.error) + '</span>';
        html += '</li>';
      });
      html += '</ul>';
    }
    return html;
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  global.AiPortalUI = {
    initPromptEditor: initPromptEditor,
    initAiModal: initAiModal,
    renderJobsTableBody: renderJobsTableBody,
    buildLogModalHtml: buildLogModalHtml,
    buildJobInfoModalHtml: buildJobInfoModalHtml,
    escapeHtml: escapeHtml,
    statusBadgeClass: statusBadgeClass,
  };
})(window);
