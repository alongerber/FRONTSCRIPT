/* שלב 2 — הקול.
   טייק עולה בערך 11 אגורות, אז מותר לנסות. השלב הבא עולה פי 25 —
   ולכן הנעילה כאן היא מה שפותח אותו. */

import { api } from '../api.js';
import { el, clear, ok, err, field, slider, jobRow } from '../ui.js';

let voiceCache = null;

export async function renderVoice(ctx) {
  const { project, refresh, setBusy, boot } = ctx;
  const root = el('div');
  const voice = project.voice;

  if (!project.script.lines.length) {
    return el('div', { class: 'empty' }, [
      el('div', { class: 'empty-icon', text: '📝' }),
      el('div', { class: 'empty-title', text: 'קודם צריך תסריט' }),
      el('div', { class: 'empty-text', text: 'חזור לשלב הראשון וכתוב את מה שייאמר.' }),
    ]);
  }

  const scriptText = project.script.lines.map((line) => line.text).join('\n');

  // ------------------------------------------------------------ בחירת קול

  const voiceBox = el('div', { class: 'voice-list' }, [jobRow('טוען קולות')]);
  let chosenVoice = voice.voice_id || '';

  const loadVoices = async () => {
    try {
      if (!voiceCache) voiceCache = (await api.get('/api/voices')).voices;
      clear(voiceBox);
      if (!voiceCache.length) {
        voiceBox.append(el('div', { class: 'muted', text: 'אין קולות בחשבון' }));
        return;
      }
      for (const item of voiceCache) {
        const node = el('button', {
          class: `voice-item ${item.voice_id === chosenVoice ? 'active' : ''}`,
          onClick: () => {
            chosenVoice = item.voice_id;
            voiceBox.querySelectorAll('.voice-item').forEach((n) => n.classList.remove('active'));
            node.classList.add('active');
          },
        }, [
          el('div', { style: { flex: '1' } }, [
            el('div', { class: 'voice-name', text: item.name || 'ללא שם' }),
          ]),
          item.category === 'cloned' ? el('span', { class: 'voice-tag', text: 'הקול שלך' }) : null,
          item.preview_url ? el('audio', { src: item.preview_url, controls: 'controls', style: { height: '28px', width: '160px' } }) : null,
        ]);
        voiceBox.append(node);
      }
    } catch (error) { clear(voiceBox); voiceBox.append(el('div', { class: 'muted', text: error.message })); }
  };
  loadVoices();

  // ---------------------------------------------------------- מודל והגדרות

  const models = boot.voice_models || [];
  const modelSelect = el('select', { class: 'select' },
    models.map((m) => el('option', { value: m.id, selected: m.id === voice.model_id }, [`${m.name} — ${m.he}`])));

  const settingsState = { ...voice.settings };

  const stabilityHelp = 'נמוך = משחק ורגש. גבוה = שטוח ומונוטוני. לדדפאן דווקא רוצים גבוה.';
  const stabilityNode = slider({
    label: 'יציבות', help: stabilityHelp, min: 0, max: 1, step: 0.05,
    value: settingsState.stability, format: (v) => v.toFixed(2),
    onInput: (v) => { settingsState.stability = v; },
  });
  const similarityNode = slider({
    label: 'דמיון למקור', help: 'כמה להידבק לקול המקורי. גבוה מדי מכניס לפעמים רעשי רקע מההקלטה.',
    min: 0, max: 1, step: 0.05, value: settingsState.similarity_boost, format: (v) => v.toFixed(2),
    onInput: (v) => { settingsState.similarity_boost = v; },
  });
  const styleNode = slider({
    label: 'סגנוניות', help: 'מגזים את המאפיינים של הקול. במוקיומנטרי משאירים על אפס.',
    min: 0, max: 1, step: 0.05, value: settingsState.style, format: (v) => v.toFixed(2),
    onInput: (v) => { settingsState.style = v; },
  });
  const speedNode = slider({
    label: 'מהירות דיבור', help: '1 זה רגיל. דדפאן חי בסביבות 0.9 — קצת יותר לאט מהטבעי.',
    min: 0.5, max: 1.6, step: 0.05, value: settingsState.speed, format: (v) => `${v.toFixed(2)}x`,
    onInput: (v) => { settingsState.speed = v; },
  });

  const boostInput = el('input', { type: 'checkbox', checked: settingsState.use_speaker_boost });
  boostInput.addEventListener('change', () => { settingsState.use_speaker_boost = boostInput.checked; });

  const seedInput = el('input', { class: 'input', type: 'number', placeholder: 'ריק = אקראי', min: 0 });
  const textArea = el('textarea', { class: 'textarea', rows: 5 });
  textArea.value = scriptText;

  const takesBox = el('div');
  const jobsBox = el('div');

  function paintTakes(takes) {
    clear(takesBox);
    if (!takes.length) {
      takesBox.append(el('div', { class: 'muted', style: { fontSize: '13px' }, text: 'עוד אין טייקים. תפיק אחד ותשמע.' }));
      return;
    }
    for (const take of takes) {
      const isChosen = take.id === project.voice.chosen_take;
      takesBox.append(el('div', { class: `take ${isChosen ? 'chosen' : ''}` }, [
        el('audio', { src: take.url, controls: 'controls', preload: 'none' }),
        el('span', { class: 'take-meta', text: take.model_id ? take.model_id.replace('eleven_', '') : take.kind }),
        isChosen
          ? el('span', { class: 'tag ok', text: 'נבחר ✓' })
          : el('button', {
              class: 'btn btn-sm', text: 'בחר',
              onClick: async () => {
                try {
                  await api.post(`/api/projects/${project.id}/voice/choose`, { take_id: take.id, locked: true });
                  ok('הקול נעול. שלב האווטאר נפתח.');
                  refresh();
                } catch (error) { err(error.message); }
              },
            }),
        el('button', {
          class: 'btn btn-ghost btn-sm btn-danger', text: '✕',
          onClick: async () => { await api.del(`/api/projects/${project.id}/voice/takes/${take.id}`); refresh(); },
        }),
      ]));
    }
  }
  paintTakes(voice.takes || []);

  const commonBody = () => ({
    text: textArea.value.trim(),
    voice_id: chosenVoice,
    model_id: modelSelect.value,
    settings: settingsState,
    seed: seedInput.value ? parseInt(seedInput.value, 10) : null,
  });

  const btnGenerate = el('button', {
    class: 'btn btn-primary', text: '🔊 הפק טייק',
    onClick: async () => {
      if (!chosenVoice) return err('בחר קול קודם');
      setBusy(btnGenerate, true);
      clear(jobsBox);
      jobsBox.append(jobRow('ElevenLabs מקריא'));
      try {
        await api.post(`/api/projects/${project.id}/voice/tts`, commonBody());
        clear(jobsBox);
        ok('טייק חדש מוכן');
        refresh();
      } catch (error) { clear(jobsBox); err(error.message); }
      finally { setBusy(btnGenerate, false); }
    },
  });

  const btnCompare = el('button', {
    class: 'btn', text: '⚖ השווה מודלים',
    title: 'אותו טקסט בשני מודלים. בעברית זה ההבדל בין נקי למשתולל.',
    onClick: async () => {
      if (!chosenVoice) return err('בחר קול קודם');
      setBusy(btnCompare, true);
      clear(jobsBox);
      jobsBox.append(jobRow('מפיק שתי גרסאות להשוואה'));
      try {
        await api.post(`/api/projects/${project.id}/voice/compare`, {
          ...commonBody(), models: ['eleven_v3', 'eleven_multilingual_v2'],
        });
        clear(jobsBox);
        ok('שתי גרסאות מוכנות — תשמע ותחליט');
        refresh();
      } catch (error) { clear(jobsBox); err(error.message); }
      finally { setBusy(btnCompare, false); }
    },
  });

  // ------------------------------------------------------ הקלטה והעלאה

  const dropZone = el('div', { class: 'drop' }, [
    el('div', { class: 'drop-icon', text: '🎙' }),
    el('div', { class: 'drop-title', text: 'גרור לכאן הקלטה שלך' }),
    el('div', { class: 'drop-sub', text: 'ההפסקות, הנשימות והטון שלך — בקול הקלון. MP3, WAV, M4A' }),
  ]);
  const fileInput = el('input', { type: 'file', accept: 'audio/*', class: 'hidden' });

  const uploadAudio = async (file, asSts) => {
    if (!file) return;
    if (asSts && !chosenVoice) return err('בחר קול יעד קודם');
    clear(jobsBox);
    jobsBox.append(jobRow(asSts ? 'ממיר לקול שלך' : 'מעלה קובץ'));
    const formData = new FormData();
    formData.append('file', file);
    if (asSts) formData.append('voice_id', chosenVoice);
    try {
      await api.form(`/api/projects/${project.id}/voice/${asSts ? 'sts' : 'upload'}`, formData);
      clear(jobsBox); ok('מוכן'); refresh();
    } catch (error) { clear(jobsBox); err(error.message); }
  };

  let pendingFile = null;
  const modeRow = el('div', { class: 'row mt hidden' });

  const offerModes = (file) => {
    pendingFile = file;
    clear(modeRow);
    modeRow.classList.remove('hidden');
    modeRow.append(
      el('span', { class: 'muted', style: { fontSize: '12.5px' }, text: `${file.name} — מה לעשות איתו?` }),
      el('button', { class: 'btn btn-sm btn-primary', text: 'המר לקול שלי', onClick: () => { modeRow.classList.add('hidden'); uploadAudio(pendingFile, true); } }),
      el('button', { class: 'btn btn-sm', text: 'השתמש כמו שהוא', onClick: () => { modeRow.classList.add('hidden'); uploadAudio(pendingFile, false); } }),
    );
  };

  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) offerModes(fileInput.files[0]); });
  ['dragenter', 'dragover'].forEach((event) =>
    dropZone.addEventListener(event, (e) => { e.preventDefault(); dropZone.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((event) =>
    dropZone.addEventListener(event, (e) => { e.preventDefault(); dropZone.classList.remove('over'); }));
  dropZone.addEventListener('drop', (e) => { if (e.dataTransfer.files[0]) offerModes(e.dataTransfer.files[0]); });

  // הקלטה חיה מהדפדפן
  let recorder = null;
  let chunks = [];
  const btnRecord = el('button', {
    class: 'btn', text: '⏺ הקלט עכשיו',
    onClick: async () => {
      if (recorder && recorder.state === 'recording') {
        recorder.stop();
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (event) => chunks.push(event.data);
        recorder.onstop = () => {
          stream.getTracks().forEach((track) => track.stop());
          btnRecord.textContent = '⏺ הקלט עכשיו';
          btnRecord.classList.remove('btn-danger');
          const blob = new Blob(chunks, { type: 'audio/webm' });
          offerModes(new File([blob], `rec_${Date.now()}.webm`, { type: 'audio/webm' }));
        };
        recorder.start();
        btnRecord.textContent = '⏹ עצור הקלטה';
        btnRecord.classList.add('btn-danger');
      } catch { err('אין גישה למיקרופון. בדוק הרשאות בדפדפן.'); }
    },
  });

  // ------------------------------------------------------------- הרכבה

  root.append(el('div', { class: 'grid-2' }, [
    el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'הקול' })]),
      el('div', { class: 'card-hint', text: 'קולות מסומנים "הקול שלך" הם קלונים שיצרת ב-ElevenLabs.' }),
      voiceBox,
    ]),
    el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'הגדרות' })]),
      field('מנוע', 'בעברית החדש לא תמיד הטוב יותר. תשווה ותחליט בעצמך.', modelSelect),
      stabilityNode, similarityNode, styleNode, speedNode,
      el('div', { class: 'field' }, [
        el('label', { class: 'label', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, [
          boostInput, 'חידוד קול',
        ]),
        el('span', { class: 'label-help', text: 'משפר חדות. תכבה רק אם שומעים עיוותים.' }),
      ]),
      field('נעילת תוצאה', 'אותו מספר מחזיר בדיוק אותה הקראה. רשום את המספר כשמצאת טייק טוב.', seedInput),
    ]),
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'הטקסט' }),
      el('div', { class: 'card-spacer' }),
      el('span', { class: 'muted', style: { fontSize: '11.5px' }, text: '~11 אגורות לטייק' }),
    ]),
    el('div', { class: 'card-hint', text: 'נטען מהתסריט. אפשר להוסיף כאן נקודות ופסיקים כדי לשלוט בהפסקות בלי לשנות את התסריט עצמו.' }),
    textArea,
    el('div', { class: 'row mt' }, [btnGenerate, btnCompare]),
    jobsBox,
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'ההקלטה שלך' })]),
    el('div', { class: 'card-hint', text: 'הדרך הכי מדויקת: אתה אומר את זה בדיוק בטון ובהפסקות שאתה רוצה, והמערכת מלבישה על זה את הקול.' }),
    dropZone, fileInput, modeRow,
    el('div', { class: 'row mt' }, [btnRecord]),
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'טייקים' }),
      el('div', { class: 'card-spacer' }),
      project.voice.locked ? el('span', { class: 'tag ok', text: 'נעול ✓' }) : null,
    ]),
    el('div', { class: 'card-hint', text: 'הכל נשמר. בחר את הטייק שהולך לאווטאר — זה מה שפותח את השלב הבא.' }),
    takesBox,
    project.voice.chosen_take ? el('div', { class: 'row mt' }, [
      el('button', {
        class: 'btn btn-ok', text: 'המשך ל-B-roll ←',
        onClick: async () => { await api.patch(`/api/projects/${project.id}`, { stage: 'broll' }); refresh('broll'); },
      }),
    ]) : null,
  ]));

  return root;
}
