/**
 * 보험 청구 서류 정리 - Frontend Application
 */

const $ = (s, el = document) => el.querySelector(s);
const jobsEl = $('#jobs');
const emptyEl = $('#empty');
const jobsCountBadge = $('#jobsCountBadge');
const fileInput = $('#fileInput');
const dz = $('#dropzone');
const imageModal = $('#imageModal');
const modalImg = $('#modalImg');
const modalFilename = $('#modalFilename');
const modalDownload = $('#modalDownload');
const modalClose = $('#modalClose');
const modalCounter = $('#modalCounter');
const modalPrev = $('#modalPrev');
const modalNext = $('#modalNext');

const STATUS_LABEL = {
  queued: '접수 대기중',
  classifying: '비전 AI 서류 구분중',
  extracting: '청구 항목 추출중',
  done: '정리 완료',
  failed: '처리 실패',
};

let pollTimer = null;
let currentGallery = [];
let currentGalleryIndex = 0;

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderDiagnosis(diagText) {
  if (!diagText) return '진단명 없음';
  // 형식 예: H368(기타 망막장애), H400(녹내장의증)
  const chipPattern = /([A-Z]\d{2}(?:\.?\d{1,2})?)\(([^)]+)\)/g;
  let match;
  let lastIndex = 0;
  const parts = [];
  let hasMatch = false;

  while ((match = chipPattern.exec(diagText)) !== null) {
    hasMatch = true;
    if (match.index > lastIndex) {
      const textBefore = diagText.slice(lastIndex, match.index).trim().replace(/^[,;\s]+|[,;\s]+$/g, '');
      if (textBefore) parts.push(`<span class="diag-text">${escapeHtml(textBefore)}</span>`);
    }
    const code = match[1];
    const desc = match[2];
    parts.push(`
      <span class="diag-chip" title="질병분류기호 ${escapeHtml(code)}: ${escapeHtml(desc)}">
        <span class="diag-chip-code">${escapeHtml(code)}</span>
        <span class="diag-chip-name">${escapeHtml(desc)}</span>
      </span>
    `);
    lastIndex = chipPattern.lastIndex;
  }

  if (hasMatch) {
    if (lastIndex < diagText.length) {
      const textAfter = diagText.slice(lastIndex).trim().replace(/^[,;\s]+|[,;\s]+$/g, '');
      if (textAfter) parts.push(`<span class="diag-text">${escapeHtml(textAfter)}</span>`);
    }
    return parts.join(' ');
  }

  return escapeHtml(diagText);
}

// ---------- 알림 (Toast) 시스템 ----------
function showToast(message, type = 'info', duration = 3200) {
  const container = $('#toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const iconSvg = type === 'success'
    ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`
    : type === 'error'
    ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="8"/></svg>`;

  toast.innerHTML = `${iconSvg}<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// ---------- 이미지 라이트박스 갤러리 모달 & 좌우 키 네비게이션 ----------
function updateModalView() {
  if (!currentGallery.length) return;
  const item = currentGallery[currentGalleryIndex];
  modalImg.src = item.src;
  modalFilename.textContent = item.filename || '서류 사진 미리보기';
  modalDownload.href = item.src;
  modalDownload.download = item.downloadName || item.filename || 'document.webp';

  if (modalCounter) {
    modalCounter.textContent = `${currentGalleryIndex + 1} / ${currentGallery.length}`;
  }

  const hasMultiple = currentGallery.length > 1;
  if (modalPrev) {
    modalPrev.style.display = hasMultiple ? 'flex' : 'none';
    modalPrev.disabled = !hasMultiple;
  }
  if (modalNext) {
    modalNext.style.display = hasMultiple ? 'flex' : 'none';
    modalNext.disabled = !hasMultiple;
  }
}

function openImageGallery(items, initialIndex = 0) {
  if (!imageModal || !items || !items.length) return;
  currentGallery = items;
  currentGalleryIndex = Math.max(0, Math.min(initialIndex, items.length - 1));
  updateModalView();
  imageModal.showModal();
}

function openImageModal(src, filename) {
  openImageGallery([{ src, filename, downloadName: filename }], 0);
}

function navigateModal(direction) {
  if (!imageModal?.open || !currentGallery.length) return;
  const len = currentGallery.length;
  currentGalleryIndex = (currentGalleryIndex + direction + len) % len;
  updateModalView();
}

modalPrev?.addEventListener('click', (e) => {
  e.stopPropagation();
  navigateModal(-1);
});

modalNext?.addEventListener('click', (e) => {
  e.stopPropagation();
  navigateModal(1);
});

// 키보드 좌우 화살표 키로 사진 네비게이션
window.addEventListener('keydown', (e) => {
  if (imageModal && imageModal.open) {
    if (e.key === 'ArrowLeft' || e.key === 'Left') {
      e.preventDefault();
      navigateModal(-1);
    } else if (e.key === 'ArrowRight' || e.key === 'Right') {
      e.preventDefault();
      navigateModal(1);
    }
  }
});

modalClose?.addEventListener('click', () => imageModal.close());
imageModal?.addEventListener('click', (e) => {
  const rect = imageModal.getBoundingClientRect();
  const isInDialog = (
    rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
    rect.left <= e.clientX && e.clientX <= rect.left + rect.width
  );
  if (!isInDialog || e.target === imageModal) {
    imageModal.close();
  }
});

// ---------- 클립보드 복사 ----------
async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const origHtml = btn.innerHTML;
      btn.classList.add('copied');
      btn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        <span>복사됨!</span>
      `;
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = origHtml;
      }, 1800);
    }
    showToast(`디렉터리 경로를 복사했습니다.`, 'success', 2000);
  } catch {
    showToast('클립보드 복사에 실패했습니다.', 'error');
  }
}

// ---------- 시간 표시 포맷터 ----------
function formatTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr.replace('T', ' ');

  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);

  if (diffSec < 45) return '방금 전';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`;

  const pad = n => String(n).padStart(2, '0');
  const year = d.getFullYear();
  const month = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  const hours = pad(d.getHours());
  const minutes = pad(d.getMinutes());

  const isToday = now.toDateString() === d.toDateString();
  if (isToday) return `오늘 ${hours}:${minutes}`;
  return `${year}.${month}.${day} ${hours}:${minutes}`;
}

// ---------- 업로드 핸들러 ----------
$('#addBtn')?.addEventListener('click', () => fileInput.click());
$('#emptyUploadBtn')?.addEventListener('click', () => fileInput.click());
fileInput?.addEventListener('change', (e) => upload(e.target.files));

if (dz) {
  ['dragenter', 'dragover'].forEach(ev =>
    dz.addEventListener(ev, e => {
      e.preventDefault();
      dz.classList.add('drag');
    })
  );
  ['dragleave', 'drop'].forEach(ev =>
    dz.addEventListener(ev, e => {
      e.preventDefault();
      dz.classList.remove('drag');
    })
  );
  dz.addEventListener('drop', e => upload(e.dataTransfer.files));
  dz.addEventListener('click', (e) => {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {
      fileInput.click();
    }
  });
}

// 단축키 (Cmd+O / Ctrl+O)
window.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'o') {
    e.preventDefault();
    fileInput.click();
  }
});

// 새로고침 버튼
$('#refreshBtn')?.addEventListener('click', () => {
  refresh();
  showToast('작업 목록을 새로고침했습니다.', 'info', 1500);
});

async function upload(fileList) {
  const files = [...fileList].filter(f =>
    f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|heif|bmp|tiff?)$/i.test(f.name)
  );

  if (!files.length) {
    showToast('이미지 파일(JPG, PNG, HEIC 등)을 선택해 주세요.', 'error');
    return;
  }

  showToast(`${files.length}장의 서류 사진 업로드를 시작합니다...`, 'info', 2500);

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));

  try {
    const r = await fetch('/api/jobs', { method: 'POST', body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    showToast('서류가 등록되어 비전 AI 분석이 시작되었습니다.', 'success');
    refresh();
  } catch (err) {
    showToast('업로드 실패: ' + err.message, 'error', 4500);
  } finally {
    fileInput.value = '';
  }
}

// ---------- 상태 폴링 ----------
function scheduleNextPoll(ms) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(refresh, ms);
}

async function refresh() {
  let jobs = [];
  try {
    const r = await fetch('/api/jobs');
    jobs = (await r.json()).jobs || [];
  } catch {
    scheduleNextPoll(5000);
    return;
  }

  if (emptyEl) {
    emptyEl.hidden = jobs.length > 0;
  }
  if (jobsCountBadge) {
    jobsCountBadge.textContent = `${jobs.length}개 작업`;
  }

  const tpl = $('#job-tpl');

  // 이미 렌더된 카드 갱신, 없으면 추가
  for (const job of jobs) {
    let card = jobsEl.querySelector(`[data-job="${job.id}"]`);
    if (!card) {
      card = tpl.content.cloneNode(true).querySelector('article');
      card.dataset.job = job.id;
      jobsEl.prepend(card);
    }
    renderJob(card, job);
  }

  // 활성 작업 여부에 따른 가변 폴링 주기 (진행 중일 땐 2초, 정적 상태일 땐 5초)
  const hasActive = jobs.some(j => ['queued', 'classifying', 'extracting'].includes(j.status));
  scheduleNextPoll(hasActive ? 2000 : 5000);
}

function renderJob(card, job) {
  // 상태 뱃지
  const badge = $('.status-badge', card);
  if (badge) {
    badge.className = 'status-badge ' + job.status;
    const statusText = $('.status-text', badge);
    if (statusText) {
      statusText.textContent = STATUS_LABEL[job.status] || job.status;
    }
  }

  // 작업 ID 및 파일 수
  const idVal = $('.job-id-val', card);
  if (idVal) idVal.textContent = `#${job.id}`;

  const fileNum = $('.job-file-num', card);
  if (fileNum) fileNum.textContent = job.files?.length ?? 0;

  // 생성 시각
  const timeEl = $('.job-time', card);
  if (timeEl) {
    timeEl.textContent = formatTime(job.created_at);
    timeEl.title = `접수 시각: ${job.created_at?.replace('T', ' ') ?? ''}`;
  }

  // 진행 상태 표시
  const prog = $('.job-progress', card);
  const active = ['queued', 'classifying', 'extracting'].includes(job.status);
  if (prog) {
    prog.classList.toggle('hidden', !active && job.status !== 'done');
    prog.classList.toggle('done', job.status === 'done');

    const spinner = $('.spinner', prog);
    if (spinner) spinner.style.display = active ? '' : 'none';

    const progText = $('.progress-text', prog);
    if (progText) {
      if (job.status === 'done') {
        progText.textContent = `완료 · 청구 ${job.claims?.length ?? 0}건 정리됨`;
      } else {
        progText.textContent = `${STATUS_LABEL[job.status] || job.status} — ${job.progress || '진행 중'}`;
      }
    }
  }

  // 에러 박스
  const errorEl = $('.job-error', card);
  if (errorEl) {
    const errorMsg = $('.error-msg', errorEl);
    if (job.error) {
      errorEl.classList.add('active');
      if (errorMsg) errorMsg.textContent = job.error;
    } else {
      errorEl.classList.remove('active');
      if (errorMsg) errorMsg.textContent = '';
    }
  }

  // 업로드된 원본 서류 사진 썸네일 스트립
  const filesStrip = $('.job-files-strip', card);
  if (filesStrip) {
    const files = job.files || [];
    // 썸네일이 변경된 경우에만 다시 렌더링
    if (filesStrip.dataset.renderedFiles !== String(files.length)) {
      filesStrip.dataset.renderedFiles = String(files.length);
      filesStrip.innerHTML = '';
      files.forEach((f, idx) => {
        const thumb = document.createElement('div');
        thumb.className = 'thumb-item';
        thumb.title = `${f.original || f.saved} (${idx + 1}/${files.length}장) - 클릭하여 크게 보기 (←/→ 키 탐색)`;
        const imgSrc = `/api/images/${job.id}/${f.saved}`;
        thumb.innerHTML = `
          <img src="${imgSrc}" alt="${f.original || f.saved}" loading="lazy" />
          <span class="thumb-tooltip">${f.original || f.saved}</span>
        `;
        thumb.addEventListener('click', (e) => {
          e.stopPropagation();
          const gallery = files.map(item => ({
            src: `/api/images/${job.id}/${item.saved}`,
            filename: item.original || item.saved,
            downloadName: item.original || item.saved,
          }));
          openImageGallery(gallery, idx);
        });
        filesStrip.appendChild(thumb);
      });
    }
  }

  // 분류된 청구 건 목록
  const claimsWrap = $('.claims-wrap', card);
  const claimsCount = $('.claims-count', card);
  if (claimsCount) {
    claimsCount.textContent = `${job.claims?.length ?? 0}건`;
  }

  const claimsEl = $('.claims', card);
  if (claimsEl) {
    claimsEl.innerHTML = '';
    const tpl = $('#claim-tpl');
    for (const c of job.claims || []) {
      const el = tpl.content.cloneNode(true).querySelector('.claim');
      const isInj = c.claim_type === '상해';
      el.className = 'claim ' + (isInj ? 'claim-상해' : 'claim-질병');

      const typeEl = $('.type', el);
      if (typeEl) typeEl.textContent = c.claim_type || '질병';

      const hospEl = $('.hosp', el);
      if (hospEl) hospEl.textContent = c.hospitalization || '통원';

      const patientEl = $('.claim-patient', el);
      if (patientEl) patientEl.textContent = c.patient || '알수없음';

      const dateEl = $('.claim-date-text', el);
      if (dateEl) dateEl.textContent = c.date || '-';

      const diagEl = $('.claim-diagnosis', el);
      if (diagEl) diagEl.innerHTML = renderDiagnosis(c.diagnosis);

      // 청구 디렉터리에 변환되어 저장된 이미지 썸네일 스트립
      const claimImages = c.images || [];
      const imagesStrip = $('.claim-images-strip', el);
      const imagesWrap = $('.claim-images-wrap', el);
      if (imagesStrip && claimImages.length > 0) {
        imagesStrip.innerHTML = '';
        claimImages.forEach((imgName, imgIdx) => {
          const cThumb = document.createElement('div');
          cThumb.className = 'claim-thumb';
          cThumb.title = `${imgName} (${imgIdx + 1}/${claimImages.length}장) - 클릭하여 크게 보기 (←/→ 키 탐색)`;
          const imgSrc = `/api/claims/${encodeURIComponent(c.dir)}/${encodeURIComponent(imgName)}`;
          cThumb.innerHTML = `
            <img src="${imgSrc}" alt="${imgName}" loading="lazy" />
            <span class="claim-thumb-badge">${imgIdx + 1}</span>
          `;
          cThumb.addEventListener('click', (e) => {
            e.stopPropagation();
            const gallery = claimImages.map(name => ({
              src: `/api/claims/${encodeURIComponent(c.dir)}/${encodeURIComponent(name)}`,
              filename: `${c.dir} / ${name}`,
              downloadName: name,
            }));
            openImageGallery(gallery, imgIdx);
          });
          imagesStrip.appendChild(cThumb);
        });
      } else if (imagesWrap) {
        imagesWrap.style.display = 'none';
      }

      const dirCode = $('.claim-dir', el);
      const fullDir = 'data/claims/' + c.dir;
      if (dirCode) {
        dirCode.textContent = fullDir;
        dirCode.title = fullDir;
      }

      const copyBtn = $('.btn-copy-dir', el);
      if (copyBtn) {
        copyBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          copyToClipboard(fullDir, copyBtn);
        });
      }

      claimsEl.appendChild(el);
    }
  }
}

// 최초 실행
refresh();

