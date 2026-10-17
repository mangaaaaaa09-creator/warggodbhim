function switchTab(which) {
  const isLogin = which === 'login';
  const loginForm = document.getElementById('form-login');
  const signupForm = document.getElementById('form-signup');
  document.getElementById('tab-login').classList.toggle('active', isLogin);
  document.getElementById('tab-signup').classList.toggle('active', !isLogin);
  loginForm.classList.toggle('hidden', !isLogin);
  signupForm.classList.toggle('hidden', isLogin);
  loginForm.style.display = isLogin ? '' : 'none';
  signupForm.style.display = isLogin ? 'none' : '';
  document.getElementById('auth-heading').textContent = isLogin ? 'Welcome Back' : 'Create Account';
  document.getElementById('auth-subtitle').innerHTML = isLogin
    ? 'Sign in to <b>FFGlory</b> panel'
    : 'Join the <b>FFGlory</b> community';
  const loginError = document.getElementById('login-err');
  const signupError = document.getElementById('signup-err');
  const signupSuccess = document.getElementById('signup-ok');
  if (loginError) loginError.textContent = '';
  if (signupError) signupError.textContent = '';
  if (signupSuccess) signupSuccess.textContent = '';
}

async function postAuth(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(payload)
  });
  let data;
  try { data = await response.json(); }
  catch (_) { throw new Error('Server returned an invalid response. Please try again.'); }
  if (!response.ok || !data || data.ok !== true) {
    throw new Error((data && data.error) || 'Request failed. Please try again.');
  }
  return data;
}

function setBusy(form, busy, text) {
  const button = form.querySelector('button[type="submit"]');
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.disabled = true;
    button.textContent = text;
  } else {
    button.disabled = false;
    if (button.dataset.originalText) button.textContent = button.dataset.originalText;
    delete button.dataset.originalText;
  }
}

async function doLogin(event) {
  event.preventDefault();
  const form = document.getElementById('form-login');
  const error = document.getElementById('login-err');
  error.textContent = '';
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  setBusy(form, true, 'Signing in…');
  try {
    await postAuth('/api/login', { username, password });
    window.location.assign('/dashboard');
  } catch (exception) {
    error.textContent = exception.message || 'Sign in failed. Please check your details.';
  } finally {
    setBusy(form, false);
  }
  return false;
}

async function doRegister(event) {
  event.preventDefault();
  const form = document.getElementById('form-signup');
  const error = document.getElementById('signup-err');
  const success = document.getElementById('signup-ok');
  error.textContent = '';
  success.textContent = '';
  const username = document.getElementById('signup-username').value.trim();
  const password = document.getElementById('signup-password').value;
  const confirmation = document.getElementById('signup-confirm').value;
  if (username.length < 3) { error.textContent = 'Username must be at least 3 characters.'; return false; }
  if (password.length < 6) { error.textContent = 'Password must be at least 6 characters.'; return false; }
  if (password !== confirmation) { error.textContent = 'The passwords do not match.'; return false; }
  setBusy(form, true, 'Creating account…');
  try {
    await postAuth('/api/register', { username, password });
    success.textContent = 'Account created successfully. Opening your dashboard…';
    window.location.assign('/dashboard');
  } catch (exception) {
    error.textContent = exception.message || 'Registration failed. Please try again.';
  } finally {
    setBusy(form, false);
  }
  return false;
}
