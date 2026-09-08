const $ = (s, el = document) => el.querySelector(s);
const jobsEl = $('#jobs');
const emptyEl = $('#empty');
const STATUS_LABEL = {
  queued: '대기중',
  classifying: '서류 구분중',
  extracting: '정보 추출중',
  done: '완료',
  failed: '실패',
};
let knownJobs = new Set();

// ---------- 업로드 ----------
$('#addBtn').addEventListener('click', () => $('#fileInput').click());
$('#fileInput').addEventListener('change', (e) => upload(e.target.files));

const dz = $('#dropzone');
['dragenter', 'dragover'].forEach(ev =>
  dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('drag'); }));
['dragleave', 'drop'].forEach(ev =>
  dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('drag'); }));
dz.addEventListener('drop', e => upload(e.dataTransfer.files));

async function upload(fileList) {
  const files = [...fileList].filter(f => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|heif|bmp|tiff?)$/i.test(f.name));
  if (!files.length) { alert('이미지 파일을 드래그하거나 선택해 주세요.'); return; }
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  try {
    const r = await fetch('/api/jobs', { method: 'POST', body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    knownJobs.add(data.job_id);
    refresh();
  } catch (err) {
    alert('업로드 실패: ' + err.message);
  } finally {
    $('#fileInput').value = '';
  }
}

// ---------- 상태 폴링 ----------
async function refresh() {
  let jobs = [];
  try {
    const r = await fetch('/api/jobs');
    jobs = (await r.json()).jobs || [];
  } catch { return; }

  emptyEl.hidden = jobs.length > 0;
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
  // 삭제된 잡 정리 (현재는 삭제 API 없으므로 무시)
}

function renderJob(card, job) {
  $('.status-badge', card).className = 'status-badge ' + job.status;
  $('.job-name', card).textContent = `작업 ${job.id} · 사진 ${job.files.length}장`;
  $('.job-time', card).textContent = job.created_at?.replace('T', ' ') ?? '';

  const prog = $('.job-progress', card);
  const active = ['queued', 'classifying', 'extracting'].includes(job.status);
  prog.classList.toggle('hidden', !active && job.status !== 'done');
  prog.classList.toggle('done', job.status === 'done');
  const icon = $('.spinner', prog);
  icon.style.display = active ? '' : 'none';
  $('.progress-text', prog).textContent =
    job.status === 'done' ? `완료 · 청구 ${job.claims.length}건` : `${STATUS_LABEL[job.status] || job.status} — ${job.progress || ''}`;

  $('.job-error', card).textContent = job.error || '';

  const claimsEl = $('.claims', card);
  claimsEl.innerHTML = '';
  const tpl = $('#claim-tpl');
  for (const c of job.claims || []) {
    const el = tpl.content.cloneNode(true).querySelector('.claim');
    el.className = 'claim claim-' + (c.claim_type === '상해' ? '상해' : '질병');
    $('.type', el).textContent = c.claim_type || '-';
    $('.hosp', el).textContent = c.hospitalization || '-';
    $('.claim-patient', el).textContent = c.patient || '알수없음';
    $('.claim-date', el).textContent = c.date || '';
    $('.claim-diagnosis', el).textContent = c.diagnosis || '진단명 없음';
    $('.claim-dir', el).textContent = 'data/claims/' + c.dir;
    claimsEl.appendChild(el);
  }
}

refresh();
setInterval(refresh, 2000);
