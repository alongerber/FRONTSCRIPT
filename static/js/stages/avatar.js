/* שלב 4 — האווטאר.
   הכפתור האדום של המערכת. עולה בין דולר לשלושה בכל לחיצה, ולכן
   הוא נעול עד שהאזנת לקול המלא ואישרת אותו. */

import { api, watchJob } from '../api.js';
import { el, clear, ok, err, field, jobRow } from '../ui.js';

let avatarCache = null;

export function renderAvatar(ctx) {
  const { project, refresh, boot, setBusy } = ctx;
  const root = el('div');

  const takeId = project.voice.chosen_take;
  const take = (project.voice.takes || []).find((t) => t.id === takeId);

  if (!take) {
    return el('div', { class: 'empty' }, [
      el('div', { class: 'empty-icon', text: '🔒' }),
      el('div', { class: 'empty-title', text: 'הקול עוד לא נעול' }),
      el('div', { class: 'empty-text', text: 'רינדור אווטאר עולה כסף אמיתי בכל לחיצה. חזור לשלב הקול, בחר טייק ונעל אותו.' }),
    ]);
  }

  // ------------------------------------------------- שער האזנה לפני תשלום

  let listened = Boolean(project.avatar.file);
  const gateAudio = el('audio', { src: take.url, controls: 'controls', style: { width: '100%' } });
  const gate = el('div', { class: 'gate' });

  const paintGate = () => {
    clear(gate);
    gate.append(
      el('div', { class: 'gate-icon', text: listened ? '✅' : '⚠️' }),
      el('div', { style: { flex: '1' } }, [
        el('div', { class: 'gate-title', text: listened ? 'מוכן לרנדר' : 'תשמע את הקול עד הסוף' }),
        el('div', { class: 'gate-text', text: listened
          ? 'אישרת את הקול. אפשר להמשיך.'
          : 'הלחיצה הבאה עולה בין $1 ל-$3. אם תגלה טעות אחרי הרינדור — תשלם שוב על אותו סרטון. שתי דקות של האזנה עכשיו חוסכות את זה.' }),
        el('div', { class: 'mt' }, [gateAudio]),
      ]),
    );
  };
  paintGate();

  gateAudio.addEventListener('ended', () => {
    if (listened) return;
    listened = true;
    paintGate();
    ok('הקול אושר. כפתור הרינדור נפתח.');
    paintRenderButton();
  });

  // ---------------------------------------------------------- בחירת אווטאר

  let chosenAvatar = project.avatar.avatar_id || '';
  let chosenKind = 'avatar';
  const avatarsBox = el('div', { class: 'avatars' }, [jobRow('טוען אווטארים')]);

  const loadAvatars = async () => {
    try {
      if (!avatarCache) avatarCache = await api.get('/api/avatars');
      const all = [...avatarCache.avatars, ...avatarCache.talking_photos];
      clear(avatarsBox);
      if (!all.length) {
        avatarsBox.append(el('div', { class: 'muted', text: 'אין אווטארים בחשבון' }));
        return;
      }
      for (const item of all) {
        const node = el('button', {
          class: `av ${item.avatar_id === chosenAvatar ? 'chosen' : ''}`,
          onClick: () => {
            chosenAvatar = item.avatar_id;
            chosenKind = item.kind === 'talking_photo' ? 'talking_photo' : 'avatar';
            avatarsBox.querySelectorAll('.av').forEach((n) => n.classList.remove('chosen'));
            node.classList.add('chosen');
          },
        }, [
          item.preview
            ? el('img', { class: 'av-img', src: item.preview, loading: 'lazy', alt: '' })
            : el('div', { class: 'av-img' }),
          el('div', { class: 'av-name', text: item.name || 'ללא שם' }),
        ]);
        avatarsBox.append(node);
      }
    } catch (error) { clear(avatarsBox); avatarsBox.append(el('div', { class: 'muted', text: error.message })); }
  };
  loadAvatars();

  // ---------------------------------------------------------- הגדרות פלט

  const engineSelect = el('select', { class: 'select' },
    (boot.avatar_engines || []).map((e) =>
      el('option', { value: e.id, selected: e.id === project.avatar.engine }, [`${e.name} — ${e.he}`])));

  const resolutionSelect = el('select', { class: 'select' },
    (boot.resolutions || []).map((r) =>
      el('option', { value: r.id, selected: r.id === project.avatar.resolution }, [`${r.id} — ${r.he}`])));

  const motionInput = el('input', {
    class: 'input',
    placeholder: 'איך הגוף זז? "כמעט לא זז, מבט ישר למצלמה, יד אחת בכיס"',
  });

  const bgColor = el('input', { type: 'color', value: '#101418', style: { width: '48px', height: '38px', border: 'none', background: 'none', cursor: 'pointer' } });
  const bgToggle = el('input', { type: 'checkbox' });

  // ------------------------------------------------------------- רינדור

  const jobBox = el('div');
  const renderRow = el('div', { class: 'row mt' });

  function paintRenderButton() {
    clear(renderRow);
    const button = el('button', {
      class: 'btn btn-money btn-lg',
      text: '🎬 רנדר אווטאר',
      disabled: !listened || !chosenAvatar ? 'disabled' : null,
      onClick: async () => {
        if (!chosenAvatar) return err('בחר אווטאר');
        setBusy(button, true);
        clear(jobBox);
        const row = jobRow('HeyGen מרנדר');
        jobBox.append(row);
        jobBox.append(el('div', { class: 'card-hint', text: 'זה לוקח בדרך כלל 2 עד 10 דקות. אפשר לסגור את הלשונית ולחזור — העבודה ממשיכה בשרת.' }));
        try {
          const payload = {
            avatar_id: chosenAvatar, kind: chosenKind,
            engine: engineSelect.value, resolution: resolutionSelect.value,
            motion_prompt: motionInput.value.trim(),
          };
          if (bgToggle.checked) payload.background = { type: 'color', value: bgColor.value };
          const { job } = await api.post(`/api/projects/${project.id}/avatar/render`, payload);
          await watchJob(job.id, (snapshot) => row.update(snapshot));
          ok('הסרטון מוכן'); refresh('captions');
        } catch (error) { err(error.message); }
        finally { setBusy(button, false); }
      },
    });
    renderRow.append(button);
    if (!listened) {
      renderRow.append(el('span', { class: 'muted', style: { fontSize: '12.5px' }, text: 'נפתח אחרי שתשמע את הקול עד הסוף' }));
    }
  }
  paintRenderButton();

  // --------------------------------------------------- סרטון קיים / העלאה

  const existing = project.avatar.file ? el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'הסרטון שהתקבל' }),
      el('span', { class: 'tag ok', text: 'מוכן ✓' }),
      el('div', { class: 'card-spacer' }),
      el('button', {
        class: 'btn btn-ok btn-sm', text: 'המשך לכתוביות ←',
        onClick: async () => { await api.patch(`/api/projects/${project.id}`, { stage: 'captions' }); refresh('captions'); },
      }),
    ]),
    el('video', { src: project.avatar.url, controls: 'controls', style: { width: '250px', borderRadius: '12px', background: '#000' } }),
  ]) : null;

  const uploadInput = el('input', { type: 'file', accept: 'video/*', class: 'hidden' });
  uploadInput.addEventListener('change', async () => {
    if (!uploadInput.files[0]) return;
    const formData = new FormData();
    formData.append('file', uploadInput.files[0]);
    clear(jobBox);
    jobBox.append(jobRow('מעלה סרטון'));
    try {
      await api.form(`/api/projects/${project.id}/avatar/upload`, formData);
      clear(jobBox); ok('הועלה'); refresh('captions');
    } catch (error) { clear(jobBox); err(error.message); }
  });

  // ------------------------------------------------------------- הרכבה

  if (existing) root.append(existing);
  root.append(gate);

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'האווטאר' })]),
    avatarsBox,
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'הגדרות רינדור' })]),
    el('div', { class: 'grid-2' }, [
      field('מנוע', 'ההבדל במחיר בין הזול ליקר הוא פי ארבעה. בטלפון ההבדל קטן ממה שנדמה.', engineSelect),
      field('רזולוציה', 'לטיקטוק 1080p זה יותר ממספיק. 4K מייקר ומאט בלי תמורה נראית.', resolutionSelect),
    ]),
    field('תנועת גוף', 'עובד עם Avatar V ועם תמונות מדברות. במוקיומנטרי — כמה שפחות תנועה, כך יותר מצחיק.', motionInput),
    el('div', { class: 'field' }, [
      el('label', { class: 'label', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, [
        bgToggle, 'רקע בצבע אחיד', bgColor,
      ]),
      el('span', { class: 'label-help', text: 'בלי סימון — נשאר הרקע המקורי של האווטאר.' }),
    ]),
    renderRow,
    jobBox,
    el('div', { class: 'divider' }),
    el('div', { class: 'row' }, [
      el('span', { class: 'muted', style: { fontSize: '12.5px' }, text: 'כבר יש לך סרטון אווטאר מוכן?' }),
      el('button', { class: 'btn btn-sm', text: 'העלה במקום לרנדר', onClick: () => uploadInput.click() }),
      uploadInput,
    ]),
  ]));

  return root;
}
