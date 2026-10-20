import {api, nav, esc, message} from './admin.js';

document.querySelector('#nav').innerHTML = nav('settings');
let data;
const types = {
  allow_extended_load_when_repeating_failed_course: 'checkbox',
  allow_final_two_semester_graduation_load: 'checkbox',
  allow_training_postponement: 'checkbox',
  auto_extend_horizon: 'checkbox',
  diagnostic_logging: 'checkbox',
  allow_cross_track_shared_sections: 'checkbox',
  prefer_own_track_sections: 'checkbox',
  future_offering_assumption: 'text',
};

async function load() {
  data = await api('/api/admin/settings');
  document.querySelector('#settings').innerHTML = Object.entries(data.values).map(([key, value]) => {
    const type = types[key] || 'number';
    const checked = type === 'checkbox' && value ? 'checked' : '';
    const assumption = data.metadata[key]?.unverified_assumption ? ' · Unverified assumption' : '';
    return `<label class="setting"><span><strong>${esc(key.replaceAll('_', ' '))}</strong><small>${esc(data.metadata[key]?.description)}${assumption}</small></span><input name="${esc(key)}" type="${type}" ${checked} value="${esc(value ?? '')}" step="any"></label>`;
  }).join('');
}

document.querySelector('#form').onsubmit = async event => {
  event.preventDefault();
  const values = {};
  for (const element of event.target.elements) {
    if (element.name) values[element.name] = element.type === 'checkbox' ? element.checked : element.type === 'number' ? (element.value === '' ? null : +element.value) : element.value;
  }
  try {
    await api('/api/admin/settings', {method: 'PUT', body: JSON.stringify({values})});
    message('Settings saved. They will affect the next planning run.');
    await load();
  } catch (error) { message(error.message, true); }
};

document.querySelector('#reset').onclick = async () => {
  if (confirm('Reset all engine settings to documented defaults?')) {
    await api('/api/admin/settings/reset', {method: 'POST'});
    await load();
    message('Defaults restored.');
  }
};

load().catch(error => message(error.message, true));
