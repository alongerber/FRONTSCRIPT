/* שלב 5 — כתוביות.
   המילים באות מהתסריט, התזמון בא מהקול. לכן אין שמות משובשים
   ואין מה לתקן — רק לגרור מילה שקופצת מוקדם מדי. */

import { api, watchJob } from '../api.js';
import { el, clear, ok, err, field, slider, jobRow } from '../ui.js';

export function renderCaptions(ctx) {
  const { project, refresh, setBusy } = ctx;
  const root = el('div');
  const caps = project.captions;

  if (!project.avatar.file) {
    return el('div', { class: 'empty' }, [
      el('div', { class: 'empty-icon', text: '🎬' }),
      el('div', { class: 'empty-title', text: 'עוד אין סרטון אווטאר' }),
      el('div', { class: 'empty-text', text: 'חזור לשלב הקודם, רנדר את האווטאר או העלה סרטון קיים.' }),
    ]);
  }

  let words = (caps.words || []).map((w) => ({ ...w }));
  const style = { ...caps.style };

  // ---------------------------------------------------- טלפון עם תצוגה חיה

  const video = el('video', { src: project.avatar.url, controls: 'controls', playsinline: 'playsinline' });
  const captionLayer = el('div', { class: 'phone-caption' });
  const phone = el('div', { class: 'phone' }, [video, captionLayer]);

  const paintPreviewStyle = () => {
    captionLayer.style.fontSize = `${style.font_size / 1920 * 480}px`;
    captionLayer.style.color = style.primary;
    captionLayer.style.top = `${style.y_percent}%`;
    captionLayer.style.fontFamily = `"${style.font || 'Noto Sans Hebrew'}", Assistant, sans-serif`;
  };
  paintPreviewStyle();

  const paintCaptionAt = (time) => {
    if (!words.length) { captionLayer.textContent = ''; return; }
    const index = words.findIndex((w) => time >= w.start && time <= w.end);
    if (index === -1) { captionLayer.textContent = ''; return; }

    if (style.mode === 'single') {
      captionLayer.textContent = words[index].w;
      captionLayer.style.color = style.highlight;
      return;
    }
    const per = Math.max(1, style.words_per_screen);
    const groupStart = Math.floor(index / per) * per;
    const group = words.slice(groupStart, groupStart + per);
    clear(captionLayer);
    group.forEach((word, position) => {
      captionLayer.append(el('span', {
        text: word.w + ' ',
        style: { color: groupStart + position === index ? style.highlight : style.primary },
      }));
    });
  };

  video.addEventListener('timeupdate', () => paintCaptionAt(video.currentTime));

  // ------------------------------------------------------- רשימת המילים

  const wordsBox = el('div', { class: 'words' });

  const paintWords = () => {
    clear(wordsBox);
    if (!words.length) {
      wordsBox.append(el('div', { class: 'muted', style: { fontSize: '13px' }, text: 'עוד לא נבנו כתוביות. לחץ על הכפתור למעלה.' }));
      return;
    }
    words.forEach((word, index) => {
      const node = el('div', { class: 'word', title: 'לחץ כדי לקפוץ לנקודה בסרטון' }, [
        el('span', { text: word.w }),
        el('span', { class: 'word-t', text: word.start.toFixed(2) }),
      ]);
      node.addEventListener('click', () => { video.currentTime = word.start; });

      // גרירה אופקית מתקנת תזמון
      let dragX = null;
      node.addEventListener('pointerdown', (event) => {
        dragX = { x: event.clientX, start: word.start, end: word.end };
        node.setPointerCapture(event.pointerId);
      });
      node.addEventListener('pointermove', (event) => {
        if (!dragX) return;
        const delta = (dragX.x - event.clientX) / 90; // ימין = מוקדם יותר ב-RTL
        word.start = Math.max(0, dragX.start + delta);
        word.end = Math.max(word.start + 0.05, dragX.end + delta);
        node.querySelector('.word-t').textContent = word.start.toFixed(2);
      });
      node.addEventListener('pointerup', async () => {
        if (!dragX) return;
        dragX = null;
        await api.patch(`/api/projects/${project.id}/captions`, { words });
      });

      wordsBox.append(node);
    });
  };
  paintWords();

  // --------------------------------------------------------------- בנייה

  const buildJob = el('div');
  const btnBuild = el('button', {
    class: 'btn btn-primary', text: words.length ? '↻ בנה מחדש' : '⚡ בנה כתוביות',
    onClick: async () => {
      setBusy(btnBuild, true);
      clear(buildJob);
      const row = jobRow('מתזמן מילים');
      buildJob.append(row);
      try {
        const { job } = await api.post(`/api/projects/${project.id}/captions/build`);
        const result = await watchJob(job.id, (snapshot) => row.update(snapshot));
        words = result.result.words;
        clear(buildJob);
        paintWords();
        ok(`${words.length} מילים מתוזמנות`);
      } catch (error) { err(error.message); }
      finally { setBusy(btnBuild, false); }
    },
  });

  // ---------------------------------------------------------------- סגנון

  const persistStyle = async () => {
    paintPreviewStyle();
    paintCaptionAt(video.currentTime);
    await api.patch(`/api/projects/${project.id}/captions`, { style });
  };

  const modeSelect = el('select', { class: 'select' }, [
    el('option', { value: 'progressive', selected: style.mode !== 'single' }, ['מילה מודגשת בתוך קבוצה']),
    el('option', { value: 'single', selected: style.mode === 'single' }, ['מילה אחת גדולה בכל רגע']),
  ]);
  modeSelect.addEventListener('change', () => { style.mode = modeSelect.value; persistStyle(); });

  const primaryColor = el('input', { type: 'color', value: style.primary, class: 'input', style: { height: '40px', padding: '3px' } });
  primaryColor.addEventListener('change', () => { style.primary = primaryColor.value; persistStyle(); });

  const highlightColor = el('input', { type: 'color', value: style.highlight, class: 'input', style: { height: '40px', padding: '3px' } });
  highlightColor.addEventListener('change', () => { style.highlight = highlightColor.value; persistStyle(); });

  const enabledInput = el('input', { type: 'checkbox', checked: caps.enabled });
  enabledInput.addEventListener('change', async () => {
    await api.patch(`/api/projects/${project.id}/captions`, { enabled: enabledInput.checked });
  });

  // ------------------------------------------------------------- הרכבה

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'כתוביות' }),
      el('div', { class: 'card-spacer' }),
      words.length ? el('a', { class: 'btn btn-sm', href: `/api/projects/${project.id}/captions/srt`, text: '⬇ הורד SRT' }) : null,
      btnBuild,
    ]),
    el('div', { class: 'card-hint', text: 'המערכת יודעת מה נאמר כי היא כתבה את התסריט — היא מחפשת רק מתי. לכן האיות תמיד נכון, גם בשמות.' }),
    buildJob,
    el('div', { class: 'preview-wrap' }, [
      phone,
      el('div', { style: { flex: '1', minWidth: '0' } }, [
        el('div', { class: 'field' }, [
          el('label', { class: 'label', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, [
            enabledInput, 'לצרוב כתוביות בסרטון הסופי',
          ]),
          el('span', { class: 'label-help', text: 'בלי סימון — הסרטון ייוצא נקי, ותוכל להוריד SRT בנפרד.' }),
        ]),
        el('div', { class: 'grid-2' }, [
          field('סגנון', 'איך הכתוביות מופיעות', modeSelect),
          field('מילים במסך', 'כמה מילים רואים בו-זמנית',
            (() => {
              const input = el('input', { class: 'input', type: 'number', min: 1, max: 8, value: style.words_per_screen });
              input.addEventListener('change', () => { style.words_per_screen = parseInt(input.value, 10) || 3; persistStyle(); });
              return input;
            })()),
        ]),
        slider({
          label: 'גודל טקסט', help: 'ביחס לפריים של 1920 פיקסלים',
          min: 40, max: 140, step: 2, value: style.font_size,
          onInput: (v) => { style.font_size = v; persistStyle(); },
        }),
        slider({
          label: 'גובה במסך', help: 'אחוזים מלמעלה. 74 יושב מעל כפתורי הממשק של טיקטוק.',
          min: 20, max: 90, step: 1, value: style.y_percent, format: (v) => `${v}%`,
          onInput: (v) => { style.y_percent = v; persistStyle(); },
        }),
        el('div', { class: 'grid-2' }, [
          field('צבע רגיל', 'המילים שעוד לא נאמרו', primaryColor),
          field('צבע הדגשה', 'המילה שנאמרת ברגע זה', highlightColor),
        ]),
        field('פונט', 'שם הפונט כפי שהוא מותקן בשרת. אם הוא חסר — המערכת תיפול לפונט עברי אחר לבד.',
          (() => {
            const input = el('input', { class: 'input', value: style.font || 'Noto Sans Hebrew' });
            input.addEventListener('change', () => { style.font = input.value.trim(); persistStyle(); });
            return input;
          })()),
      ]),
    ]),
    el('div', { class: 'divider' }),
    el('div', { class: 'card-hint', text: 'לחץ על מילה כדי לקפוץ אליה בסרטון. גרור אותה שמאלה או ימינה כדי לתקן תזמון.' }),
    wordsBox,
  ]));

  root.append(el('div', { class: 'row' }, [
    el('button', {
      class: 'btn btn-ok', text: 'המשך לעריכה וייצוא ←',
      onClick: async () => { await api.patch(`/api/projects/${project.id}`, { stage: 'export' }); refresh('export'); },
    }),
  ]));

  return root;
}
