/**
 * 보험 청구 서류 정리 - Frontend Application
 */

const $ = (s, el = document) => el.querySelector(s);
const jobsEl = $('#jobs');
const emptyEl = $('#empty');
const jobsCountBadge = $('#jobsCountBadge');
const loadError = $('#loadError');
const retryBtn = $('#retryBtn');
const appAnnouncements = $('#appAnnouncements');
const fileInput = $('#fileInput');
const dz = $('#dropzone');
const uploadModal = $('#uploadModal');
const uploadModalClose = $('#uploadModalClose');
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
let refreshInFlight = false;
let uploadInFlight = false;
let imageDialogReturnFocus = null;

function announce(message) {
  if (appAnnouncements) appAnnouncements.textContent = message;
}

// ---------- 테마 전환 (Light / Dark / Auto) 시스템 ----------
const THEME_KEY = 'claim_theme_pref';

function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredTheme() {
  return localStorage.getItem(THEME_KEY) || 'auto';
}

function applyTheme(preference, announce = false) {
  const effectiveTheme = preference === 'auto' ? getSystemTheme() : preference;
  document.documentElement.setAttribute('data-theme', effectiveTheme);
  document.documentElement.setAttribute('data-theme-pref', preference);

  const themeBtns = document.querySelectorAll('.theme-btn');
  themeBtns.forEach(btn => {
    const val = btn.getAttribute('data-theme-val');
    const isActive = val === preference;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    btn.tabIndex = isActive ? 0 : -1;
  });

  if (announce) {
    const labelMap = {
      light: '라이트 (병원 데이 클리닉) 테마로 전환되었습니다.',
      dark: '다크 (메디컬 워크스테이션) 테마로 전환되었습니다.',
      auto: `오토 (시스템 설정: ${effectiveTheme === 'dark' ? '다크' : '라이트'}) 모드로 설정되었습니다.`
    };
    showToast(labelMap[preference] || `${preference} 테마 적용`, 'info', 2200);
  }
}

function initTheme() {
  const currentPref = getStoredTheme();
  applyTheme(currentPref, false);

  const switcher = document.querySelector('.theme-switcher');
  if (switcher) {
    switcher.addEventListener('click', (e) => {
      const btn = e.target.closest('.theme-btn');
      if (!btn) return;
      const targetVal = btn.getAttribute('data-theme-val');
      if (!targetVal) return;

      localStorage.setItem(THEME_KEY, targetVal);
      applyTheme(targetVal, true);
    });

    // 키보드 좌우 방향키로 테마 전환 지원
    switcher.addEventListener('keydown', (e) => {
      const btns = Array.from(switcher.querySelectorAll('.theme-btn'));
      const activeIdx = btns.findIndex(b => b.classList.contains('active'));
      if (activeIdx === -1) return;

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        const nextIdx = (activeIdx + 1) % btns.length;
        btns[nextIdx].click();
        btns[nextIdx].focus();
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prevIdx = (activeIdx - 1 + btns.length) % btns.length;
        btns[prevIdx].click();
        btns[prevIdx].focus();
      }
    });
  }

  // OS 다크모드 변경 감지 (Auto 모드일 때 실시간 반영)
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  const handleMediaChange = () => {
    if (getStoredTheme() === 'auto') {
      applyTheme('auto', false);
    }
  };
  if (mediaQuery.addEventListener) {
    mediaQuery.addEventListener('change', handleMediaChange);
  } else if (mediaQuery.addListener) {
    mediaQuery.addListener(handleMediaChange);
  }
}

function appendDiagnosis(container, diagText) {
  container.replaceChildren();
  if (!diagText) {
    container.textContent = '진단명 없음';
    return;
  }

  // 형식 예: H368(기타 망막장애), H400(녹내장의증)
  const chipPattern = /([A-Z]\d{2}(?:\.?\d{1,2})?)\(([^)]+)\)/g;
  let match;
  let lastIndex = 0;
  let hasMatch = false;

  const appendText = text => {
    if (!text) return;
    const textEl = document.createElement('span');
    textEl.className = 'diag-text';
    textEl.textContent = text;
    container.appendChild(textEl);
  };

  const appendChip = (code, description) => {
    const chip = document.createElement('span');
    chip.className = 'diag-chip';
    chip.title = `질병분류기호 ${code}: ${description}`;

    const label = document.createElement('span');
    label.className = 'diag-chip-badge';
    label.textContent = 'KCD';
    const codeEl = document.createElement('span');
    codeEl.className = 'diag-chip-code';
    codeEl.textContent = code;
    const descriptionEl = document.createElement('span');
    descriptionEl.className = 'diag-chip-name';
    descriptionEl.textContent = description;

    chip.append(label, codeEl, descriptionEl);
    container.appendChild(chip);
  };

  while ((match = chipPattern.exec(diagText)) !== null) {
    hasMatch = true;
    if (match.index > lastIndex) {
      const textBefore = diagText.slice(lastIndex, match.index).trim().replace(/^[,;\s]+|[,;\s]+$/g, '');
      appendText(textBefore);
    }
    const code = match[1];
    const desc = match[2];
    appendChip(code, desc);
    lastIndex = chipPattern.lastIndex;
  }

  if (hasMatch) {
    if (lastIndex < diagText.length) {
      const textAfter = diagText.slice(lastIndex).trim().replace(/^[,;\s]+|[,;\s]+$/g, '');
      appendText(textAfter);
    }
    return;
  }

  container.textContent = diagText;
}

function formatClaimDate(claim) {
  const start = claim.treatment_start || claim.date;
  const end = claim.treatment_end;
  if (!start) return '-';
  return end && end !== start ? `${start}~${end}` : start;
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

  toast.innerHTML = iconSvg;
  const messageEl = document.createElement('span');
  messageEl.textContent = message;
  toast.appendChild(messageEl);
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
  modalDownload.download = item.downloadName || item.filename || 'document.jpg';

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

function openImageGallery(items, initialIndex = 0, trigger = document.activeElement) {
  if (!imageModal || !items || !items.length) return;
  currentGallery = items;
  currentGalleryIndex = Math.max(0, Math.min(initialIndex, items.length - 1));
  imageDialogReturnFocus = trigger instanceof HTMLElement ? trigger : null;
  updateModalView();
  imageModal.showModal();
  modalClose?.focus();
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
imageModal?.addEventListener('close', () => {
  imageDialogReturnFocus?.focus();
  imageDialogReturnFocus = null;
});
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
function openUploadModal() {
  if (!uploadInFlight && !uploadModal?.open) uploadModal?.showModal();
}

$('#addBtn')?.addEventListener('click', openUploadModal);
$('#emptyUploadBtn')?.addEventListener('click', openUploadModal);
uploadModalClose?.addEventListener('click', () => uploadModal.close());
uploadModal?.addEventListener('click', (e) => {
  if (e.target === uploadModal) uploadModal.close();
});
fileInput?.addEventListener('change', (e) => upload(e.target.files));

if (dz) {
  ['dragenter', 'dragover'].forEach(ev =>
    dz.addEventListener(ev, e => {
      if (uploadInFlight) return;
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
  dz.addEventListener('drop', e => {
    if (uploadInFlight) return;
    upload(e.dataTransfer.files);
  });
  dz.addEventListener('click', (e) => {
    if (uploadInFlight) return;
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {
      fileInput.click();
    }
  });
  dz.addEventListener('keydown', (e) => {
    if (uploadInFlight) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });
}

// 단축키 (Cmd+O / Ctrl+O)
window.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'o') {
    e.preventDefault();
    openUploadModal();
  }
});

// 새로고침 버튼
$('#refreshBtn')?.addEventListener('click', () => {
  refresh();
  showToast('작업 내역을 새로고침합니다.', 'info', 1500);
});
retryBtn?.addEventListener('click', refresh);

function setUploadInFlight(isBusy) {
  uploadInFlight = isBusy;
  [$('#addBtn'), $('#emptyUploadBtn')].filter(Boolean).forEach(button => {
    button.disabled = isBusy;
  });
  if (dz) {
    dz.classList.toggle('is-disabled', isBusy);
    dz.setAttribute('aria-disabled', String(isBusy));
  }
}

async function responseError(response) {
  try {
    const payload = await response.json();
    return payload.error || payload.detail || response.statusText;
  } catch {
    return response.statusText || '서버가 요청을 처리하지 못했습니다.';
  }
}

async function upload(fileList) {
  if (uploadInFlight) return;
  const files = [...fileList].filter(f =>
    f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|heif|bmp|tiff?)$/i.test(f.name)
  );

  if (!files.length) {
    showToast('이미지 파일(JPG, PNG, HEIC 등)을 선택해 주세요.', 'error');
    return;
  }

  if (uploadModal?.open) uploadModal.close();
  showToast(`${files.length}장의 서류 사진 업로드를 시작합니다...`, 'info', 2500);

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  setUploadInFlight(true);

  try {
    const r = await fetch('/api/jobs', { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await responseError(r));
    showToast('서류가 등록되어 비전 AI 분석이 시작되었습니다.', 'success');
    refresh();
  } catch (err) {
    showToast('업로드 실패: ' + err.message, 'error', 4500);
  } finally {
    fileInput.value = '';
    setUploadInFlight(false);
  }
}

// ---------- 상태 폴링 ----------
function scheduleNextPoll(ms) {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  pollTimer = setTimeout(refresh, ms);
}

function setLoadError(isVisible) {
  if (loadError) loadError.hidden = !isVisible;
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;

  let jobs = [];
  let nextPollDelay = 15000;
  try {
    const r = await fetch('/api/jobs', { cache: 'no-store' });
    if (!r.ok) throw new Error(await responseError(r));
    const payload = await r.json();
    jobs = Array.isArray(payload.jobs) ? payload.jobs : [];

    setLoadError(false);

    if (emptyEl) {
      emptyEl.hidden = jobs.length > 0;
    }
    if (jobsCountBadge) {
      jobsCountBadge.textContent = `${jobs.length}개 작업`;
    }

    const tpl = $('#job-tpl');

    const jobIds = new Set(jobs.map(job => String(job.id)));
    Array.from(jobsEl.children).forEach(card => {
      if (!jobIds.has(card.dataset.job)) card.remove();
    });

    // 이미 렌더된 카드 갱신, 없으면 추가
    for (const job of jobs) {
      let card = Array.from(jobsEl.children).find(item => item.dataset.job === String(job.id));
      if (!card) {
        card = tpl.content.cloneNode(true).querySelector('article');
        card.dataset.job = String(job.id);
        jobsEl.prepend(card);
      }
      renderJob(card, job);
    }

    // 진행 중에는 빠르게, 완료 목록만 있을 때는 가볍게 확인한다.
    const hasActive = jobs.some(job => ['queued', 'classifying', 'extracting'].includes(job.status));
    nextPollDelay = hasActive ? 2000 : 30000;
  } catch {
    const wasHidden = loadError?.hidden;
    setLoadError(true);
    if (wasHidden) announce('작업 내역을 불러오지 못했습니다. 다시 시도할 수 있습니다.');
  } finally {
    refreshInFlight = false;
    scheduleNextPoll(nextPollDelay);
  }
}

function jobImageUrl(jobId, filename) {
  return `/api/images/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`;
}

function createDocumentThumbnail({ className, imageSrc, name, index, total, badge, gallery }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.title = `${name} (${index + 1}/${total}장) - 크게 보기`;
  button.setAttribute('aria-label', `${name}, ${index + 1}/${total}번째 서류 사진 크게 보기`);
  button.setAttribute('aria-haspopup', 'dialog');

  const image = document.createElement('img');
  image.src = imageSrc;
  image.alt = '';
  image.loading = 'lazy';
  image.decoding = 'async';
  button.appendChild(image);

  if (badge !== undefined) {
    const badgeEl = document.createElement('span');
    badgeEl.className = 'claim-thumb-badge';
    badgeEl.textContent = String(badge);
    badgeEl.setAttribute('aria-hidden', 'true');
    button.appendChild(badgeEl);
  } else {
    const tooltip = document.createElement('span');
    tooltip.className = 'thumb-tooltip';
    tooltip.textContent = name;
    tooltip.setAttribute('aria-hidden', 'true');
    button.appendChild(tooltip);
  }

  button.addEventListener('click', () => openImageGallery(gallery, index, button));
  return button;
}

function renderJob(card, job) {
  const status = STATUS_LABEL[job.status] || job.status || '상태 확인 중';
  const active = ['queued', 'classifying', 'extracting'].includes(job.status);
  card.dataset.status = job.status || '';
  card.setAttribute('aria-busy', String(active));

  // 상태 뱃지
  const badge = $('.status-badge', card);
  if (badge) {
    badge.className = 'status-badge ' + job.status;
    const statusText = $('.status-text', badge);
    if (statusText) {
      statusText.textContent = status;
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
        progText.textContent = `${status} — ${job.progress || '진행 중'}`;
      }
      prog.setAttribute('aria-label', progText.textContent);
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
    const filesSignature = JSON.stringify(files.map(file => [file.saved, file.original]));
    if (filesStrip.dataset.signature !== filesSignature) {
      filesStrip.dataset.signature = filesSignature;
      filesStrip.replaceChildren();
      const gallery = files.map(file => ({
        src: jobImageUrl(job.id, file.saved),
        filename: file.original || file.saved,
        downloadName: file.original || file.saved,
      }));
      files.forEach((f, idx) => {
        filesStrip.appendChild(createDocumentThumbnail({
          className: 'thumb-item',
          imageSrc: jobImageUrl(job.id, f.saved),
          name: f.original || f.saved,
          index: idx,
          total: files.length,
          gallery,
        }));
      });
    }
  }

  // 분류된 청구 건 목록
  const claimsCount = $('.claims-count', card);
  if (claimsCount) {
    claimsCount.textContent = `${job.claims?.length ?? 0}건`;
  }

  const claimsEl = $('.claims', card);
  if (claimsEl) {
    const claims = job.claims || [];
    const claimsSignature = JSON.stringify(claims);
    if (claimsEl.dataset.signature === claimsSignature) return;
    claimsEl.dataset.signature = claimsSignature;
    claimsEl.replaceChildren();
    const tpl = $('#claim-tpl');
    for (const c of claims) {
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
      if (dateEl) dateEl.textContent = formatClaimDate(c);

      const diagEl = $('.claim-diagnosis', el);
      if (diagEl) appendDiagnosis(diagEl, c.diagnosis);

      // 청구 디렉터리에 변환되어 저장된 이미지 썸네일 스트립
      const claimImages = c.images || [];
      const imagesStrip = $('.claim-images-strip', el);
      const imagesWrap = $('.claim-images-wrap', el);
      if (imagesStrip && claimImages.length > 0) {
        imagesStrip.replaceChildren();
        const gallery = claimImages.map(name => ({
          src: `/api/claims/${encodeURIComponent(c.dir)}/${encodeURIComponent(name)}`,
          filename: `${c.dir} / ${name}`,
          downloadName: name,
        }));
        claimImages.forEach((imgName, imgIdx) => {
          imagesStrip.appendChild(createDocumentThumbnail({
            className: 'claim-thumb',
            imageSrc: `/api/claims/${encodeURIComponent(c.dir)}/${encodeURIComponent(imgName)}`,
            name: imgName,
            index: imgIdx,
            total: claimImages.length,
            badge: imgIdx + 1,
            gallery,
          }));
        });
      } else if (imagesWrap) {
        imagesWrap.style.display = 'none';
      }

      const downloadBtn = $('.btn-download-claim', el);
      if (downloadBtn) {
        downloadBtn.href = `/api/claims/${encodeURIComponent(c.dir)}/download`;
        downloadBtn.download = `${c.dir}.zip`;
      }

      claimsEl.appendChild(el);
    }
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
    return;
  }
  refresh();
});

// 최초 실행
initTheme();
refresh();
