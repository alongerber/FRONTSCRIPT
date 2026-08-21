/* שלב 1 — התסריט.
   זו מכונת ניסוחים: כל כפתור כאן מחזיר מילים, לא הגדרות טון.
   לחיצה חוזרת על "עוד" תמיד מביאה חדשים, כי השרת זוכר מה כבר ראית. */

import { api } from '../api.js';
import { el, clear, ok, err, field, jobRow } from '../ui.js';

const DIRECTION_KEY = 'front.directions';

function savedDirections() {
  try { return JSON.parse(localStorage.getItem(DIRECTION_KEY) || '[]'); } catch { return []; }
}

function rememberDirection(text) {
  const value = (text || '').trim();
  if (!value) return;
  const list = savedDirections().filter((d) => d !== value);
  list.unshift(value);
  localStorage.setItem(DIRECTION_KEY, JSON.stringify(list.slice(0, 24)));
}

export function renderScript(ctx) {
  const { project, refresh, setBusy } = ctx;
  const root = el('div');
  const brief = project.brief;

  // ---------------------------------------------------------------- הבריף

  const topic = el('textarea', {
    class: 'textarea', rows: 2, placeholder: 'על מה הסרטון?',
    style: { minHeight: '62px' },
  });
  topic.value = brief.topic || '';

  const direction = el('textarea', {
    class: 'textarea', rows: 2,
    placeholder: 'תכתוב במילים שלך. "מופרע לגמרי", "הומור עצמי שאני היוצא פתטי", "יבש כמו דוח מס הכנסה"…',
    style: { minHeight: '62px' },
  });
  direction.value = brief.direction || '';

  const reference = el('textarea', {
    class: 'textarea', rows: 3,
    placeholder: 'אופציונלי — הדבק כאן טקסט שהרוח שלו נכונה. תסריט ישן, סטנד-אפ, פוסט. זה מדויק יותר מכל תיאור במילים.',
  });
  reference.value = brief.reference || '';

  const seconds = el('input', { class: 'input', type: 'number', min: 8, max: 180, step: 1 });
  seconds.value = brief.target_seconds || 40;

  const collect = () => ({
    topic: topic.value.trim(),
    direction: direction.value.trim(),
    reference: reference.value.trim(),
    target_seconds: parseInt(seconds.value, 10) || 40,
  });

  // היסטוריית כיוונים — נבנית מעצמה מהניסוחים שלך, לא מרשימה מוכנה
  const chipRow = el('div', { class: 'chips' });
  const paintChips = () => {
    clear(chipRow);
    const list = savedDirections();
    if (!list.length) return;
    chipRow.append(el('span', { class: 'muted', style: { fontSize: '11.5px', alignSelf: 'center' }, text: 'כיוונים שכתבת בעבר:' }));
    for (const value of list.slice(0, 10)) {
      chipRow.append(el('button', {
        class: 'chip', text: value.length > 42 ? value.slice(0, 42) + '…' : value,
        title: value,
        onClick: () => { direction.value = value; direction.focus(); },
      }));
    }
  };
  paintChips();

  const readingsBox = el('div', { class: 'mt' });

  const btnSharpen = el('button', {
    class: 'btn', text: '🎯 חדד לי את הכיוון',
    onClick: async () => {
      const payload = collect();
      if (!payload.topic) return err('קודם תכתוב על מה הסרטון');
      setBusy(btnSharpen, true);
      clear(readingsBox);
      readingsBox.append(jobRow('קורא את מה שכתבת'));
      try {
        const data = await api.post(`/api/projects/${project.id}/script/sharpen`, payload);
        clear(readingsBox);
        if (data.question) {
          readingsBox.append(el('div', { class: 'warn-box info' }, [
            el('div', { text: '💬' }),
            el('div', { text: data.question }),
          ]));
        }
        readingsBox.append(el('div', { class: 'card-hint', text: 'ארבע קריאות אפשריות של מה שכתבת, עם שורת דוגמה לכל אחת. לחץ על אחת כדי לאמץ אותה — או פשוט תתעלם ותכתוב משלך.' }));
        const grid = el('div', { class: 'grid-2' });
        for (const reading of data.readings) {
          grid.append(el('button', { class: 'reading', onClick: () => {
            direction.value = reading.direction;
            rememberDirection(reading.direction);
            paintChips();
            clear(readingsBox);
            ok('הכיוון עודכן');
          } }, [
            el('div', { class: 'reading-dir', text: reading.direction }),
            reading.sample ? el('div', { class: 'reading-sample', text: `"${reading.sample}"` }) : null,
          ]));
        }
        readingsBox.append(grid);
      } catch (error) {
        clear(readingsBox);
        err(error.message);
      } finally { setBusy(btnSharpen, false); }
    },
  });

  const draftsBox = el('div');

  async function loadDrafts(more = false) {
    const payload = { ...collect(), count: 6, more };
    if (!payload.topic) return err('קודם תכתוב על מה הסרטון');
    rememberDirection(payload.direction);
    paintChips();
    clear(draftsBox);
    draftsBox.append(jobRow(more ? 'מחפש כיוונים חדשים לגמרי' : 'כותב שישה תסריטים'));
    try {
      const data = await api.post(`/api/projects/${project.id}/script/drafts`, payload);
      paintDrafts(data.drafts);
    } catch (error) { clear(draftsBox); err(error.message); }
  }

  function paintDrafts(drafts) {
    clear(draftsBox);
    if (!drafts.length) return;
    draftsBox.append(el('div', { class: 'opt-bar' }, [
      el('span', { class: 'opt-bar-label', text: `${drafts.length} תסריטים. בחר אחד ואז תלטש שורה-שורה.` }),
      el('div', { class: 'card-spacer' }),
      el('button', { class: 'btn btn-sm', text: '↻ עוד שישה חדשים', onClick: () => loadDrafts(true) }),
    ]));

    const grid = el('div', { class: 'grid-3' });
    for (const draft of drafts) {
      grid.append(el('div', { class: 'draft' }, [
        el('div', { class: 'draft-head' }, [
          el('span', { class: 'draft-angle', text: draft.angle || 'גרסה' }),
          el('span', { class: 'draft-secs', text: `~${draft.seconds}ש׳` }),
        ]),
        el('div', { class: 'draft-lines' },
          draft.lines.map((line) => el('div', { class: 'draft-line', text: line.text }))),
        el('button', {
          class: 'btn btn-primary btn-sm btn-block', text: 'קח את זה',
          onClick: async () => {
            await api.post(`/api/projects/${project.id}/script/apply`, { lines: draft.lines });
            ok('התסריט נטען לעורך');
            refresh();
          },
        }),
      ]));
    }
    draftsBox.append(grid);
  }

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'מה כותבים' })]),
    el('div', { class: 'grid-2' }, [
      field('על מה הסרטון', 'משפט אחד. ככל שיהיה ספציפי יותר, כך התסריט יהיה טוב יותר.', topic),
      field('איך זה נשמע', 'אין רשימה סגורה ואין קטגוריות — תכתוב מה שבא לך.', direction),
    ]),
    chipRow,
    el('div', { class: 'mt' }, [
      field('רפרנס', 'אופציונלי, אבל מדויק יותר מכל תיאור במילים.', reference),
    ]),
    el('div', { class: 'grid-2' }, [
      field('אורך יעד בשניות', 'המנוע יכוון לשם. תמיד אפשר לקצר או להאריך אחר כך.', seconds),
      el('div', { class: 'field', style: { display: 'flex', alignItems: 'flex-end', gap: '9px' } }, [
        btnSharpen,
        el('button', { class: 'btn btn-primary', text: '✨ צור תסריטים', onClick: () => loadDrafts(false) }),
      ]),
    ]),
    readingsBox,
  ]));

  root.append(draftsBox);

  // -------------------------------------------------------- עורך התסריט

  if (project.script.lines.length) {
    root.append(renderEditor(ctx, collect));
  }

  return root;
}

/* ------------------------------------------------------------------ העורך */

function renderEditor(ctx, collectBrief) {
  const { project, refresh, setBusy } = ctx;
  let lines = project.script.lines.map((line) => ({ ...line }));

  const listBox = el('div', { class: 'lines' });
  const optionsBox = el('div', { class: 'mt' });
  const statsBox = el('div', { class: 'script-stats' });

  const save = async (silent = false) => {
    const data = await api.post(`/api/projects/${project.id}/script/apply`, { lines });
    lines = data.lines;
    paintStats(data.seconds);
    if (!silent) ok('נשמר');
    return data;
  };

  function paintStats(secs) {
    const chars = lines.reduce((sum, line) => sum + line.text.length, 0);
    const target = collectBrief().target_seconds;
    const seconds = secs ?? Math.round((chars / 13.5 + 0.45 * lines.length) * 10) / 10;
    const over = Math.abs(seconds - target) > target * 0.25;
    clear(statsBox);
    statsBox.append(
      el('span', {}, ['אורך משוער: ', el('span', { class: `stat-num ${over ? 'over' : ''}`, text: `${seconds} שניות` })]),
      el('span', {}, ['יעד: ', el('span', { class: 'stat-num', text: `${target} שניות` })]),
      el('span', {}, ['שורות: ', el('span', { class: 'stat-num', text: String(lines.length) })]),
      el('span', {}, ['תווים: ', el('span', { class: 'stat-num', text: String(chars) })]),
    );
    if (over) {
      statsBox.append(el('button', {
        class: 'btn btn-sm', style: { marginRight: 'auto' },
        text: seconds > target ? '✂ קצר ליעד' : '➕ הרחב ליעד',
        onClick: async () => {
          try {
            const data = await api.post(`/api/projects/${project.id}/script/rework`, { fit_seconds: target });
            lines = data.lines; paint(); paintStats(data.seconds); ok('הותאם לאורך');
          } catch (error) { err(error.message); }
        },
      }));
    }
  }

  /* לוח האפשרויות — כאן מגיעות המילים. תמיד עם כפתור "עוד". */
  async function showOptions({ kind, lineId, title, hint, count = 8 }) {
    clear(optionsBox);
    optionsBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const instruction = el('input', {
      class: 'input',
      placeholder: 'אופציונלי — "יותר קצר", "בלי המילה הזאת", "שיסתיים בשאלה"…',
    });
    const grid = el('div', { class: 'options' });
    let busy = false;

    const load = async (more) => {
      if (busy) return;
      busy = true;
      clear(grid);
      grid.append(jobRow(more ? 'מחפש ניסוחים חדשים' : 'כותב אפשרויות'));
      try {
        const data = await api.post(`/api/projects/${project.id}/script/options`, {
          kind, line_id: lineId, count, more,
          instruction: instruction.value.trim(),
        });
        clear(grid);
        if (!data.options.length) { grid.append(el('div', { class: 'muted', text: 'לא חזרו אפשרויות. נסה שוב.' })); return; }
        for (const option of data.options) {
          grid.append(el('button', { class: 'opt', onClick: async () => {
            applyOption(kind, lineId, option.text);
            clear(optionsBox);
            await save(true);
            paint();
          } }, [
            el('div', { class: 'opt-text', text: option.text }),
            option.note ? el('div', { class: 'opt-note', text: option.note }) : null,
            el('div', { class: 'opt-pick', text: 'קח את זה ←' }),
          ]));
        }
      } catch (error) { clear(grid); err(error.message); }
      finally { busy = false; }
    };

    optionsBox.append(el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [
        el('h3', { class: 'card-title', text: title }),
        el('div', { class: 'card-spacer' }),
        el('button', { class: 'btn btn-sm', text: '↻ עוד ' + count, onClick: () => load(true) }),
        el('button', { class: 'btn btn-ghost btn-sm', text: '✕', onClick: () => clear(optionsBox) }),
      ]),
      el('div', { class: 'card-hint', text: hint }),
      el('div', { class: 'row mb' }, [
        instruction,
        el('button', { class: 'btn', text: 'החל', onClick: () => load(false) }),
      ]),
      grid,
    ]));

    load(false);
  }

  function applyOption(kind, lineId, text) {
    if (kind === 'punchline') {
      if (lines.length) lines[lines.length - 1].text = text;
      else lines.push({ id: `l_${Date.now()}`, text });
    } else if (kind === 'opener') {
      if (lines.length) lines[0].text = text;
      else lines.push({ id: `l_${Date.now()}`, text });
    } else {
      const line = lines.find((item) => item.id === lineId);
      if (line) line.text = text;
    }
  }

  /* ציור השורות, כולל גרירה לסידור מחדש */
  let dragIndex = null;

  function paint() {
    clear(listBox);
    lines.forEach((line, index) => {
      const isLast = index === lines.length - 1;
      const isFirst = index === 0;

      const text = el('textarea', { class: 'line-text', rows: 1 });
      text.value = line.text;
      const autosize = () => { text.style.height = 'auto'; text.style.height = `${text.scrollHeight}px`; };
      text.addEventListener('input', () => { line.text = text.value; autosize(); });
      text.addEventListener('blur', () => save(true).catch(() => {}));
      requestAnimationFrame(autosize);

      const row = el('div', {
        class: `line-row ${isLast ? 'is-last' : ''}`,
        draggable: 'true',
        onDragstart: () => { dragIndex = index; },
        onDragover: (event) => event.preventDefault(),
        onDrop: (event) => {
          event.preventDefault();
          if (dragIndex === null || dragIndex === index) return;
          const [moved] = lines.splice(dragIndex, 1);
          lines.splice(index, 0, moved);
          dragIndex = null;
          paint();
          save(true).catch(() => {});
        },
      }, [
        el('div', { class: 'line-grip', text: '⠿', title: 'גרור כדי לשנות סדר' }),
        text,
        isFirst && lines.length > 1 ? el('span', { class: 'line-badge', text: 'פתיחה' }) : null,
        isLast && lines.length > 1 ? el('span', { class: 'line-badge', text: 'פאנץ׳' }) : null,
        el('div', { class: 'line-tools' }, [
          el('button', {
            class: 'btn btn-ghost btn-sm', text: '↻ ניסוחים', title: 'ניסוחים אחרים לשורה הזאת',
            onClick: () => showOptions({
              kind: 'line', lineId: line.id, count: 8,
              title: 'ניסוחים אחרים לשורה הזאת',
              hint: 'אותה כוונה, מילים אחרות. אורך אחר, מקצב אחר, מילה אחרת שנושאת את המשקל.',
            }),
          }),
          el('button', {
            class: 'btn btn-ghost btn-sm', text: '✕', title: 'מחק שורה',
            onClick: () => { lines.splice(index, 1); paint(); save(true).catch(() => {}); },
          }),
        ]),
      ]);
      listBox.append(row);
    });

    listBox.append(el('button', {
      class: 'btn btn-ghost btn-sm mt', text: '+ שורה',
      onClick: () => { lines.push({ id: `l_${Date.now()}`, text: '' }); paint(); },
    }));
    paintStats();
  }

  paint();

  // -------- שכתוב חופשי --------
  const instruction = el('input', {
    class: 'input',
    placeholder: 'מה לשנות בתסריט כולו? "תעיף את השורה על הכלב", "שהכל יהיה בגוף שלישי"…',
  });
  const btnRework = el('button', {
    class: 'btn', text: 'שכתב',
    onClick: async () => {
      const value = instruction.value.trim();
      if (!value) return err('כתוב מה לשנות');
      setBusy(btnRework, true);
      try {
        const data = await api.post(`/api/projects/${project.id}/script/rework`, { instruction: value });
        lines = data.lines; paint(); instruction.value = ''; ok('שוכתב');
      } catch (error) { err(error.message); }
      finally { setBusy(btnRework, false); }
    },
  });

  const locked = project.script.locked;

  return el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'התסריט' }),
      locked ? el('span', { class: 'tag ok', text: 'נעול ✓' }) : null,
      el('div', { class: 'card-spacer' }),
      el('button', {
        class: 'btn btn-sm', text: '⚡ פתיחות אחרות',
        onClick: () => showOptions({
          kind: 'opener', count: 10,
          title: 'פתיחות אחרות',
          hint: 'בסרטון אנכי יש שלוש שניות לפני שגוללים הלאה. השורה הזאת קובעת אם ממשיכים.',
        }),
      }),
      el('button', {
        class: 'btn btn-primary btn-sm', text: '💥 פאנצ׳ים אחרים',
        onClick: () => showOptions({
          kind: 'punchline', count: 10,
          title: 'פאנצ׳ים אחרים',
          hint: 'שורות סיום חלופיות לסטאפ הקיים. כל אחת מסוג אחר לגמרי.',
        }),
      }),
    ]),
    el('div', { class: 'card-hint', text: 'לחץ על שורה כדי לערוך ישירות. גרור את ⠿ כדי לשנות סדר. "ניסוחים" מחליף רק את השורה הזאת ומשאיר את השאר.' }),
    listBox,
    statsBox,
    optionsBox,
    el('div', { class: 'divider' }),
    el('div', { class: 'row' }, [instruction, btnRework]),
    el('div', { class: 'row mt' }, [
      el('button', {
        class: 'btn btn-ok', text: locked ? '✓ התסריט נעול — המשך לקול' : '✓ נעל תסריט והמשך לקול',
        onClick: async () => {
          await api.post(`/api/projects/${project.id}/script/apply`, { lines, locked: true });
          await api.patch(`/api/projects/${project.id}`, { stage: 'voice' });
          refresh('voice');
        },
      }),
      el('button', { class: 'btn btn-ghost', text: 'שמור בלי לנעול', onClick: () => save() }),
    ]),
  ]);
}
