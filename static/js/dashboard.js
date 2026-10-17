let REFRESH_TIMER = null;
let CURRENT_EDIT_JOB = null;
let ALERT_RETURN_FOCUS = null;
let selectedPlan = 'normal';

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}
function showAlert(message, title = 'Notice') {
  const modal = document.getElementById('alert-modal');
  if (!modal) { window.alert(message); return; }
  ALERT_RETURN_FOCUS = document.activeElement;
  document.getElementById('alert-title').textContent = title;
  document.getElementById('alert-message').textContent = message;
  modal.classList.remove('hidden');
  modal.querySelector('button').focus();
}
function closeAlert() {
  document.getElementById('alert-modal')?.classList.add('hidden');
  ALERT_RETURN_FOCUS?.focus?.();
}
function showComingSoon(feature) {
  showAlert(`${feature} is still in development — coming soon. Standard access is free for now.`, 'Coming soon');
}
function selectPlan(plan) {
  if (plan === 'premium') {
    showComingSoon('Premium service');
    return;
  }
  selectedPlan = 'normal';
  document.getElementById('plan-normal').classList.add('selected');
  document.getElementById('plan-premium').classList.remove('selected');
}
function updateRegionPreview() {
  const selector = document.getElementById('region');
  document.getElementById('region-code').textContent = selector.value;
  document.getElementById('region-name').textContent = 'Region selected';
}
function navigateTo(sectionId) {
  const target = document.getElementById(sectionId);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.target === sectionId));
}
function openAccount() {
  document.getElementById('account-modal').classList.remove('hidden');
  document.getElementById('account-modal').querySelector('.modal-close').focus();
}
function closeAccount() { document.getElementById('account-modal').classList.add('hidden'); }
async function loadMe() {
  try {
    const me = await api('/api/me');
    const username = me.username || 'Wargood';
    document.getElementById('who').textContent = username;
    document.getElementById('profile-initial').textContent = username.slice(0, 1).toUpperCase();
  } catch (error) { location.href = '/login'; }
}
async function doLogout() {
  try { await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }); }
  finally { location.href = '/login'; }
}
function openConfirm() {
  const clanId = document.getElementById('clan_id').value.trim();
  if (!/^\d+$/.test(clanId)) {
    showAlert('Enter a valid Clan ID using numbers only.', 'Invalid Clan ID');
    document.getElementById('clan_id').focus();
    return;
  }
  const selector = document.getElementById('region');
  document.getElementById('confirm-clan').textContent = clanId;
  document.getElementById('confirm-region').textContent = selector.options[selector.selectedIndex].text;
  document.getElementById('accept-terms').checked = false;
  document.getElementById('confirm-modal').classList.remove('hidden');
  document.getElementById('confirm-send-btn').focus();
}
function closeConfirm() { document.getElementById('confirm-modal').classList.add('hidden'); }
async function confirmCreateJob() {
  const clan_id = document.getElementById('confirm-clan').textContent.trim();
  const region = document.getElementById('region').value;
  if (!document.getElementById('accept-terms').checked) {
    showAlert('Please confirm the team details before continuing.', 'Confirmation required');
    return;
  }
  const button = document.getElementById('confirm-send-btn');
  button.disabled = true;
  button.textContent = 'Creating team…';
  try {
    await api('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clan_id, region }) });
    closeConfirm();
    document.getElementById('launch-msg').textContent = 'Your team request has been received. Track its progress in Activity.';
    document.getElementById('launch-msg').className = 'msg ok';
    document.getElementById('clan_id').value = '';
    await loadJobs();
    navigateTo('activity');
  } catch (error) {
    closeConfirm();
    document.getElementById('launch-msg').textContent = error.message;
    document.getElementById('launch-msg').className = 'msg err';
    showAlert(error.message || 'A bot or server error occurred. Please try again.', 'Could not create team');
  } finally {
    button.disabled = false;
    button.innerHTML = 'Create Team <span>✓</span>';
  }
}
async function changePassword(event) {
  event.preventDefault();
  const message = document.getElementById('password-msg');
  message.textContent = '';
  message.className = 'msg';
  const current_password = document.getElementById('current-password').value;
  const new_password = document.getElementById('new-password').value;
  const confirm_password = document.getElementById('confirm-password').value;
  if (new_password !== confirm_password) {
    message.textContent = 'The password confirmation does not match.';
    message.classList.add('err');
    return false;
  }
  try {
    const data = await api('/api/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password, new_password, confirm_password }) });
    message.textContent = data.message || 'Password changed successfully.';
    message.classList.add('ok');
    document.getElementById('password-form').reset();
  } catch (error) {
    message.textContent = error.message;
    message.classList.add('err');
  }
  return false;
}
function badgeClass(status) {
  if (status === 'running') return 'running';
  if (status === 'starting') return 'starting';
  if (status === 'stopping') return 'stopping';
  return 'stopped';
}
function botStatusClass(status) {
  return ['idle', 'playing', 'in_clan', 'invite_failed', 'searching'].includes(status) ? status : 'idle';
}
function readableStatus(status) {
  return ({ running: 'ONLINE', starting: 'SEARCHING', stopping: 'STOPPING', stopped: 'OFFLINE', idle: 'IDLE', playing: 'PLAYING', in_clan: 'IN CLAN', invite_failed: 'FAILED', searching: 'SEARCHING' })[status] || String(status || 'OFFLINE').toUpperCase();
}
async function loadJobs() {
  const list = document.getElementById('jobs-list');
  try {
    const jobs = await api('/api/jobs');
    const count = jobs.length;
    document.getElementById('team-count').textContent = count;
    document.getElementById('activity-count').textContent = count;
    document.getElementById('slots-progress').style.width = `${Math.min(count * 33, 100)}%`;
    document.getElementById('slots-caption').textContent = count ? `${count} team${count === 1 ? '' : 's'} in your workspace.` : 'Your workspace is ready.';
    if (!count) {
      list.innerHTML = '<div class="empty">No teams yet. Enter your Clan ID above to create the first one.</div>';
      return;
    }
    list.innerHTML = jobs.map(job => `
      <article class="job-card" data-id="${escapeHtml(job.id)}">
        <div class="job-head"><div><div class="job-clan">Clan ${escapeHtml(job.clan_id)} <span class="job-region">· ${escapeHtml(job.region)}</span></div><div class="job-meta">Team ID: ${escapeHtml(job.id)}<br>Region: ${escapeHtml(job.region)}</div></div><span class="badge ${badgeClass(job.status)}">${readableStatus(job.status)}${job.stage ? ' · ' + escapeHtml(job.stage) : ''}</span></div>
        <div class="job-actions"><button class="btn btn-create sm" onclick="startJob('${escapeHtml(job.id)}')">▶ Start</button><button class="btn btn-outline sm" onclick="stopJob('${escapeHtml(job.id)}')">Ⅱ Stop</button><button class="btn btn-outline sm" onclick="editJob('${escapeHtml(job.id)}')">Bot Details</button><button class="btn danger sm" onclick="deleteJob('${escapeHtml(job.id)}')">Delete</button></div>
        <div class="bot-list">${(job.bots || []).map(bot => `<div class="bot-row"><span><strong>${escapeHtml(bot.name || 'Bot Account')}</strong><br><span class="bot-uid">UID: ${escapeHtml(bot.uid || '-')}</span></span><span class="bot-status ${botStatusClass(bot.status)}">${readableStatus(bot.status)}</span></div><div class="bot-info-grid"><div class="bot-info-cell"><small>Account ID</small><strong>${escapeHtml(bot.account_id || '-')}</strong></div><div class="bot-info-cell"><small>Level</small><strong>${escapeHtml(bot.level ?? '-')}</strong></div><div class="bot-info-cell"><small>XP</small><strong>${escapeHtml(bot.xp ?? '-')}</strong></div><div class="bot-info-cell"><small>Games</small><strong>${escapeHtml(bot.games ?? '-')}</strong></div></div>`).join('') || '<div class="bot-row"><span><strong>No bots linked yet</strong><br><span class="bot-uid">Bot account details will appear here when available.</span></span><span class="badge badge-online">READY</span></div>'}</div>
      </article>`).join('');
  } catch (error) {
    list.innerHTML = `<div class="empty">Unable to load teams: ${escapeHtml(error.message)}</div>`;
  }
}
async function startJob(id) {
  try { await api('/api/jobs/' + encodeURIComponent(id) + '/start', { method: 'POST' }); await loadJobs(); }
  catch (error) { showAlert(error.message, 'Could not start team'); }
}
async function stopJob(id) {
  try { await api('/api/jobs/' + encodeURIComponent(id) + '/stop', { method: 'POST' }); await loadJobs(); }
  catch (error) { showAlert(error.message, 'Could not stop team'); }
}
async function deleteJob(id) {
  if (!window.confirm('Delete this team?')) return;
  try { await api('/api/jobs/' + encodeURIComponent(id), { method: 'DELETE' }); await loadJobs(); }
  catch (error) { showAlert(error.message, 'Could not delete team'); }
}
async function editJob(id) {
  try {
    const data = await api('/api/jobs/' + encodeURIComponent(id) + '/edit', { method: 'POST' });
    CURRENT_EDIT_JOB = id;
    document.getElementById('edit-title').textContent = `Clan ${data.clan_id} [${data.region}] — ${readableStatus(data.status)}`;
    document.getElementById('edit-body').innerHTML = `<p class="job-meta">Job ID: ${escapeHtml(data.job_id)} · Stage: ${escapeHtml(data.stage || '-')}</p><h4>BOTS</h4>${data.bots.length ? data.bots.map(bot => `<div class="bot-row"><span><b>${escapeHtml(bot.name || '-')}</b><br><span class="bot-uid">UID: ${escapeHtml(bot.uid || '-')} · ACC: ${escapeHtml(bot.account_id || '-')}<br>XP: ${escapeHtml(bot.xp ?? '-')} · Level: ${escapeHtml(bot.level ?? '-')} · Games: ${escapeHtml(bot.games ?? '-')}</span></span><span class="bot-status ${botStatusClass(bot.status)}">${readableStatus(bot.status)}</span></div>`).join('') : '<p class="empty">No bots yet.</p>'}`;
    document.getElementById('edit-modal').classList.remove('hidden');
  } catch (error) { showAlert(error.message, 'Could not open team'); }
}
function closeEdit() { document.getElementById('edit-modal').classList.add('hidden'); CURRENT_EDIT_JOB = null; }
for (const [id, close] of [['edit-modal', closeEdit], ['confirm-modal', closeConfirm], ['alert-modal', closeAlert], ['account-modal', closeAccount]]) {
  document.getElementById(id).addEventListener('click', event => { if (event.target.id === id) close(); });
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') { closeConfirm(); closeEdit(); closeAlert(); closeAccount(); }
});
(async () => {
  updateRegionPreview();
  await loadMe();
  await loadJobs();
  REFRESH_TIMER = setInterval(loadJobs, 5000);
})();
