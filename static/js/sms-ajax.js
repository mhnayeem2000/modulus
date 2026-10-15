(() => {
  const formatBalance = (balance) => {
    const numericBalance = Number(balance);
    if (!Number.isFinite(numericBalance)) {
      throw new Error('BulkSMSBD থেকে সঠিক balance পাওয়া যায়নি।');
    }
    return `৳${numericBalance.toFixed(2)}`;
  };

  const postForm = (url, form) => fetch(url, {
    method: 'POST',
    body: new FormData(form),
    credentials: 'same-origin',
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '',
    },
  });

  const updateSmsState = (form, enabled, message) => {
    const hero = document.querySelector('[data-sms-state]');
    const button = form.querySelector('[data-sms-toggle-button]');
    const stateInput = form.querySelector('[name="enabled"]');
    const feedback = hero?.querySelector('[data-sms-ajax-feedback]');
    if (!hero || !button || !stateInput) {
      throw new Error('SMS System toggle UI update করা যায়নি। পেজটি reload করে আবার চেষ্টা করুন।');
    }

    hero.classList.toggle('sms-system-on', enabled);
    hero.classList.toggle('sms-system-off', !enabled);
    hero.querySelector('[data-sms-state-icon]').textContent = enabled ? '✓' : 'Ⅱ';
    hero.querySelector('[data-sms-state-title]').textContent = enabled ? 'SMS is ON' : 'SMS is OFF';
    hero.querySelector('[data-sms-state-description]').textContent = enabled
      ? 'Attendance-এ SMS মাধ্যম বেছে save করলে এবং marks প্রথমবার/পরিবর্তন করে save করলে SMS পাঠানোর চেষ্টা হবে।'
      : 'Attendance save হবে, কিন্তু SMS service বন্ধ থাকবে—কোনো SMS পাঠানো হবে না।';
    stateInput.value = enabled ? 'off' : 'on';
    button.classList.toggle('is-on', enabled);
    button.classList.toggle('is-off', !enabled);
    button.setAttribute('aria-label', enabled ? 'SMS System বন্ধ করুন' : 'SMS System চালু করুন');
    button.innerHTML = `<span class="sms-system-toggle-track"><span></span></span><span>${enabled ? 'বন্ধ করুন' : 'চালু করুন'}</span>`;
    if (feedback) {
      feedback.className = 'alert alert-success';
      feedback.textContent = message;
      feedback.hidden = false;
    }
  };

  document.querySelectorAll('[data-sms-ajax-form]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      const action = form.querySelector('[name="action"]')?.value;
      const result = form.closest('.sms-system-info-card, .attendance-panel')
        ?.querySelector('[data-sms-balance-result]')
        || document.querySelector('[data-sms-balance-result]');
      const error = action === 'set_sms_state' ? null : form.closest('.sms-system-info-card, .attendance-panel')
        ?.querySelector('[data-sms-ajax-error]')
        || document.querySelector('[data-sms-ajax-error]');
      const feedback = form.querySelector('[data-sms-ajax-feedback]');
      const originalMarkup = button?.innerHTML;
      if (button) {
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        if (form.querySelector('[name="action"]')?.value === 'check_sms_balance') {
          button.textContent = 'যাচাই হচ্ছে...';
        }
      }
      if (error) error.hidden = true;
      if (feedback) feedback.hidden = true;

      try {
        const targetUrl = form.action || window.location.href;
        let response = await postForm(targetUrl, form);
        if (response.status === 404 && form.dataset.smsFallbackUrl) {
          response = await postForm(form.dataset.smsFallbackUrl, form);
        }
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
          if (response.redirected || response.url.includes('/login')) {
            throw new Error('আপনার login session শেষ হয়েছে। আবার login করে চেষ্টা করুন।');
          }
          throw new Error(
            response.status === 404
              ? 'SMS AJAX URL এবং fallback—দুটিই পাওয়া যায়নি (HTTP 404)। Django server restart করে project-এর URL configuration reload করুন।'
              : `Server JSON response দেয়নি (HTTP ${response.status})। পেজ reload করে আবার চেষ্টা করুন।`,
          );
        }
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || 'অনুরোধটি সম্পন্ন করা যায়নি।');
        }

        const action = form.querySelector('[name="action"]')?.value;
        if (action === 'set_sms_state') {
          updateSmsState(form, data.enabled, data.message);
        } else if (action === 'check_sms_balance' && result) {
          const balanceText = formatBalance(data.balance);
          const amount = result.querySelector('strong');
          if (amount) amount.textContent = balanceText;
          else result.textContent = `বর্তমান ব্যালেন্স: ${balanceText}`;
          result.hidden = false;
        }
      } catch (requestError) {
        if (error) {
          error.textContent = requestError.message || 'অনুরোধটি সম্পন্ন করা যায়নি।';
          error.hidden = false;
        } else if (feedback) {
          feedback.className = 'alert alert-error';
          feedback.textContent = requestError.message || 'অনুরোধটি সম্পন্ন করা যায়নি।';
          feedback.hidden = false;
        }
      } finally {
        if (button) {
          button.disabled = false;
          button.removeAttribute('aria-busy');
          if (originalMarkup && action === 'check_sms_balance') {
            button.innerHTML = originalMarkup;
          }
        }
      }
    });
  });
})();
