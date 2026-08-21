/* שלב 3 — B-roll.
   כאן נמצא החיסכון הגדול של המערכת. תמונה עולה אגורות, וידאו עולה דולרים,
   ולכן המסך מכריח שני שלבים: משחקים בתמונות עד שהפריים נכון, ורק אז
   מנפישים פעם אחת. עשרה ניסיונות וידאו הופכים לאחד או שניים. */

import { api, watchJob } from '../api.js';
import { el, clear, ok, err, field, jobRow, timecode } from '../ui.js';

export function renderBroll(ctx) {
  const { project, refresh, boot, setBusy } = ctx;
  const root = el('div');
  const shots = project.broll.shots;
  const catalog = boot.broll_models || { images: [], videos: [] };

  // ------------------------------------------------------- הצעות מהתסריט

  const ideasBox = el('div');
  const btnIdeas = el('button', {
    class: 'btn', text: '💡 איפה לחתוך? תציע לי',
    onClick: async () => {
      setBusy(btnIdeas, true);
      clear(ideasBox);
      ideasBox.append(jobRow('קורא את התסריט'));
      try {
        const data = await api.post(`/api/projects/${project.id}/script/broll-ideas`, { count: 4 });
        clear(ideasBox);
        if (!data.ideas.length) return;
        const grid = el('div', { class: 'options' });
        for (const idea of data.ideas) {
          const line = project.script.lines[idea.line_index];
          grid.append(el('button', { class: 'opt', onClick: async () => {
            await api.post(`/api/projects/${project.id}/broll/shots`, {
              idea: idea.idea_he, start: 0, duration: 3, source: 'generated',
            });
            ok('קטע נוסף'); refresh();
          } }, [
            el('div', { class: 'opt-text', text: idea.idea_he }),
            line ? el('div', { class: 'opt-note', text: `על: ${line.text.slice(0, 26)}…` }) : null,
            el('div', { class: 'opt-pick', text: 'הוסף ←' }),
          ]));
        }
        ideasBox.append(grid);
      } catch (error) { clear(ideasBox); err(error.message); }
      finally { setBusy(btnIdeas, false); }
    },
  });

  // ------------------------------------------------------------- ספרייה

  const libraryBox = el('div', { class: 'thumbs' });
  const paintLibrary = (items) => {
    clear(libraryBox);
    if (!items.length) {
      libraryBox.append(el('div', { class: 'muted', style: { fontSize: '13px', gridColumn: '1/-1' }, text: 'הספרייה ריקה. גרור לכאן קטעים שחוזרים אצלך בכל סרטון.' }));
      return;
    }
    for (const item of items) {
      libraryBox.append(el('div', { class: 'thumb', style: { aspectRatio: '9/16' } }, [
        el('video', { src: item.url, muted: 'muted', preload: 'metadata',
          style: { width: '100%', height: '100%', objectFit: 'cover' },
          onMouseenter: (e) => e.target.play().catch(() => {}),
          onMouseleave: (e) => { e.target.pause(); e.target.currentTime = 0; } }),
        el('button', {
          class: 'btn btn-sm btn-primary',
          style: { position: 'absolute', bottom: '6px', right: '6px', left: '6px' },
          text: 'הוסף',
          onClick: async () => {
            await api.post(`/api/projects/${project.id}/broll/shots`, {
              idea: item.name, source: 'library', file: item.name, start: 0, duration: 3,
            });
            ok('נוסף לטיימליין'); refresh();
          },
        }),
      ]));
    }
  };
  paintLibrary(boot.library || []);

  const libDrop = el('div', { class: 'drop' }, [
    el('div', { class: 'drop-icon', text: '🎞' }),
    el('div', { class: 'drop-title', text: 'גרור קטעים לספרייה' }),
    el('div', { class: 'drop-sub', text: 'נשארים כאן לתמיד וזמינים בכל סרטון. MP4, MOV, WEBM' }),
  ]);
  const libInput = el('input', { type: 'file', accept: 'video/*', multiple: 'multiple', class: 'hidden' });

  const uploadToLibrary = async (files) => {
    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const data = await api.form('/api/broll/library', formData);
        boot.library = data.library;
        paintLibrary(data.library);
      } catch (error) { err(`${file.name}: ${error.message}`); }
    }
    ok('הועלה לספרייה');
  };
  libDrop.addEventListener('click', () => libInput.click());
  libInput.addEventListener('change', () => uploadToLibrary([...libInput.files]));
  ['dragenter', 'dragover'].forEach((e) => libDrop.addEventListener(e, (ev) => { ev.preventDefault(); libDrop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((e) => libDrop.addEventListener(e, (ev) => { ev.preventDefault(); libDrop.classList.remove('over'); }));
  libDrop.addEventListener('drop', (ev) => uploadToLibrary([...ev.dataTransfer.files]));

  // ---------------------------------------------------------- כרטיס קטע

  function renderShot(shot, index) {
    const body = el('div', { class: 'shot-body' });
    const isLibrary = shot.source === 'library';

    const hasPrompt = Boolean(shot.prompt);
    const hasImages = (shot.images || []).length > 0;
    const hasChosen = Boolean(shot.chosen_image);
    const hasVideo = Boolean(shot.video || (isLibrary && shot.file));

    // מד שלבים
    if (!isLibrary) {
      body.append(el('div', { class: 'shot-steps' }, [
        el('div', { class: `shot-step ${hasPrompt ? 'done' : 'now'}`, text: '1 · פרומפט' },),
        el('div', { class: `shot-step ${hasChosen ? 'done' : hasPrompt ? 'now' : ''}`, text: '2 · תמונות (זול)' }),
        el('div', { class: `shot-step ${hasVideo ? 'done' : hasChosen ? 'now' : ''}`, text: '3 · וידאו (יקר)' }),
      ]));
    }

    // ---- תיאור ופרומפטים ----
    if (!isLibrary) {
      const idea = el('textarea', { class: 'textarea', rows: 2, placeholder: 'מה רואים? בעברית פשוטה. "מקרר עומד בכניסה לבניין, אף אחד לא ליד"' });
      idea.value = shot.idea || '';

      const promptArea = el('textarea', { class: 'textarea', rows: 3, placeholder: 'הפרומפט הטכני באנגלית. ייכתב אוטומטית — אפשר גם לערוך ידנית.' });
      promptArea.value = shot.prompt || '';

      const promptOptions = el('div');

      const loadPrompts = async (more) => {
        if (!idea.value.trim()) return err('כתוב מה רואים בקטע');
        clear(promptOptions);
        promptOptions.append(jobRow(more ? 'מחפש זוויות אחרות' : 'כותב פרומפטים'));
        try {
          const data = await api.post(`/api/projects/${project.id}/broll/prompts`, {
            idea: idea.value.trim(), shot_id: shot.id, count: 4, more,
          });
          clear(promptOptions);
          const grid = el('div', { class: 'options' });
          for (const option of data.options) {
            grid.append(el('button', { class: 'opt', onClick: async () => {
              promptArea.value = option.prompt;
              await api.patch(`/api/projects/${project.id}/broll/shots/${shot.id}`, {
                prompt: option.prompt, idea: idea.value.trim(),
              });
              clear(promptOptions);
              ok('פרומפט נבחר');
            } }, [
              el('div', { class: 'opt-text', text: option.he || option.prompt }),
              el('div', { class: 'opt-note', text: 'EN' }),
              el('div', { class: 'opt-pick', text: 'קח ←' }),
            ]));
          }
          promptOptions.append(el('div', { class: 'row mt' }, [
            el('button', { class: 'btn btn-sm', text: '↻ עוד ארבעה', onClick: () => loadPrompts(true) }),
          ]), grid);
        } catch (error) { clear(promptOptions); err(error.message); }
      };

      body.append(
        field('מה רואים בקטע', 'תאר בעברית. המערכת תתרגם לפרומפט טכני מלא — עדשה, תאורה, זווית.', idea),
        el('div', { class: 'row mb' }, [
          el('button', { class: 'btn btn-primary btn-sm', text: '✍ כתוב לי פרומפטים', onClick: () => loadPrompts(false) }),
        ]),
        promptOptions,
        field('הפרומפט', 'מה שיישלח למודל. אפשר לערוך ידנית לפני שמייצרים.', promptArea),
      );

      // ---- תמונות — השלב הזול ----
      const imageModel = el('select', { class: 'select' },
        catalog.images.map((m) => el('option', { value: m.id }, [`${m.name} — ${m.he}`])));
      const imagesBox = el('div', { class: 'thumbs' });
      const imageJob = el('div');

      const paintImages = () => {
        clear(imagesBox);
        for (const image of shot.images || []) {
          const isChosen = shot.chosen_image === image.file;
          imagesBox.append(el('button', {
            class: `thumb ${isChosen ? 'chosen' : ''}`,
            onClick: async () => {
              shot.chosen_image = image.file;
              await api.patch(`/api/projects/${project.id}/broll/shots/${shot.id}`, { chosen_image: image.file });
              paintImages();
            },
          }, [
            el('img', { src: image.url, loading: 'lazy', alt: '' }),
            el('div', { class: 'thumb-check', text: '✓' }),
          ]));
        }
      };
      paintImages();

      const btnImages = el('button', {
        class: 'btn btn-primary', text: '🖼 ייצר 4 תמונות',
        onClick: async () => {
          const prompt = promptArea.value.trim();
          if (!prompt) return err('חסר פרומפט');
          setBusy(btnImages, true);
          clear(imageJob);
          const row = jobRow('מייצר תמונות');
          imageJob.append(row);
          try {
            const { job } = await api.post(`/api/projects/${project.id}/broll/shots/${shot.id}/images`, {
              prompt, model_id: imageModel.value, count: 4,
            });
            await watchJob(job.id, (snapshot) => row.update(snapshot));
            clear(imageJob); ok('תמונות מוכנות'); refresh();
          } catch (error) { err(error.message); }
          finally { setBusy(btnImages, false); }
        },
      });

      body.append(
        el('div', { class: 'cheap-note' }, [
          el('span', { text: '💚' }),
          el('span', { html: 'זה השלב הזול — <strong>בערך 20 אגורות לסבב של ארבע</strong>. תנסה כמה פעמים שבא לך, זה עדיין פחות מניסיון וידאו אחד.' }),
        ]),
        el('div', { class: 'row mb' }, [imageModel, btnImages]),
        imageJob,
        imagesBox,
      );

      // ---- וידאו — השלב היקר ----
      const videoModel = el('select', { class: 'select' },
        catalog.videos.map((m) => el('option', { value: m.id }, [`${m.name} — ${m.he}`])));
      const videoSeconds = el('input', { class: 'input', type: 'number', min: 3, max: 10, value: Math.max(3, Math.round(shot.duration || 5)) });
      const motion = el('input', { class: 'input', placeholder: 'איך זה זז? "המצלמה מתקרבת לאט, שום דבר אחר לא זז"' });
      motion.value = shot.motion_prompt || '';

      const costLine = el('div', { class: 'cost-note' });
      const paintCost = () => {
        const model = catalog.videos.find((m) => m.id === videoModel.value);
        const secs = parseInt(videoSeconds.value, 10) || 5;
        const cost = model ? (model.per_second * secs).toFixed(2) : '?';
        clear(costLine);
        costLine.append(
          el('span', { text: '⚠️' }),
          el('span', { html: `הלחיצה הזאת תעלה בערך <strong>$${cost}</strong>. ודא שהתמונה שבחרת היא בדיוק הפריים שאתה רוצה — התנועה כבר לא תתקן קומפוזיציה שגויה.` }),
        );
      };
      videoModel.addEventListener('change', paintCost);
      videoSeconds.addEventListener('input', paintCost);
      paintCost();

      const videoJob = el('div');
      const btnAnimate = el('button', {
        class: 'btn btn-money', text: '🎬 הנפש את התמונה',
        onClick: async () => {
          if (!shot.chosen_image) return err('בחר תמונה קודם. אל תשלם על וידאו של פריים שלא אישרת.');
          setBusy(btnAnimate, true);
          clear(videoJob);
          const row = jobRow('מנפיש');
          videoJob.append(row);
          try {
            const { job } = await api.post(`/api/projects/${project.id}/broll/shots/${shot.id}/animate`, {
              image: shot.chosen_image, model_id: videoModel.value,
              seconds: parseInt(videoSeconds.value, 10) || 5,
              motion_prompt: motion.value.trim(),
            });
            await watchJob(job.id, (snapshot) => row.update(snapshot));
            clear(videoJob); ok('הקטע מוכן'); refresh();
          } catch (error) { err(error.message); }
          finally { setBusy(btnAnimate, false); }
        },
      });

      body.append(
        el('div', { class: 'divider' }),
        field('תנועה', 'מה זז בפריים. ככל שתבקש פחות תנועה, כך יש פחות סיכוי לעיוותים.', motion),
        el('div', { class: 'grid-2' }, [
          field('מנוע', 'קטע רקע? קח את הזול. הקטע שנושא את הסרטון? קח את היקר.', videoModel),
          field('אורך בשניות', 'המחיר הוא פר שנייה — כל שנייה מיותרת עולה כסף.', videoSeconds),
        ]),
        costLine,
        el('div', { class: 'row' }, [btnAnimate]),
        videoJob,
      );
    }

    // ---- תצוגה מקדימה של הקטע המוכן ----
    if (shot.url || (isLibrary && shot.file)) {
      const src = shot.url || `/media/library/${shot.file}`;
      body.append(el('div', { class: 'mt' }, [
        el('video', { src, controls: 'controls', style: { width: '190px', borderRadius: '10px', background: '#000' } }),
      ]));
    }

    // ---- תזמון ומצב ----
    const start = el('input', { class: 'input', type: 'number', min: 0, step: 0.1, value: shot.start ?? 0 });
    const duration = el('input', { class: 'input', type: 'number', min: 0.2, step: 0.1, value: shot.duration ?? 3 });
    const mode = el('select', { class: 'select' }, [
      el('option', { value: 'full', selected: shot.mode !== 'pip' }, ['קאט מלא — על כל הפריים']),
      el('option', { value: 'pip', selected: shot.mode === 'pip' }, ['חלון קטן — האווטאר נשאר גלוי']),
    ]);
    const audioMix = el('input', { class: 'input', type: 'number', min: 0, max: 1, step: 0.05, value: shot.audio_mix ?? 0 });

    // פרמטרי החלון הקטן — מופיעים רק כשבוחרים pip
    const pipScale = el('input', { class: 'input', type: 'number', min: 0.15, max: 0.9, step: 0.01, value: shot.scale ?? 0.42 });
    const pipX = el('input', { class: 'input', type: 'number', min: 0, max: 100, step: 1, value: Math.round((shot.x ?? 0.05) * 100) });
    const pipY = el('input', { class: 'input', type: 'number', min: 0, max: 100, step: 1, value: Math.round((shot.y ?? 0.08) * 100) });

    const pipRow = el('div', { class: 'grid-3' }, [
      field('גודל החלון', 'שבר מרוחב הפריים. 0.42 = בערך 40 אחוז.', pipScale),
      field('מיקום אופקי', '0 = צמוד לשמאל, 100 = צמוד לימין.', pipX),
      field('מיקום אנכי', '0 = למעלה, 100 = למטה.', pipY),
    ]);
    const syncPipRow = () => pipRow.classList.toggle('hidden', mode.value !== 'pip');
    syncPipRow();

    const persist = async () => {
      syncPipRow();
      await api.patch(`/api/projects/${project.id}/broll/shots/${shot.id}`, {
        start: parseFloat(start.value) || 0,
        duration: parseFloat(duration.value) || 3,
        mode: mode.value,
        audio_mix: parseFloat(audioMix.value) || 0,
        scale: parseFloat(pipScale.value) || 0.42,
        x: (parseFloat(pipX.value) || 0) / 100,
        y: (parseFloat(pipY.value) || 0) / 100,
      });
    };
    [start, duration, mode, audioMix, pipScale, pipX, pipY].forEach((node) => node.addEventListener('change', persist));

    body.append(
      el('div', { class: 'divider' }),
      el('div', { class: 'grid-4' }, [
        field('נכנס בשנייה', 'מתי הקטע מתחיל', start),
        field('נשאר כמה זמן', 'כל אורך שתרצה', duration),
        field('מצב', 'איך הוא מופיע', mode),
        field('קול הקטע', '0 = מושתק. מעל 0 = מתערבב מתחת לקול שלך.', audioMix),
      ]),
      pipRow,
    );

    return el('div', { class: 'shot' }, [
      el('div', { class: 'shot-head' }, [
        el('div', { class: 'shot-num', text: String(index + 1) }),
        el('div', { class: 'shot-title', text: shot.idea || 'קטע ללא שם' }),
        el('span', { class: 'tag', text: isLibrary ? 'מהספרייה' : 'נוצר' }),
        el('span', { class: 'tag mono', text: `${timecode(shot.start || 0)} · ${(shot.duration || 0).toFixed(1)}ש׳` }),
        el('button', {
          class: 'btn btn-ghost btn-sm btn-danger', text: '✕',
          onClick: async () => { await api.del(`/api/projects/${project.id}/broll/shots/${shot.id}`); refresh(); },
        }),
      ]),
      body,
    ]);
  }

  // ------------------------------------------------------------- הרכבה

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { class: 'card-title', text: 'הקטעים' }),
      el('div', { class: 'card-spacer' }),
      btnIdeas,
      el('button', {
        class: 'btn btn-primary btn-sm', text: '+ קטע חדש',
        onClick: async () => {
          await api.post(`/api/projects/${project.id}/broll/shots`, { idea: '', start: 0, duration: 3 });
          refresh();
        },
      }),
    ]),
    el('div', { class: 'card-hint', text: 'כל קטע עובר שני שלבים: תמונות זולות עד שהפריים מדויק, ואז הנפשה אחת יקרה. זה מה שמוריד עשרה ניסיונות וידאו לאחד.' }),
    ideasBox,
  ]));

  if (!shots.length) {
    root.append(el('div', { class: 'empty' }, [
      el('div', { class: 'empty-icon', text: '🎞' }),
      el('div', { class: 'empty-title', text: 'עוד אין קטעי B-roll' }),
      el('div', { class: 'empty-text', text: 'הוסף קטע חדש כדי לייצר אחד, או קח משהו מהספרייה למטה.' }),
    ]));
  } else {
    shots.forEach((shot, index) => root.append(renderShot(shot, index)));
  }

  root.append(el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [el('h3', { class: 'card-title', text: 'ספריית B-roll' })]),
    el('div', { class: 'card-hint', text: 'קטעים שנשארים כאן לתמיד — לוגו, סטוק שחוזר, כל מה שאתה מכניס לכל סרטון.' }),
    libDrop, libInput,
    el('div', { class: 'mt' }, [libraryBox]),
  ]));

  root.append(el('div', { class: 'row' }, [
    el('button', {
      class: 'btn btn-ok', text: 'המשך לאווטאר ←',
      onClick: async () => { await api.patch(`/api/projects/${project.id}`, { stage: 'avatar' }); refresh('avatar'); },
    }),
  ]));

  return root;
}
