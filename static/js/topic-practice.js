(() => {
  const root = document.querySelector('[data-topic-practice-root]');
  if (!root) return;

  const feedback = (message, isError = false) => {
    const element = root.querySelector('[data-practice-feedback]');
    if (!element) return;
    element.textContent = message;
    element.classList.toggle('is-error', isError);
    element.hidden = false;
  };

  const setLoading = (active) => {
    const panel = root.querySelector('[data-practice-loading]');
    const text = panel?.querySelector('[data-practice-loading-text]');
    if (!panel || !text) return () => {};
    let elapsedSeconds = 0;
    const baseText = 'Gemini topic অনুযায়ী প্রশ্ন ও উত্তর তৈরি করছে…';
    panel.hidden = !active;
    root.setAttribute('aria-busy', String(active));
    text.textContent = baseText;
    if (!active) return () => {};

    const timer = window.setInterval(() => {
      elapsedSeconds += 1;
      text.textContent = `${baseText} (${elapsedSeconds} সেকেন্ড)`;
    }, 1000);
    return () => {
      window.clearInterval(timer);
      panel.hidden = true;
      root.setAttribute('aria-busy', 'false');
    };
  };

  const csrfToken = () => (
    root.querySelector('[name="csrfmiddlewaretoken"]')?.value || ''
  );

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken(),
        ...(options.headers || {}),
      },
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw new Error(`Server JSON ফেরত দেয়নি (HTTP ${response.status})। আবার চেষ্টা করুন।`);
    }
    const data = await response.json();
    if (!response.ok || !data.success) {
      throw new Error(data.error || `Request ব্যর্থ হয়েছে (HTTP ${response.status})।`);
    }
    return data;
  };

  const refreshCurriculumFields = (subjectSelector, paperSelector, chapterSelector) => {
    const subject = root.querySelector(subjectSelector);
    const paper = root.querySelector(paperSelector);
    const chapter = root.querySelector(chapterSelector);
    if (!subject || !paper || !chapter) return;
    let curriculum;
    try {
      curriculum = JSON.parse(subject.dataset.curriculum);
    } catch {
      feedback('Curriculum data পড়া যায়নি। Page refresh করে আবার চেষ্টা করুন।', true);
      return;
    }
    const fill = (field, values, placeholder) => {
      field.replaceChildren(new Option(placeholder, ''));
      values.forEach((value) => field.add(new Option(value, value)));
    };
    const fillPapers = () => {
      fill(paper, Object.keys(curriculum[subject.value] || {}), 'Paper নির্বাচন করো');
      fillChapters();
    };
    const fillChapters = () => {
      const chapters = curriculum[subject.value]?.[paper.value] || [];
      fill(chapter, chapters, 'Chapter নির্বাচন করো');
    };
    subject.addEventListener('change', fillPapers);
    paper.addEventListener('change', fillChapters);
    fillPapers();
  };
  refreshCurriculumFields(
    '[data-practice-subject]',
    '[data-practice-paper]',
    '[data-practice-chapter]',
  );
  refreshCurriculumFields(
    '[data-recommend-subject]',
    '[data-recommend-paper]',
    '[data-recommend-chapter]',
  );

  const recommendationForm = root.querySelector('[data-topic-recommendation]');
  recommendationForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = recommendationForm.querySelector('button[type="submit"]');
    const panel = root.querySelector('[data-recommendation-loading]');
    const loadingText = panel?.querySelector('[data-recommendation-loading-text]');
    const output = root.querySelector('[data-recommendation-output]');
    if (!submit || !panel || !loadingText || !output) return;

    let elapsedSeconds = 0;
    const baseText = 'AI chapter-এর গুরুত্বপূর্ণ topic বাছাই করছে…';
    panel.hidden = false;
    loadingText.textContent = baseText;
    submit.disabled = true;
    root.setAttribute('aria-busy', 'true');
    const timer = window.setInterval(() => {
      elapsedSeconds += 1;
      loadingText.textContent = `${baseText} (${elapsedSeconds} সেকেন্ড)`;
    }, 1000);
    try {
      const data = await requestJson(recommendationForm.getAttribute('action'), {
        method: 'POST',
        body: new FormData(recommendationForm),
      });
      output.innerHTML = data.html;
      feedback(data.message);
    } catch (error) {
      feedback(error.message, true);
    } finally {
      window.clearInterval(timer);
      panel.hidden = true;
      submit.disabled = false;
      root.setAttribute('aria-busy', 'false');
    }
  });

  root.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-practice-create]');
    if (!form) return;
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const originalLabel = submit?.textContent;
    const stopLoading = setLoading(true);
    if (submit) {
      submit.disabled = true;
      submit.textContent = submit.dataset.loadingLabel || 'প্রশ্ন তৈরি হচ্ছে…';
    }
    try {
      const data = await requestJson(form.getAttribute('action'), {
        method: 'POST',
        body: new FormData(form),
      });
      const current = root.querySelector('[data-current-practice]');
      if (current) current.innerHTML = data.html;
      const history = root.querySelector('[data-practice-history]');
      if (history && data.history_matches) {
        const empty = history.querySelector('.practice-empty');
        empty?.remove();
        history.insertAdjacentHTML('afterbegin', data.history_html);
      }
      feedback(data.message);
      root.querySelector('[data-current-practice]')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    } catch (error) {
      feedback(error.message, true);
    } finally {
      if (submit) {
        submit.disabled = false;
        submit.textContent = originalLabel || 'প্রশ্ন তৈরি করো';
      }
      stopLoading();
    }
  });

  root.addEventListener('click', async (event) => {
    const loadMore = event.target.closest('[data-load-more-url]');
    if (loadMore) {
      const session = loadMore.closest('[data-practice-session]');
      const wasOpen = session?.open || false;
      const stopLoading = setLoading(true);
      loadMore.disabled = true;
      const originalLabel = loadMore.textContent;
      loadMore.textContent = 'প্রশ্ন তৈরি হচ্ছে…';
      try {
        const data = await requestJson(loadMore.dataset.loadMoreUrl, {method: 'POST'});
        const fragment = document.createRange().createContextualFragment(data.html);
        const replacement = fragment.querySelector('[data-practice-session]');
        if (!replacement || !session) throw new Error('Practice session update করা যায়নি।');
        replacement.open = wasOpen;
        root.querySelectorAll(`[data-session-id="${session.dataset.sessionId}"]`).forEach((item) => {
          item.replaceWith(replacement.cloneNode(true));
        });
        feedback(data.message);
      } catch (error) {
        feedback(error.message, true);
        loadMore.disabled = false;
        loadMore.textContent = originalLabel;
      } finally {
        stopLoading();
      }
      return;
    }

    const statusButton = event.target.closest('[data-question-status]');
    if (!statusButton) return;
    const actions = statusButton.closest('[data-status-url]');
    const question = statusButton.closest('[data-practice-question]');
    if (!actions || !question) return;
    const buttons = [...actions.querySelectorAll('[data-question-status]')];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const data = await requestJson(actions.dataset.statusUrl, {
        method: 'POST',
        body: new URLSearchParams({status: statusButton.dataset.questionStatus}),
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
      });
      buttons.forEach((button) => {
        const active = button.dataset.questionStatus === data.status;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
      });
      question.classList.toggle('is-practiced', data.status === 'practiced');
      question.classList.toggle('needs-help', data.status === 'needs_help');
      const label = actions.querySelector('[data-status-label]');
      if (label) label.textContent = data.status_label;
      feedback(data.message);
    } catch (error) {
      feedback(error.message, true);
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  });
})();
