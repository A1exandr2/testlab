async function api(path, data) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  const options = {credentials: 'same-origin', signal: controller.signal};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf};
    options.body = JSON.stringify(data);
  }
  try {
    const response = await fetch('/api/' + path, options);
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error || 'Не удалось выполнить действие');
      error.status = response.status;
      throw error;
    }
    return body;
  } catch (error) {
    if (!error.status) throw new Error('Нет связи с сервером. Проверьте, что приложение запущено.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
