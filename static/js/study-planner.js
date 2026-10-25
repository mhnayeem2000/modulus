(() => {
  let setupDirty = false;
  let setupRevision = 0;
  let saveTimer;
  let setupSavePromise;

  const plannerRoot = () => document.querySelector('[data-planner-root]');

  const formAction = (form) => form.getAttribute('action') || window.location.href;

  const showFeedback = (message, isError = false) => {
    const feedback = plannerRoot()?.querySelector('[data-planner-feedback]');
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('is-error', isError);
    feedback.hidden = false;
  };

  const replacePlannerPage = async (response, pushUrl = response.url) => {
    const html = await response.text();
    if (response.redirected && new URL(response.url).pathname.includes('/login')) {
      window.location.assign(response.url);
      return;
    }
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const nextRoot = parsed.querySelector('[data-planner-root]');
    const currentRoot = plannerRoot();
    if (!response.ok) {
      throw new Error(`Planner page load করা যায়নি (HTTP ${response.status})। আবার চেষ্টা করুন।`);
    }
    if (!nextRoot) {
      const title = parsed.querySelector('title')?.textContent.trim();
      throw new Error(
        title
          ? `Planner-এর বদলে অন্য পেজ এসেছে (“${title}”)। Login session যাচাই করে আবার চেষ্টা করুন।`
          : 'Server planner page ফেরত দেয়নি। Page reload করে আবার চেষ্টা করুন।',
      );
    }
    if (!currentRoot) {
      throw new Error('Planner view খুঁজে পাওয়া যাচ্ছে না। Page reload করে আবার চেষ্টা করুন।');
    }
    currentRoot.replaceWith(nextRoot);
    if (pushUrl) history.pushState({}, '', pushUrl);
    window.initializeCurriculumFields?.();
  };

  const fetchPage = async (url, pushHistory = true) => {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    await replacePlannerPage(response, pushHistory ? response.url : null);
  };

  const setupIsReadyToSave = (form) => (
    Boolean(form.querySelector('[name="preferred_study_hours"]')?.value)
    && Boolean(form.querySelector('[name="subjects"]:checked'))
  );

  const saveSetup = async (form) => {
    if (setupSavePromise) {
      const previousSaveSucceeded = await setupSavePromise;
      if (!previousSaveSucceeded || !setupDirty) return previousSaveSucceeded;
      const currentForm = plannerRoot()?.querySelector('[data-planner-setup]');
      if (!currentForm || !setupIsReadyToSave(currentForm)) {
        showFeedback('প্রতিদিনের পড়ার ঘণ্টা ও অন্তত একটি subject বেছে নিয়ে তথ্য save করো।', true);
        return false;
      }
      return saveSetup(currentForm);
    }
    const submittedRevision = setupRevision;
    setupSavePromise = (async () => {
      const response = await fetch(formAction(form), {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '',
        },
      });
      if (response.redirected && response.url.includes('/login')) {
        throw new Error('Login session শেষ হয়েছে। আবার login করে চেষ্টা করুন।');
      }
      if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error(`তথ্য সংরক্ষণ করা যায়নি (HTTP ${response.status})। পেজ reload করে আবার চেষ্টা করুন।`);
      }
      const data = await response.json();
      if (!response.ok || !data.success) {
        if (data.html) {
          const parsed = new DOMParser().parseFromString(data.html, 'text/html');
          const nextRoot = parsed.querySelector('[data-planner-root]');
          if (nextRoot && plannerRoot()) plannerRoot().replaceWith(nextRoot);
          window.initializeCurriculumFields?.();
        }
        showFeedback(data.error || 'তথ্যগুলো যাচাই করে আবার চেষ্টা করো।', true);
        return false;
      }
      if (submittedRevision === setupRevision) setupDirty = false;
      showFeedback(data.message);
      return true;
    })();
    try {
      return await setupSavePromise;
    } finally {
      setupSavePromise = null;
      const currentForm = plannerRoot()?.querySelector('[data-planner-setup]');
      if (
        setupDirty
        && setupRevision !== submittedRevision
        && currentForm
        && setupIsReadyToSave(currentForm)
      ) {
        scheduleSetupSave(currentForm);
      }
    }
  };

  const scheduleSetupSave = (form) => {
    window.clearTimeout(saveTimer);
    if (!setupIsReadyToSave(form)) return;
    saveTimer = window.setTimeout(() => {
      saveSetup(form).catch((error) => showFeedback(error.message, true));
    }, 700);
  };

  document.addEventListener('click', async (event) => {
    const addButton = event.target.closest('[data-add-row]');
    if (addButton) {
      const form = addButton.closest('[data-planner-setup]');
      const name = addButton.dataset.addRow;
      const template = form?.querySelector(`[data-empty-row="${name}"]`);
      const rowList = form?.querySelector(`[data-formset="${name}"]`);
      const totalForms = form?.querySelector(`[name="${name}-TOTAL_FORMS"]`);
      if (!template || !rowList || !totalForms) return;
      const index = Number(totalForms.value);
      rowList.insertAdjacentHTML('beforeend', template.innerHTML.split('__prefix__').join(String(index)));
      totalForms.value = String(index + 1);
      setupDirty = true;
      setupRevision += 1;
      window.initializeCurriculumFields?.();
      return;
    }

    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = new URL(link.href, window.location.href);
    if (target.origin !== window.location.origin) return;
    const isPlannerLink = Boolean(link.closest('[data-planner-root]'));
    if (!isPlannerLink && !setupDirty) return;
    event.preventDefault();
    try {
      const setupForm = plannerRoot()?.querySelector('[data-planner-setup]');
      if (setupDirty && setupForm) {
        const saved = await saveSetup(setupForm);
        if (!saved) return;
      }
      if (!isPlannerLink) {
        window.location.assign(target.href);
        return;
      }
      await fetchPage(target);
    } catch (error) {
      showFeedback(error.message, true);
    }
  });

  document.addEventListener('input', (event) => {
    const form = event.target.closest('[data-planner-setup]');
    if (!form) return;
    setupDirty = true;
    setupRevision += 1;
    scheduleSetupSave(form);
  });

  document.addEventListener('change', (event) => {
    const form = event.target.closest('[data-planner-setup]');
    if (!form) return;
    setupDirty = true;
    setupRevision += 1;
    scheduleSetupSave(form);
  });

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-planner-root] form[method="post"]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const originalMarkup = button?.innerHTML;
    if (button) {
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      const loadingLabel = button.dataset.loadingLabel;
      if (loadingLabel) {
        button.textContent = loadingLabel;
        const spinner = document.createElement('span');
        spinner.className = 'planner-button-spinner';
        spinner.setAttribute('aria-hidden', 'true');
        button.prepend(spinner);
      }
    }
    try {
      if (form.matches('[data-planner-setup]')) {
        if (await saveSetup(form)) {
          const nextUrl = new URL(window.location.href);
          nextUrl.searchParams.set('tab', 'plan');
          nextUrl.searchParams.delete('day');
          await fetchPage(nextUrl);
        }
        return;
      }
      const response = await fetch(formAction(form), {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '',
        },
      });
      if ((response.headers.get('content-type') || '').includes('application/json')) {
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.error || `তথ্য সংরক্ষণ করা যায়নি (HTTP ${response.status})।`);
        }
        if (
          form.matches('.planner-task-actions form')
          && (
            form.querySelector('[name="task_action"]')?.value
            || form.querySelector('[name="action"]')?.value
          ) === 'complete'
        ) {
          const taskCard = form.closest('.planner-task-card');
          taskCard?.classList.add('is-completed');
          form.outerHTML = '<span class="planner-complete-check">✓ শেষ</span>';
          const summary = data.summary;
          if (summary) {
            const completed = plannerRoot()?.querySelector('[data-summary-completed]');
            const pending = plannerRoot()?.querySelector('[data-summary-pending]');
            const percent = plannerRoot()?.querySelector('[data-summary-percent]');
            const progress = plannerRoot()?.querySelector('[data-summary-progress]');
            if (completed) completed.textContent = String(summary.completed_count);
            if (pending) pending.textContent = `${summary.pending_count}টি কাজ বাকি`;
            if (percent) percent.textContent = String(summary.completion_percent);
            if (progress) progress.style.width = `${summary.completion_percent}%`;
          }
          const daySummary = taskCard?.closest('.planner-day')?.querySelector('[data-day-completion]');
          if (daySummary && data.day) {
            daySummary.textContent = `${data.day.minutes} মিনিট · ${data.day.completed}/${data.day.total} সম্পন্ন`;
          }
          const dayProgress = taskCard?.closest('.planner-day')?.querySelector('.planner-day-progress');
          if (dayProgress && data.day) {
            const percent = data.day.total
              ? Math.round(data.day.completed * 100 / data.day.total)
              : 0;
            const label = dayProgress.querySelector('strong');
            const bar = dayProgress.querySelector('i > b');
            if (label) label.textContent = `${percent}%`;
            if (bar) bar.style.width = `${percent}%`;
          }
          if (data.topic_progress) {
            const progress = data.topic_progress;
            plannerRoot()?.querySelectorAll('[data-topic-status]').forEach((status) => {
              const matches = status.dataset.subject === progress.subject
                && status.dataset.paper === progress.paper
                && status.dataset.chapter === progress.chapter
                && status.dataset.topic === progress.topic;
              if (!matches) return;
              status.textContent = progress.status_label;
              status.className = `planner-topic-status topic-${progress.status}`;
            });
          }
        }
        showFeedback(data.message);
      } else {
        if (form.matches('.planner-task-actions form')) {
          throw new Error(
            `পড়া শেষের request-এ server JSON ফেরত দেয়নি (HTTP ${response.status})। ` +
            'সর্বশেষ planner version চালু আছে কি না যাচাই করে page refresh করুন।',
          );
        }
        await replacePlannerPage(response, response.url);
      }
    } catch (error) {
      showFeedback(error.message, true);
    } finally {
      if (button) {
        button.disabled = false;
        button.removeAttribute('aria-busy');
        if (originalMarkup) button.innerHTML = originalMarkup;
      }
    }
  });

  window.addEventListener('popstate', async () => {
    try {
      const setupForm = plannerRoot()?.querySelector('[data-planner-setup]');
      if (setupDirty && setupForm && !(await saveSetup(setupForm))) return;
      await fetchPage(window.location.href, false);
    } catch (error) {
      showFeedback(error.message, true);
    }
  });

  window.addEventListener('beforeunload', (event) => {
    if (!setupDirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
