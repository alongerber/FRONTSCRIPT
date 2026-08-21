/* עזרי ממשק — יצירת אלמנטים, הודעות, חלונות, פורמט. */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

export function toast(message, kind = '') {
  const root = document.getElementById('toasts');
  const node = el('div', { class: `toast ${kind}` }, [
    el('div', { style: { flex: '1' }, text: message }),
    el('button', { class: 'toast-x', onClick: () => node.remove(), text: '✕' }),
  ]);
  root.append(node);
  setTimeout(() => node.remove(), kind === 'err' ? 9000 : 4500);
}

export const ok = (m) => toast(m, 'ok');
export const err = (m) => toast(m, 'err');

/** חלון קופץ. מחזיר Promise עם התוצאה או null אם בוטל. */
export function modal({ title, sub, body, confirmText = 'אישור', cancelText = 'ביטול', onConfirm }) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    const close = (value) => { clear(root); resolve(value); };

    const card = el('div', { class: 'modal' }, [
      el('h3', { class: 'modal-title', text: title }),
      sub ? el('p', { class: 'modal-sub', text: sub }) : null,
      body || null,
      el('div', { class: 'modal-actions' }, [
        el('button', {
          class: 'btn btn-primary',
          text: confirmText,
          onClick: async () => close(onConfirm ? await onConfirm() : true),
        }),
        el('button', { class: 'btn', text: cancelText, onClick: () => close(null) }),
      ]),
    ]);

    const back = el('div', {
      class: 'modal-back',
      onClick: (event) => { if (event.target === back) close(null); },
    }, [card]);

    document.addEventListener('keydown', function esc(event) {
      if (event.key === 'Escape') { document.removeEventListener('keydown', esc); close(null); }
    });

    clear(root);
    root.append(back);
    card.querySelector('input, textarea')?.focus();
  });
}

/** שדה עם תווית והסבר בעברית פשוטה מתחתיה. */
export function field(label, help, control) {
  return el('div', { class: 'field' }, [
    el('label', { class: 'label' }, [label, help ? el('span', { class: 'label-help', text: help }) : null]),
    control,
  ]);
}

/** מד ערך עם תצוגת מספר חיה. */
export function slider({ label, help, min, max, step, value, format, onInput }) {
  const readout = el('span', { class: 'slider-val', text: format ? format(value) : value });
  const input = el('input', {
    type: 'range', min, max, step, value,
    onInput: (event) => {
      const next = parseFloat(event.target.value);
      readout.textContent = format ? format(next) : next;
      onInput?.(next);
    },
  });
  return field(label, help, el('div', { class: 'slider-row' }, [input, readout]));
}

export function timecode(seconds) {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function spinnerRow(label, message = '') {
  return el('div', { class: 'job' }, [
    el('div', { class: 'spinner' }),
    el('div', { class: 'job-body' }, [
      el('div', { class: 'job-label', text: label }),
      el('div', { class: 'job-msg', text: message }),
    ]),
  ]);
}

/** שורת התקדמות שמתעדכנת בזמן אמת מתוך עבודת רקע. */
export function jobRow(label) {
  const message = el('div', { class: 'job-msg', text: 'מתחיל' });
  const fill = el('div', { class: 'job-fill', style: { width: '2%' } });
  const percent = el('div', { class: 'job-pct', text: '0%' });
  const spin = el('div', { class: 'spinner' });
  const node = el('div', { class: 'job' }, [
    spin,
    el('div', { class: 'job-body' }, [
      el('div', { class: 'job-label', text: label }),
      message,
      el('div', { class: 'job-bar' }, [fill]),
    ]),
    percent,
  ]);

  node.update = (snapshot) => {
    message.textContent = snapshot.error || snapshot.message || '';
    const pct = Math.round((snapshot.progress || 0) * 100);
    fill.style.width = `${Math.max(2, pct)}%`;
    percent.textContent = `${pct}%`;
    if (snapshot.status === 'done') { node.classList.add('done'); spin.replaceWith(el('div', { text: '✓', style: { color: 'var(--ok)', fontWeight: '800' } })); }
    if (snapshot.status === 'error') { node.classList.add('error'); spin.replaceWith(el('div', { text: '✕', style: { color: 'var(--danger)', fontWeight: '800' } })); }
  };
  return node;
}

export function confirmDanger(title, sub, confirmText = 'מחק') {
  return modal({ title, sub, confirmText, body: null });
}
