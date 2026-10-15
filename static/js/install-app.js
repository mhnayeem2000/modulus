(() => {
  const page = document.querySelector('[data-install-app-page]');
  if (!page) return;

  const installButton = page.querySelector('[data-install-button]');
  const fallback = page.querySelector('[data-android-fallback]');
  const installStatus = page.querySelector('[data-install-status]');
  const installedBanner = page.querySelector('[data-installed-banner]');
  const guideToggle = page.querySelector('[data-guide-toggle]');
  const guide = page.querySelector('[data-install-guide]');
  const deviceNote = page.querySelector('[data-device-note]');
  const browserNote = page.querySelector('[data-browser-note-copy]');
  const userAgent = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/i.test(userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(userAgent);
  const isInAppBrowser = /FBAN|FBAV|Instagram|Messenger|Line\/|TikTok/i.test(userAgent);
  let deferredInstallPrompt = null;
  let installDismissed = false;

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.matchMedia('(display-mode: fullscreen)').matches
      || navigator.standalone === true;
  }

  function setInstalled() {
    installedBanner.hidden = false;
    installButton.hidden = true;
    fallback.hidden = true;
    guideToggle.hidden = true;
    guide.hidden = true;
    if (installStatus) {
      installStatus.hidden = true;
      installStatus.textContent = '';
    }
  }

  function updateFallback() {
    if (deferredInstallPrompt || installDismissed || isStandalone()) return;
    fallback.hidden = false;
    if (isIOS) {
      fallback.textContent = 'iPhone ও iPad-এ Safari-এর Share menu থেকে Add to Home Screen বেছে নিন।';
      browserNote.textContent = isInAppBrowser
        ? 'আপনি সম্ভবত in-app browser-এ আছেন। Safari-তে এই ওয়েবসাইট খুলে Share → Add to Home Screen বেছে নিন।'
        : 'iPhone/iPad-এ Safari ব্যবহার করুন। অন্য browser-এ Add to Home Screen অপশন নাও থাকতে পারে।';
    } else if (isAndroid) {
      fallback.textContent = 'Install button না এলে Chrome menu (⋮) খুলে “Install app” বা “Add to Home screen” বেছে নিন।';
      browserNote.textContent = 'Chrome বা সমর্থিত browser ব্যবহার করুন। Browser অনুযায়ী Install app বা Add to Home screen অপশনটি menu-তে থাকতে পারে।';
    } else {
      fallback.textContent = 'এই browser-এ সরাসরি install prompt পাওয়া যাচ্ছে না।';
      browserNote.textContent = 'Chrome বা Edge-এর menu/address bar-এ Install app অপশন খুঁজুন। iPhone/iPad হলে Safari-এর Share menu থেকে Add to Home Screen ব্যবহার করুন।';
    }
  }

  if (isStandalone()) {
    setInstalled();
  } else {
    updateFallback();
    if (isIOS) {
      deviceNote.textContent = isInAppBrowser
        ? 'iPhone/iPad-এ ইনস্টল করতে Safari-তে সাইটটি খুলুন।'
        : 'iPhone/iPad-এ Safari-এর Share menu ব্যবহার করে Home Screen-এ যোগ করুন।';
    } else if (isAndroid) {
      deviceNote.textContent = 'Android-এ browser install prompt এলে এক ট্যাপেই অ্যাপটি যোগ করতে পারবেন।';
    } else {
      deviceNote.textContent = 'আপনার browser ও device অনুযায়ী নিচের ইনস্টল পদ্ধতিটি বেছে নিন।';
    }
  }

  window.addEventListener('beforeinstallprompt', (event) => {
    if (isStandalone() || installDismissed) return;
    event.preventDefault();
    deferredInstallPrompt = event;
    installButton.hidden = false;
    fallback.hidden = true;
    deviceNote.textContent = 'আপনার browser-এ Modulus Edu ইনস্টল করা যাবে।';
  });

  window.addEventListener('appinstalled', () => {
    setInstalled();
    deviceNote.textContent = 'Modulus Edu সফলভাবে ইনস্টল হয়েছে।';
  });

  if (installButton) {
    installButton.addEventListener('click', async () => {
      if (!deferredInstallPrompt) {
        updateFallback();
        return;
      }

      const installPrompt = deferredInstallPrompt;
      deferredInstallPrompt = null;
      installButton.hidden = true;
      installStatus.hidden = false;
      installStatus.textContent = 'Browser-এর install dialog অনুসরণ করুন।';

      try {
        await installPrompt.prompt();
        const choice = await installPrompt.userChoice;
        if (choice.outcome === 'accepted') {
          installStatus.textContent = 'Install গ্রহণ করা হয়েছে। সম্পন্ন হলে অ্যাপটি Home Screen-এ পাবেন।';
        } else {
          installDismissed = true;
          installStatus.textContent = 'Install আপাতত করা হয়নি। চাইলে browser menu থেকে পরে ইনস্টল করতে পারবেন।';
        }
      } catch (error) {
        installDismissed = true;
        installStatus.textContent = 'Install dialog খোলা যায়নি। Browser menu থেকে “Install app” চেষ্টা করুন।';
        console.error('Could not show the Modulus Edu installation prompt.', error);
      }
    });
  }

  if (guideToggle && guide) {
    guideToggle.addEventListener('click', () => {
      const shouldOpen = guide.hidden;
      guide.hidden = !shouldOpen;
      guideToggle.setAttribute('aria-expanded', String(shouldOpen));
      guideToggle.querySelector('span').textContent = shouldOpen ? '↑' : '→';
    });
  }

  const standaloneQuery = window.matchMedia('(display-mode: standalone)');
  standaloneQuery.addEventListener?.('change', (event) => {
    if (event.matches) setInstalled();
  });
})();
