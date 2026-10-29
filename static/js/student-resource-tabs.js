(() => {
  const tablist = document.querySelector('#student-resource-tabs');
  if (!tablist) return;

  const tabs = Array.from(tablist.querySelectorAll('[data-resource-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-resource-panel]'));
  if (!tabs.length || !panels.length) return;

  const activateTab = (kind, focus = false) => {
    const selectedTab = tabs.find((tab) => tab.dataset.resourceTab === kind) || tabs[0];
    const selectedKind = selectedTab.dataset.resourceTab;

    tabs.forEach((tab) => {
      const isSelected = tab === selectedTab;
      tab.classList.toggle('active', isSelected);
      tab.setAttribute('aria-selected', String(isSelected));
      tab.tabIndex = isSelected ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.resourcePanel !== selectedKind;
    });

    if (focus) selectedTab.focus();

    const url = new URL(window.location.href);
    if (selectedKind === 'sheet') url.searchParams.delete('kind');
    else url.searchParams.set('kind', selectedKind);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.resourceTab));
    tab.addEventListener('keydown', (event) => {
      let nextIndex;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') nextIndex = 0;
      else if (event.key === 'End') nextIndex = tabs.length - 1;
      else return;

      event.preventDefault();
      activateTab(tabs[nextIndex].dataset.resourceTab, true);
    });
  });

  activateTab(tablist.dataset.activeTab);

  const mobilePdfQuery = window.matchMedia('(max-width: 820px)');
  const mobilePdfLinks = Array.from(document.querySelectorAll('[data-mobile-preview-url]'));
  const updateMobilePdfLinks = () => {
    mobilePdfLinks.forEach((link) => {
      link.href = mobilePdfQuery.matches
        ? link.dataset.mobilePreviewUrl
        : link.dataset.desktopUrl;
    });
  };

  updateMobilePdfLinks();
  if (mobilePdfQuery.addEventListener) {
    mobilePdfQuery.addEventListener('change', updateMobilePdfLinks);
  } else {
    mobilePdfQuery.addListener(updateMobilePdfLinks);
  }
})();
