(() => {
  const initialize = () => {
    document.querySelectorAll('[data-curriculum]:not([data-curriculum-ready])').forEach((subjectField) => {
      const scope = subjectField.closest('[data-form-row]') || subjectField.closest('form');
      const paperField = scope?.querySelector('[name$="-paper"], [name="paper"]');
      const chapterField = scope?.querySelector('[name$="-chapter"], [name="chapter"]');
      if (!paperField || !chapterField) return;

      const curriculum = JSON.parse(subjectField.dataset.curriculum);

      const fill = (field, values, placeholder, selectedValue = '') => {
        field.replaceChildren(new Option(placeholder, ''));
        values.forEach((value) => field.add(new Option(value, value)));
        if (selectedValue && !values.includes(selectedValue)) {
          field.add(new Option(selectedValue, selectedValue));
        }
        field.value = selectedValue;
      };

      const syncPapers = (preserveSelection) => {
        const currentSubject = subjectField.value;
        const availablePapers = Object.keys(curriculum[currentSubject] || {});
        const selectedPaper = preserveSelection ? paperField.value : '';
        fill(paperField, availablePapers, 'পত্র নির্বাচন করুন', selectedPaper);
        syncChapters(preserveSelection);
      };

      const syncChapters = (preserveSelection) => {
        const papers = curriculum[subjectField.value];
        const availableChapters = papers && papers[paperField.value]
          ? papers[paperField.value]
          : [];
        const selectedChapter = preserveSelection ? chapterField.value : '';
        fill(chapterField, [...new Set(availableChapters)], 'অধ্যায় নির্বাচন করুন', selectedChapter);
      };

      subjectField.dataset.curriculumReady = 'true';
      subjectField.addEventListener('change', () => syncPapers(false));
      subjectField.addEventListener('input', () => syncPapers(true));
      paperField.addEventListener('change', () => syncChapters(false));
      syncPapers(true);
    });
  };

  window.initializeCurriculumFields = initialize;
  initialize();
})();
