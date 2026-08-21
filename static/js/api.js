/* קריאות לשרת + מעקב אחרי עבודות רקע. */

async function request(method, url, body, isForm = false) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) {
      options.body = body;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
  }
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('לא מחובר');
  }
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!response.ok) {
    throw new Error((data && (data.detail || data.error)) || `שגיאה ${response.status}`);
  }
  return data;
}

export const api = {
  get:   (url)          => request('GET', url),
  post:  (url, body)    => request('POST', url, body ?? {}),
  patch: (url, body)    => request('PATCH', url, body ?? {}),
  del:   (url)          => request('DELETE', url),
  form:  (url, formData)=> request('POST', url, formData, true),
};

/**
 * עוקב אחרי עבודת רקע עד שהיא נגמרת.
 * מנסה זרם חי; אם הוא נופל (פרוקסי, רשת) עובר לבדיקה תקופתית.
 */
export function watchJob(jobId, onUpdate) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let source = null;

    const finish = (snapshot) => {
      if (settled) return;
      settled = true;
      if (source) source.close();
      if (snapshot.status === 'done') resolve(snapshot);
      else reject(new Error(snapshot.error || 'העבודה נכשלה'));
    };

    const handle = (snapshot) => {
      onUpdate?.(snapshot);
      if (['done', 'error', 'cancelled'].includes(snapshot.status)) finish(snapshot);
    };

    const poll = async () => {
      while (!settled) {
        try {
          const snapshot = await api.get(`/api/jobs/${jobId}`);
          handle(snapshot);
        } catch (error) {
          if (!settled) { settled = true; reject(error); }
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    };

    try {
      source = new EventSource(`/api/jobs/${jobId}/stream`);
      source.onmessage = (event) => handle(JSON.parse(event.data));
      source.onerror = () => {
        if (settled) return;
        source.close();
        source = null;
        poll();
      };
    } catch {
      poll();
    }
  });
}
