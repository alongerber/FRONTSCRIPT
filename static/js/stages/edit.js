/* שלב 6 — עריכה וייצוא.
   טיימליין עם גל הקול. גורר קטע — הוא זז. מותח אותו — הוא מתארך.
   הקול של האווטאר לא זז לרגע. */

import { api, watchJob } from '../api.js';
import { el, clear, ok, err, jobRow, timecode } from '../ui.js';

export function renderEdit(ctx) {
  const { project, refresh, boot, setBusy } = ctx;
  const root = el('div');

  if (!project.avatar.file) {
    return el('div', { class: 'empty' }, [
      el('div', { class: 'empty-icon', text: '🎬' }),
      el('div', { class: 'empty-title', text: 'עוד אין סרטון אווטאר' }),
      el('div', { class: 'empty-text', text: 'צריך את הסרטון של האווטאר לפני שאפשר להרכיב עליו B-roll.' }),
    ]);
  }

  if (!boot.ffmpeg) {
    root.append(el('div', { class: 'warn-box' }, [
      el('div', { text: '⚠️' }),
      el('div', { html: '<strong>FFmpeg לא מותקן בשרת.</strong> בלעדיו אי אפשר לחבר B-roll או לייצא. במחשב מקומי: <code>brew install ffmpeg</code> או <code>apt install ffmpeg</code>. בענן — ה-Dockerfile כבר כולל אותו.' }),
    ]));
  }

  const shots = project.broll.shots.filter((s) => s.file || s.video);
  const duration = project.avatar.duration || 30;

  // ------------------------------------------------------------ טיימליין

  const ruler = el('div', { class: 'tl-ruler' });
  const track = el('div', { class: 'tl-track' });
  const playhead = el('div', { class: 'tl-playhead', style: { right: '0' } });
  const waveCanvas = el('canvas', { class: 'tl-wave' });

  const paintRuler = () => {
    clear(ruler);
    const step = duration > 60 ? 10 : duration > 24 ? 5 : 2;
    for (let t = 0; t <= duration; t += step) {
      ruler.append(el('div', {
        class: 'tl-tick', text: timecode(t),
        style: { right: `${(t / duration) * 100}%` },
      }));
    }
  };
  paintRuler();

  const drawWave = (peaks) => {
    const rect = track.getBoundingClientRect();
    const width = Math.max(320, Math.round(rect.width));
    const height = 58;
    waveCanvas.width = width * devicePixelRatio;
    waveCanvas.height = height * devicePixelRatio;
    const context = waveCanvas.getContext('2d');
    context.scale(devicePixelRatio, devicePixelRatio);
    context.clearRect(0, 0, width, height);
    if (!peaks || !peaks.length) return;
    context.fillStyle = '#5aa9ff';
    const step = width / peaks.length;
    peaks.forEach((peak, index) => {
      const h = Math.max(1, peak * (height - 8));
      // RTL: הזמן רץ מימין לשמאל
      context.fillRect(width - (index + 1) * step, (height - h) / 2, Math.max(1, step - 0.4), h);
    });
  };

  api.get(`/api/projects/${project.id}/waveform`)
    .then((data) => drawWave(data.peaks))
    .catch(() => {});

  /* גרירת קטע לאורך הציר, ומתיחה של הקצוות לשינוי אורך */
  const paintClips = () => {
    track.querySelectorAll('.tl-clip').forEach((n) => n.remove());
    shots.forEach((shot, index) => {
      const clip = el('div', {
        class: `tl-clip ${shot.mode === 'pip' ? 'pip' : ''}`,
        style: {
          right: `${(shot.start / duration) * 100}%`,
          width: `${(shot.duration / duration) * 100}%`,
        },
        title: shot.idea || `קטע ${index + 1}`,
      }, [
        el('div', { class: 'tl-handle s' }),
        el('span', { text: shot.idea ? shot.idea.slice(0, 22) : `קטע ${index + 1}` }),
        el('div', { class: 'tl-handle e' }),
      ]);

      let drag = null;
      const pxPerSecond = () => track.getBoundingClientRect().width / duration;

      clip.addEventListener('pointerdown', (event) => {
        const handle = event.target.closest('.tl-handle');
        drag = {
          mode: handle ? (handle.classList.contains('s') ? 'start' : 'end') : 'move',
          x: event.clientX,
          start: shot.start,
          duration: shot.duration,
        };
        clip.setPointerCapture(event.pointerId);
        event.preventDefault();
      });

      clip.addEventListener('pointermove', (event) => {
        if (!drag) return;
        const delta = (drag.x - event.clientX) / pxPerSecond(); // RTL
        if (drag.mode === 'move') {
          shot.start = Math.max(0, Math.min(duration - shot.duration, drag.start + delta));
        } else if (drag.mode === 'start') {
          const next = Math.max(0, Math.min(drag.start + drag.duration - 0.3, drag.start + delta));
          shot.duration = drag.duration + (drag.start - next);
          shot.start = next;
        } else {
          shot.duration = Math.max(0.3, Math.min(duration - shot.start, drag.duration - delta));
        }
        clip.style.right = `${(shot.start / duration) * 100}%`;
        clip.style.width = `${(shot.duration / duration) * 100}%`;
        meta.textContent = `${timecode(shot.start)} · ${shot.duration.toFixed(1)}ש׳`;
      });

      clip.addEventListener('pointerup', async () => {
        if (!drag) return;
        drag = null;
        await api.patch(`/api/projects/${project.id}/broll/shots/${shot.id}`, {
          start: Math.round(shot.start * 100) / 100,
          duration: Math.round(shot.duration * 100) / 100,
        });
      });

      const meta = el('span');
      track.append(clip);
    });
  };
  paintClips();
  track.append(waveCanvas, playhead);
  requestAnimationFrame(() => drawWave(null));

  // -------------------------------------------------- טבלת הקטעים המדויקת

  const listBox = el('div');
  const paintList = () => {
    clear(listBox);
    if (!shots.length) {
      listBox.append(el('div', { class: 'muted', style: { fontSize: '13px' }, text: 'אין קטעים בטיימליין. חזור לשלב ה-B-roll.' }));
      return;
    }
    for (const [index, shot] of shots.entries()) {
      const start = el('input', { class: 'input', type: 'number', step: 0.1, min: 0, value: shot.start.toFixed(1), style: { width: '92px' } });
      const dur = el('input', { class: 'input', type: 'number', step: 0.1, min: 0.2, value: shot.duration.toFixed(1), style: { width: '92px' } });
      const mode = el('select', { class: 'select', style: { width: '190px' } }, [
        el('option', { value: 'full', selected: shot.mode !== 'pip' }, ['קאט מלא']),
        el('option', { value: 'pip', selected: shot.mode === 'pip' }, ['חלון קטן']),
      ]);
      const save = async () => {
        shot.start = parseFloat(start.value) || 0;
        shot.duration = parseFloat(dur.value) || 1;
        shot.mode = mode.value;
        await api.patch(`/api/projects/${project.id}/broll/shots/${shot.id}`, {
          start: shot.start, duration: shot.duration, mode: shot.mode,
        });
        paintClips();
      };
      [start, dur, mode].forEach((n) => n.addEventListener('change', save));

      listBox.append(el('div', { class: 'row', style: { marginBottom: '8px', flexWrap: 'wrap' } }, [
        el('div', { class: 'shot-num', text: String(index + 1) }),
        el('div', { style: { flex: '1', minWidth: '120px', fontSize: '13.5px' }, text: shot.idea || `קטע ${index + 1}` }),
        el('span', { class: 'muted', style: { fontSize: '12px' }, text: 'נכנס' }), start,
        el('span', { class: 'muted', style: { fontSize: '12px' }, text: 'למשך' }), dur,
        mode,
      ]));
    }
  };
  paintList();

  // ------------------------------------------------------------ תצוגה וייצוא

  const outputBox = el('div');
  const jobBox = el('div');

  const runRender = async (button, final) => {
    setBusy(button, true);
    clear(jobBox);
    const row = jobRow(final ? 'מרנדר סופי' : 'מרנדר תצוגה מקדימה');
    jobBox.append(row);
    try {
      const { job } = await api.post(`/api/projects/${project.id}/${final ? 'export' : 'preview'}`);
      const result = await watchJob(job.id, (snapshot) => row.update(snapshot));
      clear(jobBox);
      clear(outputBox);
      outputBox.append(
        el('video', { src: result.result.url, controls: 'controls', style: { width: '250px', borderRadius: '12px', background: '#000' } }),
      );
      if (final) {
        outputBox.append(el('div', { class: 'row mt' }, [
          el('a', { class: 'btn btn-ok', href: result.result.download, download: 'download', text: '⬇ הורד MP4' }),
        ]));
        ok('הסרטון מוכן להעלאה');
        refresh();
      } else {
        ok('תצוגה מקדימה מוכנה');
      }
    } catch (error) { err(error.message); }
    finally { setBusy(button, false); }
  };

  const btnPreview = el('button', { class: 'btn', text: '👁 תצוגה מקדימה', onClick: () => runRender(btnPreview, false) });
  const btnExport = el('button', { class: 'btn btn-ok btn-lg', text: '⬇ ייצא MP4 סופי', onClick: () => runRender(btnExport, true) });

  if (project.export?.url) {
    outputBox.append(
      el('video', { src: project.export.url, controls: 'controls', style: { width: '250px', borderRadius: '12px', background: '#000' } }),
      project.export.download ? el('div', { class: 'row mt' }, [
        el('a', { class: 'btn btn-ok', href: project.export.download, download: 'download', text: '⬇ הורד MP4' }),
      ]) : null,
    );
  }

  // ------------------------------------------------------------- הרכבה

  root.append(el('div', { class: 'timeline' }, [
    el('div', { class: 'tl-label', text: 'ציר הזמן' }),
    ruler,
    track,
    el('div', { class: 'card-hint', style: { marginTop: '10px', marginBottom: '0' }, text: 'גרור קטע כדי להזיז אותו. תפוס קצה כדי לשנות אורך. הכל גמיש — אין אורכים קבועים.' }),
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'תזמון מדויק' })]),
    listBox,
  ]));

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'ייצוא' }),
      el('div', { class: 'card-spacer' }),
      el('span', { class: 'tag', text: `${boot.canvas.width}×${boot.canvas.height} · 9:16` }),
      project.captions?.enabled && project.captions?.words?.length
        ? el('span', { class: 'tag ok', text: 'כתוביות נצרבות' }) : null,
    ]),
    el('div', { class: 'card-hint', text: 'התצוגה המקדימה מהירה ובאיכות נמוכה — היא רק לבדיקה. הייצוא הסופי לוקח יותר זמן ויוצא באיכות מלאה. הקול המקורי מועתק as-is בשני המקרים.' }),
    el('div', { class: 'row' }, [btnPreview, btnExport]),
    jobBox,
    el('div', { class: 'mt' }, [outputBox]),
  ]));

  return root;
}
