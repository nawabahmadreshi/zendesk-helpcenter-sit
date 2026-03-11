document.addEventListener('DOMContentLoaded', restore_options);
document.getElementById('save').addEventListener('click', save_options);

function save_options() {
  const apiUrl = document.getElementById('apiUrl').value.trim().replace(/\/$/, "");
  chrome.storage.sync.set({
    apiUrl: apiUrl || 'http://localhost:8000'
  }, function() {
    const status = document.getElementById('status');
    status.textContent = 'Options saved.';
    setTimeout(function() {
      status.textContent = '';
    }, 1500);
  });
}

function restore_options() {
  chrome.storage.sync.get({
    apiUrl: 'http://localhost:8000'
  }, function(items) {
    document.getElementById('apiUrl').value = items.apiUrl;
  });
}
