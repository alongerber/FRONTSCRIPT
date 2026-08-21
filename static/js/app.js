/* המנצח — טוען מצב, מצייר את המדרגות, ומחליף בין שלבים. */

import { api } from './api.js';
import { el, clear, ok, err, toast, modal } from './ui.js';
import { renderScript } from './stages/script.js';
import { renderVoice } from './stages/voice.js';
import { renderBroll } from './stages/broll.js';
import { renderAvatar } from './stages/avatar.js';
import { renderCaptions } from './stages/captions.js';
import { renderEdit } from './stages/edit.js';

const STAGES = [
  { id: 'script',   num: 1, name: 'תסריט',  title: 'התסריט',
    sub: 'מכונת ניסוחים. לא בוחרים טון — מקבלים מילים, ולוחצים "עוד" עד שזה נשמע נכון.',
    render: renderScript },
  { id: 'voice',    num: 2, name: 'קול',    title: 'הקול', cost: '11¢',
    sub: 'טייק עולה אגורות. תנסה כמה שבא לך — השלב הבא הוא זה שעולה כסף.',
    render: renderVoice },
  { id: 'broll',    num: 3, name: 'B-roll', title: 'ה-B-roll', cost: '$2',
    sub: 'תמונות זולות עד שהפריים מדויק, ואז הנפשה אחת. ככה עשרה ניסיונות וידאו הופכים לאחד.',
    render: renderBroll },
  { id: 'avatar',   num: 4, name: 'אווטאר', title: 'האווטאר', cost: '$2.7', money: true,
    sub: 'השלב היקר בצינור. נפתח רק אחרי שהאזנת לקול המלא ואישרת אותו.',
    render: renderAvatar },
  { id: 'captions', num: 5, name: 'כתוביות', title: 'הכתוביות',
    sub: 'המילים מהתסריט, התזמון מהקול. לכן האיות תמיד נכון ואין מה לתקן.',
    render: renderCaptions },
  { id: 'export',   num: 6, name: 'עריכה', title: 'עריכה וייצוא',
    sub: 'גורר, מותח, מייצא. הקול של האווטאר לא זז לרגע.',
    render: renderEdit },
];

const state = {
  boot: null,
  project: null,
  stage: 'script',
};

/* ------------------------------------------------------------- כלי עזר */

function setBusy(button, busy) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.textContent = '… רגע';
  } else {
    button.disabled = false;
    if (button.dataset.label) button.textContent = button.dataset.label;
  }
}

function stageComplete(stage) {
  const project = state.project;
  if (!project) return false;
  switch (stage.id) {
    case 'script':   return project.script.locked && project.script.lines.length > 0;
    case 'voice':    return Boolean(project.voice.chosen_take);
    case 'broll':    return project.broll.shots.some((s) => s.file || s.video);
    case 'avatar':   return Boolean(project.avatar.file);
    case 'captions': return (project.captions.words || []).length > 0;
    case 'export':   return Boolean(project.export?.file);
    default:         return false;
  }
}

function stageLocked(stage) {
  const project = state.project;
  if (!project) return true;
  if (stage.id === 'avatar')   return !project.voice.chosen_take;
  if (stage.id === 'captions') return !project.avatar.file;
  if (stage.id === 'export')   return !project.avatar.file;
  if (stage.id === 'voice' || stage.id === 'broll') return !project.script.lines.length;
  return false;
}

/* ------------------------------------------------------------- ציור */

function paintEngines() {
  const box = document.getElementById('engine-pills');
  clear(box);
  const labels = { script: 'תסריט', voice: 'קול', broll: 'B-roll', avatar: 'אווטאר' };
  for (const [key, ready] of Object.entries(state.boot.engines)) {
    box.append(el('span', {
      class: `pill ${ready ? 'on' : 'off'}`,
      text: labels[key] || key,
      title: ready ? 'המנוע מחובר' : 'חסר מפתח API בקובץ .env',
    }));
  }
  if (!state.boot.ffmpeg) {
    box.append(el('span', { class: 'pill off', text: 'FFmpeg', title: 'FFmpeg לא מותקן — אי אפשר לערוך או לייצא' }));
  }
}

function paintProjects() {
  const box = document.getElementById('project-list');
  clear(box);
  if (!state.boot.projects.length) {
    box.append(el('div', { class: 'muted', style: { fontSize: '12.5px', padding: '10px 8px' }, text: 'עוד אין פרויקטים.' }));
    return;
  }
  for (const item of state.boot.projects) {
    box.append(el('button', {
      class: `proj ${state.project?.id === item.id ? 'active' : ''}`,
      onClick: () => openProject(item.id),
    }, [
      el('div', { class: 'proj-name', text: item.name }),
      el('div', { class: 'proj-meta' }, [
        el('span', { class: `proj-dot ${item.has_export ? 'done' : ''}` }),
        el('span', { text: item.has_export ? 'יוצא' : 'בעבודה' }),
      ]),
    ]));
  }
}

function paintSteps() {
  const box = document.getElementById('steps');
  clear(box);
  if (!state.project) return;

  for (const stage of STAGES) {
    const locked = stageLocked(stage);
    const complete = stageComplete(stage);
    box.append(el('button', {
      class: [
        'step',
        stage.id === state.stage ? 'active' : '',
        locked ? 'locked' : '',
        complete ? 'complete' : '',
        stage.money ? 'money' : '',
      ].filter(Boolean).join(' '),
      title: locked ? 'צריך להשלים את השלב הקודם' : stage.sub,
      onClick: () => { if (!locked) { state.stage = stage.id; paintSteps(); paintStage(); } },
    }, [
      el('span', { class: 'step-num', text: complete ? '✓' : String(stage.num) }),
      el('span', { class: 'step-name', text: stage.name }),
      stage.cost ? el('span', { class: 'step-cost', text: stage.cost }) : null,
    ]));
  }
}

async function paintStage() {
  const box = document.getElementById('stage');
  const stage = STAGES.find((s) => s.id === state.stage) || STAGES[0];
  clear(box);

  const inner = el('div', { class: 'stage-inner' }, [
    el('div', { class: 'stage-head' }, [
      el('h1', { class: 'stage-title', text: stage.title }),
      el('p', { class: 'stage-sub', text: stage.sub }),
    ]),
  ]);
  box.append(inner);

  const missing = {
    script: 'script', voice: 'voice', broll: 'broll', avatar: 'avatar',
  }[stage.id];
  if (missing && state.boot.engines[missing] === false) {
    inner.append(el('div', { class: 'warn-box' }, [
      el('div', { text: '🔑' }),
      el('div', { html: `<strong>המנוע של השלב הזה לא מחובר.</strong> חסר מפתח API בקובץ <code>.env</code>. המסך יעבוד, אבל הכפתורים שמייצרים יחזירו שגיאה.` }),
    ]));
  }

  const ctx = {
    project: state.project,
    boot: state.boot,
    setBusy,
    refresh: (goTo) => refresh(goTo),
  };

  try {
    const content = await stage.render(ctx);
    inner.append(content);
  } catch (error) {
    inner.append(el('div', { class: 'warn-box' }, [el('div', { text: '⚠️' }), el('div', { text: error.message })]));
  }
}

/* --------------------------------------------------------- זרימת עבודה */

async function openProject(projectId, goTo) {
  try {
    state.project = await api.get(`/api/projects/${projectId}`);
    localStorage.setItem('front.last', projectId);
    state.stage = goTo || state.project.stage || 'script';
    if (stageLocked(STAGES.find((s) => s.id === state.stage) || STAGES[0])) state.stage = 'script';
    document.getElementById('head-project').textContent = state.project.name;
    paintProjects();
    paintSteps();
    await paintStage();
  } catch (error) { err(error.message); }
}

async function refresh(goTo) {
  if (!state.project) return;
  state.boot.projects = (await api.get('/api/projects')).projects;
  await openProject(state.project.id, goTo);
}

async function createProject() {
  const input = el('input', { class: 'input', placeholder: 'למשל: מקרר שלא נכנס בדלת' });
  const name = await modal({
    title: 'סרטון חדש',
    sub: 'תן לו שם שתזהה אחר כך. אפשר לשנות בכל רגע.',
    body: input,
    confirmText: 'פתח',
    onConfirm: () => input.value.trim() || 'סרטון ללא שם',
  });
  if (!name) return;
  try {
    const project = await api.post('/api/projects', { name });
    state.boot.projects = (await api.get('/api/projects')).projects;
    await openProject(project.id, 'script');
    ok('הפרויקט נפתח');
  } catch (error) { err(error.message); }
}

/* ------------------------------------------------------------ הפעלה */

async function boot() {
  try {
    state.boot = await api.get('/api/bootstrap');
  } catch (error) {
    err(`לא הצלחתי לטעון: ${error.message}`);
    return;
  }

  paintEngines();
  paintProjects();

  document.getElementById('btn-new').addEventListener('click', createProject);

  const missing = Object.entries(state.boot.engines).filter(([, ready]) => !ready).map(([key]) => key);
  if (missing.length === Object.keys(state.boot.engines).length) {
    toast('אף מנוע לא מחובר. מלא את המפתחות בקובץ .env והפעל מחדש.', 'err');
  }

  const last = localStorage.getItem('front.last');
  if (last && state.boot.projects.some((p) => p.id === last)) {
    openProject(last);
  } else if (state.boot.projects.length) {
    openProject(state.boot.projects[0].id);
  }
}

boot();
